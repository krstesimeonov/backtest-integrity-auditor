"""Paths the generators never exercise: a trading day that crosses UTC
midnight, and every CLI option reaching the report's settings."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest_auditor.edge_audit.cli import REPORT_JSON, main
from backtest_auditor.edge_audit.report_schema import REPORT_JSON_SCHEMA
from backtest_auditor.edge_audit.schema import parse_price_table, parse_trade_log
from backtest_auditor.edge_audit.synthetic import timing_log, write_log
from backtest_auditor.edge_audit.timing import decompose_trade_timing

pytestmark = pytest.mark.filterwarnings(
    "ignore:A future version of pandas will return a BaseOffset"
)

# Local session 13:00-17:00 in Los Angeles (UTC-8 in January) is 21:00-01:00 UTC.
PRICES = pd.DataFrame(
    {
        "instrument": ["X"] * 10,
        "timestamp": [
            "2025-01-06T21:00:00Z",
            "2025-01-06T22:00:00Z",
            "2025-01-06T23:00:00Z",
            "2025-01-07T00:00:00Z",
            "2025-01-07T01:00:00Z",
            "2025-01-07T21:00:00Z",
            "2025-01-07T22:00:00Z",
            "2025-01-07T23:00:00Z",
            "2025-01-08T00:00:00Z",
            "2025-01-08T01:00:00Z",
        ],
        "price": ["100", "101", "102", "103", "104", "110", "111", "112", "113", "114"],
    }
)
TRADE = pd.DataFrame(
    {
        "instrument": ["X"],
        "side": ["long"],
        "quantity": ["1"],
        "entry_time": ["2025-01-06T22:00:00Z"],  # bar 101
        "entry_price": ["101"],
        "exit_time": ["2025-01-08T00:00:00Z"],  # bar 113
        "exit_price": ["113"],
        "fees": ["0"],
    }
)


def components(timezone: str) -> dict[str, float]:
    parts = decompose_trade_timing(
        parse_trade_log(TRADE),
        parse_price_table(PRICES),
        mode="day",
        day_timezone=timezone,
    )
    return {name: round(float(v[0]), 9) for name, v in parts.values.items()}


def test_day_windows_follow_the_declared_timezone():
    # Local days: Jan 6 bars 100..104 (mean 102), Jan 7 bars 110..114 (mean 112).
    assert components("America/Los_Angeles") == {
        "holding": 10.0,
        "entry_timing": 1.0,
        "exit_timing": 1.0,
        "execution": 0.0,
    }
    # UTC days cut the session: entry window 100..102 (mean 101), exit window
    # 113..114 (mean 113.5).
    assert components("UTC") == {
        "holding": 12.5,
        "entry_timing": 0.0,
        "exit_timing": -0.5,
        "execution": 0.0,
    }


def test_every_cli_option_reaches_the_report(tmp_path):
    import jsonschema

    trades, prices = write_log(
        timing_log(5, trades=120, entry_candidates=3, direction_skill=0.8),
        tmp_path,
        "opts",
    )
    out = tmp_path / "out"
    code = main(
        [
            "run",
            str(trades),
            "--trials",
            "4",
            "--prices",
            str(prices),
            "--out",
            str(out),
            "--confidence",
            "0.9",
            "--seed",
            "11",
            "--bootstrap",
            "150",
            "--block-length",
            "3",
            "--trial-sharpe-std",
            "0.05",
            "--timing-window",
            "holding",
            "--day-timezone",
            "America/New_York",
            "--timing-draws",
            "120",
            "--permutations",
            "130",
            "--vol-lookback-bars",
            "30",
            "--cost-grid",
            "0,3",
            "--reference-trades",
            "40",
            "--decay-shift",
            "0.3",
            "--decay-false-alarm",
            "0.1",
            "--decay-horizon",
            "400",
            "--rolling-window",
            "20",
        ]
    )
    assert code == 0
    report = json.loads((out / REPORT_JSON).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(REPORT_JSON_SCHEMA).validate(report)
    assert report["settings"] == {
        "declared_trials": 4,
        "confidence_level": 0.9,
        "bootstrap_replications": 150,
        "mean_block_length": 3,
        "seed": 11,
        "trial_sharpe_std": 0.05,
        "timing_mode": "holding",
        "day_timezone": "America/New_York",
        "timing_draws": 120,
        "permutation_draws": 130,
        "volatility_lookback_bars": 30,
        "cost_grid_bps": [0.0, 3.0],
        "reference_trades": 40,
        "decay_shift_sigma": 0.3,
        "decay_false_alarm_probability": 0.1,
        "decay_horizon": 400,
        "rolling_window": 20,
    }
    luck = report["luck_vs_skill"]
    assert (
        luck["trial_sharpe_std_source"] == "declared"
        and luck["trial_sharpe_std"] == 0.05
    )
    assert report["performance"]["expectancy"]["replications"] == 150
    assert report["performance"]["expectancy"]["confidence_level"] == 0.9
    assert report["timing"]["mode"] == "holding" and report["timing"]["draws"] == 120
    assert report["decay"]["reference_trades"] == 40
    assert report["decay"]["rolling_window"] == 20
    assert report["decay"]["shift_source"] == "declared"
    assert report["conditional"]["holding_period"]["permutation_draws"] == 130
    assert report["decay"]["status"] == "computed"
    assert report["decay"]["false_alarm_probability"] == 0.1
    assert report["decay"]["horizon_requested"] == 400
    for item in report["decay"]["detectors"]:
        assert item["false_alarm_probability"] == 0.1
        assert item["horizon"] == report["decay"]["horizon"]
        assert item["calibration_null"] == "iid_normal"
    rolling = next(
        item
        for item in report["decay"]["detectors"]
        if item["name"] == "rolling_expectancy"
    )
    assert rolling["parameters"]["window"] == 20
    sprt = next(
        item for item in report["decay"]["detectors"] if item["name"] == "mixture_sprt"
    )
    assert sprt["parameters"]["shift_sigma"] == 0.3
    added = sorted({point["added_cost_bps"] for point in report["costs"]["curve"]})
    assert 0.0 in added and 3.0 in added


@pytest.mark.parametrize(
    ("zone", "stamp", "start", "end"),
    [
        # Clocks jump from 00:00 to 01:00: local midnight does not exist.
        (
            "Africa/Cairo",
            "2025-04-25T12:00:00Z",
            "2025-04-24T22:00:00",
            "2025-04-25T21:00:00",
        ),
        (
            "America/Santiago",
            "2025-09-07T15:00:00Z",
            "2025-09-07T04:00:00",
            "2025-09-08T03:00:00",
        ),
        # Clocks go back at 01:00 to 00:00: midnight occurs twice, take the first.
        (
            "America/Havana",
            "2025-11-02T12:00:00Z",
            "2025-11-02T04:00:00",
            "2025-11-03T05:00:00",
        ),
        # A 23-hour day in a zone that changes at 02:00.
        (
            "Europe/Berlin",
            "2025-03-30T12:00:00Z",
            "2025-03-29T23:00:00",
            "2025-03-30T22:00:00",
        ),
    ],
)
def test_day_bounds_where_the_clock_changes(zone, stamp, start, end):
    from backtest_auditor.edge_audit.timing import _day_bounds

    first, last = _day_bounds(pd.DatetimeIndex([stamp]).tz_convert("UTC"), zone)
    assert pd.Timestamp(first[0]).isoformat() == start
    assert pd.Timestamp(last[0]).isoformat() == end


def test_a_trade_on_a_dst_change_at_midnight_does_not_stop_the_audit():
    prices = pd.DataFrame(
        {
            "instrument": ["X"] * 4,
            "timestamp": [
                "2025-04-25T08:00:00Z",
                "2025-04-25T09:00:00Z",
                "2025-04-26T08:00:00Z",
                "2025-04-26T09:00:00Z",
            ],
            "price": ["10", "11", "12", "13"],
        }
    )
    trade = pd.DataFrame(
        {
            "instrument": ["X"],
            "side": ["long"],
            "quantity": ["1"],
            "entry_time": ["2025-04-25T08:00:00Z"],
            "entry_price": ["10"],
            "exit_time": ["2025-04-26T09:00:00Z"],
            "exit_price": ["13"],
            "fees": ["0"],
        }
    )
    parts = decompose_trade_timing(
        parse_trade_log(trade),
        parse_price_table(prices),
        mode="day",
        day_timezone="Africa/Cairo",
    )
    values = {name: round(float(v[0]), 9) for name, v in parts.values.items()}
    assert values == {
        "holding": 2.0,
        "entry_timing": 0.5,
        "exit_timing": 0.5,
        "execution": 0.0,
    }


def test_an_entry_before_the_session_with_a_later_exit_is_excluded():
    """The adversarial reviewer's case: entered at 09:00Z, first bar 14:30Z."""

    prices = pd.DataFrame(
        {
            "instrument": ["X"] * 8,
            "timestamp": [
                f"2025-01-0{day}T14:{minute}:00Z"
                for day in (6, 7)
                for minute in ("30", "35", "40", "45")
            ],
            "price": ["100", "98", "101", "103", "104", "106", "105", "109"],
        }
    )
    trade = pd.DataFrame(
        {
            "instrument": ["X"],
            "side": ["long"],
            "quantity": ["10"],
            "entry_time": ["2025-01-07T09:00:00Z"],
            "entry_price": ["103"],
            "exit_time": ["2025-01-07T14:45:00Z"],
            "exit_price": ["109"],
            "fees": ["0"],
        }
    )
    parts = decompose_trade_timing(
        parse_trade_log(trade), parse_price_table(prices), mode="day"
    )
    assert parts.trade_index.size == 0
    assert parts.excluded == {"price_in_force_from_an_earlier_day": 1}
