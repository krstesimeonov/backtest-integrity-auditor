import math
from statistics import NormalDist

import numpy as np
from scipy.stats import chi2

from backtest_auditor.domain.assumptions import (
    SerialDependenceSpec,
)
from backtest_auditor.domain.enums import (
    ReturnConvention,
    SerialDependenceStatus,
)
from backtest_auditor.domain.results import (
    AutocorrelationEstimate,
    SerialDependenceResult,
    VarianceRatioResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.return_basis import (
    to_simple_returns,
)


def calculate_serial_dependence(
    series: ReturnSeries,
    *,
    spec: SerialDependenceSpec | None = None,
) -> SerialDependenceResult | None:
    """Estimate the ACF and one Ljung-Box test at the selected lag."""

    if spec is None:
        return None

    values = to_simple_returns(series)
    observation_count = int(values.size)
    if observation_count <= spec.maximum_lag:
        return _ineligible_result(
            observation_count,
            spec,
            status=(SerialDependenceStatus.INSUFFICIENT_OBSERVATIONS),
        )

    centered = values - np.mean(values)
    denominator = float(np.dot(centered, centered))
    if has_zero_sample_variation(values) or denominator == 0.0:
        return _ineligible_result(
            observation_count,
            spec,
            status=SerialDependenceStatus.ZERO_VARIANCE,
        )

    estimates = tuple(
        AutocorrelationEstimate(
            lag=lag,
            autocorrelation=float(
                np.dot(centered[lag:], centered[:-lag]) / denominator
            ),
        )
        for lag in range(1, spec.maximum_lag + 1)
    )

    ljung_box_statistic = float(
        observation_count
        * (observation_count + 2)
        * sum(
            estimate.autocorrelation**2 / (observation_count - estimate.lag)
            for estimate in estimates
        )
    )
    p_value = float(chi2.sf(ljung_box_statistic, df=spec.maximum_lag))
    strongest = max(
        estimates,
        key=lambda estimate: abs(estimate.autocorrelation),
    )

    partial_autocorrelations = _partial_autocorrelations(
        centered,
        maximum_lag=spec.maximum_lag,
    )
    critical = NormalDist().inv_cdf(1.0 - spec.significance_level / 2.0)
    confidence_bound = critical / math.sqrt(observation_count)
    mean_ratio = 1.0 + 2.0 * sum(
        (1.0 - estimate.lag / observation_count) * estimate.autocorrelation
        for estimate in estimates
    )
    mean_effective_count = (
        observation_count / mean_ratio
        if math.isfinite(mean_ratio) and mean_ratio > 0.0
        else None
    )
    runs = _runs_test(values, significance_level=spec.significance_level)
    variance_ratios = tuple(
        _variance_ratio(
            values,
            horizon=horizon,
            significance_level=spec.significance_level,
        )
        for horizon in range(2, min(spec.maximum_lag, observation_count - 1) + 1)
    )

    return SerialDependenceResult(
        status=SerialDependenceStatus.ELIGIBLE,
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        maximum_lag=spec.maximum_lag,
        significance_level=spec.significance_level,
        autocorrelations=estimates,
        strongest_absolute_autocorrelation_lag=strongest.lag,
        strongest_absolute_autocorrelation=abs(strongest.autocorrelation),
        ljung_box_statistic=ljung_box_statistic,
        degrees_of_freedom=spec.maximum_lag,
        p_value=p_value,
        serial_dependence_detected=(p_value < spec.significance_level),
        partial_autocorrelations=partial_autocorrelations,
        acf_confidence_bound=confidence_bound,
        mean_long_run_variance_ratio=mean_ratio,
        mean_effective_observation_count=mean_effective_count,
        runs_observation_count=runs[0],
        runs_count=runs[1],
        runs_expected_count=runs[2],
        runs_z_statistic=runs[3],
        runs_p_value=runs[4],
        runs_dependence_detected=runs[5],
        variance_ratios=variance_ratios,
    )


def _ineligible_result(
    observation_count: int,
    spec: SerialDependenceSpec,
    *,
    status: SerialDependenceStatus,
) -> SerialDependenceResult:
    return SerialDependenceResult(
        status=status,
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        maximum_lag=spec.maximum_lag,
        significance_level=spec.significance_level,
        autocorrelations=(),
        strongest_absolute_autocorrelation_lag=None,
        strongest_absolute_autocorrelation=None,
        ljung_box_statistic=None,
        degrees_of_freedom=None,
        p_value=None,
        serial_dependence_detected=None,
        partial_autocorrelations=(),
        acf_confidence_bound=None,
        mean_long_run_variance_ratio=None,
        mean_effective_observation_count=None,
        runs_observation_count=None,
        runs_count=None,
        runs_expected_count=None,
        runs_z_statistic=None,
        runs_p_value=None,
        runs_dependence_detected=None,
        variance_ratios=(),
    )


def _partial_autocorrelations(
    centered: np.ndarray,
    *,
    maximum_lag: int,
) -> tuple[AutocorrelationEstimate, ...]:
    estimates: list[AutocorrelationEstimate] = []
    observation_count = len(centered)
    for lag in range(1, maximum_lag + 1):
        response = centered[lag:]
        design = np.column_stack(
            [
                centered[lag - offset : observation_count - offset]
                for offset in range(1, lag + 1)
            ]
        )
        coefficients, _, rank, _ = np.linalg.lstsq(design, response, rcond=None)
        if rank == lag:
            estimates.append(
                AutocorrelationEstimate(
                    lag=lag,
                    autocorrelation=float(coefficients[-1]),
                )
            )
    return tuple(estimates)


def _runs_test(
    values: np.ndarray,
    *,
    significance_level: float,
) -> tuple[
    int | None, int | None, float | None, float | None, float | None, bool | None
]:
    median = float(np.median(values))
    signs = np.sign(values - median)
    signs = signs[signs != 0.0]
    observation_count = int(len(signs))
    positives = int(np.count_nonzero(signs > 0.0))
    negatives = int(np.count_nonzero(signs < 0.0))
    if observation_count < 2 or positives == 0 or negatives == 0:
        return observation_count, None, None, None, None, None

    runs = 1 + int(np.count_nonzero(signs[1:] != signs[:-1]))
    expected = 1.0 + 2.0 * positives * negatives / observation_count
    variance = (
        2.0
        * positives
        * negatives
        * (2.0 * positives * negatives - observation_count)
        / (observation_count**2 * (observation_count - 1))
    )
    if variance <= 0.0:
        return observation_count, runs, expected, None, None, None
    difference = runs - expected
    # The continuity correction moves |R - E| toward zero by 1/2 and never
    # past it: within 1/2 of the expectation there is no deviation left.
    shrunk = max(abs(difference) - 0.5, 0.0)
    corrected = math.copysign(shrunk, difference) if shrunk > 0.0 else 0.0
    statistic = corrected / math.sqrt(variance)
    p_value = _two_sided_normal_p_value(statistic)
    return (
        observation_count,
        runs,
        expected,
        statistic,
        p_value,
        p_value < significance_level,
    )


def _two_sided_normal_p_value(statistic: float) -> float:
    """2 * (1 - Phi(|z|)) from erfc, which keeps its precision in the far tail."""

    return math.erfc(abs(statistic) / math.sqrt(2.0))


def _variance_ratio(
    values: np.ndarray,
    *,
    horizon: int,
    significance_level: float,
) -> VarianceRatioResult:
    observation_count = len(values)
    mean = float(np.mean(values))
    centered = values - mean
    denominator_sum = float(np.dot(centered, centered))
    one_period_variance = denominator_sum / (observation_count - 1)
    horizon_returns = np.convolve(values, np.ones(horizon), mode="valid")
    scale = (
        horizon
        * (observation_count - horizon + 1)
        * (1.0 - horizon / observation_count)
    )
    horizon_variance = float(np.sum((horizon_returns - horizon * mean) ** 2) / scale)
    variance_ratio = horizon_variance / one_period_variance

    theta = 0.0
    for lag in range(1, horizon):
        cross = float(np.sum((centered[lag:] ** 2) * (centered[:-lag] ** 2)))
        delta = observation_count * cross / (denominator_sum**2)
        theta += (2.0 * (horizon - lag) / horizon) ** 2 * delta
    if not math.isfinite(theta) or theta <= 0.0:
        return VarianceRatioResult(horizon, variance_ratio, None, None, None, None)
    # theta estimates the asymptotic variance of sqrt(n) * (VR - 1), so the
    # standard error of VR itself is sqrt(theta / n) (Lo-MacKinlay eq. 18).
    standard_error = math.sqrt(theta / observation_count)
    statistic = (variance_ratio - 1.0) / standard_error
    p_value = _two_sided_normal_p_value(statistic)
    return VarianceRatioResult(
        horizon=horizon,
        variance_ratio=variance_ratio,
        heteroskedastic_robust_standard_error=standard_error,
        z_statistic=statistic,
        p_value=p_value,
        dependence_detected=p_value < significance_level,
    )
