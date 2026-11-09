"""Shared builders for the night3 adversarial suite.

Everything here constructs V1 domain objects from plain arrays so each test can
generate its own seeded synthetic data. The reference implementations live in
tests/adversarial/reference/reference_stats.py (night3/reference/ in night 3's
archive) and are imported as `ref`. Night 3's baseline reports that the tests
compare against (night3/baseline/) are in tests/adversarial/data/ (`DATA`).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / "data"

from .reference import reference_stats as ref  # noqa: E402

from backtest_auditor.domain.assumptions import (  # noqa: E402
    BootstrapSpec,
    CSCVSpec,
    DeflatedSharpeRatioSpec,
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (  # noqa: E402
    BootstrapIntervalMethod,
    BootstrapMethod,
    CSCVMethod,
    CSCVPerformanceMetric,
    CSCVRankTieMethod,
    CSCVWinnerTiePolicy,
    DeflatedSharpeRatioMethod,
    DSRTrialCountPolicy,
    HACKernel,
    ReturnConvention,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (  # noqa: E402
    ExperimentFamily,
    ExperimentFamilyManifest,
    ExperimentTrial,
    TrialParameter,
    TrialReturnMatrix,
)
from backtest_auditor.domain.runs import StrategyRun  # noqa: E402
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec  # noqa: E402
from backtest_auditor.statistics.annualized import calculate_annualized_statistics  # noqa: E402
from backtest_auditor.statistics.distribution import calculate_distribution_statistics  # noqa: E402
from backtest_auditor.statistics.sampling import assess_sampling  # noqa: E402


def make_series(
    values,
    *,
    freq: str = "B",
    start: str = "2015-01-01",
    periods_per_year: int | None = 252,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
    declared: bool = True,
    tz: str | None = None,
    timestamps=None,
) -> ReturnSeries:
    values = np.asarray(values, dtype=float)
    if timestamps is None:
        timestamps = pd.date_range(start, periods=len(values), freq=freq, tz=tz)
    sampling = SamplingSpec(
        declared_frequency=freq if declared else None,
        periods_per_year=periods_per_year,
    )
    return ReturnSeries(
        timestamps=timestamps, values=values, convention=convention, sampling=sampling
    )


def sharpe_spec(rf: float = 0.0) -> SharpeRatioSpec:
    return SharpeRatioSpec(annual_risk_free_rate=rf)


def psr_spec(
    benchmark: float = 0.0, confidence: float | None = 0.95
) -> ProbabilisticSharpeRatioSpec:
    return ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=benchmark,
        required_psr_confidence_level=confidence,
    )


def serial_dependence_spec(
    max_lag: int = 5, alpha: float = 0.05
) -> SerialDependenceSpec:
    return SerialDependenceSpec(maximum_lag=max_lag, significance_level=alpha)


def serial_adjustment_spec(max_lag: int = 5) -> SerialAdjustmentSpec:
    return SerialAdjustmentSpec(maximum_lag=max_lag, kernel=HACKernel.BARTLETT)


def bootstrap_spec(
    *,
    replications: int = 1000,
    level: float = 0.95,
    block_length: int = 5,
    seed: int = 7,
) -> BootstrapSpec:
    return BootstrapSpec(
        method=BootstrapMethod.MOVING_BLOCK,
        interval_method=BootstrapIntervalMethod.PERCENTILE,
        replications=replications,
        confidence_level=level,
        block_length=block_length,
        random_seed=seed,
    )


def dsr_spec(
    rf: float = 0.0, confidence: float = 0.95, **kw
) -> DeflatedSharpeRatioSpec:
    return DeflatedSharpeRatioSpec(
        method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        annual_risk_free_rate=rf,
        required_confidence_level=confidence,
        **kw,
    )


def cscv_spec(
    partitions: int = 4,
    rf: float = 0.0,
    max_combinations: int = 100000,
    max_pbo: float = 0.5,
) -> CSCVSpec:
    return CSCVSpec(
        method=CSCVMethod.COMBINATORIALLY_SYMMETRIC,
        performance_metric=CSCVPerformanceMetric.PERIOD_SHARPE_RATIO,
        selection_metric_name="period_sharpe_ratio",
        partition_count=partitions,
        annual_risk_free_rate=rf,
        maximum_combinations=max_combinations,
        rank_tie_method=CSCVRankTieMethod.AVERAGE,
        winner_tie_policy=CSCVWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        maximum_acceptable_pbo=max_pbo,
    )


def make_family(
    matrix,
    *,
    periods_per_year: int | None = 252,
    freq: str = "B",
    rf_annual: float = 0.0,
    selected: int | None = None,
    declared_total: int | None = None,
    trial_ids: tuple[str, ...] | None = None,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
) -> ExperimentFamily:
    """Build a complete, all-eligible family. The selected trial defaults to the
    column with the highest period Sharpe (what DSR requires)."""
    M = np.asarray(matrix, dtype=float)
    T, N = M.shape
    ppy = periods_per_year if periods_per_year is not None else 252
    rf_p = ref.annual_to_period_rate_geometric(rf_annual, ppy)
    scores = (M.mean(axis=0) - rf_p) / M.std(axis=0, ddof=1)
    scores = np.where(np.isfinite(scores), scores, -np.inf)
    if selected is None:
        selected = int(np.argmax(scores))
    if trial_ids is None:
        trial_ids = tuple(f"t{index + 1:03d}" for index in range(N))
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_ids[i],
            attempt_index=i + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=(i == selected),
            selection_score=float(scores[i]) if np.isfinite(scores[i]) else -1e300,
            parameters=(TrialParameter("p", i + 1),),
        )
        for i in range(N)
    )
    sampling = SamplingSpec(declared_frequency=freq, periods_per_year=periods_per_year)
    manifest = ExperimentFamilyManifest(
        schema_version="1.0",
        family_id="adv-family",
        declared_total_attempted_trials=declared_total or N,
        search_complete=True,
        selected_trial_id=trial_ids[selected],
        selection_rule="maximize period Sharpe",
        selection_metric="period_sharpe_ratio",
        selection_direction=SelectionDirection.MAXIMIZE,
        parameter_names=("p",),
        return_convention=convention,
        sampling=sampling,
    )
    returns = TrialReturnMatrix(
        timestamps=pd.date_range("2015-01-01", periods=T, freq=freq),
        trial_ids=trial_ids,
        values=M,
        convention=convention,
        sampling=sampling,
    )
    return ExperimentFamily(manifest=manifest, trials=trials, returns=returns)


def annualized_and_distribution(series: ReturnSeries, rf: float = 0.0):
    sampling = assess_sampling(series)
    annualized = calculate_annualized_statistics(
        series, sampling, sharpe_spec=sharpe_spec(rf)
    )
    distribution = calculate_distribution_statistics(series)
    return sampling, annualized, distribution


def random_returns(
    rng: np.random.Generator,
    n: int,
    kind: str,
    *,
    mu: float = 0.0005,
    sigma: float = 0.01,
):
    """Three return families used across the suite."""
    if kind == "normal":
        z = rng.standard_normal(n)
    elif kind == "skewed":
        z = rng.gamma(2.0, 1.0, n)
        z = (z - 2.0) / np.sqrt(2.0)
    elif kind == "fat":
        z = rng.standard_t(4, n) / np.sqrt(2.0)
    else:
        raise ValueError(kind)
    return mu + sigma * z


@pytest.fixture
def rng():
    return np.random.default_rng(20261020)


def pytest_configure(config):
    # test_bootstrap.py marks its coverage study `slow`; register it so the suite
    # does not emit PytestUnknownMarkWarning inside the package's `pytest` run.
    config.addinivalue_line("markers", "slow: long-running statistical study")


__all__ = [
    "ref",
    "make_series",
    "make_family",
    "sharpe_spec",
    "psr_spec",
    "dsr_spec",
    "cscv_spec",
    "serial_dependence_spec",
    "serial_adjustment_spec",
    "bootstrap_spec",
    "annualized_and_distribution",
    "random_returns",
    "StrategyRun",
    "ReturnConvention",
]
