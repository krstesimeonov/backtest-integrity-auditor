from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

import backtest_auditor.implementation_risk.exporters.nautilustrader as nt
import backtest_auditor.implementation_risk.exporters.quantconnect_lean as lean


def test_lean_strict_json_and_scalar_helpers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not be read"):
        lean._load_json(tmp_path / "missing", field="source")

    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        lean._load_json(invalid, field="source")

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        lean._load_json(duplicate, field="source")

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"a":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite JSON"):
        lean._load_json(nonfinite, field="source")

    with pytest.raises(ValueError, match="JSON object"):
        lean._mapping([], field="object")
    with pytest.raises(ValueError, match="ambiguous"):
        lean._pick({"a": 1, "b": 2}, "a", "b", field="choice")
    with pytest.raises(ValueError, match="missing"):
        lean._pick({}, "a", field="choice")
    assert lean._pick({}, "a", field="choice", required=False) is None
    with pytest.raises(ValueError, match="non-empty text"):
        lean._text(" ", field="text")

    for value, message in (
        (True, "boolean"),
        (object(), "ISO-8601 or Unix"),
        ("invalid", "valid ISO-8601"),
        ("2026-01-01T00:00:00", "disclose its UTC offset"),
    ):
        with pytest.raises(ValueError, match=message):
            lean._timestamp(value, field="timestamp")
    # Since afa7b80 an order's last update is the latest lifecycle instant
    # (_order_last_update); the old _optional_timestamp lost its only caller.
    assert lean._order_last_update({}) == ""
    assert lean._order_last_update(
        {
            "lastUpdateTime": "2026-01-02T14:31:00Z",
            "lastFillTime": "2026-01-02T14:35:00Z",
        }
    ) == lean._timestamp("2026-01-02T14:35:00Z", field="timestamp")
    with pytest.raises(ValueError, match="finite"):
        lean._decimal(float("inf"), field="number")
    with pytest.raises(ValueError, match="positive"):
        lean._decimal(0, field="number", positive=True)
    assert lean._optional_decimal(None, field="number") == ""


def test_lean_enum_structure_fee_and_equity_helpers() -> None:
    mapping = {0: "Zero", 1: "One"}
    with pytest.raises(ValueError, match="invalid"):
        lean._enum(True, mapping, field="enum")
    with pytest.raises(ValueError, match="numeric value"):
        lean._enum(2, mapping, field="enum")
    with pytest.raises(ValueError, match="value is unsupported"):
        lean._enum("two", mapping, field="enum")
    assert lean._enum("one", mapping, field="enum") == "One"
    assert lean._instrument("AAPL", field="symbol") == "AAPL"

    assert lean._time_in_force({}) == "Custom"
    assert lean._time_in_force({"properties": {}}) == "Custom"
    assert lean._time_in_force({"properties": {"$type": "GoodTilCanceled"}}) == "GTC"
    assert lean._time_in_force({"properties": {"timeInForce": "IOC"}}) == "IOC"
    assert lean._time_in_force({"properties": {"timeInForce": "Unknown"}}) == "Custom"

    assert lean._results_root({"Results": {"Orders": []}}) == {"Orders": []}
    assert lean._orders({"Orders": [{"id": 1}]}) == ({"id": 1},)
    with pytest.raises(ValueError, match="object or array"):
        lean._orders({"Orders": 1})
    assert lean._order_events({"OrderEvents": []}) == ()
    assert lean._order_events({"b": [], "a": []}) == ()
    with pytest.raises(ValueError, match="JSON array"):
        lean._order_events({"bad": 1})

    assert lean._fee({}) == ("0", "")
    assert lean._fee({"orderFee": {}}) == ("0", "")
    assert lean._fee({"OrderFee": {"Value": {"Amount": "1.5", "Currency": "USD"}}}) == (
        "1.5",
        "USD",
    )

    with pytest.raises(ValueError, match="at least one point"):
        lean._equity_points(
            {"Charts": {"Strategy Equity": {"Series": {"Equity": {"Values": []}}}}}
        )
    with pytest.raises(ValueError, match="timestamps must be unique"):
        lean._equity_points(
            {
                "Charts": {
                    "Strategy Equity": {
                        "Series": {
                            "Equity": {
                                "Values": [
                                    {"x": 1, "y": 100},
                                    {"x": 1, "y": 101},
                                ]
                            }
                        }
                    }
                }
            }
        )


def test_nautilustrader_strict_frame_and_scalar_helpers() -> None:
    with pytest.raises(ValueError, match="DataFrame"):
        nt._frame(object(), field="frame", require_unique_index=True)
    duplicate_columns = pd.DataFrame([[1, 2]], columns=["a", "a"])
    with pytest.raises(ValueError, match="columns must be unique"):
        nt._frame(duplicate_columns, field="frame", require_unique_index=True)
    duplicate_index = pd.DataFrame({"a": [1, 2]}, index=[0, 0])
    with pytest.raises(ValueError, match="index must be unique"):
        nt._frame(duplicate_index, field="frame", require_unique_index=True)
    with pytest.raises(ValueError, match="missing columns"):
        nt._require_columns(pd.DataFrame({"a": [1]}), ("a", "b"), field="frame")
    with pytest.raises(ValueError, match="non-empty text"):
        nt._text(pd.NA, field="text")
    with pytest.raises(ValueError, match="finite"):
        nt._decimal(float("nan"), field="number")
    assert nt._optional_decimal(pd.NA, field="number") == ""

    with pytest.raises(ValueError, match="boolean"):
        nt._timestamp(True, field="timestamp")
    with pytest.raises(ValueError, match="valid timestamp"):
        nt._timestamp("invalid", field="timestamp")
    with pytest.raises(ValueError, match="UTC offset"):
        nt._timestamp("2026-01-01", field="timestamp")
    assert nt._optional_timestamp(pd.NA, field="timestamp") == ""

    with pytest.raises(ValueError, match="amount and currency"):
        nt._money(pd.NA, field="money", allow_empty=False)
    with pytest.raises(ValueError, match="<amount> <currency>"):
        nt._money("1", field="money", allow_empty=False)

    class MoneyLike:
        currency = "USD"

        def as_decimal(self) -> Decimal:
            return Decimal("1.25")

    assert nt._money(MoneyLike(), field="money", allow_empty=False) == (
        "1.25",
        "USD",
    )


def test_nautilustrader_public_fail_closed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nt, "installed_engine_version", lambda _name: "future")
    empty = pd.DataFrame()
    with pytest.raises(ValueError, match="tested only"):
        nt.export_nautilustrader_reports(
            empty,
            empty,
            empty,
            empty,
            tmp_path / "wrong",
            run_id="wrong",
            base_currency="USD",
        )

    with pytest.raises(ValueError, match="must be callable"):
        nt.export_nautilustrader_engine(
            object(),
            "SIM",
            tmp_path / "missing",
            run_id="missing",
            base_currency="USD",
        )

    class FailingEngine:
        def generate_orders_report(self) -> pd.DataFrame:
            raise RuntimeError("engine failure")

        generate_fills_report = generate_orders_report
        generate_positions_report = generate_orders_report
        generate_account_report = generate_orders_report

    with pytest.raises(ValueError, match="could not be generated"):
        nt.export_nautilustrader_engine(
            FailingEngine(),
            "SIM",
            tmp_path / "failing",
            run_id="failing",
            base_currency="USD",
        )
