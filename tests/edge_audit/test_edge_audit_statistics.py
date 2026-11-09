"""Trade metrics, bootstrap intervals and luck-vs-skill, against hand values
and against independent V1 code paths."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest
from scipy import stats

import backtest_auditor.edge_audit.metrics as metrics_module
from backtest_auditor.edge_audit.metrics import (
    bootstrap_distributions,
    expectancy,
    percentile_interval,
    profit_factor,
    win_rate,
)
from backtest_auditor.edge_audit.skill import (
    EVIDENCE,
    INSUFFICIENT,
    NO_EVIDENCE,
    assess_luck_vs_skill,
    deflated_min_track_record,
    null_trial_sharpe_std,
    sharpe_t_statistic,
)
from backtest_auditor.statistics.deflated_sharpe import (
    _expected_maximum_standard_normal,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:A future version of pandas will return a BaseOffset"
)

EXAMPLE = np.array([120.0, -80.0, 50.0, -40.0, 0.0, 150.0, -60.0, 30.0])


def test_expectancy_profit_factor_win_rate_by_hand():
    # Sum 170 over 8 trades; wins 120+50+150+30 = 350; losses 80+40+60 = 180.
    assert expectancy(EXAMPLE) == pytest.approx(21.25)
    assert profit_factor(EXAMPLE) == pytest.approx(350.0 / 180.0)
    assert win_rate(EXAMPLE) == pytest.approx(4 / 8)  # the 0.0 trade is not a win


def test_profit_factor_edges():
    assert profit_factor(np.array([1.0, 2.0])) == math.inf
    assert math.isnan(profit_factor(np.array([0.0, 0.0])))
    assert profit_factor(np.array([-1.0, 0.0])) == 0.0


def test_bootstrap_uses_the_v1_resampler(monkeypatch):
    calls = []
    original = metrics_module.stationary_bootstrap_indices

    def spy(count, *, mean_block_length, rng):
        calls.append((count, mean_block_length))
        return original(count, mean_block_length=mean_block_length, rng=rng)

    monkeypatch.setattr(metrics_module, "stationary_bootstrap_indices", spy)
    bootstrap_distributions(
        8,
        {"mean": lambda idx: float(np.mean(EXAMPLE[idx]))},
        replications=5,
        mean_block_length=3,
        seed=1,
    )
    assert calls == [(8, 3)] * 5


def test_bootstrap_is_deterministic_and_centred():
    rng = np.random.default_rng(4)
    values = rng.normal(2.0, 1.0, 400)
    run = lambda seed: bootstrap_distributions(  # noqa: E731
        values.size,
        {"mean": lambda idx: float(np.mean(values[idx]))},
        replications=400,
        mean_block_length=1,
        seed=seed,
    )["mean"]
    first, second = run(9), run(9)
    np.testing.assert_array_equal(first, second)
    interval = percentile_interval(float(values.mean()), first, confidence_level=0.95)
    # Bootstrap SE of a mean ~ s / sqrt(n) = 0.05.
    assert interval.standard_error == pytest.approx(values.std(ddof=1) / 20.0, rel=0.15)
    assert interval.lower < values.mean() < interval.upper
    assert interval.excludes_zero()


def test_percentile_interval_keeps_infinite_profit_factor_resamples():
    draws = np.array([1.0, 2.0, 3.0, np.inf, np.inf, np.nan])
    interval = percentile_interval(2.0, draws, confidence_level=0.9)
    assert interval.valid_replications == 5
    assert interval.upper is None and interval.upper_unbounded is True
    # Lower tail 0.05 of 5 sorted values: position 0.05 * 4 = 0.2 -> 1 + 0.2 * (2 - 1).
    assert interval.lower == pytest.approx(1.2)
    assert interval.standard_error is None


def test_t_statistic_is_sharpe_times_root_t_and_equals_the_one_sample_t():
    rng = np.random.default_rng(11)
    values = rng.normal(0.1, 1.0, 250)
    sharpe, t = sharpe_t_statistic(values)
    assert t == pytest.approx(sharpe * math.sqrt(250), rel=1e-15)
    assert t == pytest.approx(stats.ttest_1samp(values, 0.0).statistic, rel=1e-12)


def test_dsr_at_one_trial_is_the_null_z_and_plug_in_dsr_is_v1_psr():
    rng = np.random.default_rng(5)
    values = rng.normal(0.15, 1.0, 300)
    one = assess_luck_vs_skill(values, span_years=1.0, declared_trials=1)
    assert one.expected_max_standard_normal == 0.0
    # Verdict DSR: SE under H0 is 1/sqrt(T-1), so DSR = Phi(SR * sqrt(T-1)).
    assert one.null_standard_error == pytest.approx(1.0 / math.sqrt(299))
    assert one.dsr == pytest.approx(
        NormalDist().cdf(one.sharpe_per_trade * math.sqrt(299)), rel=1e-12
    )
    # Classical (plug-in) DSR at N = 1 is V1's PSR against SR* = 0.
    assert one.dsr_plug_in == one.psr_vs_zero
    dsrs = [
        assess_luck_vs_skill(values, span_years=1.0, declared_trials=n).dsr
        for n in (1, 2, 10, 100, 1000)
    ]
    assert all(a > b for a, b in zip(dsrs, dsrs[1:]))


def test_both_dsrs_match_the_formula_with_v1_expected_maximum():
    rng = np.random.default_rng(6)
    values = rng.normal(0.2, 1.0, 200)
    result = assess_luck_vs_skill(values, span_years=0.8, declared_trials=25)
    sigma = 1.0 / math.sqrt(200 - 1)
    expected_max = sigma * _expected_maximum_standard_normal(25)
    assert result.trial_sharpe_std == pytest.approx(sigma)
    assert result.expected_max_sharpe_per_trade == pytest.approx(
        expected_max, rel=1e-12
    )
    z = (result.sharpe_per_trade - expected_max) / sigma  # null SE = sigma here
    assert result.dsr == pytest.approx(NormalDist().cdf(z), rel=1e-12)
    assert result.dsr_test_statistic == pytest.approx(z, rel=1e-12)
    # Plug-in SE is V1's: sqrt((1 - g3*SR + (g4 - 1)/4*SR^2) / (T - 1)).
    sr = result.sharpe_per_trade
    variance = (
        1.0
        - result.sample_skewness * sr
        + (result.sample_pearson_kurtosis - 1.0) / 4.0 * sr**2
    )
    assert result.sharpe_standard_error == pytest.approx(math.sqrt(variance / 199))
    plug_in_z = (sr - expected_max) / result.sharpe_standard_error
    assert result.dsr_plug_in == pytest.approx(NormalDist().cdf(plug_in_z), rel=1e-12)


def test_skew_that_moves_with_sharpe_makes_the_plug_in_dsr_larger():
    # A lucky positive outlier raises SR and the sample skewness together.
    rng = np.random.default_rng(12)
    values = rng.standard_t(3, 250)
    values -= values.mean()  # SR exactly 0 ...
    values[np.argmax(values)] += 15.0  # ... until one lucky outlier
    result = assess_luck_vs_skill(values, span_years=1.0, declared_trials=1)
    assert result.sample_skewness > 0.5 and result.sharpe_per_trade > 0.0
    assert result.sharpe_standard_error < result.null_standard_error
    assert result.dsr_plug_in > result.dsr


def test_statistics_are_invariant_to_the_pnl_scale():
    rng = np.random.default_rng(7)
    values = rng.standard_t(4, 150) + 0.3
    small = assess_luck_vs_skill(values, span_years=2.0, declared_trials=7)
    large = assess_luck_vs_skill(values * 12345.0, span_years=2.0, declared_trials=7)
    for name in ("sharpe_per_trade", "psr_vs_zero", "dsr", "sample_pearson_kurtosis"):
        assert getattr(large, name) == pytest.approx(getattr(small, name), rel=1e-9)
    assert large.min_track_record_trades == small.min_track_record_trades


def test_declared_cross_trial_spread_is_used_and_labelled():
    values = np.random.default_rng(8).normal(0.2, 1.0, 200)
    declared = assess_luck_vs_skill(
        values, span_years=1.0, declared_trials=10, trial_sharpe_std=0.0
    )
    assert declared.trial_sharpe_std_source == "declared"
    assert declared.expected_max_sharpe_per_trade == 0.0
    assert declared.dsr_plug_in == pytest.approx(declared.psr_vs_zero)
    assert declared.dsr == pytest.approx(
        NormalDist().cdf(declared.sharpe_per_trade * math.sqrt(199))
    )


def test_trades_needed_for_a_declared_spread_come_from_v1_mintrl():
    values = np.random.default_rng(13).normal(0.15, 1.0, 120)
    sigma, trials, level = 0.05, 8, 0.95
    result = assess_luck_vs_skill(
        values, span_years=1.0, declared_trials=trials, trial_sharpe_std=sigma
    )
    benchmark = sigma * _expected_maximum_standard_normal(trials)
    z = NormalDist().inv_cdf(level)
    sr = result.sharpe_per_trade
    assert sr > benchmark
    # V1 MinTRL with variance adjustment 1: 1 + (z / (SR - SR*))^2.
    assert result.deflated_min_track_record_trades == max(
        4, math.ceil(1.0 + (z / (sr - benchmark)) ** 2)
    )


def test_deflated_min_track_record_is_where_dsr_crosses_the_level():
    sharpe, variance, n_trials, level = 0.12, 1.3, 20, 0.95
    e_n = _expected_maximum_standard_normal(n_trials)
    needed = deflated_min_track_record(sharpe, variance, e_n, level)

    def dsr_at(trades: int) -> float:
        se = math.sqrt(variance / (trades - 1))
        return NormalDist().cdf((sharpe - e_n / math.sqrt(trades - 1)) / se)

    assert dsr_at(needed) >= level > dsr_at(needed - 1)
    # With one trial it is V1's MinTRL: 1 + V (z / SR)^2.
    z = NormalDist().inv_cdf(level)
    assert deflated_min_track_record(sharpe, variance, 0.0, level) == math.ceil(
        1.0 + variance * (z / sharpe) ** 2
    )
    assert deflated_min_track_record(-0.1, variance, e_n, level) is None


def test_null_spread_is_the_standard_error_at_zero_sharpe():
    assert null_trial_sharpe_std(101) == pytest.approx(0.1)


def test_verdicts():
    rng = np.random.default_rng(10)
    strong = rng.normal(0.5, 1.0, 200)
    assert (
        assess_luck_vs_skill(strong, span_years=1.0, declared_trials=1).verdict
        == EVIDENCE
    )
    weak = rng.normal(0.0, 1.0, 200) - 0.05
    assert (
        assess_luck_vs_skill(weak, span_years=1.0, declared_trials=1).verdict
        == NO_EVIDENCE
    )
    short = assess_luck_vs_skill(strong[:20], span_years=1.0, declared_trials=1)
    assert short.verdict == INSUFFICIENT and "minimum" in short.verdict_reason
    flat = assess_luck_vs_skill(np.full(50, 3.0), span_years=1.0, declared_trials=1)
    assert flat.verdict == INSUFFICIENT and flat.sharpe_per_trade is None
    with pytest.raises(ValueError):
        assess_luck_vs_skill(strong, span_years=1.0, declared_trials=0)


def test_the_verdict_goes_through_v1_functions(monkeypatch):
    """Fails if skill.py stops calling V1 and computes these itself."""

    import backtest_auditor.edge_audit.skill as skill_module

    calls: dict[str, int] = {}

    def spy(name):
        original = getattr(skill_module, name)

        def wrapper(*args, **kwargs):
            calls[name] = calls.get(name, 0) + 1
            return original(*args, **kwargs)

        monkeypatch.setattr(skill_module, name, wrapper)

    for name in (
        "calculate_annualized_statistics",
        "calculate_distribution_statistics",
        "calculate_sharpe_uncertainty",
        "calculate_track_record_length",
        "_calculate_scenario",
    ):
        spy(name)
    values = np.random.default_rng(14).normal(0.2, 1.0, 150)
    assess_luck_vs_skill(values, span_years=1.0, declared_trials=1)
    # SR, moments, PSR, MinTRL (classical + the verdict's trades needed),
    # and _calculate_scenario twice (verdict SE and plug-in SE).
    assert calls == {
        "calculate_annualized_statistics": 1,
        "calculate_distribution_statistics": 1,
        "calculate_sharpe_uncertainty": 1,
        "calculate_track_record_length": 2,
        "_calculate_scenario": 2,
    }


def test_the_verdict_follows_v1s_sharpe_ratio(monkeypatch):
    """Shift V1's SR on the way out: the verdict must move with it."""

    import dataclasses

    import backtest_auditor.edge_audit.skill as skill_module

    values = np.random.default_rng(17).normal(0.05, 1.0, 400)
    before = assess_luck_vs_skill(values, span_years=1.0, declared_trials=1)
    original = skill_module.calculate_sharpe_uncertainty

    def shifted(*args, **kwargs):
        result = original(*args, **kwargs)
        return dataclasses.replace(
            result, period_sharpe_ratio=result.period_sharpe_ratio + 0.05
        )

    monkeypatch.setattr(skill_module, "calculate_sharpe_uncertainty", shifted)
    after = assess_luck_vs_skill(values, span_years=1.0, declared_trials=1)
    assert after.sharpe_per_trade == pytest.approx(before.sharpe_per_trade + 0.05)
    assert after.dsr == pytest.approx(
        NormalDist().cdf(after.sharpe_per_trade * math.sqrt(399)), rel=1e-12
    )
    assert after.dsr > before.dsr
    assert after.t_statistic == before.t_statistic  # t stays the local identity


def test_the_verdict_sharpe_ratio_is_v1s_and_t_agrees_with_it():
    from backtest_auditor.edge_audit.skill import trade_clock_series
    from backtest_auditor.statistics.annualized import calculate_annualized_statistics
    from backtest_auditor.statistics.sampling import assess_sampling
    from backtest_auditor.domain.assumptions import SharpeRatioSpec

    values = np.random.default_rng(15).standard_t(5, 300) + 0.1
    result = assess_luck_vs_skill(values, span_years=1.5, declared_trials=3)
    series = trade_clock_series(values, result.periods_per_year)
    annualized = calculate_annualized_statistics(
        series, assess_sampling(series), sharpe_spec=SharpeRatioSpec(0.0)
    )
    v1_sharpe = annualized.annualized_sharpe_ratio / math.sqrt(result.periods_per_year)
    assert result.sharpe_per_trade == v1_sharpe
    assert result.t_statistic == pytest.approx(v1_sharpe * math.sqrt(300), rel=1e-12)


def test_percentile_intervals_are_v1s_when_the_draws_are_finite(monkeypatch):
    calls = []
    original = metrics_module._metric_result

    def spy(*args, **kwargs):
        calls.append(kwargs["lower_quantile"])
        return original(*args, **kwargs)

    monkeypatch.setattr(metrics_module, "_metric_result", spy)
    percentile_interval(1.0, np.array([0.5, 1.0, 2.0]), confidence_level=0.9)
    percentile_interval(1.0, np.array([0.5, np.inf, 2.0]), confidence_level=0.9)
    assert calls == [pytest.approx(0.05)]  # only the finite distribution


def test_trades_needed_never_falls_below_the_verdict_minimum():
    values = np.random.default_rng(16).normal(0.8, 1.0, 20)
    result = assess_luck_vs_skill(values, span_years=0.1, declared_trials=1)
    assert result.verdict == INSUFFICIENT
    assert result.deflated_min_track_record_trades == 30
