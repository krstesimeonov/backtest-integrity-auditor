import math
from statistics import NormalDist

import numpy as np

from backtest_auditor.domain.assumptions import BenchmarkInferenceSpec
from backtest_auditor.domain.enums import (
    BenchmarkAlignmentStatus,
    BenchmarkInferenceStatus,
)
from backtest_auditor.domain.results import (
    BenchmarkAlignmentResult,
    BenchmarkAlphaInferenceResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.return_basis import to_simple_returns


def calculate_benchmark_alpha_inference(
    strategy: ReturnSeries,
    benchmark: ReturnSeries | None,
    alignment: BenchmarkAlignmentResult | None,
    *,
    spec: BenchmarkInferenceSpec | None = None,
) -> BenchmarkAlphaInferenceResult | None:
    """Estimate OLS alpha and a Bartlett-HAC standard error."""

    if spec is None:
        return None
    observation_count = len(strategy.timestamps)
    if benchmark is None or alignment is None:
        return _empty(
            BenchmarkInferenceStatus.BENCHMARK_UNAVAILABLE, observation_count, spec
        )
    if alignment.status is not BenchmarkAlignmentStatus.ELIGIBLE:
        return _empty(
            BenchmarkInferenceStatus.TIMESTAMP_MISMATCH, observation_count, spec
        )
    if observation_count <= max(2, spec.maximum_lag):
        return _empty(
            BenchmarkInferenceStatus.INSUFFICIENT_OBSERVATIONS, observation_count, spec
        )

    y = to_simple_returns(strategy)
    x_value = to_simple_returns(benchmark)
    x = np.column_stack((np.ones(observation_count), x_value))
    gram = x.T @ x
    try:
        gram_inverse = np.linalg.inv(gram)
    except np.linalg.LinAlgError:
        return _empty(BenchmarkInferenceStatus.SINGULAR_DESIGN, observation_count, spec)

    coefficients = gram_inverse @ x.T @ y
    residuals = y - x @ coefficients
    meat = np.zeros((2, 2), dtype=np.float64)
    for index in range(observation_count):
        meat += residuals[index] ** 2 * np.outer(x[index], x[index])
    for lag in range(1, spec.maximum_lag + 1):
        weight = 1.0 - lag / (spec.maximum_lag + 1)
        for index in range(lag, observation_count):
            cross = residuals[index] * residuals[index - lag]
            meat += (
                weight
                * cross
                * (
                    np.outer(x[index], x[index - lag])
                    + np.outer(x[index - lag], x[index])
                )
            )
    covariance = gram_inverse @ meat @ gram_inverse
    variance = float(covariance[0, 0])
    if not math.isfinite(variance) or variance <= 0.0:
        return _empty(
            BenchmarkInferenceStatus.NON_POSITIVE_VARIANCE,
            observation_count,
            spec,
            alpha=float(coefficients[0]),
            beta=float(coefficients[1]),
        )

    standard_error = math.sqrt(variance)
    statistic = float(coefficients[0]) / standard_error
    p_value = 2.0 * NormalDist().cdf(-abs(statistic))
    critical = NormalDist().inv_cdf(0.5 + spec.confidence_level / 2.0)
    lower = float(coefficients[0]) - critical * standard_error
    upper = float(coefficients[0]) + critical * standard_error
    return BenchmarkAlphaInferenceResult(
        status=BenchmarkInferenceStatus.ELIGIBLE,
        observation_count=observation_count,
        maximum_lag=spec.maximum_lag,
        confidence_level=spec.confidence_level,
        period_alpha=float(coefficients[0]),
        beta=float(coefficients[1]),
        hac_standard_error=standard_error,
        test_statistic=statistic,
        two_sided_p_value=p_value,
        confidence_interval_lower=lower,
        confidence_interval_upper=upper,
        statistically_different_from_zero=(p_value < 1.0 - spec.confidence_level),
    )


def _empty(
    status: BenchmarkInferenceStatus,
    observation_count: int,
    spec: BenchmarkInferenceSpec,
    *,
    alpha: float | None = None,
    beta: float | None = None,
) -> BenchmarkAlphaInferenceResult:
    return BenchmarkAlphaInferenceResult(
        status=status,
        observation_count=observation_count,
        maximum_lag=spec.maximum_lag,
        confidence_level=spec.confidence_level,
        period_alpha=alpha,
        beta=beta,
        hac_standard_error=None,
        test_statistic=None,
        two_sided_p_value=None,
        confidence_interval_lower=None,
        confidence_interval_upper=None,
        statistically_different_from_zero=None,
    )
