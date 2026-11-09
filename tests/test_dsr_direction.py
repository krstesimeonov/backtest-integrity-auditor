"""Monte Carlo check of the direction and size of the package's DSR correction.

Why this module exists
----------------------
Two earlier write-ups disagree about which way the classical Deflated Sharpe
Ratio (Bailey & López de Prado, 2014) errs when the trials are correlated.

Claim 1, night-1 sample report section 3.3 and Appendix B (kept by the night-5
correction pass):

    "mean pairwise return correlation 0.68, so the trials are far from
    independent and the classical DSR, which assumes independence, is if
    anything lenient"

    "The trials in this review are strongly correlated (mean pairwise
    correlation above 0.6), so N overstates the number of independent trials
    and the DSR values shown are upper bounds."

Claim 2, night-8 notebook (dsr_worked_example) and ASSUMPTIONS.md A7:

    "Correlated trials behave like fewer independent ones, so for a given
    spread the raw count overstates the luck threshold, and the DSR at the
    raw count is on the strict side."

    "I believe the report's sentence is reversed. E[max] rises with N at a
    fixed σ_SR, and correlated trials have a smaller effective N."

What the package does
---------------------
``calculate_deflated_sharpe_ratio`` deflates the selected period Sharpe by the
threshold SR0 = sigma_hat * E_N, where sigma_hat is the ddof=1 standard
deviation of the N trial Sharpes and E_N is the Bailey & López de Prado closed
form for E[max of N iid N(0, 1)]; DSR = Phi((SR_selected - SR0) / SE). SR0 is
meant to be the expected maximum Sharpe of N no-skill trials. Phi is
increasing, so a threshold above the true expected maximum makes the DSR too
low (strict) and a threshold below it makes the DSR too high (lenient, an
upper bound).

Scenarios
---------
Every trial has T = 1000 daily returns and every Sharpe is computed as the
package computes it: mean / std(ddof=1) with a zero risk-free rate.

S0   independent normal trials, true Sharpe 0, N in {10, 100, 1000}.
S1   the same with true daily Sharpe 0.05 (0.79 annualised); S1h gives every
     trial its own true Sharpe drawn from N(0.05, 0.02^2).
S2   skewed, fat-tailed returns, true Sharpe 0 (S2) and 0.05 (S2s): a
     two-regime normal mixture (5% stress days N(-1.5, 2.5^2), calm days
     N(0.079, 0.85^2), standardized) with skewness -1.20 and excess kurtosis
     6.49. Full return paths, because the sample mean and variance of skewed
     returns are not independent.
S3   correlated trials, full return paths, true Sharpe 0:
     S3a equicorrelated returns with rho = 0.68, the report's mean pairwise
         correlation; N in {10, 100, 1000}.
     S3b 100 independent clusters of 10 near-duplicates (within-cluster return
         correlation 0.98), N = 1000; its mean pairwise correlation is only
         0.01, and S3c adds a common component to reach 0.68.
     S3c the report's mid grid: a 7 x 3 x 6 x 3 = 378-trial factorial whose
         returns share a common component and one component per parameter
         level (5% idiosyncratic), with mean pairwise correlation 0.68.
     S3d a stress case outside the report's balanced design: one configuration
         duplicated 271 times next to 29 distinct ones, N = 300.
     The effective counts given to the package are rho + (1 - rho) N for S3a
     and S3c (the usual average-correlation heuristic) and the number of
     independent units for S3b (100) and S3d (30).

S0, S1 and S1h draw each trial's (mean, sd) from their exact joint law for iid
normal returns (mean ~ normal, (T-1)s^2/sigma^2 ~ chi-square(T-1), independent);
S2 and S3 simulate T x N return matrices. Each scenario simulates panels of
1000 trials (378 for S3c, 300 for S3d); smaller families are disjoint groups of
one panel, and standard errors are computed across panels, which stays valid
when the groups share a panel's common component (S3a). S3a and S3c returns
have a component shared by every trial; since every trial's Sharpe has
expectation exactly 0 (the returns are symmetric about zero), E[max SR] is
estimated there as the mean of (max - the family's mean Sharpe), which has the
same expectation without most of the shared component's noise. The plain mean
of the maximum is printed beside it. The real
``calculate_deflated_sharpe_ratio`` runs on simulated families of every kind
and must reproduce the vectorized numbers used for the bulk.

Finding (asserted in test_verdict_on_the_two_correlation_claims)
----------------------------------------------------------------
With equicorrelated trials the package's threshold at the raw N already
matches the simulated expected maximum to within about 1%, because sigma_hat
measured across the trials shrinks by sqrt(1 - rho). With clustered trials
and with the factorial grid it lies above it (about +19% and +10%), so the
raw-N DSR is strict. At a fixed spread a smaller effective N always raises the
DSR. Claim 1 is therefore reversed and Claim 2 holds on these structures. The
exception, S3d, is a family dominated by one duplicated configuration: there
sigma_hat collapses, the raw-N DSR is lenient (about -40%) and a smaller N
makes it worse, so the fault lies in the spread, not in the count.

Tolerances
----------
Package faithfulness: per-trial Sharpes, sigma_hat, the observed maximum and
    SR0 from the vectorized code equal the package's on the same paths to a
    relative 1e-12.
Exact order statistics: E[max Z_N] by quadrature agrees with a second
    quadrature to 1e-9 and with the published tables (1.53875, 2.50759,
    3.24144) to 5e-6.
Direction: E_sim[SR_max] - s exceeds 4 Monte Carlo standard errors (SE) and
    rises with N by more than 4 combined SE; mean SR0 is positive and rises
    with N; on real package results the DSR falls strictly as N rises at a
    fixed spread and winner, equals PSR(0) at N = 1 to 1e-12, and is below
    PSR(0) for N >= 2.
Magnitude (S0, S1, S1h, S2, S2s): |E_sim[SR_max - SR0] - s| <= tol with
    tol = sd_SR * E[max Z_N] * (|closed-form error| + spread bias)
          + |shape shift| + |estimator bias| + 4 SE.
    sd_SR is the simulated sampling sd of one trial's Sharpe (the package's
    SE formula at the population moments agrees to 0.2% in S0-S2). The
    closed-form error is E_N / E[max Z_N] - 1: +2.33%, +0.92%, +0.42% at
    N = 10, 100, 1000. The spread bias is 1 - c4(N), the normal-theory
    shortfall of E[sigma_hat]: 2.73%, 0.25%, 0.03%. The shape shift is the
    second-order Cornish-Fisher change in E[max] implied by the measured
    skewness and excess kurtosis of the Sharpe estimates; it matters for S2,
    whose Sharpe estimates have skewness about -2 * (-1.20) / sqrt(T) =
    +0.076. The estimator bias, E_sim[SR_i] - s, is not selection, and no
    selection correction removes it. SE is the standard error of the paired
    per-panel difference. The printed table shows every term.
Simulation vs exact theory: |E_sim[SR_max] - E_sim[SR_i] - sd_SR * E[max Z_N]|
    <= |shape shift| + 4 SE.
Skewed shortfall: for S2 and S2s, E_sim[SR_max - SR0] - s > 4 SE, documenting
    that the normal-theory threshold sits slightly low for negatively skewed
    returns.
S2 innovations: the mean, variance, skewness and excess kurtosis of 16
    million draws lie within 4 SE (from 16 chunks) of 0, 1, -1.196 and 6.488.
Heterogeneous skill (S1h): the winner's true Sharpe exceeds E_sim[SR_max -
    SR0] by more than 4 SE.
Correlated verdicts: gap = mean SR0(raw N) - E_sim[SR_max] and
    tol = E_sim[SR_max] * (|closed-form error| + spread bias + shape term)
          + 4 SE(gap);
    "strict" if gap > tol, "lenient" if gap < -tol, otherwise "about right".
    Claim 1 survives only if no report-like structure (S3a-S3c) is strict;
    Claim 2 survives only if none is lenient. Also: E_sim[max] > 4 SE; the
    plain and centred estimates agree within 4 plain SE; S3a's E_sim[max]
    rises with N by more than 4 combined SE; on every real package run
    DSR(raw N) < DSR(effective N), an exact inequality.

Run ``pytest -q -s tests/test_dsr_direction.py`` to print the results tables.
"""

import functools
import math
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import product
from statistics import NormalDist
from typing import TypeVar

import numpy as np
import pandas as pd
import pytest
from scipy import integrate, optimize, special

from backtest_auditor.domain.assumptions import DeflatedSharpeRatioSpec
from backtest_auditor.domain.enums import (
    DeflatedSharpeRatioMethod,
    DeflatedSharpeRatioStatus,
    DSRTrialCountBasis,
    DSRTrialCountPolicy,
    ReturnConvention,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (
    ExperimentFamily,
    ExperimentFamilyManifest,
    ExperimentTrial,
    TrialParameter,
    TrialReturnMatrix,
)
from backtest_auditor.domain.results import (
    DeflatedSharpeRatioResult,
    DeflatedSharpeScenarioResult,
)
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.statistics.deflated_sharpe import (
    _expected_maximum_standard_normal,
    calculate_deflated_sharpe_ratio,
)

OBSERVATIONS = 1000  # T, daily returns per trial
TRIAL_COUNTS = (10, 100, 1000)
PANEL_WIDTH = max(TRIAL_COUNTS)
TRUE_SHARPE = 0.05  # daily; 0.05 * sqrt(252) = 0.79 annualised
TRUE_SHARPE_SPREAD = 0.02  # S1h: true Sharpes ~ N(0.05, 0.02^2)
REPORT_CORRELATION = 0.68
EXACT_PANELS = 20_000  # S0, S1, S1h
PATH_PANELS = 2_000  # S2, S3: full T x N return matrices
FAMILIES_PER_DESIGN = 5  # real package runs per correlated structure and N
DAILY_VOLATILITY = 0.01  # scale for package families (simple returns > -1)
WORKERS = 4  # numpy releases the GIL in its generators and reductions
EULER_GAMMA = 0.5772156649015329
NORMAL = NormalDist()

# S2: two-regime mixture with mean exactly zero, standardized to unit variance.
STRESS_PROBABILITY = 0.05
STRESS_MEAN = -1.5
STRESS_SD = 2.5
CALM_SD = 0.85
CALM_MEAN = -STRESS_PROBABILITY * STRESS_MEAN / (1.0 - STRESS_PROBABILITY)

# S3b and S3d: near-duplicates share 98% of their return variance.
CLUSTER_OWN_SHARE = 0.02
BALANCED_CLUSTERS = (10,) * 100
DOMINANT_CLUSTERS = (271,) + (1,) * 29

# S3c: lookback (7) x volatility factor (3) x SMA filter (6) x bond (3), with
# shares chosen so that the expected mean pairwise correlation is 0.68.
FACTORIAL_LEVELS = (7, 3, 6, 3)
FACTORIAL_LEVEL_OF_TRIAL = np.array(
    list(product(*(range(levels) for levels in FACTORIAL_LEVELS)))
).T
FACTORIAL_TRIALS = FACTORIAL_LEVEL_OF_TRIAL.shape[1]
FACTORIAL_OWN_SHARE = 0.05
_SHARED_LEVEL_PROBABILITY = sum(
    (FACTORIAL_TRIALS / levels - 1.0) / (FACTORIAL_TRIALS - 1.0)
    for levels in FACTORIAL_LEVELS
)
FACTORIAL_LEVEL_SHARE = (1.0 - REPORT_CORRELATION - FACTORIAL_OWN_SHARE) / (
    len(FACTORIAL_LEVELS) - _SHARED_LEVEL_PROBABILITY
)
FACTORIAL_COMMON_SHARE = (
    1.0 - len(FACTORIAL_LEVELS) * FACTORIAL_LEVEL_SHARE - FACTORIAL_OWN_SHARE
)

ChunkResult = TypeVar("ChunkResult")


# --------------------------------------------------------------------------- #
# Exact order statistics and the package's closed form
# --------------------------------------------------------------------------- #


@functools.cache
def _normal_maximum_moments(trial_count: int) -> tuple[float, float, float]:
    """E[M], E[M^2], E[M^3] for M the maximum of N iid N(0, 1), by quadrature."""

    log_count = math.log(trial_count)

    def density(x: float) -> float:
        log_density = (
            log_count
            + (trial_count - 1) * float(special.log_ndtr(x))
            - 0.5 * x * x
            - 0.5 * math.log(2.0 * math.pi)
        )
        return math.exp(log_density)

    mode = NORMAL.inv_cdf(1.0 - 1.0 / trial_count)
    moments = []
    for power in (1, 2, 3):
        value, _ = integrate.quad(
            lambda x: x**power * density(x),
            -12.0,
            12.0,
            points=[mode],
            limit=200,
            epsabs=1e-14,
            epsrel=1e-12,
        )
        moments.append(value)
    return moments[0], moments[1], moments[2]


def _expected_maximum_by_survival(trial_count: int) -> float:
    """E[M] as the integral of 1 - Phi^N over x > 0 minus Phi^N over x < 0."""

    upper, _ = integrate.quad(
        lambda x: -math.expm1(trial_count * float(special.log_ndtr(x))),
        0.0,
        12.0,
        limit=200,
        epsabs=1e-14,
    )
    lower, _ = integrate.quad(
        lambda x: math.exp(trial_count * float(special.log_ndtr(x))),
        -12.0,
        0.0,
        limit=200,
        epsabs=1e-14,
    )
    return upper - lower


def _exact_expected_maximum(trial_count: int) -> float:
    return _normal_maximum_moments(trial_count)[0]


def _closed_form(trial_count: float) -> float:
    """The package's closed form, extended to a real-valued trial count."""

    return (1.0 - EULER_GAMMA) * NORMAL.inv_cdf(
        1.0 - 1.0 / trial_count
    ) + EULER_GAMMA * NORMAL.inv_cdf(1.0 - 1.0 / (trial_count * math.e))


def _closed_form_error(trial_count: int) -> float:
    return (
        _expected_maximum_standard_normal(trial_count)
        / _exact_expected_maximum(trial_count)
        - 1.0
    )


def _spread_bias(trial_count: int) -> float:
    """1 - c4(N): relative shortfall of E[sigma_hat] for N normal Sharpes."""

    log_ratio = special.gammaln(trial_count / 2.0) - special.gammaln(
        (trial_count - 1.0) / 2.0
    )
    return 1.0 - math.sqrt(2.0 / (trial_count - 1.0)) * math.exp(log_ratio)


def _shape_shift(trial_count: int, skewness: float, excess_kurtosis: float) -> float:
    """Change in E[max] / sd caused by non-normal Sharpe estimates.

    The second-order Cornish-Fisher map x = z + g(z^2 - 1)/6 + k(z^3 - 3z)/24
    - g^2(2z^3 - 5z)/36 is increasing for small g and k, so it carries the
    maximum of N standard normals to the maximum of N estimates.
    """

    first, second, third = _normal_maximum_moments(trial_count)
    return (
        skewness / 6.0 * (second - 1.0)
        + excess_kurtosis / 24.0 * (third - 3.0 * first)
        - skewness**2 / 36.0 * (2.0 * third - 5.0 * first)
    )


def _implied_trial_count(multiplier: float) -> float:
    """Trial count at which the package's closed form equals `multiplier`."""

    root = optimize.brentq(
        lambda log_count: _closed_form(math.exp(log_count)) - multiplier,
        math.log(1.5),
        math.log(1e12),
        xtol=1e-12,
    )
    return math.exp(root)


def _average_correlation_count(trial_count: int) -> int:
    """The usual effective-count heuristic rho + (1 - rho) N."""

    return round(REPORT_CORRELATION + (1.0 - REPORT_CORRELATION) * trial_count)


def _sharpe_sd_theory(
    true_sharpe: float,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
    spread: float = 0.0,
) -> float:
    """The package's Sharpe standard error at the population moments."""

    variance_adjustment = (
        1.0 - skewness * true_sharpe + (excess_kurtosis + 2.0) / 4.0 * true_sharpe**2
    )
    return math.sqrt(variance_adjustment / (OBSERVATIONS - 1) + spread**2)


# --------------------------------------------------------------------------- #
# Return generators
# --------------------------------------------------------------------------- #


def _period_sharpes(returns: np.ndarray) -> np.ndarray:
    """Per-trial period Sharpe as the package computes it (r_f = 0, ddof=1)."""

    return np.mean(returns, axis=0) / np.std(returns, axis=0, ddof=1)


def _mixture_moments() -> tuple[float, float, float]:
    """Standard deviation, skewness and excess kurtosis of the S2 mixture."""

    components = (
        (1.0 - STRESS_PROBABILITY, CALM_MEAN, CALM_SD),
        (STRESS_PROBABILITY, STRESS_MEAN, STRESS_SD),
    )
    # The mixture mean is zero, so raw moments are central moments.
    second = sum(w * (m**2 + s**2) for w, m, s in components)
    third = sum(w * (m**3 + 3.0 * m * s**2) for w, m, s in components)
    fourth = sum(w * (m**4 + 6.0 * m**2 * s**2 + 3.0 * s**4) for w, m, s in components)
    return math.sqrt(second), third / second**1.5, fourth / second**2 - 3.0


MIXTURE_SD, MIXTURE_SKEWNESS, MIXTURE_EXCESS_KURTOSIS = _mixture_moments()


def _skewed_innovations(rng: np.random.Generator, shape: tuple[int, int]) -> np.ndarray:
    """Standardized two-regime mixture draws (mean 0, variance 1)."""

    stress = rng.random(shape) < STRESS_PROBABILITY
    values = rng.standard_normal(shape)
    values *= np.where(stress, STRESS_SD, CALM_SD)
    values += np.where(stress, STRESS_MEAN, CALM_MEAN)
    values /= MIXTURE_SD
    return values


MIXTURE_SAMPLE_CHUNKS = 16


@dataclass(frozen=True)
class SampleMoments:
    mean: float
    variance: float
    skewness: float
    excess_kurtosis: float
    standard_errors: tuple[float, float, float, float]


@functools.cache
def _measured_mixture_moments() -> SampleMoments:
    """Moments of 16 million S2 draws, with standard errors from 16 chunks."""

    rng = np.random.default_rng(15)
    estimates = []
    for _ in range(MIXTURE_SAMPLE_CHUNKS):
        draws = _skewed_innovations(rng, (OBSERVATIONS, PANEL_WIDTH)).ravel()
        centred = draws - np.mean(draws)
        variance = np.mean(centred**2)
        estimates.append(
            [
                np.mean(draws),
                variance,
                np.mean(centred**3) / variance**1.5,
                np.mean(centred**4) / variance**2 - 3.0,
            ]
        )
    values = np.asarray(estimates)
    means = values.mean(axis=0)
    errors = values.std(axis=0, ddof=1) / math.sqrt(len(values))
    return SampleMoments(
        mean=float(means[0]),
        variance=float(means[1]),
        skewness=float(means[2]),
        excess_kurtosis=float(means[3]),
        standard_errors=(
            float(errors[0]),
            float(errors[1]),
            float(errors[2]),
            float(errors[3]),
        ),
    )


def _equicorrelated_returns(rng: np.random.Generator, trial_count: int) -> np.ndarray:
    common = rng.standard_normal((OBSERVATIONS, 1))
    own = rng.standard_normal((OBSERVATIONS, trial_count))
    return (
        math.sqrt(REPORT_CORRELATION) * common
        + math.sqrt(1.0 - REPORT_CORRELATION) * own
    )


def _clustered_returns(
    rng: np.random.Generator,
    cluster_sizes: Sequence[int],
) -> np.ndarray:
    shared = rng.standard_normal((OBSERVATIONS, len(cluster_sizes)))
    own = rng.standard_normal((OBSERVATIONS, sum(cluster_sizes)))
    return (
        math.sqrt(1.0 - CLUSTER_OWN_SHARE) * np.repeat(shared, cluster_sizes, axis=1)
        + math.sqrt(CLUSTER_OWN_SHARE) * own
    )


def _balanced_cluster_returns(
    rng: np.random.Generator,
    trial_count: int,
) -> np.ndarray:
    assert trial_count == sum(BALANCED_CLUSTERS)
    return _clustered_returns(rng, BALANCED_CLUSTERS)


def _dominant_cluster_returns(
    rng: np.random.Generator,
    trial_count: int,
) -> np.ndarray:
    assert trial_count == sum(DOMINANT_CLUSTERS)
    return _clustered_returns(rng, DOMINANT_CLUSTERS)


def _factorial_returns(rng: np.random.Generator, trial_count: int) -> np.ndarray:
    assert trial_count == FACTORIAL_TRIALS
    returns = math.sqrt(FACTORIAL_COMMON_SHARE) * rng.standard_normal(
        (OBSERVATIONS, 1)
    ) + math.sqrt(FACTORIAL_OWN_SHARE) * rng.standard_normal(
        (OBSERVATIONS, FACTORIAL_TRIALS)
    )
    for levels, level_of_trial in zip(FACTORIAL_LEVELS, FACTORIAL_LEVEL_OF_TRIAL):
        level_components = rng.standard_normal((OBSERVATIONS, levels))
        returns += (
            math.sqrt(FACTORIAL_LEVEL_SHARE) * level_components[:, level_of_trial]
        )
    return returns


# --------------------------------------------------------------------------- #
# Simulation and per-panel summaries
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PanelSummary:
    """Per-panel statistics of one scenario, for each family size N.

    ``families[N]`` has one row per simulated panel holding the panel's
    average, over its disjoint N-trial families, of: the maximum trial Sharpe,
    the cross-trial spread sigma_hat (ddof=1), the true Sharpe of the maximum
    trial, and the family's mean trial Sharpe.
    """

    families: dict[int, np.ndarray]
    power_sums: np.ndarray  # count and sums of (SR - centre)^k, k = 1..4


@dataclass(frozen=True)
class Moments:
    mean: float
    sd: float
    skewness: float
    excess_kurtosis: float


@dataclass(frozen=True)
class Scenario:
    key: str
    description: str
    true_sharpe: float
    return_skewness: float
    return_excess_kurtosis: float
    sharpe_sd_theory: float
    panels: int
    panel_width: int
    summary: PanelSummary

    @property
    def moments(self) -> Moments:
        """Moments of a single trial's Sharpe, pooled over every trial."""

        count, first, second, third, fourth = self.summary.power_sums
        offset = first / count
        central_2 = second / count - offset**2
        central_3 = third / count - 3.0 * offset * second / count + 2.0 * offset**3
        central_4 = (
            fourth / count
            - 4.0 * offset * third / count
            + 6.0 * offset**2 * second / count
            - 3.0 * offset**4
        )
        return Moments(
            mean=self.true_sharpe + offset,
            sd=math.sqrt(central_2 * count / (count - 1.0)),
            skewness=central_3 / central_2**1.5,
            excess_kurtosis=central_4 / central_2**2 - 3.0,
        )


def _run_in_chunks(
    simulate: Callable[[np.random.Generator, int], ChunkResult],
    seed: int,
    panels: int,
    chunk_size: int,
) -> list[ChunkResult]:
    """Simulate `panels` in equal chunks, each with its own child seed.

    Results come back in chunk order, so they do not depend on thread timing.
    """

    chunk_count, remainder = divmod(panels, chunk_size)
    assert remainder == 0
    generators = [
        np.random.default_rng(child)
        for child in np.random.SeedSequence(seed).spawn(chunk_count)
    ]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(simulate, generators, [chunk_size] * chunk_count))


def _summarize(
    sharpes: np.ndarray,
    true_sharpes: np.ndarray,
    trial_counts: Sequence[int],
    centre: float,
) -> PanelSummary:
    panels, width = sharpes.shape
    families: dict[int, np.ndarray] = {}
    for trial_count in trial_counts:
        assert width % trial_count == 0
        shape = (panels, width // trial_count, trial_count)
        grouped = sharpes.reshape(shape)
        winner = np.argmax(grouped, axis=2)[..., np.newaxis]
        maximum = np.take_along_axis(grouped, winner, axis=2)[..., 0]
        winner_truth = np.take_along_axis(true_sharpes.reshape(shape), winner, axis=2)
        per_family = (
            maximum,
            np.std(grouped, axis=2, ddof=1),
            winner_truth[..., 0],
            np.mean(grouped, axis=2),
        )
        families[trial_count] = np.column_stack(
            [values.mean(axis=1) for values in per_family]
        )
    deviations = sharpes.ravel() - centre
    power_sums = np.array(
        [deviations.size, *(np.sum(deviations**power) for power in (1, 2, 3, 4))],
        dtype=np.float64,
    )
    return PanelSummary(families=families, power_sums=power_sums)


def _combine(chunks: Sequence[PanelSummary]) -> PanelSummary:
    return PanelSummary(
        families={
            trial_count: np.concatenate(
                [chunk.families[trial_count] for chunk in chunks]
            )
            for trial_count in chunks[0].families
        },
        power_sums=np.sum([chunk.power_sums for chunk in chunks], axis=0),
    )


def _exact_normal_simulator(
    true_sharpe: float,
    spread: float,
) -> Callable[[np.random.Generator, int], PanelSummary]:
    def simulate(rng: np.random.Generator, panels: int) -> PanelSummary:
        shape = (panels, PANEL_WIDTH)
        truth = np.full(shape, true_sharpe)
        if spread > 0.0:
            truth += spread * rng.standard_normal(shape)
        mean_noise = rng.standard_normal(shape) / math.sqrt(OBSERVATIONS)
        chi_square = rng.chisquare(OBSERVATIONS - 1, size=shape)
        sharpes = (truth + mean_noise) / np.sqrt(chi_square / (OBSERVATIONS - 1))
        return _summarize(sharpes, truth, TRIAL_COUNTS, centre=true_sharpe)

    return simulate


def _simulate_skewed(
    rng: np.random.Generator,
    panels: int,
) -> tuple[PanelSummary, PanelSummary]:
    """Full mixture paths; S2 and S2s share them (common random numbers).

    For returns r = vol * (s + e) the package's Sharpe is (s + mean e) / sd e.
    """

    means = np.empty((panels, PANEL_WIDTH))
    sds = np.empty((panels, PANEL_WIDTH))
    for row in range(panels):
        innovations = _skewed_innovations(rng, (OBSERVATIONS, PANEL_WIDTH))
        means[row] = np.mean(innovations, axis=0)
        sds[row] = np.std(innovations, axis=0, ddof=1)
    summaries = []
    for true_sharpe in (0.0, TRUE_SHARPE):
        truth = np.full(means.shape, true_sharpe)
        sharpes = (true_sharpe + means) / sds
        summaries.append(_summarize(sharpes, truth, TRIAL_COUNTS, centre=true_sharpe))
    return summaries[0], summaries[1]


@functools.cache
def _skewed_summaries() -> tuple[PanelSummary, PanelSummary]:
    chunks = _run_in_chunks(
        _simulate_skewed, seed=14, panels=PATH_PANELS, chunk_size=125
    )
    return (
        _combine([chunk[0] for chunk in chunks]),
        _combine([chunk[1] for chunk in chunks]),
    )


INDEPENDENT_KEYS = ("S0", "S1", "S1h", "S2", "S2s")


@functools.cache
def _independent_scenario(key: str) -> Scenario:
    if key in ("S2", "S2s"):
        true_sharpe = 0.0 if key == "S2" else TRUE_SHARPE
        return Scenario(
            key=key,
            description=f"skewed mixture, s={true_sharpe:g}",
            true_sharpe=true_sharpe,
            return_skewness=MIXTURE_SKEWNESS,
            return_excess_kurtosis=MIXTURE_EXCESS_KURTOSIS,
            sharpe_sd_theory=_sharpe_sd_theory(
                true_sharpe, MIXTURE_SKEWNESS, MIXTURE_EXCESS_KURTOSIS
            ),
            panels=PATH_PANELS,
            panel_width=PANEL_WIDTH,
            summary=_skewed_summaries()[0 if key == "S2" else 1],
        )
    seed, true_sharpe, spread, description = {
        "S0": (11, 0.0, 0.0, "normal, s=0"),
        "S1": (12, TRUE_SHARPE, 0.0, "normal, s=0.05"),
        "S1h": (13, TRUE_SHARPE, TRUE_SHARPE_SPREAD, "normal, s~N(0.05,0.02^2)"),
    }[key]
    chunks = _run_in_chunks(
        _exact_normal_simulator(true_sharpe, spread),
        seed=seed,
        panels=EXACT_PANELS,
        chunk_size=500,
    )
    return Scenario(
        key=key,
        description=description,
        true_sharpe=true_sharpe,
        return_skewness=0.0,
        return_excess_kurtosis=0.0,
        sharpe_sd_theory=_sharpe_sd_theory(true_sharpe, spread=spread),
        panels=EXACT_PANELS,
        panel_width=PANEL_WIDTH,
        summary=_combine(chunks),
    )


@dataclass(frozen=True)
class CorrelatedDesign:
    key: str
    description: str
    seed: int
    trial_counts: tuple[int, ...]
    effective_counts: tuple[int, ...]
    report_like: bool
    common_component: bool  # one return component shared by every trial
    returns: Callable[[np.random.Generator, int], np.ndarray]


CORRELATED_DESIGNS = (
    CorrelatedDesign(
        key="S3a",
        description="equicorrelated, rho=0.68",
        seed=31,
        trial_counts=TRIAL_COUNTS,
        effective_counts=tuple(_average_correlation_count(n) for n in TRIAL_COUNTS),
        report_like=True,
        common_component=True,
        returns=_equicorrelated_returns,
    ),
    CorrelatedDesign(
        key="S3b",
        description="100 clusters x 10 near-dups",
        seed=32,
        trial_counts=(sum(BALANCED_CLUSTERS),),
        effective_counts=(len(BALANCED_CLUSTERS),),
        report_like=True,
        common_component=False,
        returns=_balanced_cluster_returns,
    ),
    CorrelatedDesign(
        key="S3c",
        description="7x3x6x3 factorial, rho=0.68",
        seed=33,
        trial_counts=(FACTORIAL_TRIALS,),
        effective_counts=(_average_correlation_count(FACTORIAL_TRIALS),),
        report_like=True,
        common_component=True,
        returns=_factorial_returns,
    ),
    CorrelatedDesign(
        key="S3d",
        description="stress: 271 dups + 29 distinct",
        seed=34,
        trial_counts=(sum(DOMINANT_CLUSTERS),),
        effective_counts=(len(DOMINANT_CLUSTERS),),
        report_like=False,
        common_component=False,
        returns=_dominant_cluster_returns,
    ),
)
DESIGNS_BY_KEY = {design.key: design for design in CORRELATED_DESIGNS}


@functools.cache
def _correlated_scenario(key: str) -> Scenario:
    design = DESIGNS_BY_KEY[key]
    width = max(design.trial_counts)

    def simulate(rng: np.random.Generator, panels: int) -> PanelSummary:
        sharpes = np.stack(
            [_period_sharpes(design.returns(rng, width)) for _ in range(panels)]
        )
        return _summarize(sharpes, np.zeros_like(sharpes), design.trial_counts, 0.0)

    chunks = _run_in_chunks(
        simulate, seed=design.seed, panels=PATH_PANELS, chunk_size=125
    )
    return Scenario(
        key=key,
        description=design.description,
        true_sharpe=0.0,
        return_skewness=0.0,
        return_excess_kurtosis=0.0,
        sharpe_sd_theory=_sharpe_sd_theory(0.0),
        panels=PATH_PANELS,
        panel_width=width,
        summary=_combine(chunks),
    )


# --------------------------------------------------------------------------- #
# Result rows
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IndependentRow:
    key: str
    trial_count: int
    families: int
    simulated_maximum: float
    simulated_maximum_se: float
    inflation: float  # E_sim[SR_max] - s
    order_statistic_inflation: float  # sd_SR * E[max Z_N]
    order_statistic_gap: float  # E_sim[SR_max] - E_sim[SR_i] - sd_SR * E[max Z_N]
    order_statistic_tolerance: float
    package_threshold: float  # mean SR0
    residual: float  # E_sim[SR_max - SR0] - s
    residual_se: float
    closed_form_error: float
    spread_bias: float
    shape_shift: float  # in Sharpe units
    estimator_bias: float  # E_sim[SR_i] - s
    tolerance: float
    selected_true_sharpe: float  # E[true Sharpe of the maximum trial]


@functools.cache
def _independent_row(key: str, trial_count: int) -> IndependentRow:
    scenario = _independent_scenario(key)
    moments = scenario.moments
    maximum, spread, winner_truth, _ = scenario.summary.families[trial_count].T
    root_panels = math.sqrt(len(maximum))
    threshold = _expected_maximum_standard_normal(trial_count) * spread
    residual_per_panel = maximum - threshold
    maximum_se = float(np.std(maximum, ddof=1)) / root_panels
    residual_se = float(np.std(residual_per_panel, ddof=1)) / root_panels
    order_statistic = moments.sd * _exact_expected_maximum(trial_count)
    shape_shift = moments.sd * _shape_shift(
        trial_count, moments.skewness, moments.excess_kurtosis
    )
    estimator_bias = moments.mean - scenario.true_sharpe
    closed_form_error = _closed_form_error(trial_count)
    spread_bias = _spread_bias(trial_count)
    tolerance = (
        order_statistic * (abs(closed_form_error) + spread_bias)
        + abs(shape_shift)
        + abs(estimator_bias)
        + 4.0 * residual_se
    )
    simulated_maximum = float(np.mean(maximum))
    return IndependentRow(
        key=key,
        trial_count=trial_count,
        families=scenario.panels * (scenario.panel_width // trial_count),
        simulated_maximum=simulated_maximum,
        simulated_maximum_se=maximum_se,
        inflation=simulated_maximum - scenario.true_sharpe,
        order_statistic_inflation=order_statistic,
        order_statistic_gap=simulated_maximum - moments.mean - order_statistic,
        order_statistic_tolerance=abs(shape_shift) + 4.0 * maximum_se,
        package_threshold=float(np.mean(threshold)),
        residual=float(np.mean(residual_per_panel)) - scenario.true_sharpe,
        residual_se=residual_se,
        closed_form_error=closed_form_error,
        spread_bias=spread_bias,
        shape_shift=shape_shift,
        estimator_bias=estimator_bias,
        tolerance=tolerance,
        selected_true_sharpe=float(np.mean(winner_truth)),
    )


def _independent_rows() -> list[IndependentRow]:
    return [_independent_row(key, n) for key in INDEPENDENT_KEYS for n in TRIAL_COUNTS]


@dataclass(frozen=True)
class CorrelatedRow:
    key: str
    description: str
    trial_count: int
    effective_count: int
    report_like: bool
    families: int
    simulated_maximum: float  # E_sim[SR_max], centred when common_component
    simulated_maximum_se: float
    plain_maximum: float  # plain mean of SR_max
    plain_maximum_se: float
    mean_spread: float
    raw_threshold: float
    raw_gap: float  # mean SR0(raw N) - E_sim[SR_max]
    raw_gap_se: float
    effective_threshold: float
    effective_gap: float
    implied_count: float  # N at which the closed form matches E_sim[SR_max]
    tolerance: float
    verdict: str


@functools.cache
def _correlated_row(key: str, trial_count: int) -> CorrelatedRow:
    design = DESIGNS_BY_KEY[key]
    scenario = _correlated_scenario(key)
    moments = scenario.moments
    effective_count = design.effective_counts[design.trial_counts.index(trial_count)]
    maximum, spread, _, family_mean = scenario.summary.families[trial_count].T
    root_panels = math.sqrt(len(maximum))
    if design.common_component:
        # E[SR_i] = 0 exactly (returns symmetric about zero), so subtracting the
        # family's mean Sharpe keeps E[max] and removes the common noise.
        centred_maximum = maximum - family_mean
    else:
        centred_maximum = maximum
    raw_threshold = _expected_maximum_standard_normal(trial_count) * spread
    effective_threshold = _expected_maximum_standard_normal(effective_count) * spread
    raw_gap_per_panel = raw_threshold - centred_maximum
    raw_gap = float(np.mean(raw_gap_per_panel))
    raw_gap_se = float(np.std(raw_gap_per_panel, ddof=1)) / root_panels
    simulated_maximum = float(np.mean(centred_maximum))
    shape_term = abs(
        _shape_shift(trial_count, moments.skewness, moments.excess_kurtosis)
    ) / _exact_expected_maximum(trial_count)
    allowance = (
        abs(_closed_form_error(trial_count)) + _spread_bias(trial_count) + shape_term
    )
    tolerance = simulated_maximum * allowance + 4.0 * raw_gap_se
    if raw_gap > tolerance:
        verdict = "strict"
    elif raw_gap < -tolerance:
        verdict = "lenient"
    else:
        verdict = "about right"
    mean_spread = float(np.mean(spread))
    return CorrelatedRow(
        key=key,
        description=design.description,
        trial_count=trial_count,
        effective_count=effective_count,
        report_like=design.report_like,
        families=scenario.panels * (scenario.panel_width // trial_count),
        simulated_maximum=simulated_maximum,
        simulated_maximum_se=float(np.std(centred_maximum, ddof=1)) / root_panels,
        plain_maximum=float(np.mean(maximum)),
        plain_maximum_se=float(np.std(maximum, ddof=1)) / root_panels,
        mean_spread=mean_spread,
        raw_threshold=float(np.mean(raw_threshold)),
        raw_gap=raw_gap,
        raw_gap_se=raw_gap_se,
        effective_threshold=float(np.mean(effective_threshold)),
        effective_gap=float(np.mean(effective_threshold)) - simulated_maximum,
        implied_count=_implied_trial_count(simulated_maximum / mean_spread),
        tolerance=tolerance,
        verdict=verdict,
    )


def _correlated_rows() -> list[CorrelatedRow]:
    return [
        _correlated_row(design.key, n)
        for design in CORRELATED_DESIGNS
        for n in design.trial_counts
    ]


# --------------------------------------------------------------------------- #
# Real package runs on simulated families
# --------------------------------------------------------------------------- #


def _spec(effective_count: int | None = None) -> DeflatedSharpeRatioSpec:
    return DeflatedSharpeRatioSpec(
        method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        annual_risk_free_rate=0.0,
        required_confidence_level=0.95,
        effective_independent_trial_count=effective_count,
        effective_trial_count_methodology=(
            None if effective_count is None else "simulation design"
        ),
    )


def _family(values: np.ndarray) -> ExperimentFamily:
    """A complete search whose selected trial is the observed-Sharpe winner."""

    observation_count, trial_count = values.shape
    sharpes = _period_sharpes(values)
    selected_index = int(np.argmax(sharpes))
    trial_ids = tuple(f"trial-{index + 1}" for index in range(trial_count))
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == selected_index,
            selection_score=float(sharpes[index]),
            parameters=(TrialParameter("configuration", index + 1),),
        )
        for index, trial_id in enumerate(trial_ids)
    )
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=252)
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="dsr-direction-simulation",
            declared_total_attempted_trials=trial_count,
            search_complete=True,
            selected_trial_id=trial_ids[selected_index],
            selection_rule="maximize observed Sharpe",
            selection_metric="sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("configuration",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=pd.date_range("2022-01-03", periods=observation_count, freq="B"),
            trial_ids=trial_ids,
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


def _dsr_scenario(
    result: DeflatedSharpeRatioResult,
    basis: DSRTrialCountBasis,
) -> DeflatedSharpeScenarioResult:
    return next(item for item in result.scenarios if item.trial_count_basis is basis)


def _psr_against_zero(result: DeflatedSharpeRatioResult) -> float:
    assert result.selected_period_sharpe_ratio is not None
    assert result.selected_period_sharpe_standard_error is not None
    return NORMAL.cdf(
        result.selected_period_sharpe_ratio
        / result.selected_period_sharpe_standard_error
    )


@dataclass(frozen=True)
class SimulatedFamily:
    key: str
    trial_count: int
    effective_count: int | None
    sharpes: np.ndarray  # vectorized per-trial Sharpes on the same paths
    result: DeflatedSharpeRatioResult


def _evaluate(
    key: str,
    values: np.ndarray,
    effective_count: int | None,
) -> SimulatedFamily:
    return SimulatedFamily(
        key=key,
        trial_count=values.shape[1],
        effective_count=effective_count,
        sharpes=_period_sharpes(values),
        result=calculate_deflated_sharpe_ratio(_family(values), _spec(effective_count)),
    )


@functools.cache
def _simulated_families() -> tuple[SimulatedFamily, ...]:
    families = []
    rng = np.random.default_rng(41)
    for key, true_sharpe, trial_count in (
        ("S0", 0.0, 10),
        ("S0", 0.0, 100),
        ("S0", 0.0, 1000),
        ("S1", TRUE_SHARPE, 100),
        ("S2", 0.0, 100),
        ("S2s", TRUE_SHARPE, 1000),
    ):
        shape = (OBSERVATIONS, trial_count)
        if key.startswith("S2"):
            innovations = _skewed_innovations(rng, shape)
        else:
            innovations = rng.standard_normal(shape)
        values = DAILY_VOLATILITY * (true_sharpe + innovations)
        families.append(_evaluate(key, values, None))
    for design in CORRELATED_DESIGNS:
        rng = np.random.default_rng(design.seed + 100)
        for trial_count, effective_count in zip(
            design.trial_counts, design.effective_counts
        ):
            for _ in range(FAMILIES_PER_DESIGN):
                values = DAILY_VOLATILITY * design.returns(rng, trial_count)
                families.append(_evaluate(design.key, values, effective_count))
    return tuple(families)


def _correlated_families() -> list[SimulatedFamily]:
    return [family for family in _simulated_families() if family.key in DESIGNS_BY_KEY]


@dataclass(frozen=True)
class FamilyDsrSummary:
    """Medians over the real package runs for one correlated structure and N."""

    key: str
    trial_count: int
    effective_count: int
    mean_correlation: float
    spread: float
    selected_sharpe: float
    psr: float
    dsr_raw: float
    dsr_effective: float
    dsr_simulated: float  # with SR0 = sigma_hat * E_sim[max] / E_sim[sigma_hat]
    raw_below_effective: int
    family_count: int


def _family_dsr_summaries() -> list[FamilyDsrSummary]:
    summaries = []
    for row in _correlated_rows():
        multiplier = row.simulated_maximum / row.mean_spread
        records = []
        for family in _correlated_families():
            if (family.key, family.trial_count) != (row.key, row.trial_count):
                continue
            result = family.result
            correlation = result.correlation_summary
            spread = result.cross_trial_sample_standard_deviation
            selected = result.selected_period_sharpe_ratio
            standard_error = result.selected_period_sharpe_standard_error
            assert correlation is not None and correlation.mean_correlation is not None
            assert spread is not None and selected is not None
            assert standard_error is not None
            raw = _dsr_scenario(result, DSRTrialCountBasis.SELECTION_ELIGIBLE)
            effective = _dsr_scenario(
                result, DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE
            )
            records.append(
                (
                    correlation.mean_correlation,
                    spread,
                    selected,
                    _psr_against_zero(result),
                    raw.deflated_sharpe_ratio,
                    effective.deflated_sharpe_ratio,
                    NORMAL.cdf((selected - spread * multiplier) / standard_error),
                )
            )
        medians = np.median(np.asarray(records), axis=0)
        summaries.append(
            FamilyDsrSummary(
                key=row.key,
                trial_count=row.trial_count,
                effective_count=row.effective_count,
                mean_correlation=float(medians[0]),
                spread=float(medians[1]),
                selected_sharpe=float(medians[2]),
                psr=float(medians[3]),
                dsr_raw=float(medians[4]),
                dsr_effective=float(medians[5]),
                dsr_simulated=float(medians[6]),
                raw_below_effective=sum(record[4] < record[5] for record in records),
                family_count=len(records),
            )
        )
    return summaries


def _claims() -> tuple[bool, bool]:
    """Whether Claim 1 and Claim 2 survive on the report-like structures."""

    report_like = [row for row in _correlated_rows() if row.report_like]
    claim_1 = not any(row.verdict == "strict" for row in report_like)
    claim_2 = not any(row.verdict == "lenient" for row in report_like)
    return claim_1, claim_2


# --------------------------------------------------------------------------- #
# Results table
# --------------------------------------------------------------------------- #


def _table(
    title: str,
    header: str,
    rows: Sequence[Sequence[str]],
    text_columns: int,
) -> str:
    """Align `rows` under a `|`-separated header; text columns left-aligned."""

    cells = [header.split("|"), *rows]
    widths = [max(len(cell) for cell in column) for column in zip(*cells)]
    lines = [title]
    for row in cells:
        lines.append(
            "  ".join(
                cell.ljust(width) if index < text_columns else cell.rjust(width)
                for index, (cell, width) in enumerate(zip(row, widths))
            )
        )
    return "\n".join(lines)


def _percent(value: float, decimals: int = 2) -> str:
    return f"{100.0 * value:+.{decimals}f}%"


def _share(value: float, decimals: int = 2) -> str:
    """An unsigned percentage, for tolerances and other magnitudes."""

    return f"{100.0 * value:.{decimals}f}%"


def _moments_table() -> str:
    scenarios = [_independent_scenario(key) for key in INDEPENDENT_KEYS]
    scenarios += [_correlated_scenario(design.key) for design in CORRELATED_DESIGNS]
    rows = []
    for scenario in scenarios:
        moments = scenario.moments
        rows.append(
            [
                scenario.key,
                scenario.description,
                f"{scenario.return_skewness:+.2f}",
                f"{scenario.return_excess_kurtosis:+.2f}",
                f"{scenario.true_sharpe:.3f}",
                f"{moments.mean:+.5f}",
                f"{scenario.sharpe_sd_theory:.5f}",
                f"{moments.sd:.5f}",
                f"{moments.skewness:+.3f}",
                f"{moments.excess_kurtosis:+.3f}",
                f"{scenario.panels} x {scenario.panel_width}",
            ]
        )
    measured = _measured_mixture_moments()
    note = (
        f"S2 innovations, {MIXTURE_SAMPLE_CHUNKS} x 10^6 draws: mean "
        f"{measured.mean:+.5f}, variance {measured.variance:.4f}, skewness "
        f"{measured.skewness:+.3f} (exact {MIXTURE_SKEWNESS:+.3f}), excess "
        f"kurtosis {measured.excess_kurtosis:+.2f} "
        f"(exact {MIXTURE_EXCESS_KURTOSIS:+.2f})"
    )
    title = (
        "[1] One trial's Sharpe estimate, pooled over every simulated trial; "
        "sd theory is the package's SE formula at the population moments"
    )
    header = (
        "key|design|ret skew|ret exkurt|true s|E[SR_i]|sd theory|sd sim|SR skew|"
        "SR exkurt|panels x trials"
    )
    return _table(title, header, rows, text_columns=2) + "\n" + note


def _independent_table() -> str:
    rows = []
    for row in _independent_rows():
        passed = (
            abs(row.residual) <= row.tolerance
            and abs(row.order_statistic_gap) <= row.order_statistic_tolerance
        )
        rows.append(
            [
                row.key,
                str(row.trial_count),
                str(row.families),
                f"{row.simulated_maximum:.5f}",
                f"{row.simulated_maximum_se:.5f}",
                f"{row.inflation:.5f}",
                f"{row.order_statistic_inflation:.5f}",
                _percent(row.order_statistic_gap / row.order_statistic_inflation),
                _share(row.order_statistic_tolerance / row.order_statistic_inflation),
                f"{row.package_threshold:.5f}",
                _percent(-row.residual / row.inflation),
                _share(row.tolerance / row.inflation),
                _percent(row.closed_form_error),
                _share(row.spread_bias),
                _percent(row.shape_shift / row.inflation),
                _percent(row.estimator_bias / row.inflation),
                f"{row.selected_true_sharpe:.4f}",
                "yes" if passed else "NO",
            ]
        )
    title = (
        "[2] Independent trials. infl = E_sim[SR_max] - s; exact = sd sim x "
        "E[max Z_N] (quadrature); SR0 = the package's threshold; shape and SR "
        "bias are fractions of infl; ok = both checks within tolerance"
    )
    header = (
        "key|N|families|E_sim[max]|SE|infl|exact|sim/exact-1|tol|mean SR0|"
        "SR0/infl-1|tol|closed-form|c4 bias|shape|SR bias|E[s winner]|ok"
    )
    return _table(title, header, rows, text_columns=1)


def _correlated_table() -> str:
    rows = []
    for row in _correlated_rows():
        rows.append(
            [
                row.key,
                row.description,
                str(row.trial_count),
                str(row.effective_count),
                str(row.families),
                f"{row.plain_maximum:.5f}",
                f"{row.plain_maximum_se:.5f}",
                f"{row.simulated_maximum:.5f}",
                f"{row.simulated_maximum_se:.5f}",
                f"{row.raw_threshold:.5f}",
                _percent(row.raw_gap / row.simulated_maximum, 1),
                f"{row.effective_threshold:.5f}",
                _percent(row.effective_gap / row.simulated_maximum, 1),
                f"{row.implied_count:.4g}",
                _share(row.tolerance / row.simulated_maximum, 1),
                row.verdict,
            ]
        )
    title = (
        "[3] Correlated trials, true Sharpe 0. E_sim[max] is the mean of (max - "
        "family mean Sharpe) for S3a and S3c and the plain mean otherwise; "
        "gaps are SR0 / E_sim[max] - 1;\n    N* is the trial count at which the "
        "closed form times the mean sigma_hat equals E_sim[max]"
    )
    header = (
        "key|design|N|N eff|families|plain max|SE|E_sim[max]|SE|SR0 raw N|"
        "gap raw|SR0 eff N|gap eff|N*|tol|verdict"
    )
    return _table(title, header, rows, text_columns=2)


def _family_table() -> str:
    rows = []
    for summary in _family_dsr_summaries():
        rows.append(
            [
                summary.key,
                str(summary.trial_count),
                str(summary.effective_count),
                f"{summary.mean_correlation:.3f}",
                f"{summary.spread:.5f}",
                f"{summary.selected_sharpe:.5f}",
                f"{summary.psr:.3f}",
                f"{summary.dsr_raw:.3f}",
                f"{summary.dsr_simulated:.3f}",
                f"{summary.dsr_effective:.3f}",
                f"{summary.raw_below_effective}/{summary.family_count}",
            ]
        )
    title = (
        f"[4] Real calculate_deflated_sharpe_ratio on simulated correlated "
        f"families (medians of {FAMILIES_PER_DESIGN}); DSR sim uses SR0 = "
        f"sigma_hat x E_sim[max] / E_sim[sigma_hat], the threshold the "
        f"simulation supports"
    )
    header = (
        "key|N|N eff|rho (pkg)|sigma_hat|SR winner|PSR(0)|DSR raw N|DSR sim|"
        "DSR eff N|raw<eff"
    )
    return _table(title, header, rows, text_columns=1)


def _verdict_text() -> str:
    def relative(gap: float, row: CorrelatedRow) -> str:
        return _percent(gap / row.simulated_maximum, 1)

    rows = _correlated_rows()
    report_like = [row for row in rows if row.report_like]
    claim_1, claim_2 = _claims()
    summaries = _family_dsr_summaries()
    lines = [
        "Verdict (gap = mean SR0 at the raw N / E_sim[max] - 1; positive = strict)",
        "  Report-like rows: "
        + "; ".join(
            f"{row.key} N={row.trial_count} {relative(row.raw_gap, row)} {row.verdict}"
            for row in report_like
        ),
        f"  Claim 1, raw-N DSR lenient or an upper bound: "
        f"{'SURVIVES' if claim_1 else 'REFUTED'} "
        f"({sum(row.verdict == 'strict' for row in report_like)} of "
        f"{len(report_like)} report-like rows strict)",
        f"  Claim 2, raw-N DSR on the strict side: "
        f"{'SURVIVES' if claim_2 else 'REFUTED'} "
        f"({sum(row.verdict == 'lenient' for row in report_like)} of "
        f"{len(report_like)} report-like rows lenient)",
        f"  Same spread and winner: DSR(raw N) < DSR(effective N) in "
        f"{sum(s.raw_below_effective for s in summaries)} of "
        f"{sum(s.family_count for s in summaries)} package runs",
    ]
    for row in rows:
        if not row.report_like:
            lines.append(
                f"  Outside the report's design: {row.key} ({row.description}) "
                f"raw-N gap {relative(row.raw_gap, row)} ({row.verdict}), "
                f"N={row.effective_count} gap {relative(row.effective_gap, row)}"
            )
    lines.append(
        "Tolerances: direction checks need more than 4 SE; [2] tol for "
        "sim/exact = |shape| + 4 SE; [2] tol for SR0 = exact x (|closed-form| + "
        "c4 bias) + |shape| + |SR bias| + 4 SE;\n  [3] tol = E_sim[max] x "
        "(|closed-form| + c4 bias + shape) + 4 SE; S2 draw moments within 4 SE; "
        "package reproduction rel 1e-12."
    )
    return "\n".join(lines)


def _format_tables() -> str:
    heading = (
        "DSR direction Monte Carlo: T = 1000 daily returns per trial, Sharpe = "
        "mean / std(ddof=1), r_f = 0, daily Sharpe units (x 15.87 to annualise)"
    )
    sections = (
        heading,
        _moments_table(),
        _independent_table(),
        _correlated_table(),
        _family_table(),
        _verdict_text(),
    )
    return "\n\n".join(sections)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_exact_expected_maximum_and_the_closed_form_error() -> None:
    published = {10: 1.53875, 100: 2.50759, 1000: 3.24144}
    for trial_count, value in published.items():
        exact = _exact_expected_maximum(trial_count)
        assert exact == pytest.approx(value, abs=5e-6)
        assert exact == pytest.approx(
            _expected_maximum_by_survival(trial_count), abs=1e-9
        )
        assert _closed_form(trial_count) == pytest.approx(
            _expected_maximum_standard_normal(trial_count), rel=1e-12
        )
    errors = [_closed_form_error(n) for n in TRIAL_COUNTS]
    # The closed form overstates E[max Z_N] at these N, by less as N grows.
    assert all(error > 0.0 for error in errors)
    assert errors == sorted(errors, reverse=True)


def test_vectorized_threshold_reproduces_the_package() -> None:
    for family in _simulated_families():
        result = family.result
        spread = float(np.std(family.sharpes, ddof=1))
        package_sharpes = [
            item.period_sharpe_ratio for item in result.trial_sharpe_estimates
        ]
        raw = _dsr_scenario(result, DSRTrialCountBasis.SELECTION_ELIGIBLE)

        assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE
        np.testing.assert_allclose(
            package_sharpes, family.sharpes, rtol=1e-12, atol=1e-15
        )
        assert result.cross_trial_sample_standard_deviation == pytest.approx(
            spread, rel=1e-12
        )
        assert result.observed_maximum_period_sharpe_ratio == pytest.approx(
            float(np.max(family.sharpes)), rel=1e-12
        )
        assert raw.trial_count == family.trial_count
        assert raw.expected_maximum_period_sharpe_ratio == pytest.approx(
            spread * _expected_maximum_standard_normal(family.trial_count), rel=1e-12
        )
        if family.effective_count is not None:
            effective = _dsr_scenario(
                result, DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE
            )
            assert effective.expected_maximum_period_sharpe_ratio == pytest.approx(
                spread * _expected_maximum_standard_normal(family.effective_count),
                rel=1e-12,
            )


@pytest.mark.parametrize("innovations", ["normal", "skewed"])
def test_dsr_falls_as_the_trial_count_rises(innovations: str) -> None:
    rng = np.random.default_rng(51)
    shape = (OBSERVATIONS, 100)
    if innovations == "normal":
        noise = rng.standard_normal(shape)
    else:
        noise = _skewed_innovations(rng, shape)
    family = _family(DAILY_VOLATILITY * (TRUE_SHARPE + noise))
    counts = (1, 2, 3, 5, 10, 20, 50, 100)
    results = [calculate_deflated_sharpe_ratio(family, _spec(n)) for n in counts]
    scenarios = [
        _dsr_scenario(result, DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE)
        for result in results
    ]
    thresholds = [item.expected_maximum_period_sharpe_ratio for item in scenarios]
    dsr = [item.deflated_sharpe_ratio for item in scenarios]
    psr = _psr_against_zero(results[0])

    # The same family each time: one spread and one winner, only N changes.
    spreads = {result.cross_trial_sample_standard_deviation for result in results}
    assert len(spreads) == 1
    assert thresholds[0] == 0.0
    assert dsr[0] == pytest.approx(psr, rel=1e-12)
    assert all(np.diff(thresholds) > 0.0)
    assert all(np.diff(dsr) < 0.0)
    assert all(value < psr for value in dsr[1:])


def test_correction_never_raises_the_deflated_sharpe() -> None:
    for family in _simulated_families():
        psr = _psr_against_zero(family.result)
        for scenario in family.result.scenarios:
            if scenario.trial_count >= 2:
                assert scenario.expected_maximum_period_sharpe_ratio > 0.0
                assert scenario.deflated_sharpe_ratio < psr


@pytest.mark.parametrize("key", INDEPENDENT_KEYS)
def test_selection_inflation_and_threshold_rise_with_trial_count(key: str) -> None:
    rows = [_independent_row(key, n) for n in TRIAL_COUNTS]
    for row in rows:
        assert row.inflation > 4.0 * row.simulated_maximum_se
        assert row.package_threshold > 0.0
    for smaller, larger in zip(rows, rows[1:]):
        combined_se = math.hypot(
            smaller.simulated_maximum_se, larger.simulated_maximum_se
        )
        assert larger.simulated_maximum - smaller.simulated_maximum > 4.0 * combined_se
        assert larger.package_threshold > smaller.package_threshold


@pytest.mark.parametrize("key", INDEPENDENT_KEYS)
@pytest.mark.parametrize("trial_count", TRIAL_COUNTS)
def test_simulation_matches_exact_order_statistics(key: str, trial_count: int) -> None:
    row = _independent_row(key, trial_count)
    assert abs(row.order_statistic_gap) <= row.order_statistic_tolerance


@pytest.mark.parametrize("key", INDEPENDENT_KEYS)
@pytest.mark.parametrize("trial_count", TRIAL_COUNTS)
def test_package_correction_removes_the_selection_inflation(
    key: str,
    trial_count: int,
) -> None:
    row = _independent_row(key, trial_count)
    assert abs(row.residual) <= row.tolerance


def test_skewed_returns_have_the_documented_moments() -> None:
    measured = _measured_mixture_moments()
    observed = (
        measured.mean,
        measured.variance,
        measured.skewness,
        measured.excess_kurtosis,
    )
    expected = (0.0, 1.0, MIXTURE_SKEWNESS, MIXTURE_EXCESS_KURTOSIS)
    for value, target, error in zip(observed, expected, measured.standard_errors):
        assert abs(value - target) <= 4.0 * error


@pytest.mark.parametrize("key", ["S2", "S2s"])
def test_skewed_returns_leave_a_small_shortfall(key: str) -> None:
    # Negatively skewed returns give right-skewed Sharpe estimates, so the
    # normal-theory threshold sits a little below the simulated inflation.
    for trial_count in TRIAL_COUNTS:
        row = _independent_row(key, trial_count)
        assert row.residual > 4.0 * row.residual_se
        assert row.shape_shift > 0.0


def test_heterogeneous_skill_correction_is_conservative_for_the_winner() -> None:
    # The spread includes real skill differences, so the correction brings the
    # winner back to the family's mean skill, below the winner's own skill.
    for trial_count in TRIAL_COUNTS:
        row = _independent_row("S1h", trial_count)
        removed_to = row.residual + TRUE_SHARPE  # E_sim[SR_max - SR0]
        assert row.selected_true_sharpe - removed_to > 4.0 * row.residual_se


def test_correlated_trials_raw_and_effective_counts() -> None:
    rows = _correlated_rows()
    for row in rows:
        assert row.simulated_maximum > 4.0 * row.simulated_maximum_se
        assert abs(row.plain_maximum - row.simulated_maximum) <= (
            4.0 * row.plain_maximum_se
        )
        assert row.raw_threshold > row.effective_threshold
    equicorrelated = [row for row in rows if row.key == "S3a"]
    for smaller, larger in zip(equicorrelated, equicorrelated[1:]):
        combined_se = math.hypot(
            smaller.simulated_maximum_se, larger.simulated_maximum_se
        )
        assert larger.simulated_maximum - smaller.simulated_maximum > 4.0 * combined_se
        assert larger.raw_threshold > smaller.raw_threshold
    # Real package runs: one spread and one winner, so the smaller effective
    # count always gives the higher DSR.
    for family in _correlated_families():
        assert family.effective_count is not None
        assert family.effective_count < family.trial_count
        raw = _dsr_scenario(family.result, DSRTrialCountBasis.SELECTION_ELIGIBLE)
        effective = _dsr_scenario(
            family.result, DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE
        )
        assert raw.deflated_sharpe_ratio < effective.deflated_sharpe_ratio


def test_verdict_on_the_two_correlation_claims() -> None:
    rows = {(row.key, row.trial_count): row for row in _correlated_rows()}
    claim_1, claim_2 = _claims()

    # What the simulation shows. Equicorrelated trials: the package's SR0 at
    # the raw N matches E_sim[max] within tolerance, because sigma_hat already
    # shrinks by sqrt(1 - rho). Clustered and factorial trials: SR0 at the raw
    # N is above E_sim[max], so the raw-N DSR is too low (strict).
    assert [rows["S3a", n].verdict for n in TRIAL_COUNTS] == ["about right"] * 3
    assert rows["S3b", sum(BALANCED_CLUSTERS)].verdict == "strict"
    assert rows["S3c", FACTORIAL_TRIALS].verdict == "strict"
    # Hence the raw-N DSR is not an upper bound (Claim 1 is reversed) and is
    # never lenient on report-like structures (Claim 2 holds).
    assert not claim_1
    assert claim_2
    # Outside the report's balanced design, one dominant duplicate cluster
    # shrinks sigma_hat and the raw-N DSR turns lenient; a smaller effective
    # N makes it more lenient, so Claim 1's mechanism is reversed there too.
    stress = rows["S3d", sum(DOMINANT_CLUSTERS)]
    assert stress.verdict == "lenient"
    assert stress.effective_gap < stress.raw_gap < 0.0


def test_print_results_table() -> None:
    table = _format_tables()
    print("\n" + table)
    assert "Verdict" in table
