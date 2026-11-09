"""Adversarial tests for statistics.bootstrap (moving-block percentile intervals).

Reference: reference_stats.moving_block_bootstrap, arch.bootstrap.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("arch")
from arch.bootstrap import MovingBlockBootstrap, StationaryBootstrap

from .conftest import (
    annualized_and_distribution,
    bootstrap_spec,
    make_series,
    psr_spec,
    ref,
    serial_adjustment_spec,
)

from backtest_auditor.domain.enums import BootstrapMetric, BootstrapStatus
from backtest_auditor.statistics.bootstrap import (
    _moving_block_resample,
    calculate_bootstrap_confidence_intervals,
)
from backtest_auditor.statistics.serial_adjustment import calculate_serial_adjustment
from backtest_auditor.statistics.sharpe_uncertainty import calculate_sharpe_uncertainty


def _run(r, *, ppy=252, rf=0.0, spec=None, hac_lag=None):
    series = make_series(r, periods_per_year=ppy)
    sampling, annualized, dist = annualized_and_distribution(series, rf)
    adjustment = None
    if hac_lag is not None:
        unc = calculate_sharpe_uncertainty(
            annualized, dist, psr_spec=psr_spec(0.0, None)
        )
        adjustment = calculate_serial_adjustment(
            series,
            annualized,
            unc,
            spec=serial_adjustment_spec(hac_lag),
            psr_spec=psr_spec(0.0, None),
        )
    return calculate_bootstrap_confidence_intervals(
        series, sampling, annualized, adjustment, spec=spec or bootstrap_spec()
    )


def _metric(result, metric):
    return next(m for m in result.metrics if m.metric is metric)


def test_resampler_draws_overlapping_blocks_with_replacement():
    """Künsch MBB: ⌈n/b⌉ starts uniform on [0, n−b], concatenated, truncated to n."""
    x = np.arange(100, dtype=float)
    rng = np.random.default_rng(1)
    sample = _moving_block_resample(
        x,
        block_length=7,
        blocks_per_replication=math.ceil(100 / 7),
        random_generator=rng,
    )
    assert sample.size == 100
    for i in range(0, 98, 7):
        block = sample[i : i + 7]
        assert np.all(np.diff(block) == 1.0), "a block is not a contiguous run"
        assert 0 <= block[0] <= 93


def test_percentile_interval_matches_reference_given_same_resampling_rng():
    """The reference bootstrap mimics V1's RNG consumption exactly (same draws),
    so the intervals must match to float precision — this pins the arithmetic,
    not just the distribution."""
    rng = np.random.default_rng(2)
    r = 0.01 * rng.standard_normal(300) + 0.0004
    result = _run(r, spec=bootstrap_spec(replications=500, block_length=5, seed=11))
    sr = _metric(result, BootstrapMetric.PERIOD_SHARPE_RATIO)
    samples = ref.moving_block_bootstrap(
        r, lambda s: s.mean() / s.std(ddof=1), 5, 500, 11
    )
    lo, hi = ref.percentile_interval(samples, 0.95)
    assert sr.lower_bound == pytest.approx(lo, rel=1e-12)
    assert sr.upper_bound == pytest.approx(hi, rel=1e-12)
    assert sr.bootstrap_standard_error == pytest.approx(samples.std(ddof=1), rel=1e-12)
    mean = _metric(result, BootstrapMetric.PERIOD_MEAN_RETURN)
    msamples = ref.moving_block_bootstrap(r, np.mean, 5, 500, 11)
    assert mean.lower_bound == pytest.approx(np.quantile(msamples, 0.025), rel=1e-12)


def test_block_length_changes_the_interval_on_an_autocorrelated_series():
    """AR(1) with φ = 0.6: block length 1 (iid bootstrap) vs 20 must give different
    Sharpe intervals; the longer block should be wider because it preserves the
    positive dependence that inflates the variance of the mean."""
    rng = np.random.default_rng(3)
    n = 1000
    e = 0.01 * rng.standard_normal(n)
    r = np.empty(n)
    r[0] = e[0]
    for t in range(1, n):
        r[t] = 0.6 * r[t - 1] + e[t]
    r += 0.0003
    short = _metric(
        _run(r, spec=bootstrap_spec(replications=800, block_length=1, seed=5)),
        BootstrapMetric.PERIOD_SHARPE_RATIO,
    )
    long = _metric(
        _run(r, spec=bootstrap_spec(replications=800, block_length=20, seed=5)),
        BootstrapMetric.PERIOD_SHARPE_RATIO,
    )
    width_short = short.upper_bound - short.lower_bound
    width_long = long.upper_bound - long.lower_bound
    assert width_long > 1.5 * width_short, (width_short, width_long)


def test_moving_block_and_stationary_bootstrap_differ_on_autocorrelated_series():
    """V1 has only the moving-block method; arch provides both. Documents that the
    choice matters (the stationary bootstrap draws geometric block lengths)."""
    rng = np.random.default_rng(4)
    n = 800
    e = rng.standard_normal(n)
    r = np.empty(n)
    r[0] = e[0]
    for t in range(1, n):
        r[t] = 0.7 * r[t - 1] + e[t]
    stat = lambda x: x.mean() / x.std(ddof=1)  # noqa: E731
    mbb = MovingBlockBootstrap(10, r, seed=1)
    sb = StationaryBootstrap(10, r, seed=1)
    ci_m = mbb.conf_int(stat, reps=1000, method="percentile").ravel()
    ci_s = sb.conf_int(stat, reps=1000, method="percentile").ravel()
    assert not np.allclose(ci_m, ci_s, atol=1e-3)


@pytest.mark.slow
@pytest.mark.xfail(
    strict=True,
    reason="F02: method property, not a defect: this seed set covers 92.6% at nominal 95% (four disjoint sets of 500: 92.6/97.0/95.0/92.6%, pooled 94.3%, notes/evidence/f02_coverage_seeds.txt); arithmetic exact",
)
def test_ninety_five_percent_interval_coverage_on_iid_normal_sharpe():
    """500 iid-normal series, n = 500, true period Sharpe 0.08 (≈1.27 annual).
    Percentile MBB with b = 5 and 400 replications; nominal 95 %, require 93–97 %.
    (Efron percentile intervals for a ratio statistic are known to under-cover
    slightly; the band is the spec's.)"""
    true_sr = 0.08
    hits = 0
    sims = 500
    for seed in range(sims):
        rng = np.random.default_rng(10_000 + seed)
        r = 0.01 * (rng.standard_normal(500) + true_sr)
        res = _run(r, spec=bootstrap_spec(replications=400, block_length=5, seed=seed))
        m = _metric(res, BootstrapMetric.PERIOD_SHARPE_RATIO)
        hits += m.lower_bound <= true_sr <= m.upper_bound
    coverage = hits / sims
    assert 0.93 <= coverage <= 0.97, f"coverage={coverage:.3f} over {sims} simulations"


def test_coverage_with_block_length_two_on_iid_data_is_recorded():
    """The README example uses --bootstrap-block-length 2. With iid data and n = 250
    the percentile interval with b = 2 should still be close to nominal; 300 sims."""
    true_sr = 0.1
    hits = 0
    sims = 300
    for seed in range(sims):
        rng = np.random.default_rng(20_000 + seed)
        r = 0.01 * (rng.standard_normal(250) + true_sr)
        res = _run(r, spec=bootstrap_spec(replications=300, block_length=2, seed=seed))
        m = _metric(res, BootstrapMetric.PERIOD_SHARPE_RATIO)
        hits += m.lower_bound <= true_sr <= m.upper_bound
    coverage = hits / sims
    assert 0.92 <= coverage <= 0.98, f"coverage={coverage:.3f}"


def test_annualized_metrics_are_period_metrics_scaled():
    rng = np.random.default_rng(6)
    r = 0.01 * rng.standard_normal(300) + 0.0004
    res = _run(r, ppy=252)
    p = _metric(res, BootstrapMetric.PERIOD_SHARPE_RATIO)
    a = _metric(res, BootstrapMetric.IID_ANNUALIZED_SHARPE_RATIO)
    assert a.lower_bound == pytest.approx(p.lower_bound * math.sqrt(252), rel=1e-12)
    assert a.upper_bound == pytest.approx(p.upper_bound * math.sqrt(252), rel=1e-12)
    pm = _metric(res, BootstrapMetric.PERIOD_MEAN_RETURN)
    am = _metric(res, BootstrapMetric.ANNUALIZED_ARITHMETIC_MEAN_RETURN)
    assert am.lower_bound == pytest.approx(pm.lower_bound * 252, rel=1e-12)


def test_hac_adjusted_sharpe_replicates_use_the_replicate_autocorrelation():
    """Each replicate's HAC Sharpe must be recomputed from that replicate's own
    Bartlett ratio, not the point estimate's."""
    rng = np.random.default_rng(7)
    n = 400
    e = 0.01 * rng.standard_normal(n)
    r = np.empty(n)
    r[0] = e[0]
    for t in range(1, n):
        r[t] = 0.4 * r[t - 1] + e[t]
    r += 0.0005
    res = _run(
        r, spec=bootstrap_spec(replications=300, block_length=10, seed=9), hac_lag=5
    )
    hac = _metric(res, BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO)
    assert hac.status.value == "eligible", hac.status

    def stat(x):
        sr = x.mean() / x.std(ddof=1)
        ratio = ref.bartlett_lrv_ratio(x, 5)
        return sr * math.sqrt(252 / ratio)

    samples = ref.moving_block_bootstrap(r, stat, 10, 300, 9)
    lo, hi = ref.percentile_interval(samples, 0.95)
    assert hac.lower_bound == pytest.approx(lo, rel=1e-9)
    assert hac.upper_bound == pytest.approx(hi, rel=1e-9)


def test_block_length_not_below_n_is_refused():
    rng = np.random.default_rng(8)
    r = 0.01 * rng.standard_normal(20)
    res = _run(r, spec=bootstrap_spec(block_length=20))
    assert res.status is BootstrapStatus.BLOCK_LENGTH_NOT_BELOW_OBSERVATION_COUNT


def test_point_estimate_is_the_full_sample_statistic_not_bootstrap_mean():
    rng = np.random.default_rng(9)
    r = 0.01 * rng.standard_normal(300) + 0.0004
    res = _run(r)
    p = _metric(res, BootstrapMetric.PERIOD_SHARPE_RATIO)
    assert p.point_estimate == pytest.approx(ref.period_sharpe(r), rel=1e-12)
