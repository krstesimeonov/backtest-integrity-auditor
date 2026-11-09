"""Independent reference implementations for the night3 adversarial pass.

Written from the papers, not from V1's code. Every function documents the
equation it implements and its source. Plain numpy only, loops where a loop is
the clearest statement of the definition.

Sources
-------
[BLdP12]  Bailey, D. H. & López de Prado, M. (2012). "The Sharpe Ratio Efficient
          Frontier." Journal of Risk 15(2). PSR eq. (11); MinTRL eq. (13).
[BLdP14]  Bailey, D. H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio:
          Correcting for Selection Bias, Backtest Overfitting and Non-Normality."
          Journal of Portfolio Management 40(5). E[max SR] eq. (6)-(7); DSR eq. (8).
[BBLZ17]  Bailey, Borwein, López de Prado & Zhu (2017). "The Probability of Backtest
          Overfitting." Journal of Computational Finance 20(4). CSCV §4, PBO eq. (3)-(4).
[Lo02]    Lo, A. W. (2002). "The Statistics of Sharpe Ratios." Financial Analysts
          Journal 58(4). IID SE eq. (10); autocorrelation-adjusted annualization eq. (20).
[Kun89]   Künsch, H. R. (1989). "The Jackknife and the Bootstrap for General
          Stationary Observations." Annals of Statistics 17(3). Moving-block bootstrap.
[LB78]    Ljung, G. M. & Box, G. E. P. (1978). "On a measure of lack of fit in time
          series models." Biometrika 65(2). Q statistic.
[JG98]    Joanes, D. N. & Gill, C. A. (1998). "Comparing measures of sample skewness
          and kurtosis." The Statistician 47(1). G1, G2 estimators.
[Holm79]  Holm, S. (1979). Scand. J. Statist. 6, 65-70.
[BH95]    Benjamini, Y. & Hochberg, Y. (1995). JRSS-B 57(1), 289-300.
[HLZ16]   Harvey, C. R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected
          Returns." RFS 29(1). Haircut Sharpe (Harvey & Liu 2015 "Backtesting").
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import chi2, norm

EULER_GAMMA = 0.5772156649015329  # Euler–Mascheroni constant γ

# --------------------------------------------------------------------------- #
# Risk-free rate and Sharpe
# --------------------------------------------------------------------------- #


def annual_to_period_rate_geometric(
    annual_rate: float, periods_per_year: float
) -> float:
    """r_p = (1 + r_a)^(1/p) − 1.  Effective-annual to per-period compounding.

    Matches ASSUMPTIONS.md A3 (V1's convention) so the Sharpe comparison isolates
    the statistic rather than the rate convention.
    """
    return (1.0 + annual_rate) ** (1.0 / periods_per_year) - 1.0


def annual_to_period_rate_linear(annual_rate: float, periods_per_year: float) -> float:
    """r_p = r_a / p.  The textbook (Sharpe 1994) simple-proration convention."""
    return annual_rate / periods_per_year


def period_sharpe(returns: np.ndarray, period_rf: float = 0.0) -> float:
    """SR = (mean(r) − r_f) / s,  s = sample std with ddof = 1.  [Lo02 eq. 1]."""
    r = np.asarray(returns, dtype=float)
    return (r.mean() - period_rf) / r.std(ddof=1)


def annualized_sharpe(
    returns: np.ndarray,
    periods_per_year: float,
    annual_rf: float = 0.0,
    *,
    rate_convention: str = "geometric",
) -> float:
    """SR_annual = SR_period · √p   [Lo02 eq. 2, iid case].

    Mean annualizes by p, volatility by √p, so the ratio scales by √p.
    """
    rf = (
        annual_to_period_rate_geometric(annual_rf, periods_per_year)
        if rate_convention == "geometric"
        else annual_to_period_rate_linear(annual_rf, periods_per_year)
    )
    return period_sharpe(returns, rf) * math.sqrt(periods_per_year)


def annualized_mean(returns: np.ndarray, periods_per_year: float) -> float:
    """μ_annual = mean(r) · p  (arithmetic)."""
    return float(np.mean(returns)) * periods_per_year


def annualized_volatility(returns: np.ndarray, periods_per_year: float) -> float:
    """σ_annual = s · √p  (square-root-of-time rule, ddof = 1)."""
    return float(np.std(returns, ddof=1)) * math.sqrt(periods_per_year)


# --------------------------------------------------------------------------- #
# Moments
# --------------------------------------------------------------------------- #


def plugin_skewness(returns: np.ndarray) -> float:
    """g1 = m3 / m2^{3/2},  m_k = (1/n) Σ (r − r̄)^k.  Plug-in (biased) [JG98]."""
    r = np.asarray(returns, dtype=float)
    d = r - r.mean()
    return float(np.mean(d**3) / np.mean(d**2) ** 1.5)


def plugin_kurtosis(returns: np.ndarray) -> float:
    """g2 + 3 = m4 / m2²  (Pearson, non-excess), plug-in [JG98]."""
    r = np.asarray(returns, dtype=float)
    d = r - r.mean()
    return float(np.mean(d**4) / np.mean(d**2) ** 2)


def adjusted_skewness(returns: np.ndarray) -> float:
    """G1 = g1 · √(n(n−1)) / (n−2)   [JG98 eq. for G1]."""
    n = len(returns)
    return plugin_skewness(returns) * math.sqrt(n * (n - 1)) / (n - 2)


def adjusted_pearson_kurtosis(returns: np.ndarray) -> float:
    """G2 + 3, with G2 = (n−1)/((n−2)(n−3)) · ((n+1) g2_excess + 6)   [JG98]."""
    n = len(returns)
    g2_excess = plugin_kurtosis(returns) - 3.0
    G2 = (n - 1) / ((n - 2) * (n - 3)) * ((n + 1) * g2_excess + 6.0)
    return G2 + 3.0


# --------------------------------------------------------------------------- #
# PSR, MinTRL, DSR
# --------------------------------------------------------------------------- #


def sharpe_se_period(sr: float, n: int, skew: float, kurt: float) -> float:
    """σ̂(SR) = √[(1 − γ3·SR + (γ4 − 1)/4 · SR²) / (n − 1)]   [BLdP12 eq. 10].

    γ3 = skewness, γ4 = (non-excess) kurtosis of the period returns.
    """
    return math.sqrt((1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2) / (n - 1))


def psr(sr: float, sr_benchmark: float, n: int, skew: float, kurt: float) -> float:
    """PSR(SR*) = Φ[ (SR − SR*) · √(n−1) / √(1 − γ3 SR + (γ4−1)/4 SR²) ]  [BLdP12 eq. 11].

    All Sharpe quantities are per period (not annualized).
    """
    return float(norm.cdf((sr - sr_benchmark) / sharpe_se_period(sr, n, skew, kurt)))


def min_trl(
    sr: float, sr_benchmark: float, skew: float, kurt: float, alpha: float
) -> float:
    """MinTRL = 1 + (1 − γ3 SR + (γ4−1)/4 SR²) · (Z_α / (SR − SR*))²   [BLdP12 eq. 13].

    Z_α = Φ⁻¹(α), α the required confidence (e.g. 0.95). Observations, not years.
    """
    z = norm.ppf(alpha)
    return (
        1.0
        + (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2)
        * (z / (sr - sr_benchmark)) ** 2
    )


def expected_max_standard_normal(n_trials: int) -> float:
    """E[max of N iid N(0,1)] ≈ (1−γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))   [BLdP14 eq. 6].

    Returns 0 for N = 1 by convention (the approximation is undefined there; the
    max of one draw has expectation 0).
    """
    if n_trials <= 1:
        return 0.0
    return (1.0 - EULER_GAMMA) * norm.ppf(
        1.0 - 1.0 / n_trials
    ) + EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n_trials * math.e))


def expected_max_sharpe(
    trial_sharpes: np.ndarray, n_trials: int | None = None, *, ddof: int = 1
) -> float:
    """SR*₀ = √V[SR_n] · E[max Z_N]   [BLdP14 eq. 7].

    V[SR_n] is the (sample, ddof as given) variance of the N trial period Sharpes.
    """
    s = np.asarray(trial_sharpes, dtype=float)
    n = len(s) if n_trials is None else n_trials
    return math.sqrt(np.var(s, ddof=ddof)) * expected_max_standard_normal(n)


def dsr(
    selected_sr: float,
    trial_sharpes: np.ndarray,
    n_obs: int,
    skew: float,
    kurt: float,
    *,
    n_trials: int | None = None,
    ddof: int = 1,
) -> float:
    """DSR = PSR(SR*₀) with SR*₀ = expected_max_sharpe(...)   [BLdP14 eq. 8].

    skew/kurt are those of the *selected* trial's period returns.
    """
    sr_star = expected_max_sharpe(trial_sharpes, n_trials, ddof=ddof)
    return psr(selected_sr, sr_star, n_obs, skew, kurt)


# --------------------------------------------------------------------------- #
# CSCV / PBO
# --------------------------------------------------------------------------- #


def ascending_average_ranks(x: np.ndarray) -> np.ndarray:
    """1-based ascending ranks, ties get the average rank (as scipy rankdata 'average')."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i : j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return ranks


@dataclass
class CSCVOutcome:
    pbo: float
    logits: np.ndarray
    is_scores: np.ndarray
    oos_scores: np.ndarray


def cscv_pbo(matrix: np.ndarray, S: int, period_rf: float = 0.0) -> CSCVOutcome:
    """CSCV / PBO [BBLZ17 §4].

    1. Split the T×N matrix M into S disjoint contiguous sub-matrices of equal rows.
    2. For each of the C(S, S/2) combinations c: J = IS (rows of the chosen S/2 blocks),
       J̄ = complementary OOS rows.
    3. Per column n compute the performance metric (period Sharpe) on J → R_n and on
       J̄ → R̄_n.  n* = argmax_n R_n.
    4. ω̄_c = rank of R̄_{n*} among {R̄_n} (ascending, 1 = worst) / (N + 1);
       λ_c = log(ω̄_c / (1 − ω̄_c))   [eq. 3].
    5. PBO = (1/#c) Σ 1[λ_c ≤ 0]   [eq. 4].

    T must be divisible by S. Ties in argmax resolve to the lowest column index.
    """
    M = np.asarray(matrix, dtype=float)
    T, N = M.shape
    if T % S:
        raise ValueError("T must be divisible by S")
    rows = T // S
    blocks = [np.arange(k * rows, (k + 1) * rows) for k in range(S)]
    logits, is_scores, oos_scores = [], [], []
    for combo in itertools.combinations(range(S), S // 2):
        J = np.concatenate([blocks[k] for k in combo])
        Jbar = np.concatenate([blocks[k] for k in range(S) if k not in combo])
        R = (M[J].mean(axis=0) - period_rf) / M[J].std(axis=0, ddof=1)
        Rbar = (M[Jbar].mean(axis=0) - period_rf) / M[Jbar].std(axis=0, ddof=1)
        n_star = int(np.argmax(R))
        omega = ascending_average_ranks(Rbar)[n_star] / (N + 1.0)
        logits.append(math.log(omega / (1.0 - omega)))
        is_scores.append(R[n_star])
        oos_scores.append(Rbar[n_star])
    logits = np.asarray(logits)
    return CSCVOutcome(
        float(np.mean(logits <= 0.0)),
        logits,
        np.asarray(is_scores),
        np.asarray(oos_scores),
    )


# --------------------------------------------------------------------------- #
# Multiple testing (V1 does not implement these; written for completeness and
# cross-checked against statsmodels in the tests)
# --------------------------------------------------------------------------- #


def bonferroni(p: np.ndarray) -> np.ndarray:
    """p̃_i = min(1, m · p_i)."""
    p = np.asarray(p, dtype=float)
    return np.minimum(1.0, len(p) * p)


def holm(p: np.ndarray) -> np.ndarray:
    """Step-down [Holm79]: order p_(1) ≤ … ≤ p_(m); p̃_(i) = max_{j≤i} min(1, (m−j+1) p_(j))."""
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    running = 0.0
    for i, idx in enumerate(order):
        running = max(running, min(1.0, (m - i) * p[idx]))
        adj[idx] = running
    return adj


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """Step-up [BH95]: p̃_(i) = min_{j≥i} min(1, m p_(j) / j)."""
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    running = 1.0
    for i in range(m - 1, -1, -1):
        idx = order[i]
        running = min(running, min(1.0, m * p[idx] / (i + 1)))
        adj[idx] = running
    return adj


def haircut_sharpe_bonferroni(
    sr_annual: float, n_obs: int, periods_per_year: float, n_trials: int
) -> float:
    """Harvey & Liu (2015) haircut, Bonferroni variant.

    t = SR_annual · √(n/p); p = 2(1 − Φ(t)); p̃ = min(1, N p); t̃ = Φ⁻¹(1 − p̃/2);
    SR̃ = t̃ / √(n/p). Returns the haircut annual Sharpe.
    """
    t = sr_annual * math.sqrt(n_obs / periods_per_year)
    p = 2.0 * (1.0 - norm.cdf(t))
    p_adj = min(1.0, n_trials * p)
    t_adj = norm.ppf(1.0 - p_adj / 2.0)
    return t_adj / math.sqrt(n_obs / periods_per_year)


# --------------------------------------------------------------------------- #
# Serial dependence
# --------------------------------------------------------------------------- #


def acf(returns: np.ndarray, max_lag: int) -> np.ndarray:
    """ρ̂_k = Σ_{t=k+1}^{n} (r_t − r̄)(r_{t−k} − r̄) / Σ_t (r_t − r̄)²,  k = 1..L."""
    r = np.asarray(returns, dtype=float)
    d = r - r.mean()
    den = float(d @ d)
    return np.asarray([float(d[k:] @ d[:-k]) / den for k in range(1, max_lag + 1)])


def ljung_box(returns: np.ndarray, max_lag: int) -> tuple[float, float]:
    """Q = n(n+2) Σ_{k=1}^{L} ρ̂_k² / (n − k);  p = P(χ²_L > Q)   [LB78]."""
    n = len(returns)
    rho = acf(returns, max_lag)
    Q = n * (n + 2) * sum(rho[k - 1] ** 2 / (n - k) for k in range(1, max_lag + 1))
    return float(Q), float(chi2.sf(Q, max_lag))


def lo_annualized_sharpe(returns: np.ndarray, q: int, period_rf: float = 0.0) -> float:
    """SR(q) = η(q) · SR,  η(q) = q / √(q + 2 Σ_{k=1}^{q−1} (q − k) ρ̂_k)   [Lo02 eq. 20].

    q = periods per year; aggregates q consecutive period returns.
    """
    sr = period_sharpe(returns, period_rf)
    rho = acf(returns, q - 1)
    eta = q / math.sqrt(q + 2.0 * sum((q - k) * rho[k - 1] for k in range(1, q)))
    return eta * sr


def bartlett_lrv_ratio(x: np.ndarray, max_lag: int) -> float:
    """Newey–West / Bartlett long-run-variance ratio:  1 + 2 Σ_{k=1}^{L} (1 − k/(L+1)) ρ̂_k."""
    rho = acf(x, max_lag)
    return 1.0 + 2.0 * sum(
        (1.0 - k / (max_lag + 1.0)) * rho[k - 1] for k in range(1, max_lag + 1)
    )


def sharpe_influence(returns: np.ndarray, sr: float) -> np.ndarray:
    """ψ_t = z_t − (SR/2)(z_t² − 1),  z_t = (r_t − r̄)/s.  Delta-method influence of SR.

    Var(ψ) = 1 − γ3 SR + (γ4 − 1)/4 SR² under plug-in moments (Lo02 eq. 10 / BLdP12).
    """
    r = np.asarray(returns, dtype=float)
    z = (r - r.mean()) / r.std(ddof=1)
    return z - 0.5 * sr * (z**2 - 1.0)


# --------------------------------------------------------------------------- #
# Moving-block bootstrap [Kun89]
# --------------------------------------------------------------------------- #


def moving_block_bootstrap(
    x: np.ndarray,
    stat,
    block_length: int,
    replications: int,
    seed: int,
) -> np.ndarray:
    """Künsch moving-block bootstrap.

    Blocks B_i = (x_i, …, x_{i+b−1}), i = 1..n−b+1, overlapping. Draw ⌈n/b⌉ block
    starts uniformly with replacement, concatenate, truncate to n, evaluate stat.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    k = math.ceil(n / block_length)
    rng = np.random.default_rng(seed)
    out = np.empty(replications)
    for b in range(replications):
        starts = rng.integers(0, n - block_length + 1, size=k)
        sample = np.concatenate([x[s : s + block_length] for s in starts])[:n]
        out[b] = stat(sample)
    return out


def percentile_interval(samples: np.ndarray, level: float) -> tuple[float, float]:
    """Efron percentile interval: [q_{α/2}, q_{1−α/2}] of the bootstrap distribution."""
    a = (1.0 - level) / 2.0
    lo, hi = np.quantile(samples, [a, 1.0 - a])
    return float(lo), float(hi)


# --------------------------------------------------------------------------- #
# Performance path
# --------------------------------------------------------------------------- #


@dataclass
class DrawdownOutcome:
    max_drawdown: float  # negative number, fraction of peak wealth
    peak_index: int  # observation index of the peak (-1 = starting wealth)
    trough_index: int
    recovery_index: (
        int | None
    )  # first observation at or above the peak after the trough
    duration: int  # observations from peak to recovery (or to end)
    longest_underwater: (
        int  # longest run of consecutive observations below running peak
    )


def drawdown_path(simple_returns: np.ndarray) -> DrawdownOutcome:
    """Plain-loop drawdown with starting wealth 1.0 as the first peak.

    W_t = Π_{s≤t} (1 + r_s);  P_t = max(1, max_{s≤t} W_s);  DD_t = W_t / P_t − 1.
    Max drawdown = min_t DD_t. Duration = t_recovery − t_peak in observations where
    t_peak is the last time the running peak was set before the trough (−1 for the
    starting wealth) and t_recovery the first t > trough with W_t ≥ P_trough.
    Time under water = longest consecutive run with W_t < P_t.
    """
    r = np.asarray(simple_returns, dtype=float)
    wealth = 1.0
    peak = 1.0
    peak_idx = -1
    mdd = 0.0
    mdd_peak_idx = -1
    mdd_trough_idx = -1
    mdd_peak_wealth = 1.0
    W = []
    for t, ret in enumerate(r):
        wealth *= 1.0 + ret
        W.append(wealth)
        if wealth >= peak:
            peak = wealth
            peak_idx = t
        dd = wealth / peak - 1.0
        if dd < mdd:
            mdd = dd
            mdd_peak_idx = peak_idx
            mdd_trough_idx = t
            mdd_peak_wealth = peak
    recovery = None
    if mdd < 0.0:
        for t in range(mdd_trough_idx + 1, len(r)):
            if W[t] >= mdd_peak_wealth:
                recovery = t
                break
        # Observations from the peak to recovery: with the peak at observation p
        # (p = −1 for the starting wealth) and recovery at observation q, the
        # count of observation steps is q − p; unrecovered: n − 1 − p.
        duration = (
            (recovery - mdd_peak_idx)
            if recovery is not None
            else (len(r) - 1 - mdd_peak_idx)
        )
    else:
        duration = 0
    # longest underwater run
    peak = 1.0
    run = 0
    best = 0
    for w in W:
        if w >= peak:
            peak = w
            run = 0
        else:
            run += 1
            best = max(best, run)
    return DrawdownOutcome(mdd, mdd_peak_idx, mdd_trough_idx, recovery, duration, best)


def cagr(simple_returns: np.ndarray, periods_per_year: float) -> float:
    """CAGR = W_T^{p/T} − 1."""
    W = float(np.prod(1.0 + np.asarray(simple_returns, dtype=float)))
    return W ** (periods_per_year / len(simple_returns)) - 1.0


# --------------------------------------------------------------------------- #
# Benchmark-relative
# --------------------------------------------------------------------------- #


def ols_alpha_beta(strategy: np.ndarray, benchmark: np.ndarray) -> tuple[float, float]:
    """β = Cov(r_s, r_b)/Var(r_b) (ddof cancels); α = r̄_s − β r̄_b.  Period, arithmetic."""
    s = np.asarray(strategy, dtype=float)
    b = np.asarray(benchmark, dtype=float)
    beta = float(np.cov(s, b, ddof=1)[0, 1] / np.var(b, ddof=1))
    return float(s.mean() - beta * b.mean()), beta


def information_ratio(
    strategy: np.ndarray, benchmark: np.ndarray
) -> tuple[float, float]:
    """TE = std(r_s − r_b, ddof=1);  IR = mean(r_s − r_b) / TE.  Returns (TE, IR)."""
    a = np.asarray(strategy, dtype=float) - np.asarray(benchmark, dtype=float)
    te = float(a.std(ddof=1))
    return te, float(a.mean() / te)
