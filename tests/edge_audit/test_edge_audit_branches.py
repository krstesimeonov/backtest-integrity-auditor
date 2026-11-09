"""Branches the main tests do not reach: alternative inputs, adverse
findings, exclusions, price-file errors and the warnings."""

from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.edge_audit.audit import AuditSettings, run_edge_audit
from backtest_auditor.edge_audit.report import build_report, render_markdown
from backtest_auditor.edge_audit.schema import (
    load_price_table,
    parse_price_table,
    parse_trade_log,
)
from backtest_auditor.edge_audit.synthetic import (
    pnl_trade_log,
    random_walk_bars,
    timing_log,
    to_strings,
    write_log,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:A future version of pandas will return a BaseOffset"
)
QUICK = dict(
    bootstrap_replications=100,
    permutation_draws=200,
    timing_draws=400,
)


def test_entry_volatility_column_is_the_regime_source_and_drives_the_split():
    rng = np.random.default_rng(1)
    volatility = rng.uniform(0.5, 3.0, 300)
    pnl = rng.normal(0.0, 1.0, 300) + np.where(volatility > 2.2, 1.5, 0.0)
    frame = pnl_trade_log(pnl, seed=1)
    frame["entry_volatility"] = volatility
    trades = parse_trade_log(to_strings(frame))
    result = run_edge_audit(trades, None, AuditSettings(declared_trials=1, **QUICK))
    split = result.volatility_regime
    assert split.source == "trade_log entry_volatility column"
    assert split.trades_with_value == 300
    assert split.permutation_p_value < 0.01
    assert split.rows[2].expectancy.point > split.rows[0].expectancy.point + 1.0


def anti_skilled_log(seed: int, trades: int = 150) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Entries at the worst of 3 random bars of the entry day."""

    rng = np.random.default_rng(seed)
    bars = random_walk_bars(seed, days=60, bars_per_day=78)
    price = bars["price"].to_numpy().reshape(60, 78)
    stamps = pd.DatetimeIndex(bars["timestamp"]).as_unit("ns").asi8.reshape(60, 78)
    rows = []
    for number in range(trades):
        day = int(rng.integers(0, 55))
        exit_day = day + int(rng.integers(1, 4))
        side = 1 if rng.random() < 0.5 else -1
        candidates = rng.integers(0, 78, 3)
        values = price[day, candidates]
        entry = int(candidates[np.argmax(values) if side > 0 else np.argmin(values)])
        exit_bar = int(rng.integers(0, 78))
        rows.append(
            {
                "trade_id": f"W{number}",
                "instrument": "SYN",
                "side": "long" if side > 0 else "short",
                "quantity": 100.0,
                "entry_time": pd.Timestamp(stamps[day, entry], tz="UTC").isoformat(),
                "entry_price": price[day, entry],
                "exit_time": pd.Timestamp(
                    stamps[exit_day, exit_bar], tz="UTC"
                ).isoformat(),
                "exit_price": price[exit_day, exit_bar],
                "fees": 0.0,
            }
        )
    return pd.DataFrame(rows), bars


def test_bad_entry_timing_is_reported_as_costing_pnl():
    frame, bars = anti_skilled_log(3)
    result = run_edge_audit(
        parse_trade_log(to_strings(frame)),
        parse_price_table(to_strings(bars)),
        AuditSettings(declared_trials=1, **QUICK),
    )
    entry = next(c for c in result.timing.components if c.name == "entry_timing")
    assert entry.finding == "costs P&L (significant)"
    assert entry.p_value_negative < 0.05 < entry.p_value_positive
    report = build_report(
        result,
        trades_path=__file__,
        prices_path=None,
        trade_rows=len(frame),
        schema_declared=False,
    )
    answer = report["answers"]["where_does_it_come_from"]
    assert (
        f"entry timing: costs P&L (significant) (p = {entry.p_value_negative:.4f} "
        "for costing P&L)" in answer
    )


def test_trades_priced_by_an_earlier_session_are_excluded_and_warned_about():
    log = timing_log(2, trades=40)
    frame = log.trades.copy()
    # Two trades opened before the session's first bar (14:30 UTC): the bar in
    # force at entry is the previous session's, which no random entry time in
    # the entry day can reproduce, so the trade is left out of the timing test.
    frame.loc[0, ["entry_time", "exit_time"]] = [
        "2025-02-04T09:00:00Z",
        "2025-02-04T09:30:00Z",
    ]
    frame.loc[1, ["entry_time", "exit_time"]] = [
        "2025-02-05T09:00:00Z",
        "2025-02-07T18:00:00Z",
    ]
    trades = parse_trade_log(to_strings(frame))
    result = run_edge_audit(
        trades,
        parse_price_table(to_strings(log.prices)),
        AuditSettings(declared_trials=1, **QUICK),
    )
    assert result.timing.excluded == {"price_in_force_from_an_earlier_day": 2}
    assert result.timing.covered_trades == 38
    assert any(
        "covers 38 of 40 trades; 2 had no usable" in note for note in result.warnings
    )


def test_timing_with_fewer_than_two_covered_trades_is_unavailable():
    log = timing_log(4, trades=5)
    frame = log.trades.copy()
    frame.loc[1:, "instrument"] = "OTHER"  # no prices for four of five trades
    result = run_edge_audit(
        parse_trade_log(to_strings(frame)),
        parse_price_table(to_strings(log.prices)),
        AuditSettings(declared_trials=1, **QUICK),
    )
    assert result.timing.status == "unavailable"
    assert result.timing.reason.startswith("1 trade(s) have price coverage")
    assert result.timing.excluded == {"no_prices_for_instrument": 4}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("instrument,timestamp\nX,2025-01-02T10:00:00Z\n", "missing_column"),
        (
            "instrument,timestamp,price,size\nX,2025-01-02T10:00:00Z,1,2\n",
            "unknown_column",
        ),
        ("instrument,timestamp,price\nX,2025-01-02 10:00,1\n", "naive_timestamp"),
        ("instrument,timestamp,price\nX,2025-01-02T10:00:00Z,0\n", "invalid_price"),
        ("instrument,timestamp,price\n", "empty_price_table"),
        ("", "empty_file"),
    ],
)
def test_price_file_problems_are_reported(tmp_path, body, code):
    path = tmp_path / "prices.csv"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    with pytest.raises(InputValidationError) as caught:
        load_price_table(path)
    assert caught.value.issues[0].code == code


def test_sizing_that_loads_up_on_losers_is_reported_as_costing_pnl():
    rng = np.random.default_rng(6)
    signal = rng.uniform(-1.0, 1.0, 400)
    returns = (30.0 * signal + 30.0 * rng.standard_normal(400)) * 1e-4
    quantity = 100.0 * (1.0 - 0.8 * signal)  # big when the trade is bad
    frame = pnl_trade_log(100.0 * returns, seed=6, sizes=quantity)
    result = run_edge_audit(
        parse_trade_log(to_strings(frame)),
        None,
        AuditSettings(declared_trials=1, **QUICK),
    )
    assert (
        result.sizing.finding
        == "larger positions went into worse trades (sizing costs P&L)"
    )
    assert result.sizing.sizing_contribution_per_trade.point < 0.0


def test_negative_sharpe_answer_and_serial_dependence_warning(tmp_path):
    rng = np.random.default_rng(8)
    noise = rng.standard_normal(300)
    pnl = np.empty(300)
    pnl[0] = noise[0]
    for index in range(1, 300):  # AR(1), phi = 0.6, mean -0.3
        pnl[index] = 0.6 * pnl[index - 1] + noise[index]
    pnl = pnl - pnl.mean() - 0.3
    path, _ = write_log(
        type("Log", (), {"trades": pnl_trade_log(pnl, seed=8), "prices": None})(),
        tmp_path,
        "ar",
    )
    from backtest_auditor.edge_audit.schema import load_trade_log

    trades = load_trade_log(path)
    result = run_edge_audit(trades, None, AuditSettings(declared_trials=1, **QUICK))
    assert result.performance.lag_one_autocorrelation > 0.4
    assert any("serially dependent" in note for note in result.warnings)
    report = build_report(
        result,
        trades_path=path,
        prices_path=None,
        trade_rows=len(trades),
        schema_declared=True,
    )
    assert report["verdict"]["edge"] == "no_evidence_of_edge"
    assert "The observed per-trade Sharpe ratio is not positive." in render_markdown(
        report
    )


def test_concurrency_counts_zero_length_and_ignores_back_to_back_trades():
    from backtest_auditor.edge_audit.audit import _max_concurrent

    def frame(rows):
        return pd.DataFrame(
            {
                "instrument": "X",
                "side": "long",
                "quantity": "1",
                "entry_time": [entry for entry, _ in rows],
                "entry_price": "10",
                "exit_time": [exit_ for _, exit_ in rows],
                "exit_price": "11",
                "fees": "0",
            }
        )

    same_instant = [("2025-01-02T10:00:00Z", "2025-01-02T10:00:00Z")] * 40
    assert _max_concurrent(parse_trade_log(frame(same_instant))) == 40
    back_to_back = [
        ("2025-01-02T10:00:00Z", "2025-01-02T11:00:00Z"),
        ("2025-01-02T11:00:00Z", "2025-01-02T12:00:00Z"),
    ]
    assert _max_concurrent(parse_trade_log(frame(back_to_back))) == 1
    overlapping = back_to_back + [("2025-01-02T10:30:00Z", "2025-01-02T11:30:00Z")]
    assert _max_concurrent(parse_trade_log(frame(overlapping))) == 2
