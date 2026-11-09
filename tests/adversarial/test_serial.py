"""Adversarial tests for statistics.serial_dependence and statistics.serial_adjustment.

References: Ljung & Box (1978); Lo (2002) eq. 20; Newey–West/Bartlett long-run variance;
statsmodels.stats.diagnostic.acorr_ljungbox and statsmodels.tsa.stattools.acf.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("statsmodels")
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import acf as sm_acf

from .conftest import (
    annualized_and_distribution,
    make_series,
    psr_spec,
    ref,
    serial_adjustment_spec,
    serial_dependence_spec,
)

from backtest_auditor.domain.enums import SerialAdjustmentStatus
from backtest_auditor.statistics.serial_adjustment import (
    calculate_bartlett_hac_ratio,
    calculate_serial_adjustment,
)
from backtest_auditor.statistics.serial_dependence import calculate_serial_dependence
from backtest_auditor.statistics.sharpe_uncertainty import calculate_sharpe_uncertainty


def _ar1(rng, n, phi, sigma=0.01, mu=0.0):
    e = sigma * rng.standard_normal(n)
    r = np.empty(n)
    r[0] = e[0]
    for t in range(1, n):
        r[t] = phi * r[t - 1] + e[t]
    return r + mu


@pytest.mark.parametrize("seed", range(15))
@pytest.mark.parametrize("phi", [0.0, 0.3, -0.4])
def test_acf_and_ljung_box_match_statsmodels(seed, phi):
    rng = np.random.default_rng(seed)
    r = _ar1(rng, int(rng.integers(50, 600)), phi)
    L = int(rng.integers(1, 10))
    res = calculate_serial_dependence(make_series(r), spec=serial_dependence_spec(L))
    rho_sm = sm_acf(r, nlags=L, adjusted=False, fft=False)[1:]
    rho_v1 = np.asarray([a.autocorrelation for a in res.autocorrelations])
    assert np.allclose(rho_v1, rho_sm, atol=1e-12), "ACF differs from statsmodels"
    assert np.allclose(rho_v1, ref.acf(r, L), atol=1e-12)
    lb = acorr_ljungbox(r, lags=[L], return_df=True)
    assert res.ljung_box_statistic == pytest.approx(
        float(lb["lb_stat"].iloc[0]), rel=1e-9
    ), (
        f"Q: V1={res.ljung_box_statistic} statsmodels={float(lb['lb_stat'].iloc[0])} (LB78)"
    )
    assert res.p_value == pytest.approx(float(lb["lb_pvalue"].iloc[0]), abs=1e-9)
    Q, p = ref.ljung_box(r, L)
    assert res.ljung_box_statistic == pytest.approx(Q, rel=1e-9)


def test_ljung_box_detection_is_two_sided_on_the_chi_square_tail():
    """Q is always compared on the upper tail; a strongly negative AR(1) must be detected."""
    rng = np.random.default_rng(99)
    r = _ar1(rng, 500, -0.5)
    res = calculate_serial_dependence(
        make_series(r), spec=serial_dependence_spec(3, 0.05)
    )
    assert res.serial_dependence_detected is True


def test_bartlett_ratio_matches_reference_and_newey_west():
    rng = np.random.default_rng(5)
    r = _ar1(rng, 400, 0.5)
    for L in (1, 3, 10):
        est, ratio = calculate_bartlett_hac_ratio(r, maximum_lag=L)
        assert ratio == pytest.approx(ref.bartlett_lrv_ratio(r, L), rel=1e-12)
        # statsmodels: Newey–West long-run variance of the demeaned series with Bartlett
        # kernel; ratio = LRV / sample variance (ddof=0) using the same autocovariances.
        from statsmodels.tsa.stattools import acovf

        g = acovf(r, nlag=L, adjusted=False, fft=False)
        nw = g[0] + 2 * sum((1 - k / (L + 1)) * g[k] for k in range(1, L + 1))
        assert ratio == pytest.approx(nw / g[0], rel=1e-12)


@pytest.mark.parametrize("phi", [0.0, 0.25, 0.5, -0.3])
def test_full_lo_horizon_equals_lo_2002_equation_20(phi):
    """With --hac-max-lag = p − 1 the Bartlett weights (1 − k/p) are exactly Lo's
    (q − k)/q, so the HAC-adjusted annualized Sharpe must equal Lo (2002) eq. 20:
    SR(q) = SR · q / √(q + 2 Σ_{k<q} (q − k) ρ_k)."""
    rng = np.random.default_rng(abs(int(phi * 100)) + 7)
    q = 12  # monthly to annual keeps the lag count small enough to be meaningful
    r = _ar1(rng, 600, phi, mu=0.002)
    series = make_series(r, freq="MS", periods_per_year=q)
    _, annualized, dist = annualized_and_distribution(series, 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    adj = calculate_serial_adjustment(
        series,
        annualized,
        unc,
        spec=serial_adjustment_spec(q - 1),
        psr_spec=psr_spec(0.0, None),
    )
    assert adj.status is SerialAdjustmentStatus.ELIGIBLE, adj.status
    assert adj.full_lo_annual_horizon is True
    expected = ref.lo_annualized_sharpe(r, q)
    assert adj.hac_adjusted_annualized_sharpe_ratio == pytest.approx(
        expected, rel=1e-9
    ), f"V1={adj.hac_adjusted_annualized_sharpe_ratio} Lo(2002) eq.20={expected}"


def test_truncated_bandwidth_is_not_lo_and_is_flagged():
    """AR(1) φ = 0.4, n = 600, daily (q = 252). The population Lo factor is
    η = q/√(q + 2Σ(q−k)φ^k). V1's 5-lag Bartlett ratio is a truncated estimate; Lo's
    full 251-lag sum from sample autocorrelations is unbiased but very noisy
    (each ρ̂_k has sd ≈ 1/√n). The test asserts V1 is within 15 % of the population
    truth and records the full-horizon sample estimate for comparison."""
    rng = np.random.default_rng(8)
    phi, q = 0.4, 252
    r = _ar1(rng, 600, phi, mu=0.002)
    series = make_series(r, periods_per_year=q)
    _, annualized, dist = annualized_and_distribution(series, 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    adj = calculate_serial_adjustment(
        series,
        annualized,
        unc,
        spec=serial_adjustment_spec(5),
        psr_spec=psr_spec(0.0, None),
    )
    assert adj.full_lo_annual_horizon is False
    sr = ref.period_sharpe(r)
    eta_pop = q / math.sqrt(q + 2 * sum((q - k) * phi**k for k in range(1, q)))
    truth = eta_pop * sr
    lo_sample = ref.lo_annualized_sharpe(r, q)
    assert abs(adj.hac_adjusted_annualized_sharpe_ratio - truth) / abs(truth) < 0.15, (
        f"5-lag HAC={adj.hac_adjusted_annualized_sharpe_ratio:.4f}, population Lo={truth:.4f}, "
        f"full-horizon sample Lo={lo_sample:.4f}"
    )


def test_hac_psr_uses_influence_function_long_run_variance():
    """σ²_HAC(SR) = Var(ψ)·ratio_ψ/(n−1), ψ_t = z_t − SR/2 (z_t² − 1), ratio_ψ the Bartlett
    long-run variance ratio of ψ. Checks the published numbers against a direct recomputation."""
    rng = np.random.default_rng(9)
    r = _ar1(rng, 500, 0.3, mu=0.001)
    series = make_series(r, periods_per_year=252)
    _, annualized, dist = annualized_and_distribution(series, 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    L = 6
    adj = calculate_serial_adjustment(
        series,
        annualized,
        unc,
        spec=serial_adjustment_spec(L),
        psr_spec=psr_spec(0.0, None),
    )
    sr = ref.period_sharpe(r)
    psi = ref.sharpe_influence(r, sr)
    ratio = ref.bartlett_lrv_ratio(psi, L)
    assert adj.sharpe_long_run_variance_ratio == pytest.approx(ratio, rel=1e-9)
    A = unc.sharpe_variance_adjustment
    se = math.sqrt(A * ratio / (len(r) - 1))
    assert adj.hac_period_sharpe_standard_error == pytest.approx(se, rel=1e-9)
    from scipy.stats import norm

    assert adj.hac_probabilistic_sharpe_ratio == pytest.approx(
        norm.cdf(sr / se), abs=1e-9
    )
    # the iid variance adjustment A and Var(ψ) with plug-in moments agree up to the
    # G1/G2 vs plug-in convention (O(1/n)); record the gap
    assert abs(A - np.var(psi)) < 0.05, (A, np.var(psi))


@pytest.mark.xfail(
    strict=True,
    reason="F07: convention, not a defect: Lo (2002) allows effective n 569 > n = 300 under negative autocorrelation; the test expects n capped and flips only if the package caps it",
)
def test_negative_autocorrelation_raises_hac_psr_and_effective_observations_above_n():
    """Lo (2002): negative autocorrelation *increases* the annualized Sharpe and shrinks
    the long-run variance. V1 then reports effective_observation_count > n and a HAC PSR
    above the iid PSR. Consistent with the theory, but the report never says that the
    adjustment *strengthened* the evidence; the test records the magnitudes."""
    rng = np.random.default_rng(10)
    r = _ar1(rng, 300, -0.5, mu=0.004)
    assert ref.period_sharpe(r) > 0
    series = make_series(r, periods_per_year=252)
    _, annualized, dist = annualized_and_distribution(series, 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    adj = calculate_serial_adjustment(
        series,
        annualized,
        unc,
        spec=serial_adjustment_spec(3),
        psr_spec=psr_spec(0.0, None),
    )
    assert adj.status is SerialAdjustmentStatus.ELIGIBLE
    assert adj.hac_probabilistic_sharpe_ratio > unc.probabilistic_sharpe_ratio
    assert adj.hac_adjusted_annualized_sharpe_ratio > annualized.annualized_sharpe_ratio
    assert adj.effective_observation_count <= len(r), (
        f"n={len(r)} but effective_observation_count={adj.effective_observation_count:.1f}; "
        f"iid PSR={unc.probabilistic_sharpe_ratio:.4f} → HAC PSR={adj.hac_probabilistic_sharpe_ratio:.4f}; "
        f"iid annual SR={annualized.annualized_sharpe_ratio:.3f} → HAC {adj.hac_adjusted_annualized_sharpe_ratio:.3f}. "
        f"Lo (2002) eq. 20 permits this; the report should say the adjustment strengthened the evidence."
    )


def test_hac_with_tiny_sample_and_max_lag_close_to_n():
    """n = 5, lag 2 (the README example): the Bartlett ratio is estimated from three
    autocovariance products. Check V1 against the reference formula and record what
    the README example publishes (effective observations vs n)."""
    r = np.array([0.0100, -0.0050, 0.0075, 0.0025, 0.0070])
    series = make_series(r, freq="D", periods_per_year=252)
    _, annualized, dist = annualized_and_distribution(series, 0.03)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    adj = calculate_serial_adjustment(
        series,
        annualized,
        unc,
        spec=serial_adjustment_spec(2),
        psr_spec=psr_spec(0.0, None),
    )
    assert adj.status is SerialAdjustmentStatus.ELIGIBLE
    assert adj.return_long_run_variance_ratio == pytest.approx(
        ref.bartlett_lrv_ratio(r, 2), rel=1e-12
    )
    psi = ref.sharpe_influence(r, unc.period_sharpe_ratio)
    assert adj.sharpe_long_run_variance_ratio == pytest.approx(
        ref.bartlett_lrv_ratio(psi, 2), rel=1e-12
    )
    assert adj.effective_observation_count == pytest.approx(
        1 + 4 / ref.bartlett_lrv_ratio(psi, 2), rel=1e-12
    )
