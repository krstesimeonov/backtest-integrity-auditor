"""Timing decomposition, terciles, cost curve, sizing and decay detectors:
hand-computed examples and exact identities."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.integrate import trapezoid

from backtest_auditor.edge_audit.conditional import (
    between_sum_of_squares,
    split_by_terciles,
    tercile_labels,
    trailing_volatility,
)
from backtest_auditor.edge_audit.costs import (
    analyse_costs,
    break_even_added_cost_bps,
    with_added_cost,
)
from backtest_auditor.edge_audit.decay import (
    analyse_decay,
    cusum_lower,
    first_crossing,
    mixture_sprt_log_lr,
    page_hinkley_decrease,
    rolling_drop,
    rolling_expectancy,
    sprt_decay,
    threshold,
)
from backtest_auditor.edge_audit.schema import parse_price_table, parse_trade_log
from backtest_auditor.edge_audit.sizing import analyse_sizing, fixed_size_pnl
from backtest_auditor.edge_audit.skill import EVIDENCE, assess_luck_vs_skill
from backtest_auditor.edge_audit.synthetic import timing_log, to_strings
from backtest_auditor.edge_audit.timing import analyse_timing, decompose_trade_timing

pytestmark = pytest.mark.filterwarnings(
    "ignore:A future version of pandas will return a BaseOffset"
)

# Two sessions, four 5-minute bars each. Day 1 mean 100.5, day 2 mean 106.
PRICES = pd.DataFrame(
    {
        "instrument": ["X"] * 8,
        "timestamp": [
            "2025-01-06T14:30:00Z",
            "2025-01-06T14:35:00Z",
            "2025-01-06T14:40:00Z",
            "2025-01-06T14:45:00Z",
            "2025-01-07T14:30:00Z",
            "2025-01-07T14:35:00Z",
            "2025-01-07T14:40:00Z",
            "2025-01-07T14:45:00Z",
        ],
        "price": ["100", "98", "101", "103", "104", "106", "105", "109"],
    }
)


def trades_frame(rows: list[tuple]) -> pd.DataFrame:
    columns = [
        "trade_id",
        "instrument",
        "side",
        "quantity",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "fees",
    ]
    return pd.DataFrame([[str(cell) for cell in row] for row in rows], columns=columns)


SWING = (
    "A",
    "X",
    "long",
    10,
    "2025-01-06T14:35:00Z",
    98.2,
    "2025-01-07T14:40:00Z",
    104.9,
    0,
)


def test_timing_components_hand_example_day_mode():
    log = parse_trade_log(trades_frame([SWING]))
    parts = decompose_trade_timing(log, parse_price_table(PRICES), mode="day")
    values = {name: float(v[0]) for name, v in parts.values.items()}
    assert values["holding"] == pytest.approx(10 * (106.0 - 100.5))  # 55
    assert values["entry_timing"] == pytest.approx(10 * (100.5 - 98.0))  # 25
    assert values["exit_timing"] == pytest.approx(10 * (105.0 - 106.0))  # -10
    assert values["execution"] == pytest.approx(
        10 * ((98 - 98.2) + (104.9 - 105))
    )  # -3
    assert sum(values.values()) == pytest.approx(float(log.gross_pnl[0]))  # 67


def test_timing_components_hand_example_holding_mode():
    log = parse_trade_log(trades_frame([SWING]))
    parts = decompose_trade_timing(log, parse_price_table(PRICES), mode="holding")
    window_mean = (98 + 101 + 103 + 104 + 106 + 105) / 6.0
    values = {name: float(v[0]) for name, v in parts.values.items()}
    assert values["holding"] == 0.0
    assert values["entry_timing"] == pytest.approx(10 * (window_mean - 98.0))
    assert values["exit_timing"] == pytest.approx(10 * (105.0 - window_mean))
    assert sum(values.values()) == pytest.approx(67.0)


def test_intraday_trade_windows_and_short_side():
    # Short 5 from 14:35 (bar 98) to 14:40 (bar 101) on day 1.
    trade = (
        "S",
        "X",
        "short",
        5,
        "2025-01-06T14:35:00Z",
        98,
        "2025-01-06T14:40:00Z",
        101,
        0,
    )
    log = parse_trade_log(trades_frame([trade]))
    parts = decompose_trade_timing(log, parse_price_table(PRICES), mode="day")
    entry_mean = (100 + 98 + 101) / 3.0  # day-1 bars up to the exit bar
    exit_mean = (98 + 101 + 103) / 3.0  # day-1 bars from the entry bar
    k = -5.0
    assert parts.values["holding"][0] == pytest.approx(k * (exit_mean - entry_mean))
    assert parts.values["entry_timing"][0] == pytest.approx(k * (entry_mean - 98))
    assert parts.values["exit_timing"][0] == pytest.approx(k * (101 - exit_mean))
    total = sum(float(v[0]) for v in parts.values.values())
    assert total == pytest.approx(-15.0)


def test_identity_holds_for_many_random_trades_in_both_modes():
    log = timing_log(3, trades=150, entry_candidates=2, direction_skill=0.3)
    trades = parse_trade_log(to_strings(log.trades))
    prices = parse_price_table(to_strings(log.prices))
    for mode in ("day", "holding"):
        parts = decompose_trade_timing(trades, prices, mode=mode)
        total = sum(parts.values.values())
        np.testing.assert_allclose(
            total, trades.gross_pnl[parts.trade_index], rtol=1e-9, atol=1e-9
        )


def test_trades_without_price_coverage_are_excluded_and_counted():
    rows = [
        SWING,
        ("B", "Y", "long", 1, "2025-01-06T14:35:00Z", 1, "2025-01-07T14:40:00Z", 2, 0),
        ("C", "X", "long", 1, "2025-01-06T14:00:00Z", 1, "2025-01-07T14:40:00Z", 2, 0),
    ]
    parts = decompose_trade_timing(
        parse_trade_log(trades_frame(rows)), parse_price_table(PRICES), mode="day"
    )
    assert parts.trade_index.size == 1
    assert parts.excluded == {
        "no_prices_for_instrument": 1,
        "no_bar_at_or_before_entry": 1,
    }


def test_timing_without_prices_is_unavailable_not_an_error():
    log = parse_trade_log(trades_frame([SWING]))
    result = analyse_timing(
        log,
        None,
        mode="day",
        day_timezone="UTC",
        draws=10,
        bootstrap_replications=10,
        mean_block_length=1,
        confidence_level=0.95,
        seed=1,
    )
    assert result.status == "unavailable" and result.reason == "no price file"


def test_tercile_labels_balance_and_ties():
    labels = tercile_labels(np.arange(10.0))
    assert np.bincount(labels).tolist() == [4, 3, 3]
    tied = tercile_labels(np.zeros(9))
    assert np.bincount(tied).tolist() == [3, 3, 3]
    assert tied.tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2]  # stable: exit order


def test_between_sum_of_squares_by_hand():
    pnl = np.array([1.0, 1.0, 2.0, 2.0, 6.0, 6.0])
    labels = np.array([0, 0, 1, 1, 2, 2])
    # Grand mean 3: 2*(1-3)^2 + 2*(2-3)^2 + 2*(6-3)^2 = 8 + 2 + 18.
    assert between_sum_of_squares(pnl, labels) == pytest.approx(28.0)


def test_tercile_split_finds_a_planted_holding_period_effect():
    rng = np.random.default_rng(2)
    holding = rng.uniform(1.0, 100.0, 300)
    pnl = rng.normal(0.0, 1.0, 300) + (holding > 66.0) * 1.0
    split = split_by_terciles(
        pnl,
        holding,
        variable_name="holding_period_hours",
        source="test",
        labels_text=("short", "medium", "long"),
        bootstrap_replications=200,
        mean_block_length=1,
        confidence_level=0.95,
        permutation_draws=500,
        seed=3,
    )
    assert split.permutation_p_value == pytest.approx(1.0 / 501.0)
    assert split.rows[2].expectancy.lower > split.rows[0].expectancy.upper
    assert sum(row.count for row in split.rows) == 300


def test_trailing_volatility_ignores_the_entry_bar_and_later():
    log = timing_log(1, trades=30)
    trades = parse_trade_log(to_strings(log.trades))
    prices = parse_price_table(to_strings(log.prices))
    last = int(np.argmax(trades.entry_time.asi8))
    entry = trades.entry_time[last]
    before = trailing_volatility(trades, prices, 20)[last]
    stamps = pd.DatetimeIndex(log.prices["timestamp"])
    later = log.prices.copy()
    later.loc[stamps >= entry, "price"] *= 1.5  # the entry bar and everything after
    after = trailing_volatility(trades, parse_price_table(to_strings(later)), 20)[last]
    assert after == before
    earlier = log.prices.copy()
    position = int(np.flatnonzero(stamps < entry)[-3])
    earlier.loc[position, "price"] *= 1.01  # inside the 20-bar look-back
    moved = trailing_volatility(trades, parse_price_table(to_strings(earlier)), 20)[
        last
    ]
    assert moved != before


def test_cost_curve_is_linear_and_break_even_exact():
    notional = np.array([1000.0, 2000.0, 3000.0])
    net = np.array([3.0, -1.0, 4.0])
    # mean(net) = 2, mean(notional) = 2000 -> 2 / 2000 = 1e-3 = 10 bps.
    assert break_even_added_cost_bps(net, notional) == pytest.approx(10.0)
    assert np.mean(with_added_cost(net, notional, 10.0)) == pytest.approx(
        0.0, abs=1e-12
    )
    rng = np.random.default_rng(4)
    notional = rng.uniform(5_000, 15_000, 400)
    net = rng.normal(0.0012, 0.004, 400) * notional
    gross = net + 0.0002 * notional
    means = np.array([np.mean(net), np.mean(net)])
    costs = analyse_costs(
        net,
        gross,
        notional,
        span_years=1.0,
        declared_trials=1,
        confidence_level=0.95,
        trial_sharpe_std=None,
        grid_bps=(0.0, 5.0, 10.0),
        bootstrap_pnl_means=np.full(50, np.mean(net)),
        bootstrap_notional_means=np.full(50, np.mean(notional)),
    )
    del means
    slope = np.diff([p.expectancy for p in costs.curve]) / np.diff(
        [p.added_cost_bps for p in costs.curve]
    )
    np.testing.assert_allclose(slope, -1e-4 * np.mean(notional), rtol=1e-9)
    assert costs.gross_break_even_cost_bps == pytest.approx(
        costs.break_even_added_cost_bps.point + costs.fees_paid_bps
    )
    assert costs.fees_paid_bps == pytest.approx(2.0)
    lost = costs.evidence_lost_at_added_cost_bps
    assert lost is not None and 0.0 < lost < costs.break_even_added_cost_bps.point

    def verdict(cost: float) -> str:
        return assess_luck_vs_skill(
            with_added_cost(net, notional, cost), span_years=1.0, declared_trials=1
        ).verdict

    assert verdict(lost - 0.002) == EVIDENCE
    assert verdict(lost) != EVIDENCE


def test_sizing_contribution_is_the_population_covariance():
    rng = np.random.default_rng(5)
    notional = rng.uniform(1_000, 9_000, 200)
    net_return = rng.normal(0.0, 0.01, 200) + 2e-6 * (notional - 5_000)
    net = net_return * notional
    fixed = fixed_size_pnl(net_return, notional)
    covariance = np.mean(
        (notional - notional.mean()) * (net_return - net_return.mean())
    )
    assert np.mean(net) - np.mean(fixed) == pytest.approx(covariance, rel=1e-9)


def test_constant_size_has_zero_sizing_contribution():
    net = np.random.default_rng(6).normal(1.0, 5.0, 100)
    notional = np.full(100, 10_000.0)
    shared = {"fixed_size": np.full(20, net.mean()), "sizing": np.zeros(20)}
    from backtest_auditor.edge_audit.metrics import percentile_interval

    actual = percentile_interval(
        net.mean(), np.full(20, net.mean()), confidence_level=0.95
    )
    result = analyse_sizing(
        net,
        notional,
        span_years=1.0,
        declared_trials=1,
        confidence_level=0.95,
        trial_sharpe_std=None,
        bootstrap=shared,
        actual_expectancy=actual,
        permutation_draws=50,
        seed=1,
    )
    assert result.sizing_contribution_total == pytest.approx(0.0, abs=1e-9)
    assert result.permutation_p_value == 1.0
    assert result.size_return_correlation is None


def test_cusum_page_hinkley_and_sprt_by_hand():
    np.testing.assert_allclose(
        cusum_lower(np.array([-1.0, -1.0, 0.5, -2.0]), 0.25), [0.75, 1.5, 0.75, 2.5]
    )
    # PH: running means 1, 0, -1/3; cumulative 0.25, -0.5, -0.9167; peak 0.25.
    np.testing.assert_allclose(
        page_hinkley_decrease(np.array([1.0, -1.0, -1.0]), 0.25),
        [0.0, 0.75, 0.25 - (-0.5 + (-1.0 + 1.0 / 3.0 + 0.25))],
    )
    upper = math.log(0.9 / 0.05)
    alarm, path, accepted = sprt_decay(np.full(10, -2.0), 0.5, 0.05, 0.10)
    # Each step adds -0.5 * -2 - 0.125 = 0.875; 4 * 0.875 = 3.5 >= ln 18 = 2.89.
    assert alarm == 3 and accepted == 0 and path[-1] >= upper
    alarm, path, accepted = sprt_decay(np.full(10, 1.0), 0.5, 0.05, 0.10)
    # Each step adds -0.625; -2.5 <= ln(0.1/0.95) = -2.25 after 4 steps, then restart.
    assert alarm is None and accepted == 2
    assert first_crossing(np.array([0.1, 0.2, 0.9, 2.0]), 0.5) == 2
    assert first_crossing(np.array([0.1]), 0.5) is None


def test_cusum_and_page_hinkley_match_plain_loops():
    z = np.random.default_rng(7).normal(size=(3, 50))
    batch_cusum = cusum_lower(z, 0.2)
    batch_ph = page_hinkley_decrease(z, 0.2)
    for row in range(3):
        state, expected = 0.0, []
        for value in z[row]:
            state = max(0.0, state - value - 0.2)
            expected.append(state)
        np.testing.assert_allclose(batch_cusum[row], expected)
        total = cumulative = peak = 0.0
        expected = []
        for t, value in enumerate(z[row], start=1):
            total += value
            cumulative += value - total / t + 0.2
            peak = max(peak, cumulative)
            expected.append(peak - cumulative)
        np.testing.assert_allclose(batch_ph[row], expected)


def test_rolling_expectancy_by_hand():
    np.testing.assert_allclose(
        rolling_expectancy(np.array([1.0, 2.0, 3.0, 6.0]), 2), [1.5, 2.5, 4.5]
    )
    assert rolling_expectancy(np.array([1.0]), 2).size == 0


def test_table_thresholds_are_monotone_and_refuse_points_outside_the_table():
    common = dict(reference_trades=60, parameter=0.3)
    for name in ("cusum", "page_hinkley", "mixture_sprt"):
        loose = threshold(name, alpha=0.2, horizon=120, **common)
        strict = threshold(name, alpha=0.05, horizon=120, **common)
        longer = threshold(name, alpha=0.05, horizon=1200, **common)
        assert strict > loose and longer > strict, name
    with pytest.raises(ValueError, match="horizon"):
        threshold("cusum", alpha=0.05, horizon=20_000, **common)
    with pytest.raises(ValueError, match="α"):
        threshold("cusum", alpha=0.3, horizon=120, **common)
    with pytest.raises(ValueError, match="shift"):
        threshold("cusum", alpha=0.05, horizon=120, reference_trades=60, parameter=5.0)
    with pytest.raises(KeyError):
        threshold("ewma", alpha=0.05, horizon=120, **common)


def test_rolling_drop_and_mixture_sprt_by_hand():
    z = np.array([-1.0, 0.5, -2.0, 1.0])
    # Windows of 2: (-1 + 0.5), (0.5 - 2), (-2 + 1); D = -sum / sqrt(2).
    expected = [-np.inf, 0.5 / math.sqrt(2), 1.5 / math.sqrt(2), 1.0 / math.sqrt(2)]
    np.testing.assert_allclose(rolling_drop(z, 2), expected)
    assert np.all(rolling_drop(z, 5) == -np.inf)
    # Mixture SPRT against a numerical integral of the likelihood ratio.
    tau = 0.4
    path = mixture_sprt_log_lr(z, tau)
    grid = np.linspace(0.0, 8.0 * tau, 200_001)
    prior = 2.0 / (tau * math.sqrt(2.0 * math.pi)) * np.exp(-0.5 * (grid / tau) ** 2)
    for t in range(z.size):
        total = float(np.sum(z[: t + 1]))
        ratio = np.exp(-grid * total - (t + 1) * grid**2 / 2.0)
        integral = trapezoid(ratio * prior, grid)
        assert path[t] == pytest.approx(math.log(integral), abs=1e-6)


def test_decay_statuses():
    options = dict(
        reference_trades=None,
        shift_sigma=None,
        false_alarm_probability=0.05,
        horizon=1000,
        rolling_window=None,
        bootstrap_replications=50,
        mean_block_length=1,
        confidence_level=0.95,
        seed=1,
    )
    short = analyse_decay(np.ones(40), tuple("t" * 40), **options)
    assert short.status == "unavailable"
    losing = np.random.default_rng(1).normal(-0.5, 1.0, 200)
    result = analyse_decay(losing, tuple(str(i) for i in range(200)), **options)
    assert result.status == "no_reference_edge" and result.detectors == ()
    assert result.monitored_minus_reference is not None
