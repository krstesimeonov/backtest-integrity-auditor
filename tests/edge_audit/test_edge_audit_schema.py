"""Input schemas: parsing, P&L derivation and line-numbered validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.edge_audit.schema import (
    TRADES_SCHEMA,
    load_price_table,
    load_trade_log,
    parse_trade_log,
)

HEADER = (
    "trade_id,instrument,side,quantity,entry_time,entry_price,exit_time,exit_price,fees"
)


def write(tmp_path: Path, body: str, name: str = "trades.csv") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


def test_pnl_is_derived_exactly_for_long_short_multiplier_and_fees(tmp_path):
    path = write(
        tmp_path,
        f"""
        # schema: {TRADES_SCHEMA}
        trade_id,instrument,side,quantity,multiplier,entry_time,entry_price,exit_time,exit_price,fees
        A,ES,long,2,50,2025-01-02T14:30:00Z,4000,2025-01-02T15:30:00Z,4010,5
        B,ES,short,1,50,2025-01-02T16:00:00+01:00,4012,2025-01-02T16:30:00Z,4002,2.5
        """,
    )
    log = load_trade_log(path)
    assert log.schema_declared is True
    # Sorted by exit time: B exits 16:30Z, A 15:30Z -> A first.
    assert log.trade_id == ("A", "B")
    # A: +1 * 2 * 50 * (4010 - 4000) = 1000 gross, 995 net.
    # B: -1 * 1 * 50 * (4002 - 4012) = 500 gross, 497.5 net.
    np.testing.assert_array_equal(log.gross_pnl, [1000.0, 500.0])
    np.testing.assert_array_equal(log.net_pnl, [995.0, 497.5])
    np.testing.assert_array_equal(log.notional, [400000.0, 200600.0])
    # +01:00 offset converted: B entered 15:00Z, held 1.5 h.
    np.testing.assert_array_equal(log.holding_seconds, [3600.0, 5400.0])
    assert log.net_return[0] == pytest.approx(995.0 / 400000.0, rel=1e-15)


def test_rows_are_sorted_by_exit_then_entry_then_id_and_lines_kept(tmp_path):
    path = write(
        tmp_path,
        f"""
        {HEADER}
        z,X,long,1,2025-01-02T10:00:00Z,10,2025-01-03T10:00:00Z,11,0
        a,X,long,1,2025-01-02T11:00:00Z,10,2025-01-03T10:00:00Z,11,0
        b,X,long,1,2025-01-02T10:00:00Z,10,2025-01-03T10:00:00Z,11,0
        c,X,long,1,2025-01-02T09:00:00Z,10,2025-01-02T12:00:00Z,11,0
        """,
    )
    log = load_trade_log(path)
    assert log.trade_id == ("c", "b", "z", "a")
    np.testing.assert_array_equal(log.source_lines, [5, 4, 2, 3])
    assert log.schema_declared is False


def test_trade_id_is_optional_and_defaults_to_line_number(tmp_path):
    path = write(
        tmp_path,
        """
        instrument,side,quantity,entry_time,entry_price,exit_time,exit_price,fees
        X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        """,
    )
    assert load_trade_log(path).trade_id == ("L2",)


@pytest.mark.parametrize(
    ("row", "code", "line_text"),
    [
        (
            "1,X,sideways,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0",
            "invalid_side",
            "line 2",
        ),
        (
            "1,X,long,-1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0",
            "invalid_quantity",
            "line 2",
        ),
        (
            "1,X,long,1,2025-01-02T10:00:00Z,0,2025-01-02T11:00:00Z,11,0",
            "invalid_entry_price",
            "line 2",
        ),
        (
            "1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,nan,0",
            "invalid_exit_price",
            "line 2",
        ),
        (
            "1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,-1",
            "invalid_fees",
            "line 2",
        ),
        (
            "1,X,long,1,2025-01-02T10:00:00,10,2025-01-02T11:00:00Z,11,0",
            "naive_entry_time",
            "line 2",
        ),
        (
            "1,X,long,1,yesterday,10,2025-01-02T11:00:00Z,11,0",
            "invalid_entry_time",
            "line 2",
        ),
        (
            "1,X,long,1,2025-01-02T12:00:00Z,10,2025-01-02T11:00:00Z,11,0",
            "exit_before_entry",
            "line 2",
        ),
        (
            "1,,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0",
            "empty_instrument",
            "line 2",
        ),
    ],
)
def test_each_row_problem_is_reported_with_its_line(tmp_path, row, code, line_text):
    path = write(tmp_path, f"{HEADER}\n{row}\n")
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    codes = {issue.code for issue in caught.value.issues}
    assert code in codes
    assert any(issue.location == line_text for issue in caught.value.issues)


def test_all_problems_are_collected_in_one_pass(tmp_path):
    path = write(
        tmp_path,
        f"""
        {HEADER}
        1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        1,X,flat,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        3,X,long,0,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        """,
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    found = {(issue.code, issue.location) for issue in caught.value.issues}
    assert ("duplicate_trade_id", "line 3") in found
    assert ("invalid_side", "line 3") in found
    assert ("invalid_quantity", "line 4") in found


def test_missing_and_unknown_columns_are_rejected(tmp_path):
    path = write(
        tmp_path,
        """
        instrument,side,quantity,entry_time,entry_price,exit_time,exit_price,fee
        X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        """,
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    codes = [issue.code for issue in caught.value.issues]
    assert codes == ["missing_column", "unknown_column"]


def test_a_different_schema_version_is_refused(tmp_path):
    path = write(tmp_path, f"# schema: edge-audit-trades/2.0\n{HEADER}\n")
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    assert caught.value.issues[0].code == "unsupported_schema"


def test_mixed_currency_is_rejected(tmp_path):
    path = write(
        tmp_path,
        """
        instrument,side,quantity,entry_time,entry_price,exit_time,exit_price,fees,currency
        X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0,USD
        X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0,CHF
        """,
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    assert caught.value.issues[0].code == "mixed_currency"


def test_empty_file_and_missing_file(tmp_path):
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(write(tmp_path, f"{HEADER}\n"))
    assert caught.value.issues[0].code == "empty_trade_log"
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(tmp_path / "absent.csv")
    assert caught.value.issues[0].code == "file_not_found"


def test_parse_accepts_a_string_frame_directly():
    frame = pd.DataFrame(
        {
            "instrument": ["X"],
            "side": ["SHORT"],
            "quantity": ["3"],
            "entry_time": ["2025-01-02T10:00:00Z"],
            "entry_price": ["10"],
            "exit_time": ["2025-01-02T11:00:00Z"],
            "exit_price": ["9"],
            "fees": ["0.5"],
        }
    )
    log = parse_trade_log(frame)
    assert log.net_pnl.tolist() == [2.5]


def test_price_table_sorts_and_rejects_duplicate_timestamps(tmp_path):
    good = write(
        tmp_path,
        """
        instrument,timestamp,price
        X,2025-01-02T10:05:00Z,11
        X,2025-01-02T10:00:00Z,10
        Y,2025-01-02T10:00:00Z,5
        """,
        name="prices.csv",
    )
    table = load_price_table(good)
    assert table.instruments() == ("X", "Y")
    assert table.prices["X"].tolist() == [10.0, 11.0]
    bad = write(
        tmp_path,
        """
        instrument,timestamp,price
        X,2025-01-02T10:00:00Z,10
        X,2025-01-02T10:00:00Z,11
        """,
        name="bad.csv",
    )
    with pytest.raises(InputValidationError) as caught:
        load_price_table(bad)
    assert caught.value.issues[0].code == "duplicate_price_timestamp"
    assert caught.value.issues[0].location == "line 3"


def test_line_numbers_survive_blank_lines_and_quoted_line_breaks(tmp_path):
    path = write(
        tmp_path,
        f"""
        {HEADER}

        1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        "2
        b",X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        ,,,,,,,,
        3,X,long,0,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        """,
    )
    # Physical lines: 1 header, 2 blank, 3 trade 1, 4-5 a trade whose id holds
    # a line break (refused: no column may), 6 an empty spreadsheet row
    # (skipped), 7 trade 3 with quantity 0. Both problems in one pass.
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    found = {(issue.code, issue.location) for issue in caught.value.issues}
    assert found == {("line_break_in_field", "line 4"), ("invalid_quantity", "line 7")}


def test_an_unclosed_quote_in_the_last_column_is_refused_not_swallowed(tmp_path):
    """Pass-2 finding 1: the non-strict reader put every later row into one field."""

    header = "instrument,side,quantity,entry_time,entry_price,exit_time,exit_price,fees,trade_id"
    rows = [
        f"X,long,1,2025-01-06T10:00:00Z,10,2025-01-06T11:00:00Z,11,0,T{index}"
        for index in range(40)
    ]
    rows[4] = rows[4].replace(",T4", ',"T4')  # line 6 opens a quote and never closes it
    path = write(tmp_path, header + "\n" + "\n".join(rows) + "\n")
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    issue = caught.value.issues[0]
    assert (issue.code, issue.location) == ("unreadable_csv", "line 6")


def test_an_unclosed_quote_mid_row_points_at_its_own_line(tmp_path):
    path = write(
        tmp_path,
        f"""
        {HEADER}
        1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        2,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        3,"X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        4,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        """,
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    issue = caught.value.issues[0]
    assert (issue.code, issue.location) == ("unreadable_csv", "line 4")


def test_a_spreadsheet_padded_schema_line_is_recognised(tmp_path):
    body = f"{HEADER}\n1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0\n"
    good = write(tmp_path, f"# schema: {TRADES_SCHEMA},,,,,,,,\n{body}", "good.csv")
    assert load_trade_log(good).schema_declared is True
    other = write(
        tmp_path, f"# schema: edge-audit-trades/2.0,,,,,,,,\n{body}", "other.csv"
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(other)
    assert [issue.code for issue in caught.value.issues] == ["unsupported_schema"]


def test_a_wrong_field_count_does_not_hide_problems_in_other_rows(tmp_path):
    path = write(
        tmp_path,
        f"""
        {HEADER}
        1,X,up,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        2,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11
        """,
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    found = {(issue.code, issue.location) for issue in caught.value.issues}
    assert found == {("wrong_field_count", "line 3"), ("invalid_side", "line 2")}


def test_a_repeated_column_name_is_reported_as_such(tmp_path):
    path = write(
        tmp_path,
        f"""
        {HEADER},fees
        1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0,0
        """,
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    assert [issue.code for issue in caught.value.issues] == ["duplicate_column"]


@pytest.mark.parametrize(
    "stamp",
    [
        "03/04/2025 10:00 +00:00",  # day/month order would be guessed
        "Jan 2 2025 10:00 UTC",
        "2025-01-02T10:00:00 UTC",
        "20250102T100000Z",
        "2025-13-02T10:00:00Z",  # ISO layout, impossible month
    ],
)
def test_timestamps_must_be_iso_8601_with_an_offset(tmp_path, stamp):
    path = write(
        tmp_path,
        f"{HEADER}\n1,X,long,1,{stamp},10,2025-01-02T11:00:00Z,11,0\n",
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    assert [issue.code for issue in caught.value.issues] == ["invalid_entry_time"]


@pytest.mark.parametrize(
    ("stamp", "utc"),
    [
        ("2025-01-02T10:00Z", "2025-01-02T10:00:00+00:00"),
        ("2025-01-02 10:00:00.5+0100", "2025-01-02T09:00:00.500000+00:00"),
        ("2025-01-02T10:00:00-05:00", "2025-01-02T15:00:00+00:00"),
    ],
)
def test_accepted_iso_8601_variants(tmp_path, stamp, utc):
    path = write(
        tmp_path,
        f"{HEADER}\n1,X,long,1,{stamp},10,2025-01-03T11:00:00Z,11,0\n",
    )
    assert load_trade_log(path).entry_time[0].isoformat() == utc


def test_a_row_with_the_wrong_number_of_fields_is_reported_with_its_line(tmp_path):
    path = write(
        tmp_path,
        f"""
        {HEADER}
        1,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0
        2,X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11
        """,
    )
    with pytest.raises(InputValidationError) as caught:
        load_trade_log(path)
    issue = caught.value.issues[0]
    assert (issue.code, issue.location) == ("wrong_field_count", "line 3")
