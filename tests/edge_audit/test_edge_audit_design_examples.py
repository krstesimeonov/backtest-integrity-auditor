"""Every worked example in docs/edge_audit/DESIGN.md, recomputed.

Each test computes the numbers with the package code and checks that the
design document quotes exactly those numbers (whitespace-insensitive), so
the document cannot drift from the code.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from backtest_auditor.edge_audit.conditional import (
    between_sum_of_squares,
    tercile_labels,
)
from backtest_auditor.edge_audit.costs import analyse_costs, break_even_added_cost_bps
from backtest_auditor.edge_audit.decay import cusum_lower, mixture_sprt_log_lr
from backtest_auditor.edge_audit.metrics import (
    bootstrap_distributions,
    expectancy,
    percentile_interval,
    profit_factor,
    win_rate,
)
from backtest_auditor.edge_audit.schema import parse_price_table, parse_trade_log
from backtest_auditor.edge_audit.sizing import fixed_size_pnl
from backtest_auditor.edge_audit.skill import deflated_min_track_record
from backtest_auditor.edge_audit.timing import decompose_trade_timing
from backtest_auditor.statistics.deflated_sharpe import (
    _expected_maximum_standard_normal,
)

DESIGN = Path(__file__).resolve().parents[2] / "docs" / "edge_audit" / "DESIGN.md"
TEXT = re.sub(r"\s+", " ", DESIGN.read_text(encoding="utf-8"))


def quoted(*fragments: str) -> None:
    for fragment in fragments:
        assert re.sub(r"\s+", " ", fragment) in TEXT, fragment


def test_bootstrap_example():
    pnl = np.array([120.0, -80.0, 50.0, -40.0, 0.0, 150.0, -60.0, 30.0])
    assert expectancy(pnl) == 21.25
    assert round(profit_factor(pnl), 3) == 1.944
    assert win_rate(pnl) == 0.5
    assert pnl[[5, 0, 0, 3, 7, 1, 5, 2]].mean() == 62.5
    draws = bootstrap_distributions(
        8,
        {
            "e": lambda idx: float(np.mean(pnl[idx])),
            "pf": lambda idx: profit_factor(pnl[idx]),
            "wr": lambda idx: win_rate(pnl[idx]),
        },
        replications=10_000,
        mean_block_length=1,
        seed=1,
    )
    e = percentile_interval(21.25, draws["e"], confidence_level=0.95)
    pf = percentile_interval(profit_factor(pnl), draws["pf"], confidence_level=0.95)
    wr = percentile_interval(0.5, draws["wr"], confidence_level=0.95)
    assert (e.lower, e.upper) == (-31.25, 76.25)
    assert round(pf.lower, 3) == 0.238 and pf.upper_unbounded
    assert (wr.lower, wr.upper) == (0.125, 0.875)
    quoted(
        "Expectancy 21.25; profit factor 350 / 180 = 1.944; win rate 4/8 = 0.5",
        "150, 120, 120, −40, 30, −80, 150, 50, mean 62.5",
        "expectancy [−31.25, 76.25], profit factor [0.238, unbounded], win rate [0.125, 0.875]",
    )


def test_luck_versus_skill_example():
    sharpe, trades = 0.1, 400
    assert sharpe * math.sqrt(trades) == pytest.approx(2.0)
    assert round(float(stats.t.sf(2.0, trades - 1)), 4) == 0.0231
    assert round(sharpe * math.sqrt(200), 3) == 1.414
    assert round(1.414 * math.sqrt(2), 1) == 2.0
    assert round(NormalDist().cdf(sharpe * math.sqrt(trades - 1)), 4) == 0.9771
    e10 = _expected_maximum_standard_normal(10)
    se0 = 1.0 / math.sqrt(trades - 1)
    bar = e10 * se0
    z = (sharpe - bar) / se0
    assert (round(e10, 4), round(se0, 5), round(bar, 4)) == (1.5746, 0.05006, 0.0788)
    assert (round(z, 4), round(NormalDist().cdf(z), 4)) == (0.4229, 0.6638)
    assert deflated_min_track_record(sharpe, 1.0, 0.0, 0.95) == 272
    assert deflated_min_track_record(sharpe, 1.0, e10, 0.95) == 1038
    quoted(
        "t = 0.1 · √400 = 2.0 (one-sided p 0.0231",
        "SR_annual = 0.1 · √200 = 1.414",
        "DSR = Φ(0.1·√399) = 0.9771",
        "e₁₀ = 1.5746",
        "1/√399 = 0.05006",
        "SR* = 1.5746 · 0.05006 = 0.0788",
        "Φ((0.1 − 0.0788)/0.05006) = Φ(0.4229) = 0.6638",
        "272 trades with N = 1 and 1,038 with N = 10",
    )


def test_timing_example():
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
    trades = pd.DataFrame(
        {
            "instrument": ["X"],
            "side": ["long"],
            "quantity": ["10"],
            "entry_time": ["2025-01-06T14:35:00Z"],
            "entry_price": ["98.2"],
            "exit_time": ["2025-01-07T14:40:00Z"],
            "exit_price": ["104.9"],
            "fees": ["0"],
        }
    )
    log = parse_trade_log(trades)
    parts = decompose_trade_timing(log, parse_price_table(prices), mode="day")
    values = {name: round(float(v[0]), 9) for name, v in parts.values.items()}
    assert values == {
        "holding": 55.0,
        "entry_timing": 25.0,
        "exit_timing": -10.0,
        "execution": -3.0,
    }
    assert round(float(log.gross_pnl[0]), 9) == 67.0
    quoted("55 + 25 − 10 − 3 = 67", "(mean 100.5)", "(mean 106)")


def test_tercile_example():
    holding = np.array([1, 2, 3, 10, 11, 12, 40, 50, 60.0])
    pnl = np.array([-1, 0, -2, 1, 2, 0, 5, 4, 6.0])
    labels = tercile_labels(holding)
    means = [float(pnl[labels == group].mean()) for group in range(3)]
    assert means == [-1.0, 1.0, 5.0]
    assert between_sum_of_squares(pnl, labels) == pytest.approx(56.0)
    quoted("tercile means −1, 1, 5; grand mean 1.667", "= 56.0")


def test_cost_example():
    net = np.array([3.0, -1.0, 4.0])
    notional = np.array([1000.0, 2000.0, 3000.0])
    assert break_even_added_cost_bps(net, notional) == pytest.approx(10.0)
    curve = analyse_costs(
        net,
        net,
        notional,
        span_years=1.0,
        declared_trials=1,
        confidence_level=0.95,
        trial_sharpe_std=None,
        grid_bps=(0.0, 5.0, 10.0),
        bootstrap_pnl_means=np.full(10, net.mean()),
        bootstrap_notional_means=np.full(10, notional.mean()),
    ).curve
    expectancy = {point.added_cost_bps: point.expectancy for point in curve}
    assert expectancy[0.0] == pytest.approx(2.0)  # expectancy(c) = 2 - 0.2 c
    assert expectancy[5.0] == pytest.approx(1.0)
    assert expectancy[10.0] == pytest.approx(0.0, abs=1e-12)
    quoted("break-even added cost 2 / 2,000 = 0.001 = 10 bps", "2 − 0.2·c")


def test_decay_examples():
    assert cusum_lower(np.array([-1.0, -1.0, 0.5, -2.0]), 0.25).tolist() == [
        0.75,
        1.5,
        0.75,
        2.5,
    ]
    z = np.array([-1.0, -1.0, 0.5, -2.0])
    log_lr = mixture_sprt_log_lr(z, 0.5)[-1]
    by_hand = (
        math.log(2.0)
        - 0.5 * math.log(2.0)
        + 3.5**2 / 16.0
        + math.log(NormalDist().cdf(3.5 / math.sqrt(8.0)))
    )
    assert round(log_lr, 3) == round(by_hand, 3) == 0.998
    assert round(math.log(20.0), 3) == 2.996
    k, h = 0.25, 5.0
    b = h + 1.166
    siegmund = (math.exp(2 * k * b) - 2 * k * b - 1) / (2 * k * k)
    assert round(siegmund) == 142
    quoted(
        "S = 0.75, 1.5, 0.75, 2.5",
        "(S = −3.5, a = 4 + 1/0.25 = 8): log Λ = ln 2 − ½ ln 2 + 3.5²/16 + ln Φ(3.5/√8) = 0.998",
        "ln 20 = 2.996",
        "average run of 142 trades",
    )


def test_sizing_example():
    notional = np.array([1000.0, 3000.0, 1000.0, 3000.0])
    returns = np.array([-0.01, 0.01, -0.01, 0.01])
    actual = returns * notional
    fixed = fixed_size_pnl(returns, notional)
    assert actual.tolist() == pytest.approx([-10, 30, -10, 30])
    assert fixed.tolist() == pytest.approx([-20, 20, -20, 20])
    assert actual.mean() - fixed.mean() == pytest.approx(10.0)
    quoted("actual P&L −10, 30, −10, 30 (mean 10)", "−20, 20, −20, 20 (mean 0)")


def test_sample_threshold_comparison():
    import json

    sample = DESIGN.parent / "SAMPLE_AUDIT" / "output" / "edge_audit_report.json"
    decay = json.loads(sample.read_text(encoding="utf-8"))["decay"]
    k = decay["reference_sharpe"] / 2.0
    target = -decay["horizon"] / math.log(0.95)
    low, high = 0.0, 200.0
    for _ in range(200):
        middle = (low + high) / 2.0
        b = middle + 1.166
        arl = (math.exp(2 * k * b) - 2 * k * b - 1) / (2 * k * k)
        low, high = (middle, high) if arl < target else (low, middle)
    cusum = next(item for item in decay["detectors"] if item["name"] == "cusum")
    assert (decay["reference_trades"], decay["monitored_trades"]) == (140, 280)
    assert decay["horizon"] == 1000
    sr = f"{decay['reference_sharpe']:.2f}"
    quoted(
        f"(140 reference trades, SR₀ {sr}, 280 monitored, horizon 1,000) the CUSUM "
        f"threshold is {cusum['threshold']:.1f}, against {low:.1f} from Siegmund's formula",
        "ARL₀ = −1,000 / ln 0.95",
    )
