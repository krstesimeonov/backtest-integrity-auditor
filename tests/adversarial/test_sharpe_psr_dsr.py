"""Adversarial known-answer and property tests: Sharpe, moments, PSR, MinTRL, DSR.

Reference: reference/reference_stats.py (equations cited there).
Modules under test: statistics.annualized, statistics.distribution,
statistics.sharpe_uncertainty, statistics.track_record, statistics.deflated_sharpe.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import kurtosis, norm, skew

from .conftest import (
    annualized_and_distribution,
    dsr_spec,
    make_family,
    make_series,
    psr_spec,
    random_returns,
    ref,
)

from backtest_auditor.domain.enums import DeflatedSharpeRatioStatus, DSRTrialCountBasis
from backtest_auditor.statistics.deflated_sharpe import calculate_deflated_sharpe_ratio
from backtest_auditor.statistics.sharpe_uncertainty import calculate_sharpe_uncertainty
from backtest_auditor.statistics.track_record import calculate_track_record_length

KINDS = ("normal", "skewed", "fat")
SEEDS = range(67)  # 67 × 3 ≈ 200 series
TOL = 1e-6


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-12)


# --------------------------------------------------------------------------- #
# Sharpe and annualization
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", SEEDS)
def test_annualized_sharpe_mean_vol_match_reference(kind, seed):
    rng = np.random.default_rng(1000 + seed)
    n = int(rng.integers(60, 1500))
    ppy = int(rng.choice([12, 52, 252, 365]))
    rf = float(rng.choice([0.0, 0.01, 0.03, 0.05]))
    r = random_returns(rng, n, kind)
    series = make_series(r, periods_per_year=ppy)
    _, annualized, _ = annualized_and_distribution(series, rf)

    expected_sr = ref.annualized_sharpe(r, ppy, rf, rate_convention="geometric")
    expected_mean = ref.annualized_mean(r, ppy)
    expected_vol = ref.annualized_volatility(r, ppy)

    assert _rel(annualized.annualized_arithmetic_mean_return, expected_mean) < TOL, (
        f"annualized mean: V1={annualized.annualized_arithmetic_mean_return!r} "
        f"reference={expected_mean!r} (mean·p)"
    )
    assert _rel(annualized.annualized_sample_volatility, expected_vol) < TOL, (
        f"annualized vol: V1={annualized.annualized_sample_volatility!r} "
        f"reference={expected_vol!r} (s·√p, ddof=1)"
    )
    assert _rel(annualized.annualized_sharpe_ratio, expected_sr) < TOL, (
        f"annualized Sharpe: V1={annualized.annualized_sharpe_ratio!r} "
        f"reference={expected_sr!r} ((mean − r_f,p)/s · √p, Lo 2002 eq. 2, "
        f"geometric r_f conversion)"
    )


def test_sharpe_hand_computed_five_bar_example():
    """r = [0.01, -0.02, 0.03, 0.00, 0.02], p = 252, r_f = 0.
    mean = 0.008; s = sqrt(Σ(r−mean)²/4) = sqrt(0.00148/4) = 0.019235...;
    SR_period = 0.41590...; SR_annual = 0.41590·√252 = 6.6022..."""
    r = np.array([0.01, -0.02, 0.03, 0.00, 0.02])
    series = make_series(r, periods_per_year=252)
    _, annualized, _ = annualized_and_distribution(series, 0.0)
    s = math.sqrt(sum((x - 0.008) ** 2 for x in r) / 4)
    expected = 0.008 / s * math.sqrt(252)
    assert abs(annualized.annualized_sharpe_ratio - expected) < 1e-12, (
        f"V1={annualized.annualized_sharpe_ratio} expected={expected} (hand computation)"
    )


def test_risk_free_rate_convention_is_geometric_not_linear():
    """Documents which r_f convention V1 uses. The README says 'annual-to-period
    risk-free conversion'; the docstring in return_basis.py says effective annual.
    Asserts the geometric convention; a failure here means the convention changed."""
    rng = np.random.default_rng(3)
    r = random_returns(rng, 500, "normal")
    series = make_series(r, periods_per_year=252)
    _, annualized, _ = annualized_and_distribution(series, 0.05)
    geometric = ref.annualized_sharpe(r, 252, 0.05, rate_convention="geometric")
    linear = ref.annualized_sharpe(r, 252, 0.05, rate_convention="linear")
    assert _rel(annualized.annualized_sharpe_ratio, geometric) < TOL
    # record the size of the convention gap in the assertion message
    assert abs(geometric - linear) < 0.05, (
        f"geometric vs linear r_f conversion changes the annual Sharpe by "
        f"{geometric - linear:+.4f} (geometric={geometric:.4f}, linear={linear:.4f})"
    )


# --------------------------------------------------------------------------- #
# Moments
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", range(20))
def test_moments_match_bias_adjusted_estimators(kind, seed):
    """V1 publishes G1 and G2 (+3) [Joanes & Gill 1998] — the same as
    scipy.stats.skew/kurtosis with bias=False."""
    rng = np.random.default_rng(2000 + seed)
    r = random_returns(rng, int(rng.integers(30, 800)), kind)
    _, _, dist = annualized_and_distribution(make_series(r))
    assert _rel(dist.sample_skewness, skew(r, bias=False)) < TOL
    assert _rel(dist.sample_excess_kurtosis, kurtosis(r, bias=False)) < TOL
    assert _rel(dist.sample_skewness, ref.adjusted_skewness(r)) < TOL
    assert _rel(dist.sample_pearson_kurtosis, ref.adjusted_pearson_kurtosis(r)) < TOL


# --------------------------------------------------------------------------- #
# PSR
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", SEEDS)
def test_psr_matches_reference_given_v1_moments(kind, seed):
    """PSR = Φ[(SR − SR*)√(n−1)/√(1 − γ3 SR + (γ4−1)/4 SR²)]  [BLdP12 eq. 11],
    evaluated with the moment estimators V1 itself publishes."""
    rng = np.random.default_rng(3000 + seed)
    n = int(rng.integers(60, 1500))
    ppy = int(rng.choice([12, 52, 252, 365]))
    bench_annual = float(rng.choice([0.0, 0.5, 1.0]))
    r = random_returns(rng, n, kind, mu=0.0008)
    series = make_series(r, periods_per_year=ppy)
    _, annualized, dist = annualized_and_distribution(series, 0.0)
    unc = calculate_sharpe_uncertainty(
        annualized, dist, psr_spec=psr_spec(bench_annual, None)
    )

    sr = ref.period_sharpe(r)
    expected = ref.psr(
        sr,
        bench_annual / math.sqrt(ppy),
        n,
        dist.sample_skewness,
        dist.sample_pearson_kurtosis,
    )
    expected_se = ref.sharpe_se_period(
        sr, n, dist.sample_skewness, dist.sample_pearson_kurtosis
    )
    assert _rel(unc.period_sharpe_ratio, sr) < TOL
    assert _rel(unc.period_sharpe_standard_error, expected_se) < TOL, (
        f"period SE: V1={unc.period_sharpe_standard_error} reference={expected_se} "
        f"(√[(1 − γ3 SR + (γ4−1)/4 SR²)/(n−1)], BLdP12 eq. 10)"
    )
    assert abs(unc.probabilistic_sharpe_ratio - expected) < TOL, (
        f"PSR: V1={unc.probabilistic_sharpe_ratio} reference={expected} (BLdP12 eq. 11)"
    )


@pytest.mark.parametrize("n", [60, 250, 1000])
def test_psr_moment_estimator_convention_vs_plugin(n):
    """Bailey & López de Prado's published code uses plug-in (biased) skewness
    and kurtosis; V1 uses the bias-adjusted G1/G2. The gap is O(1/n). This test
    asserts the two PSRs agree to 1e-4 so the morning run shows how large the
    convention gap is at each n."""
    rng = np.random.default_rng(n)
    r = random_returns(rng, n, "fat", mu=0.001)
    _, annualized, dist = annualized_and_distribution(make_series(r), 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    sr = ref.period_sharpe(r)
    plugin = ref.psr(sr, 0.0, n, ref.plugin_skewness(r), ref.plugin_kurtosis(r))
    assert abs(unc.probabilistic_sharpe_ratio - plugin) < 1e-4, (
        f"n={n}: PSR with G1/G2 moments={unc.probabilistic_sharpe_ratio:.6f}, "
        f"with plug-in moments={plugin:.6f}, diff={unc.probabilistic_sharpe_ratio - plugin:+.2e}"
    )


def test_psr_hand_computed_example():
    """n = 100 obs, SR = 0.1 per period, γ3 = 0, γ4 = 3, SR* = 0 → PSR = Φ(0.1·√99/√(1+0.5·0.01)).
    Build a series with exactly SR=0.1 by construction then verify to 1e-9 using
    V1's own moments for the rest of the formula."""
    rng = np.random.default_rng(11)
    z = rng.standard_normal(100)
    z = (z - z.mean()) / z.std(ddof=1)
    r = 0.01 * (z + 0.1)  # mean 0.001, sd 0.01 → SR exactly 0.1
    _, annualized, dist = annualized_and_distribution(make_series(r), 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    assert abs(unc.period_sharpe_ratio - 0.1) < 1e-12
    A = 1 - dist.sample_skewness * 0.1 + (dist.sample_pearson_kurtosis - 1) / 4 * 0.01
    expected = norm.cdf(0.1 * math.sqrt(99) / math.sqrt(A))
    assert abs(unc.probabilistic_sharpe_ratio - expected) < 1e-9


# --------------------------------------------------------------------------- #
# MinTRL
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("seed", range(30))
def test_min_trl_matches_reference(seed):
    """MinTRL = 1 + (1 − γ3 SR + (γ4−1)/4 SR²)(Z_α/(SR − SR*))²  [BLdP12 eq. 13]."""
    rng = np.random.default_rng(4000 + seed)
    r = random_returns(rng, 400, "skewed", mu=0.001)
    _, annualized, dist = annualized_and_distribution(make_series(r), 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, 0.95))
    trl = calculate_track_record_length(unc, psr_spec=psr_spec(0.0, 0.95))
    sr = ref.period_sharpe(r)
    if sr <= 0:
        assert trl.minimum_track_record_length_observations is None
        return
    expected = ref.min_trl(
        sr, 0.0, dist.sample_skewness, dist.sample_pearson_kurtosis, 0.95
    )
    assert _rel(trl.minimum_track_record_length_observations, expected) < TOL, (
        f"MinTRL: V1={trl.minimum_track_record_length_observations} reference={expected}"
    )
    assert trl.minimum_track_record_length_years == pytest.approx(
        expected / 252, rel=TOL
    )


# --------------------------------------------------------------------------- #
# DSR
# --------------------------------------------------------------------------- #


def _noise_family(seed: int, T: int = 500, N: int = 20, ppy: int = 252):
    rng = np.random.default_rng(seed)
    M = 0.01 * rng.standard_normal((T, N))
    return M, make_family(M, periods_per_year=ppy)


@pytest.mark.parametrize("seed", range(25))
def test_dsr_matches_reference(seed):
    """DSR = PSR(SR*₀), SR*₀ = √V[SR_n]·[(1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N e))]  [BLdP14 eq. 6–8],
    with V[·] the sample variance (ddof=1) of the N trial period Sharpes."""
    M, family = _noise_family(
        5000 + seed, N=int(np.random.default_rng(seed).integers(3, 40))
    )
    result = calculate_deflated_sharpe_ratio(family, dsr_spec())
    assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE, result.status
    T, N = M.shape
    sharpes = M.mean(axis=0) / M.std(axis=0, ddof=1)
    k = int(np.argmax(sharpes))
    sel = M[:, k]
    expected = ref.dsr(
        sharpes[k],
        sharpes,
        T,
        ref.adjusted_skewness(sel),
        ref.adjusted_pearson_kurtosis(sel),
        ddof=1,
    )
    scenario = next(
        s
        for s in result.scenarios
        if s.trial_count_basis is DSRTrialCountBasis.SELECTION_ELIGIBLE
    )
    assert scenario.trial_count == N
    assert (
        _rel(
            scenario.expected_maximum_standard_normal,
            ref.expected_max_standard_normal(N),
        )
        < TOL
    )
    assert (
        _rel(
            scenario.expected_maximum_period_sharpe_ratio,
            ref.expected_max_sharpe(sharpes, N, ddof=1),
        )
        < TOL
    ), (
        f"E[max SR]: V1={scenario.expected_maximum_period_sharpe_ratio} "
        f"reference={ref.expected_max_sharpe(sharpes, N, ddof=1)} (BLdP14 eq. 7, ddof=1)"
    )
    assert abs(scenario.deflated_sharpe_ratio - expected) < TOL, (
        f"DSR: V1={scenario.deflated_sharpe_ratio} reference={expected} (BLdP14 eq. 8)"
    )


@pytest.mark.xfail(
    strict=True,
    reason="F01: convention, not a defect: the test expects the plug-in (ddof=0) cross-trial variance, the package uses ddof=1 (DSR 0.392 vs 0.427); flips only if that convention changes",
)
def test_dsr_variance_convention_ddof():
    """Reports the gap between ddof=1 (V1) and ddof=0 (plug-in V[SR_n], as in
    López de Prado's published code) for N = 10 trials."""
    M, family = _noise_family(77, N=10)
    result = calculate_deflated_sharpe_ratio(family, dsr_spec())
    scenario = result.scenarios[0]
    sharpes = M.mean(axis=0) / M.std(axis=0, ddof=1)
    k = int(np.argmax(sharpes))
    sel = M[:, k]
    d0 = ref.dsr(
        sharpes[k],
        sharpes,
        M.shape[0],
        ref.adjusted_skewness(sel),
        ref.adjusted_pearson_kurtosis(sel),
        ddof=0,
    )
    assert abs(scenario.deflated_sharpe_ratio - d0) < 1e-3, (
        f"DSR ddof=1 (V1)={scenario.deflated_sharpe_ratio:.6f} vs ddof=0={d0:.6f}; "
        f"diff={scenario.deflated_sharpe_ratio - d0:+.2e}. Convention, not an error, but it "
        f"must be stated in the report."
    )


def test_dsr_monotone_non_increasing_in_trial_count():
    """Holding the family fixed, E[max Z_N] is increasing in N, so DSR must be
    non-increasing in N. Uses the user-supplied effective-count scenario to vary N."""
    M, family = _noise_family(31, N=30)
    previous = None
    for N in range(1, 31):
        result = calculate_deflated_sharpe_ratio(
            family,
            dsr_spec(
                effective_independent_trial_count=N,
                effective_trial_count_methodology="test",
            ),
        )
        scenario = next(
            s
            for s in result.scenarios
            if s.trial_count_basis is DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE
        )
        if previous is not None:
            assert scenario.deflated_sharpe_ratio <= previous + 1e-15, (
                f"DSR rose from {previous} (N={N - 1}) to {scenario.deflated_sharpe_ratio} (N={N})"
            )
        previous = scenario.deflated_sharpe_ratio


def test_dsr_at_one_trial_equals_psr_against_zero():
    """N = 1 ⇒ E[max] = 0 ⇒ SR*₀ = 0 ⇒ DSR = PSR(0) of the selected trial."""
    M, family = _noise_family(32, N=8)
    result = calculate_deflated_sharpe_ratio(
        family,
        dsr_spec(
            effective_independent_trial_count=1,
            effective_trial_count_methodology="test",
        ),
    )
    scenario = next(
        s
        for s in result.scenarios
        if s.trial_count_basis is DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE
    )
    sel = family.returns.values[
        :, family.returns.trial_ids.index(family.manifest.selected_trial_id)
    ]
    series = make_series(sel)
    _, annualized, dist = annualized_and_distribution(series, 0.0)
    unc = calculate_sharpe_uncertainty(annualized, dist, psr_spec=psr_spec(0.0, None))
    assert scenario.expected_maximum_period_sharpe_ratio == 0.0
    assert (
        abs(scenario.deflated_sharpe_ratio - unc.probabilistic_sharpe_ratio) < 1e-12
    ), (
        f"DSR(N=1)={scenario.deflated_sharpe_ratio} PSR(0)={unc.probabilistic_sharpe_ratio}"
    )


def test_dsr_decreases_as_trial_sharpe_dispersion_increases():
    """Same selected trial, same N, wider spread of the other trials' Sharpes ⇒
    larger √V[SR_n] ⇒ larger SR*₀ ⇒ smaller DSR."""
    rng = np.random.default_rng(33)
    T, N = 600, 12
    base = 0.01 * rng.standard_normal((T, N))
    base -= base.mean(axis=0)
    base /= base.std(axis=0, ddof=1)
    base *= 0.01
    # give the first column the largest Sharpe; the others a controlled spread
    selected = base[:, 0] + 0.002
    results = []
    for spread in (0.0001, 0.0005, 0.0010):
        others = base[:, 1:] + np.linspace(-spread, spread, N - 1)
        M = np.column_stack([selected, others])
        family = make_family(M, selected=0)
        res = calculate_deflated_sharpe_ratio(family, dsr_spec())
        assert res.status is DeflatedSharpeRatioStatus.ELIGIBLE, res.status
        results.append(
            (
                res.cross_trial_sample_standard_deviation,
                res.scenarios[0].deflated_sharpe_ratio,
            )
        )
    stds = [s for s, _ in results]
    dsrs = [d for _, d in results]
    assert stds[0] < stds[1] < stds[2]
    assert dsrs[0] > dsrs[1] > dsrs[2], f"DSR did not fall with dispersion: {results}"


def test_dsr_declared_attempts_scenario_is_not_above_selection_eligible():
    """Declared attempts N_d ≥ eligible N_e ⇒ E[max] larger ⇒ DSR_declared ≤ DSR_eligible."""
    M, _ = _noise_family(34, N=10)
    family = make_family(M, declared_total=10)
    res = calculate_deflated_sharpe_ratio(family, dsr_spec())
    by_basis = {s.trial_count_basis: s for s in res.scenarios}
    assert (
        by_basis[DSRTrialCountBasis.DECLARED_ATTEMPTS].deflated_sharpe_ratio
        <= by_basis[DSRTrialCountBasis.SELECTION_ELIGIBLE].deflated_sharpe_ratio + 1e-15
    )


def test_dsr_known_answer_hand_case():
    """Hand case from BLdP14 §'Numerical example' style: N = 100 trials with trial-Sharpe
    variance V = 1/252 per period, E[max Z_100] = (1−γ)Φ⁻¹(0.99) + γΦ⁻¹(1 − 1/(100e))
    = 0.4228·2.3263 + 0.5772·2.6810 ≈ 2.5306; SR*₀ = √(1/252)·2.5306 ≈ 0.15941."""
    emax = ref.expected_max_standard_normal(100)
    assert (
        abs(
            emax
            - (
                (1 - ref.EULER_GAMMA) * norm.ppf(0.99)
                + ref.EULER_GAMMA * norm.ppf(1 - 1 / (100 * math.e))
            )
        )
        < 1e-12
    )
    assert abs(emax - 2.5306) < 5e-4
    from backtest_auditor.statistics.deflated_sharpe import (
        _expected_maximum_standard_normal,
    )

    assert abs(_expected_maximum_standard_normal(100) - emax) < 1e-12
