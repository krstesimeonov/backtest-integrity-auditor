"""SAMPLE_AUDIT: rebuilt byte for byte, and every quoted number traced to the JSON."""

from __future__ import annotations

import importlib.util
import json
import math
import re
from datetime import datetime
from pathlib import Path
from statistics import NormalDist

import jsonschema
import pandas as pd
import pytest

from backtest_auditor.edge_audit.report_schema import REPORT_JSON_SCHEMA

pytestmark = pytest.mark.filterwarnings(
    "ignore:A future version of pandas will return a BaseOffset"
)

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "edge_audit" / "SAMPLE_AUDIT"
FILES = (
    "inputs/trades.csv",
    "inputs/prices.csv",
    "output/edge_audit_report.json",
    "output/edge_audit_report.md",
)


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "make_sample", SAMPLE / "make_sample.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads((SAMPLE / "output" / "edge_audit_report.json").read_text())


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def money(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace("-", "−")


def day(stamp: str) -> str:
    moment = datetime.fromisoformat(stamp)
    return f"{moment.day} {moment:%B %Y}"


def test_sample_is_rebuilt_byte_for_byte(tmp_path):
    assert load_generator().build(tmp_path) == 0
    for name in FILES:
        assert (tmp_path / name).read_bytes() == (SAMPLE / name).read_bytes(), name


def test_sample_report_is_schema_valid(report):
    jsonschema.Draft202012Validator(REPORT_JSON_SCHEMA).validate(report)


def test_every_number_in_the_letter_comes_from_the_report(report):
    letter = flat((SAMPLE / "AUDIT_LETTER.md").read_text(encoding="utf-8"))
    perf, luck = report["performance"], report["luck_vs_skill"]
    timing = {item["name"]: item for item in report["timing"]["components"]}
    detectors = {item["name"]: item for item in report["decay"]["detectors"]}
    costs, sizing = report["costs"], report["sizing"]
    conditional = report["conditional"]
    expectancy = perf["expectancy"]
    one_trial_dsr = NormalDist().cdf(
        luck["sharpe_per_trade"] * math.sqrt(perf["trade_count"] - 1)
    )
    entry = timing["entry_timing"]
    assert entry["p_value_positive"] == pytest.approx(
        1.0 / (report["timing"]["draws"] + 1)
    )
    rolling = report["decay"]["rolling_expectancy"]
    # "Two of our four monitors flagged it ... CUSUM and the sequential test stayed below".
    assert [item["name"] for item in report["decay"]["detectors"]] == [
        "rolling_expectancy",
        "cusum",
        "page_hinkley",
        "mixture_sprt",
    ]
    assert detectors["cusum"]["alarm_trade_number"] is None
    assert detectors["mixture_sprt"]["alarm_trade_number"] is None
    chances = [
        item["false_alarm_probability_over_monitored"]
        for item in report["decay"]["detectors"]
    ]
    expected = [
        f"{perf['trade_count']} closed trades",
        f"{report['verdict']['declared_trials']} strategy variants tried",
        f"USD {money(expectancy['point'])} (95 % interval {money(expectancy['lower'])} to "
        f"{money(expectancy['upper'])})",
        f"Sharpe ratio of {luck['sharpe_per_trade']:.3f} and a t-statistic of "
        f"{luck['t_statistic']:.2f}",
        f"(DSR {one_trial_dsr:.3f})",
        f"about {luck['expected_max_sharpe_per_trade']:.3f} by luck",
        f"the DSR is {luck['dsr']:.3f}",
        f"about {luck['deflated_min_track_record_trades']} trades would be needed",
        f"USD {money(entry['mean_per_trade']['point'])} per trade (interval "
        f"{money(entry['mean_per_trade']['lower'])} to {money(entry['mean_per_trade']['upper'])})",
        f"(p = {entry['p_value_positive']:.4f}",
        f"None of {report['timing']['draws']:,} simulated",
        f"USD {money(timing['exit_timing']['mean_per_trade']['point'])} per trade, p = "
        f"{timing['exit_timing']['p_value_positive']:.2f}",
        f"USD {money(timing['holding']['mean_per_trade']['point'])} per trade, p = "
        f"{timing['holding']['p_value_positive']:.2f}",
        f"{report['decay']['rolling_window']}-trade rolling average at trade "
        f"{detectors['rolling_expectancy']['alarm_trade_number']} "
        f"({day(detectors['rolling_expectancy']['alarm_exit_time'])})",
        f"Page–Hinkley at trade {detectors['page_hinkley']['alarm_trade_number']} "
        f"({day(detectors['page_hinkley']['alarm_exit_time'])})",
        f"{report['decay']['rolling_window']}-trade rolling average went from a high of USD "
        f"{money(max(rolling))} to USD {money(rolling[-1])}",
        f"an alarm within {report['decay']['horizon']:,} monitored trades would have had a "
        f"{100 * report['decay']['false_alarm_probability']:.0f} % chance",
        f"over the {report['decay']['monitored_trades']} trades watched here that chance is "
        f"at most {100 * max(chances):.1f} % for any one of them",
        f"cost USD {money(-timing['execution']['mean_per_trade']['point'])} per trade and fees "
        f"{costs['fees_paid_bps']:.2f} bps",
        f"breaks even at {costs['break_even_added_cost_bps']['point']:.2f} bps of additional "
        f"cost (interval {costs['break_even_added_cost_bps']['lower']:.2f} to "
        f"{costs['break_even_added_cost_bps']['upper']:.2f})",
        f"(permutation p = {sizing['permutation_p_value']:.3f})",
        f"holding period (p = {conditional['holding_period']['permutation_p_value']:.2f})",
        f"volatility regime (p = {conditional['volatility_regime']['permutation_p_value']:.3f})",
        f"equals {round(-timing['execution']['mean_per_trade']['point'] / expectancy['point'] * 100)} % "
        f"of the average net result of USD {money(expectancy['point'])}",
        f"Up to {perf['max_concurrent_trades']} trades",
        f"seed {report['settings']['seed']}",
        f"({report['settings']['bootstrap_replications']:,} resamples)",
    ]
    after = json.loads(
        (SAMPLE.parent / "calibration" / "results_after.json").read_text()
    )
    ar1 = [
        entry["rate"]
        for name, entry in after["scenarios"]["ar1_t3/1000"]["detectors"].items()
        if not name.startswith("formula_")
    ]
    expected += [f"(in our tests up to {100 * max(ar1):.1f} % over 1,000 trades)"]
    for fragment in expected:
        assert flat(fragment) in letter, fragment
    assert (
        report["timing"]["covered_trades"] == perf["trade_count"]
    )  # "matched every trade"


def test_the_planted_change_and_the_readme_table(report):
    generator = load_generator()
    trades = pd.read_csv(SAMPLE / "inputs" / "trades.csv", comment="#")
    prices = pd.read_csv(SAMPLE / "inputs" / "prices.csv", comment="#")
    sessions = sorted(set(pd.to_datetime(prices["timestamp"]).dt.date))
    cut = sessions[generator.SKILL_UNTIL_SESSION]
    unskilled = (pd.to_datetime(trades["entry_time"]).dt.date >= cut).to_numpy()
    first = int(unskilled.argmax()) + 1
    assert unskilled[first - 1 :].all() and not unskilled[: first - 1].any()
    readme = flat((SAMPLE / "README.md").read_text(encoding="utf-8"))
    detectors = {
        item["name"]: item["alarm_trade_number"]
        for item in report["decay"]["detectors"]
    }
    timing = {item["name"]: item for item in report["timing"]["components"]}
    mean_notional = report["costs"]["mean_notional"]
    delays = [
        detectors[name] - first for name in ("rolling_expectancy", "page_hinkley")
    ]
    assert all(delay > 0 for delay in delays)  # no alarm before the change
    assert detectors["cusum"] is None and detectors["mixture_sprt"] is None
    expected = [
        f"from session {generator.SKILL_UNTIL_SESSION} ({cut.isoformat()}): exit-order trades "
        f"{first}–{len(trades)}",
        f"alarms at trades {detectors['rolling_expectancy']} (rolling expectancy), "
        f"{detectors['page_hinkley']} (Page–Hinkley): {delays[0]} and {delays[1]} trades "
        f"after trade {first}; CUSUM and mixture SPRT below their thresholds (horizon "
        f"{report['decay']['horizon']:,} trades)",
        f"entry timing +{timing['entry_timing']['mean_per_trade']['point']:.2f} USD per trade, "
        f"p = {timing['entry_timing']['p_value_positive']:.4f}",
        f"exit timing p = {timing['exit_timing']['p_value_positive']:.2f}",
        f"holding (direction) p = {timing['holding']['p_value_positive']:.2f}",
        f"execution {money(timing['execution']['mean_per_trade']['point'])} USD per trade "
        f"(2 bps of the {mean_notional:,.2f}".replace(",", "'")
        + f" mean notional is {2e-4 * mean_notional:.2f})",
        f"fees paid {report['costs']['fees_paid_bps']:.2f} bps",
        f"sizing permutation p = {report['sizing']['permutation_p_value']:.3f}",
        f"DSR {report['luck_vs_skill']['dsr']:.3f} → no evidence",
    ]
    for fragment in expected:
        assert flat(fragment) in readme, fragment
