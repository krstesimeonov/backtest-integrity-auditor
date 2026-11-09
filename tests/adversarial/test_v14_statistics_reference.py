"""Adversarial reference tests for the statistics added in V1.4 (package 1.5.0).

Covers docs/V1_4_STATISTICAL_METHODS.md: downside/tail/drawdown metrics
(statistics/advanced_risk.py), the serial-dependence extension (PACF, ACF bound,
mean long-run variance, median-sign runs, Lo-MacKinlay variance ratios), the
stationary bootstrap (statistics/resampling.py, statistics/bootstrap.py),
Bartlett-HAC benchmark alpha (statistics/benchmark_inference.py) and White RC /
Hansen SPA (statistics/data_snooping.py).

Every expected value comes from code written here from the cited formula, or
from statsmodels / arch / scipy; none comes from the package's tests or goldens.

References
----------
[SP94]   Sortino, F. & Price, L. (1994). Performance measurement in a downside
         risk framework. J. Investing 3(3).  DD = sqrt(mean(min(r - tau, 0)^2)).
[KS02]   Keating, C. & Shadwick, W. (2002). A universal performance measure.
[RU02]   Rockafellar, R. T. & Uryasev, S. (2002). Conditional value-at-risk for
         general loss distributions. J. Banking & Finance 26. ES = (1/(1-c)) *
         integral_c^1 F^{-1}(u) du.
[LM88]   Lo, A. W. & MacKinlay, A. C. (1988). Stock market prices do not follow
         random walks. RFS 1(1). VR eq. (12)-(13); robust z*(q) eq. (18)-(20):
         z*(q) = sqrt(nq) * M_r(q) / sqrt(theta(q)).
[WW40]   Wald, A. & Wolfowitz, J. (1940). On a test whether two samples are from
         the same population. Ann. Math. Stat. 11. Runs mean/variance.
[PR94]   Politis, D. N. & Romano, J. P. (1994). The stationary bootstrap. JASA 89.
         Algorithm sec. 2; Lemma 1: Var*(sqrt(N) mean*) = C(0) + 2 sum b_N(i) C(i),
         b_N(i) = (1 - i/N)(1 - p)^i + (i/N)(1 - p)^(N - i).
[NW87]   Newey, W. & West, K. (1987). Bartlett-weighted HAC covariance.
[W00]    White, H. (2000). A reality check for data snooping. Econometrica 68(5).
[H05]    Hansen, P. R. (2005). A test for superior predictive ability. JBES 23(4).
"""

from __future__ import annotations

import dataclasses
import math
import statistics as pystats

import numpy as np
import pytest

pytest.importorskip("statsmodels")
pytest.importorskip("arch")
import statsmodels.api as sm
from arch.unitroot import VarianceRatio
from scipy.stats import kstest, norm
from scipy.stats import t as student_t
from statsmodels.sandbox.stats.runs import runstest_1samp
from statsmodels.tsa.stattools import acf as sm_acf
from statsmodels.tsa.stattools import pacf as sm_pacf
from statsmodels.tsa.tsatools import lagmat

from .conftest import (
    make_family,
    make_series,
    random_returns,
    ref,
    serial_dependence_spec,
)

from backtest_auditor.audit.family_methodology import assess_experiment_family
from backtest_auditor.domain.assumptions import (
    AdvancedRiskSpec,
    BenchmarkInferenceSpec,
    BootstrapSpec,
    DataSnoopingSpec,
)
from backtest_auditor.domain.enums import (
    BenchmarkInferenceStatus,
    BootstrapIntervalMethod,
    BootstrapMethod,
    BootstrapMetric,
    DataSnoopingStatus,
    ReturnConvention,
)
from backtest_auditor.domain.experiment import ExperimentFamily
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.advanced_risk import calculate_advanced_risk_statistics
from backtest_auditor.statistics.benchmark import assess_benchmark_alignment
from backtest_auditor.statistics.benchmark_inference import (
    calculate_benchmark_alpha_inference,
)
from backtest_auditor.statistics.bootstrap import (
    calculate_bootstrap_confidence_intervals,
)
from backtest_auditor.statistics.data_snooping import calculate_data_snooping_tests
from backtest_auditor.statistics.performance_path import calculate_performance_path
from backtest_auditor.statistics.resampling import stationary_bootstrap_indices
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.serial_dependence import calculate_serial_dependence


def _ar1(rng, n, phi, sigma=0.01, mu=0.0):
    e = sigma * rng.standard_normal(n)
    r = np.empty(n)
    r[0] = e[0]
    for t in range(1, n):
        r[t] = phi * r[t - 1] + e[t]
    return r + mu


# =========================================================================== #
# 1. Downside, tail and drawdown statistics
# =========================================================================== #


def _ref_downside_deviation(r, tau):
    """[SP94] full-sample divisor: sqrt((1/n) sum_{r_t < tau} (r_t - tau)^2)."""
    total = 0.0
    for x in r:
        if x < tau:
            total += (x - tau) ** 2
    return math.sqrt(total / len(r))


def _ref_omega(r, tau):
    """[KS02] empirical: sum of gains above tau / sum of shortfalls below tau."""
    up = sum(x - tau for x in r if x > tau)
    down = sum(tau - x for x in r if x < tau)
    return None if down == 0.0 else up / down


def _ref_var(losses, c):
    """Smallest order statistic whose empirical CDF i/n reaches c (inverted CDF)."""
    s = sorted(losses)
    n = len(s)
    for i, x in enumerate(s, start=1):
        if i / n >= c - 1e-12:  # c is a decimal level; honour its decimal intent
            return x
    return s[-1]


def _ref_es(losses, c):
    """[RU02] (1/(1-c)) * integral_c^1 F^{-1}(u) du with the step quantile
    F^{-1}(u) = l_(i) on ((i-1)/n, i/n]; integrated cell by cell."""
    s = sorted(losses)
    n = len(s)
    total = 0.0
    for i, x in enumerate(s, start=1):
        lo, hi = (i - 1) / n, i / n
        total += max(0.0, hi - max(lo, c)) * x
    return total / (1.0 - c)


def _ref_ulcer(r):
    """RMS of W_t / max(1, W_1..W_t) - 1 (virtual initial wealth of one)."""
    wealth, peak, acc = 1.0, 1.0, 0.0
    for x in r:
        wealth *= 1.0 + x
        peak = max(peak, wealth)
        acc += (wealth / peak - 1.0) ** 2
    return math.sqrt(acc / len(r))


def _advanced(values, tau, c, *, periods_per_year=252):
    series = make_series(values, periods_per_year=periods_per_year)
    sampling = assess_sampling(series)
    path = calculate_performance_path(series, sampling)
    spec = AdvancedRiskSpec(
        minimum_acceptable_period_return=tau, tail_confidence_level=c
    )
    return calculate_advanced_risk_statistics(
        series, sampling, path, spec=spec
    ), sampling


def test_advanced_risk_eight_point_hand_case():
    """r = [2, -1, 3, -4, 1, 0, -2, 5] %, tau = 0. Hand arithmetic:
    shortfalls^2 = 1e-4 + 16e-4 + 4e-4 -> DD = sqrt(0.0021/8); mean = 0.04/8;
    Omega = (2+3+1+5)/(1+4+2) = 11/7; losses sorted = [-5,-3,-2,-1,0,1,2,4] %;
    c=0.75: VaR = 6th = 1 %, ES = mean(4, 2) % = 3 %;
    c=0.8: c*n = 6.4 -> VaR = 7th = 2 %; (1-c)*n = 1.6 -> ES = (4 + 0.6*2)/1.6 % = 3.25 %;
    drawdowns = [0, -1, 0, -4, -3.04, -3.04, -4.9792, -0.22816] %; max DD = 4.9792 %."""
    r = np.array([0.02, -0.01, 0.03, -0.04, 0.01, 0.00, -0.02, 0.05])
    dd_hand = math.sqrt(0.0021 / 8)
    drawdowns = np.array([0, -0.01, 0, -0.04, -0.0304, -0.0304, -0.049792, -0.0022816])
    ulcer_hand = math.sqrt(float(np.mean(drawdowns**2)))
    wealth_hand = 1.02 * 0.99 * 1.03 * 0.96 * 1.01 * 1.00 * 0.98 * 1.05
    calmar_hand = (wealth_hand ** (252 / 8) - 1.0) / 0.049792
    for c, var_hand, es_hand in ((0.75, 0.01, 0.03), (0.8, 0.02, 0.0325)):
        res, _ = _advanced(r, 0.0, c)
        checks = {
            "downside_deviation": (res.downside_deviation, dd_hand),
            "period_sortino": (res.period_sortino_ratio, 0.005 / dd_hand),
            "annualized_sortino": (
                res.annualized_sortino_ratio,
                0.005 / dd_hand * math.sqrt(252),
            ),
            "omega": (res.omega_ratio, 11 / 7),
            "VaR": (res.historical_value_at_risk, var_hand),
            "ES": (res.historical_expected_shortfall, es_hand),
            "ulcer": (res.ulcer_index, ulcer_hand),
            "calmar": (res.calmar_ratio, calmar_hand),
        }
        for name, (got, want) in checks.items():
            assert got == pytest.approx(want, rel=1e-9, abs=1e-15), (
                f"c={c} {name}: package={got!r} hand={want!r}"
            )
        assert res.downside_observation_count == 3


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("kind", ["normal", "skewed", "fat"])
def test_advanced_risk_matches_reference_on_seeded_series(seed, kind):
    """All advanced-risk numbers vs loop references (tolerance rel 1e-10)."""
    rng = np.random.default_rng(1000 + seed)
    n = int(rng.integers(40, 700))
    r = random_returns(rng, n, kind, mu=0.0004, sigma=0.012)
    tau = float(rng.choice([0.0, 0.0005, -0.001, 0.0002]))
    c = float(rng.choice([0.9, 0.95, 0.975, 0.99, 0.8]))
    res, sampling = _advanced(r, tau, c)
    losses = (-r).tolist()
    dd = _ref_downside_deviation(r, tau)
    sortino = float(np.mean(r - tau)) / dd
    path = ref.drawdown_path(r)
    calmar = (
        ref.cagr(r, 252) / abs(path.max_drawdown) if path.max_drawdown < 0 else None
    )
    checks = {
        "downside_deviation": (res.downside_deviation, dd),
        "period_sortino": (res.period_sortino_ratio, sortino),
        "annualized_sortino": (res.annualized_sortino_ratio, sortino * math.sqrt(252)),
        "omega": (res.omega_ratio, _ref_omega(r, tau)),
        "VaR": (res.historical_value_at_risk, _ref_var(losses, c)),
        "ES": (res.historical_expected_shortfall, _ref_es(losses, c)),
        "ulcer": (res.ulcer_index, _ref_ulcer(r)),
        "calmar": (res.calmar_ratio, calmar),
    }
    assert sampling.annualization_eligible
    for name, (got, want) in checks.items():
        assert got == pytest.approx(want, rel=1e-10, abs=1e-15), (
            f"{kind} seed={seed} n={n} tau={tau} c={c} {name}: package={got!r} reference={want!r}"
        )
    assert res.historical_expected_shortfall >= res.historical_value_at_risk - 1e-15


def test_var_quantile_convention_gap_to_linear_interpolation():
    """Documented convention: NumPy 'inverted_cdf' (an order statistic). The common
    textbook alternative interpolates linearly. Measure the gap: it is bounded by the
    spacing of the two neighbouring order statistics, so it is a convention, not an
    error; the message records its size."""
    rng = np.random.default_rng(77)
    r = random_returns(rng, 250, "fat")
    res, _ = _advanced(r, 0.0, 0.95)
    losses = np.sort(-r)
    linear = float(np.quantile(losses, 0.95, method="linear"))
    k = math.ceil(round(0.95 * 250, 9))
    spacing = losses[k] - losses[k - 2]
    gap = res.historical_value_at_risk - linear
    assert abs(gap) <= spacing, (
        f"VaR inverted_cdf={res.historical_value_at_risk} linear={linear}"
    )
    assert res.historical_value_at_risk == losses[k - 1]
    print(
        f"VaR(0.95) inverted_cdf={res.historical_value_at_risk:.6g} linear={linear:.6g} gap={gap:.3g}"
    )


# =========================================================================== #
# 2. Serial-dependence extension
# =========================================================================== #


def _serial(values, max_lag, alpha=0.05):
    return calculate_serial_dependence(
        make_series(values), spec=serial_dependence_spec(max_lag, alpha)
    )


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("phi", [0.0, 0.4, -0.3])
def test_pacf_matches_statsmodels_ols_on_globally_centered_lags(seed, phi):
    """Documented PACF: regress the globally mean-centred r_t on its first k lags
    (all available t, no intercept), keep the lag-k coefficient. Reference: statsmodels
    OLS on statsmodels lagmat(trim='both') of the centred series. Tolerance abs 1e-10."""
    rng = np.random.default_rng(seed)
    n = int(rng.integers(60, 500))
    r = _ar1(rng, n, phi)
    h = int(rng.integers(1, 9))
    res = _serial(r, h)
    c = r - r.mean()
    expected = []
    for k in range(1, h + 1):
        lags, lead = lagmat(c, k, trim="both", original="sep")
        expected.append(float(sm.OLS(np.ravel(lead), lags).fit().params[-1]))
    got = [p.autocorrelation for p in res.partial_autocorrelations]
    assert [p.lag for p in res.partial_autocorrelations] == list(range(1, h + 1))
    assert np.allclose(got, expected, rtol=0, atol=1e-10), (
        f"package={got} statsmodels={expected}"
    )


def test_pacf_convention_gap_to_statsmodels_default_ols():
    """statsmodels pacf(method='ols') fits an intercept in every lag regression; the
    package centres once on the global mean. Measure the gap: it must be far below the
    sampling noise 1/sqrt(n) (bound used: 1/n)."""
    worst = 0.0
    for seed in range(10):
        rng = np.random.default_rng(seed)
        r = _ar1(rng, 400, 0.3, mu=0.001)
        res = _serial(r, 8)
        got = np.array([p.autocorrelation for p in res.partial_autocorrelations])
        sm_ols = sm_pacf(r, nlags=8, method="ols")[1:]
        worst = max(worst, float(np.max(np.abs(got - sm_ols))))
    assert worst < 1.0 / 400, f"max |package - statsmodels 'ols'| = {worst:.3g}"
    print(
        f"PACF global-centring vs per-regression intercept: max gap {worst:.3g} at n=400"
    )


@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.10])
@pytest.mark.parametrize("n", [30, 251, 1000])
def test_acf_reference_bound_is_normal_quantile_over_root_n(alpha, n):
    rng = np.random.default_rng(n)
    res = _serial(rng.standard_normal(n) * 0.01, 3, alpha)
    expected = float(norm.ppf(1.0 - alpha / 2.0)) / math.sqrt(n)
    assert res.acf_confidence_bound == pytest.approx(expected, rel=1e-12), (
        f"bound: package={res.acf_confidence_bound} scipy={expected}"
    )


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("phi", [0.0, 0.5, -0.6])
def test_mean_long_run_variance_ratio_and_effective_observations(seed, phi):
    """LRV ratio = 1 + 2 sum_{k<=h} (1 - k/n) rho_k with rho from statsmodels acf
    (adjusted=False); effective n = n / ratio. Tolerance rel 1e-12."""
    rng = np.random.default_rng(50 + seed)
    n = int(rng.integers(50, 600))
    h = int(rng.integers(1, 12))
    r = _ar1(rng, n, phi)
    res = _serial(r, h)
    rho = sm_acf(r, nlags=h, adjusted=False, fft=False)[1:]
    ratio = 1.0 + 2.0 * sum((1.0 - k / n) * rho[k - 1] for k in range(1, h + 1))
    assert res.mean_long_run_variance_ratio == pytest.approx(ratio, rel=1e-12), (
        f"ratio: package={res.mean_long_run_variance_ratio} reference={ratio}"
    )
    if ratio > 0:
        assert res.mean_effective_observation_count == pytest.approx(
            n / ratio, rel=1e-12
        )
    else:
        assert res.mean_effective_observation_count is None


def _ref_runs(values):
    """[WW40] median-sign runs with the continuity correction that shrinks |R - E|
    by 1/2 toward zero without crossing it: z = sign(d) max(|d| - 1/2, 0) / sd."""
    med = pystats.median(values.tolist())
    signs = [1 if v > med else -1 for v in values.tolist() if v != med]
    N = len(signs)
    n1 = signs.count(1)
    n2 = N - n1
    runs = 1 + sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    expected = 1.0 + 2.0 * n1 * n2 / N
    variance = 2.0 * n1 * n2 * (2.0 * n1 * n2 - N) / (N**2 * (N - 1))
    d = runs - expected
    z = math.copysign(max(abs(d) - 0.5, 0.0), d) / math.sqrt(variance)
    return N, runs, expected, variance, z, 2.0 * norm.sf(abs(z))


@pytest.mark.parametrize("seed", range(10))
def test_runs_test_matches_direct_count_and_normal_approximation(seed):
    """Count, expectation and variance vs a direct count and statsmodels' Runs
    (uncorrected z = (R - E)/sd); corrected z and p vs the WW40 reference."""
    rng = np.random.default_rng(300 + seed)
    n = 2 * int(rng.integers(20, 250))  # even, continuous: no tie with the median
    r = _ar1(rng, n, float(rng.choice([0.0, 0.3, -0.3])))
    res = _serial(r, 3)
    N, runs, expected, variance, z, p = _ref_runs(r)
    z_sm, _ = runstest_1samp(r, cutoff="median", correction=False)
    assert (res.runs_observation_count, res.runs_count) == (N, runs)
    assert res.runs_expected_count == pytest.approx(expected, rel=1e-14)
    assert (runs - expected) / math.sqrt(variance) == pytest.approx(z_sm, rel=1e-12)
    assert res.runs_z_statistic == pytest.approx(z, rel=1e-12, abs=1e-15), (
        f"runs z: package={res.runs_z_statistic} reference={z} (R={runs}, E={expected})"
    )
    assert res.runs_p_value == pytest.approx(p, rel=1e-10), (
        f"runs p: package={res.runs_p_value} reference={p}"
    )


def test_runs_continuity_correction_when_runs_equal_their_expectation():
    """Signs + + - - + - - + (median 0.5): n+ = n- = 4, R = 5 = E = 1 + 2*16/8.
    With R = E there is nothing to correct: z = 0 and p = 1. A continuity correction
    moves |R - E| toward zero by 1/2; it never creates a deviation of 1/2."""
    r = np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.3, 0.0, 0.6]) * 0.01
    res = _serial(r, 2)
    assert res.runs_count == 5 and res.runs_expected_count == 5.0
    _, _, _, variance, z, p = _ref_runs(r)
    assert z == 0.0 and p == 1.0
    assert res.runs_z_statistic == pytest.approx(0.0, abs=1e-15), (
        f"R = E = 5: package z={res.runs_z_statistic} p={res.runs_p_value}; reference z=0 p=1 "
        f"(package z equals 0.5/sd = {0.5 / math.sqrt(variance):.6f})"
    )
    assert res.runs_p_value == pytest.approx(1.0, abs=1e-15)


def _ref_lo_mackinlay(x, q):
    """[LM88] with T = nq one-period returns:
    sigma_a^2 = (1/(T-1)) sum (x_t - mu)^2                               eq. (13a)
    sigma_c^2(q) = (1/m) sum_{t=q}^{T} (x_t + ... + x_{t-q+1} - q mu)^2,
        m = q (T - q + 1)(1 - q/T)                                       eq. (12)
    VR = sigma_c^2 / sigma_a^2,  M_r = VR - 1
    delta(j) = T sum_{t>j} e_t^2 e_{t-j}^2 / (sum e_t^2)^2               eq. (19)
    theta(q) = sum_{j=1}^{q-1} [2(q-j)/q]^2 delta(j)                     eq. (20)
    z*(q) = sqrt(T) M_r / sqrt(theta)  ~ N(0, 1)                         eq. (18)."""
    x = np.asarray(x, dtype=float)
    T = len(x)
    mu = sum(x) / T
    e = [v - mu for v in x]
    sigma_a = sum(v * v for v in e) / (T - 1)
    m = q * (T - q + 1) * (1.0 - q / T)
    sigma_c = (
        sum((sum(x[t - q + 1 : t + 1]) - q * mu) ** 2 for t in range(q - 1, T)) / m
    )
    vr = sigma_c / sigma_a
    e2 = [v * v for v in e]
    den = sum(e2) ** 2
    theta = 0.0
    for j in range(1, q):
        delta = T * sum(e2[t] * e2[t - j] for t in range(j, T)) / den
        theta += (2.0 * (q - j) / q) ** 2 * delta
    z = math.sqrt(T) * (vr - 1.0) / math.sqrt(theta)
    return vr, theta, z, 2.0 * norm.sf(abs(z))


_VR_CASES = [(seed, phi) for phi in (0.0, 0.3, -0.2) for seed in range(6)]


def _vr_case(seed, phi):
    rng = np.random.default_rng(700 + seed)
    n = int(rng.integers(120, 900))
    r = _ar1(rng, n, phi, mu=0.0003)
    h = int(rng.integers(2, 7))
    return n, r, h, _serial(r, h)


@pytest.mark.parametrize(("seed", "phi"), _VR_CASES)
def test_variance_ratio_matches_lo_mackinlay_1988_and_arch(seed, phi):
    """The variance ratio itself vs the LM88 reference; the reference is checked
    against arch.unitroot.VarianceRatio (overlap, debiased, robust). rel 1e-9.
    (Its z and standard error are checked separately below: finding N18.)"""
    n, r, h, res = _vr_case(seed, phi)
    assert [v.horizon for v in res.variance_ratios] == list(range(2, h + 1))
    for item in res.variance_ratios:
        q = item.horizon
        vr, theta, z, p = _ref_lo_mackinlay(r, q)
        arch_vr = VarianceRatio(
            np.r_[0.0, np.cumsum(r)],
            lags=q,
            trend="c",
            debiased=True,
            robust=True,
            overlap=True,
        )
        assert vr == pytest.approx(arch_vr.vr, rel=1e-9) and z == pytest.approx(
            arch_vr.stat, rel=1e-9
        )
        assert item.variance_ratio == pytest.approx(vr, rel=1e-9), (
            f"q={q}: VR package={item.variance_ratio} LM88={vr}"
        )


def test_variance_ratio_z_standard_error_and_p_match_lo_mackinlay_1988():
    """Robust standard error sqrt(theta/T), z* = sqrt(T)(VR - 1)/sqrt(theta) and its
    two-sided p, over the same 18 series and every horizon (finding N18)."""
    wrong = []
    for seed, phi in _VR_CASES:
        n, r, h, res = _vr_case(seed, phi)
        for item in res.variance_ratios:
            q = item.horizon
            vr, theta, z, p = _ref_lo_mackinlay(r, q)
            ok = (
                item.z_statistic == pytest.approx(z, rel=1e-9)
                and item.heteroskedastic_robust_standard_error
                == pytest.approx(math.sqrt(theta / n), rel=1e-9)
                and item.p_value == pytest.approx(p, rel=1e-9, abs=1e-300)
            )
            if not ok:
                wrong.append(
                    f"seed={seed} phi={phi} n={n} q={q}: z {item.z_statistic:+.5f} vs {z:+.5f} "
                    f"(ratio {item.z_statistic / z:.6f}, 1/sqrt(n) {1 / math.sqrt(n):.6f}), "
                    f"p {item.p_value:.4g} vs {p:.4g}"
                )
    assert not wrong, f"{len(wrong)} horizons wrong, e.g.\n" + "\n".join(wrong[:5])


def test_variance_ratio_z_is_standard_normal_under_iid_and_detects_ar1():
    """What must hold whatever the formula: under IID returns z*(2) is ~N(0,1), so its
    spread across 200 seeds is about 1; and an AR(1) with phi = 0.3 over n = 1000
    (VR(2) - 1 ~ 0.3, about 9 robust SEs) is rejected at 5 %."""
    zs = []
    for seed in range(200):
        rng = np.random.default_rng(9000 + seed)
        res = _serial(rng.standard_normal(500) * 0.01, 2)
        zs.append(res.variance_ratios[0].z_statistic)
    spread = float(np.std(zs, ddof=1))
    rng = np.random.default_rng(4)
    ar = _serial(_ar1(rng, 1000, 0.3), 2).variance_ratios[0]
    assert 0.85 < spread < 1.15 and ar.dependence_detected, (
        f"sd of z*(2) over 200 IID seeds (n=500) = {spread:.4f} (expected ~1); "
        f"AR(1) phi=0.3 n=1000: VR={ar.variance_ratio:.4f} z={ar.z_statistic:.4f} p={ar.p_value:.4f}"
    )


# =========================================================================== #
# 3. Stationary bootstrap
# =========================================================================== #


def _ref_stationary_path(n, mean_block, rng):
    """[PR94] sec. 2: I_1 ~ U{0..n-1}; for i >= 2, with probability p = 1/L draw a new
    uniform start, else continue to I_{i-1} + 1 (mod n). RNG order: one uniform per
    position, then a start index only when restarting."""
    p = 1.0 / mean_block
    path = [int(rng.integers(0, n))]
    for _ in range(1, n):
        if rng.random() < p:
            path.append(int(rng.integers(0, n)))
        else:
            path.append((path[-1] + 1) % n)
    return np.asarray(path)


@pytest.mark.parametrize(
    "n,L,seed", [(50, 1, 0), (200, 5, 1), (333, 12, 2), (97, 40, 3)]
)
def test_stationary_indices_match_politis_romano_with_same_rng(n, L, seed):
    rng_pkg = np.random.default_rng(seed)
    rng_ref = np.random.default_rng(seed)
    for _ in range(20):
        got = stationary_bootstrap_indices(n, mean_block_length=L, rng=rng_pkg)
        want = _ref_stationary_path(n, L, rng_ref)
        assert got.shape == (n,) and np.array_equal(got, want)


def test_stationary_block_lengths_average_the_declared_mean():
    """Observed blocks per path: E[#blocks] = 1 + (n-1) p (1 - 1/n) (a restart that
    lands on the successor is invisible), so mean observed length = n / E[#blocks].
    400 paths, n = 500, L = 8: about 25 000 blocks, tolerance 3 %."""
    n, L = 500, 8
    rng = np.random.default_rng(12)
    blocks = 0
    for _ in range(400):
        path = stationary_bootstrap_indices(n, mean_block_length=L, rng=rng)
        blocks += 1 + int(np.count_nonzero(path[1:] != (path[:-1] + 1) % n))
    observed = 400 * n / blocks
    expected = n / (1.0 + (n - 1) * (1.0 / L) * (1.0 - 1.0 / n))
    assert observed == pytest.approx(expected, rel=0.03), (
        f"mean observed block length {observed:.4f}, expected {expected:.4f} (declared {L})"
    )


def _stationary_spec(L, seed, reps, level=0.90):
    return BootstrapSpec(
        method=BootstrapMethod.STATIONARY,
        interval_method=BootstrapIntervalMethod.PERCENTILE,
        replications=reps,
        confidence_level=level,
        block_length=L,
        random_seed=seed,
    )


def _metric(result, metric):
    return next(m for m in result.metrics if m.metric is metric)


def test_stationary_bootstrap_interval_matches_reference_resampler():
    """Percentile interval and bootstrap SE of the mean and of the sample volatility
    vs a reference stationary bootstrap that consumes the same seeded generator in the
    same order; np.quantile 'linear' percentile interval. Tolerance rel 1e-12."""
    rng = np.random.default_rng(31)
    r = _ar1(rng, 260, 0.3, mu=0.0005)
    series = make_series(r)
    L, seed, reps = 6, 4242, 400
    result = calculate_bootstrap_confidence_intervals(
        series,
        assess_sampling(series),
        None,
        None,
        spec=_stationary_spec(L, seed, reps),
    )
    gen = np.random.default_rng(seed)
    means, vols = [], []
    for _ in range(reps):
        sample = r[_ref_stationary_path(len(r), L, gen)]
        means.append(float(np.mean(sample)))
        vols.append(float(np.std(sample, ddof=1)))
    for metric, dist, point in (
        (BootstrapMetric.PERIOD_MEAN_RETURN, means, float(np.mean(r))),
        (BootstrapMetric.PERIOD_SAMPLE_VOLATILITY, vols, float(np.std(r, ddof=1))),
    ):
        got = _metric(result, metric)
        lo, hi = ref.percentile_interval(np.asarray(dist), 0.90)
        se = float(np.std(dist, ddof=1))
        assert (
            got.lower_bound,
            got.upper_bound,
            got.bootstrap_standard_error,
        ) == pytest.approx((lo, hi, se), rel=1e-12), (
            f"{metric}: package=({got.lower_bound}, {got.upper_bound}, {got.bootstrap_standard_error}) ref=({lo}, {hi}, {se})"
        )
        assert got.point_estimate == pytest.approx(point, rel=1e-14)
        assert got.lower_bound <= got.point_estimate <= got.upper_bound


def test_stationary_bootstrap_se_of_mean_matches_politis_romano_lemma_1():
    """[PR94] Lemma 1 gives the exact conditional variance of the stationary-bootstrap
    mean. AR(1) phi = 0.4, n = 300, L = 10, 3000 replications: bootstrap SE must match
    sqrt(Var*/n) within 6 % (MC relative error ~1/sqrt(2B) = 1.3 %), and differ
    clearly from the IID value sqrt(C(0)/n); the bootstrap mean must be unbiased."""
    rng = np.random.default_rng(8)
    n, L, reps = 300, 10, 3000
    r = _ar1(rng, n, 0.4, mu=0.0004)
    series = make_series(r)
    result = calculate_bootstrap_confidence_intervals(
        series, assess_sampling(series), None, None, spec=_stationary_spec(L, 99, reps)
    )
    got = _metric(result, BootstrapMetric.PERIOD_MEAN_RETURN)
    d = r - r.mean()
    C = [float(d[: n - i] @ d[i:]) / n for i in range(n)]
    p = 1.0 / L
    b = [(1 - i / n) * (1 - p) ** i + (i / n) * (1 - p) ** (n - i) for i in range(n)]
    var_star = C[0] + 2.0 * sum(b[i] * C[i] for i in range(1, n))
    analytic_se = math.sqrt(var_star / n)
    iid_se = math.sqrt(C[0] / n)
    assert got.bootstrap_standard_error == pytest.approx(analytic_se, rel=0.06), (
        f"bootstrap SE={got.bootstrap_standard_error:.6g} PR94 Lemma 1={analytic_se:.6g} IID={iid_se:.6g}"
    )
    assert analytic_se / iid_se > 1.2
    # unbiasedness of the circular stationary bootstrap: E*[mean*] = sample mean
    gen = np.random.default_rng(99)
    boot = [float(np.mean(r[_ref_stationary_path(n, L, gen)])) for _ in range(reps)]
    assert abs(np.mean(boot) - r.mean()) < 4.0 * analytic_se / math.sqrt(reps)


# =========================================================================== #
# 4. Benchmark alpha inference
# =========================================================================== #


def _alpha(strategy, benchmark, lag, level=0.95):
    s, b = make_series(strategy), make_series(benchmark)
    return calculate_benchmark_alpha_inference(
        s,
        b,
        assess_benchmark_alignment(s, b),
        spec=BenchmarkInferenceSpec(maximum_lag=lag, confidence_level=level),
    )


def _alpha_data(rng, n, *, alpha=0.0003, beta=0.9, phi=0.3):
    bench = random_returns(rng, n, "fat", mu=0.0003, sigma=0.01)
    noise = _ar1(rng, n, phi, sigma=0.004) * (1.0 + 0.5 * np.abs(bench) / 0.01)
    return alpha + beta * bench + noise, bench


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("lag", [0, 1, 5, 12])
def test_hac_alpha_matches_statsmodels_newey_west(seed, lag):
    """OLS + Bartlett weights 1 - k/(h+1), no small-sample scaling, normal reference:
    statsmodels OLS(cov_type='HAC', maxlags=h, use_correction=False), use_t=False.
    Heteroskedastic, autocorrelated errors. Tolerance rel 1e-9."""
    rng = np.random.default_rng(40 + seed)
    n = int(rng.integers(60, 800))
    y, x = _alpha_data(rng, n)
    res = _alpha(y, x, lag, 0.95)
    fit = sm.OLS(y, sm.add_constant(x)).fit(
        cov_type="HAC", cov_kwds={"maxlags": lag, "use_correction": False}
    )
    lo, hi = fit.conf_int(alpha=0.05)[0]
    assert res.status is BenchmarkInferenceStatus.ELIGIBLE
    checks = {
        "alpha": (res.period_alpha, fit.params[0]),
        "beta": (res.beta, fit.params[1]),
        "se": (res.hac_standard_error, fit.bse[0]),
        "z": (res.test_statistic, fit.tvalues[0]),
        "p": (res.two_sided_p_value, fit.pvalues[0]),
        "ci_lower": (res.confidence_interval_lower, lo),
        "ci_upper": (res.confidence_interval_upper, hi),
    }
    for name, (got, want) in checks.items():
        assert got == pytest.approx(float(want), rel=1e-9, abs=1e-14), (
            f"n={n} h={lag} {name}: package={got!r} statsmodels={float(want)!r}"
        )
    assert res.statistically_different_from_zero == (fit.pvalues[0] < 0.05)


def test_hac_alpha_small_sample_convention_gap():
    """Not stated as a formula in the docs: no n/(n-k) scaling and a normal (not
    t_{n-2}) reference. Measure both gaps at n = 60: SE ratio = sqrt(60/58) exactly,
    and the p-value moves by less than 0.02."""
    rng = np.random.default_rng(5)
    y, x = _alpha_data(rng, 60, alpha=0.001)
    res = _alpha(y, x, 3)
    corrected = sm.OLS(y, sm.add_constant(x)).fit(
        cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": True}
    )
    assert corrected.bse[0] / res.hac_standard_error == pytest.approx(
        math.sqrt(60 / 58), rel=1e-9
    )
    p_t = 2.0 * student_t.sf(abs(res.test_statistic), df=58)
    gap = p_t - res.two_sided_p_value
    assert 0.0 <= gap < 0.02, f"p normal={res.two_sided_p_value:.6f} p t58={p_t:.6f}"
    print(
        f"HAC alpha n=60: SE x{math.sqrt(60 / 58):.5f} with n/(n-k); p normal "
        f"{res.two_sided_p_value:.5f} vs t58 {p_t:.5f}"
    )


# =========================================================================== #
# 5. White Reality Check and Hansen SPA
# =========================================================================== #


def _snooping(matrix, benchmark, *, reps=199, L=5, seed=11, trial_ids=None):
    with np.errstate(divide="ignore", invalid="ignore"):
        fam = make_family(matrix, trial_ids=trial_ids)  # selected = best Sharpe
    manifest = dataclasses.replace(
        fam.manifest,
        benchmark_id="bench",
        benchmark_return_convention=ReturnConvention.SIMPLE,
    )
    bench = ReturnSeries(
        timestamps=fam.returns.timestamps,
        values=np.asarray(benchmark, dtype=float),
        convention=ReturnConvention.SIMPLE,
        sampling=fam.returns.sampling,
    )
    family = ExperimentFamily(
        manifest=manifest,
        trials=fam.trials,
        returns=fam.returns,
        benchmark_returns=bench,
    )
    assessment = assess_experiment_family(family)[0]
    spec = DataSnoopingSpec(
        replications=reps,
        mean_block_length=L,
        random_seed=seed,
        significance_level=0.05,
    )
    return calculate_data_snooping_tests(family, assessment, spec=spec)


def _ref_rc_spa(active, reps, L, seed):
    """[W00] T_RC = max(0, max_k sqrt(n) dbar_k); T*_RC = max(0, max_k sqrt(n)(dbar*_k - dbar_k)).
    [H05] omega_k^2 = B^{-1} sum_b n (dbar*_{k,b} - dbar_k)^2 (bootstrap estimate centred at
    the observed mean); T_SPA = max(0, max_k sqrt(n) dbar_k / omega_k); consistent
    recentring g_c(dbar_k) = dbar_k 1{sqrt(n) dbar_k / omega_k >= -sqrt(2 log log n)};
    T*_SPA = max(0, max_k sqrt(n)(dbar*_k - g_c(dbar_k)) / omega_k).
    p = (#{T* >= T} + 1)/(B + 1) (documented finite-replication correction)."""
    n, K = active.shape
    dbar = active.mean(axis=0)
    gen = np.random.default_rng(seed)
    boot = np.array(
        [active[_ref_stationary_path(n, L, gen)].mean(axis=0) for _ in range(reps)]
    )
    rn = math.sqrt(n)
    t_rc = max(0.0, rn * float(dbar.max()))
    rc_star = np.maximum(0.0, rn * (boot - dbar).max(axis=1))
    p_rc = (np.count_nonzero(rc_star >= t_rc) + 1) / (reps + 1)
    omega = np.sqrt(n * np.mean((boot - dbar) ** 2, axis=0))
    t_spa = max(0.0, float(np.max(rn * dbar / omega)))
    keep = rn * dbar / omega >= -math.sqrt(2.0 * math.log(math.log(n)))
    g = np.where(keep, dbar, 0.0)
    spa_star = np.maximum(0.0, (rn * (boot - g) / omega).max(axis=1))
    p_spa = (np.count_nonzero(spa_star >= t_spa) + 1) / (reps + 1)
    return float(p_rc), float(p_spa)


@pytest.mark.parametrize("seed", range(6))
def test_reality_check_and_spa_match_reference_with_same_rng(seed):
    """White RC p-value must equal the reference exactly (same bootstrap draws).
    SPA: the package estimates omega with np.var(ddof=1) around the bootstrap average,
    Hansen's estimator is centred at the observed mean with divisor B; the gap is
    O(1/B) in omega, so the SPA p-value is compared within 0.02."""
    rng = np.random.default_rng(600 + seed)
    n, K = int(rng.integers(150, 400)), int(rng.integers(2, 7))
    bench = rng.standard_normal(n) * 0.01
    mus = rng.choice([-0.002, 0.0, 0.0005, 0.001], size=K)
    M = bench[:, None] + mus + _ar1(rng, n * K, 0.2, sigma=0.006).reshape(n, K)
    reps, L, s = 299, int(rng.integers(2, 10)), int(rng.integers(0, 10**6))
    res = _snooping(M, bench, reps=reps, L=L, seed=s)
    p_rc, p_spa = _ref_rc_spa(M - bench[:, None], reps, L, s)
    assert res.white_reality_check_p_value == p_rc, (
        f"RC p: package={res.white_reality_check_p_value} reference={p_rc}"
    )
    assert res.hansen_spa_p_value == pytest.approx(p_spa, abs=0.02), (
        f"SPA p: package={res.hansen_spa_p_value} reference={p_spa}"
    )


def test_snooping_p_values_are_probabilities_and_invariant_to_trial_order():
    rng = np.random.default_rng(21)
    n, K = 250, 5
    bench = rng.standard_normal(n) * 0.01
    M = (
        bench[:, None]
        + rng.standard_normal((n, K)) * 0.008
        + np.array([0, 3e-4, -5e-4, 1e-4, 0])
    )
    ids = tuple(f"t{i}" for i in range(K))
    base = _snooping(M, bench, trial_ids=ids)
    perm = [3, 0, 4, 2, 1]
    shuffled = _snooping(M[:, perm], bench, trial_ids=tuple(ids[i] for i in perm))
    for p in (base.white_reality_check_p_value, base.hansen_spa_p_value):
        assert 1.0 / 200 <= p <= 1.0
    assert (shuffled.white_reality_check_p_value, shuffled.hansen_spa_p_value) == (
        base.white_reality_check_p_value,
        base.hansen_spa_p_value,
    ), "permuting the trial columns changed the RC/SPA p-values"
    assert (
        shuffled.observed_maximum_mean_active_return
        == base.observed_maximum_mean_active_return
    )


def test_pure_noise_family_p_values_are_roughly_uniform():
    """Least-favourable null (every trial has zero expected active return): over 80
    seeded families the RC and SPA p-values should look U(0,1). KS test at 0.1 %,
    and the 5 % rejection rate below 15 %."""
    p_rc, p_spa = [], []
    for seed in range(80):
        rng = np.random.default_rng(5000 + seed)
        n = 200
        bench = rng.standard_normal(n) * 0.01
        M = bench[:, None] + rng.standard_normal((n, 4)) * 0.008
        res = _snooping(M, bench, reps=199, L=4, seed=seed)
        p_rc.append(res.white_reality_check_p_value)
        p_spa.append(res.hansen_spa_p_value)
    for name, ps in (("RC", p_rc), ("SPA", p_spa)):
        ks = kstest(ps, "uniform")
        rate = float(np.mean(np.asarray(ps) < 0.05))
        assert ks.pvalue > 1e-3 and rate < 0.15, (
            f"{name}: KS p={ks.pvalue:.4g}, mean p={np.mean(ps):.3f}, rejection rate={rate:.3f}"
        )


def test_one_strongly_positive_trial_gets_a_small_p_value():
    """Trial 0 earns 0.3 %/period over the benchmark with 1 % noise, n = 400
    (t about 6); the other four are pure noise. Both tests must reject at 5 %."""
    rng = np.random.default_rng(17)
    n = 400
    bench = rng.standard_normal(n) * 0.01
    M = bench[:, None] + rng.standard_normal((n, 5)) * 0.01
    M[:, 0] += 0.003
    res = _snooping(M, bench, reps=199)
    assert res.status is DataSnoopingStatus.ELIGIBLE
    assert res.white_reality_check_p_value <= 0.01 and res.hansen_spa_p_value <= 0.01, (
        f"RC p={res.white_reality_check_p_value} SPA p={res.hansen_spa_p_value}"
    )
    assert res.white_reality_check_rejects_null and res.hansen_spa_rejects_null


def test_flat_trial_with_non_representable_constant_active_return():
    """Benchmark 0.0; trials 1-2 are noise; trial 3 earns a constant active return.
    A constant has zero long-run variance, and the package drops trials whose
    bootstrap long-run SD is not > 0 from SPA studentization. With the representable
    constant 2^-11 that is what happens. With 0.0004 the bootstrap means are identical
    but np.var of identical non-representable floats is a ~1e-40 residue, so the
    trial stays in with a studentized mean of ~1e17. Both families describe the same
    situation (one flat trial), so the SPA verdict must not depend on whether the
    constant is exactly representable in binary."""
    rng = np.random.default_rng(23)
    n = 300
    noise = rng.standard_normal((n, 2)) * 0.01
    out = {}
    for const in (0.0004, 2.0**-11):
        M = np.column_stack([noise, np.full(n, const)])
        out[const] = _snooping(M, np.zeros(n), reps=499, L=5, seed=11)
    a, b = out[0.0004], out[2.0**-11]
    assert a.hansen_spa_p_value == b.hansen_spa_p_value, (
        f"flat trial at 0.0004: SPA p={a.hansen_spa_p_value} (rejects={a.hansen_spa_rejects_null}); "
        f"flat trial at 2^-11: SPA p={b.hansen_spa_p_value} (rejects={b.hansen_spa_rejects_null}); "
        f"np.var of 499 copies of mean(0.0004 x {n}) = "
        f"{np.var(np.full((499, 1), np.mean(np.full((n, 1), 0.0004), axis=0)), axis=0, ddof=1)[0]!r}"
    )
