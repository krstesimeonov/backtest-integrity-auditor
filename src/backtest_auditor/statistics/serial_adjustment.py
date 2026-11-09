import math
from statistics import NormalDist
from typing import Any

import numpy as np

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
)
from backtest_auditor.domain.enums import (
    ReturnConvention,
    SerialAdjustmentStatus,
)
from backtest_auditor.domain.results import (
    AnnualizedStatisticsResult,
    HACAutocorrelationEstimate,
    SerialAdjustmentResult,
    SharpeUncertaintyResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.return_basis import (
    to_simple_returns,
)

MINIMUM_MOMENT_OBSERVATIONS = 4


# The Sharpe influence series is computed, so a mathematically constant one
# need not be bit-identical: [4b, b, b, b, b, b] gives psi = 1/(4*sqrt(6)) at
# every observation, yet rounding leaves a variance near 1e-33 for b = 0.001
# and exactly 0.0 for b = 3 * 2**-10. The structural test is exact and cannot
# see that, so the verdict depended on the scale of the returns -- which a
# Sharpe ratio never can. The series is standardised by construction: its
# variance is the Sharpe variance adjustment 1 - skew*SR + (kurt-1)/4*SR**2,
# of order one for real returns. A threshold of 1e-20 sits about twelve orders
# above that rounding noise and twenty below any genuine value.
_NUMERICALLY_ZERO_INFLUENCE_VARIANCE = 1e-20


def calculate_serial_adjustment(
    series: ReturnSeries,
    annualized: AnnualizedStatisticsResult | None,
    uncertainty: SharpeUncertaintyResult | None,
    *,
    spec: SerialAdjustmentSpec | None = None,
    psr_spec: ProbabilisticSharpeRatioSpec | None = None,
) -> SerialAdjustmentResult | None:
    """Apply explicit Bartlett-HAC adjustments to Sharpe evidence."""

    if spec is None:
        return None

    values = to_simple_returns(series)
    observation_count = int(values.size)

    if (
        annualized is None
        or annualized.annualized_sharpe_ratio is None
        or annualized.period_risk_free_rate is None
    ):
        return _result(
            status=SerialAdjustmentStatus.SHARPE_UNAVAILABLE,
            observation_count=observation_count,
            spec=spec,
            periods_per_year=(
                None if annualized is None else annualized.periods_per_year
            ),
        )

    periods_per_year = annualized.periods_per_year
    if observation_count <= spec.maximum_lag:
        return _result(
            status=(SerialAdjustmentStatus.INSUFFICIENT_OBSERVATIONS),
            observation_count=observation_count,
            spec=spec,
            periods_per_year=periods_per_year,
            iid_annualized_sharpe_ratio=(annualized.annualized_sharpe_ratio),
        )

    return_estimates, return_ratio = calculate_bartlett_hac_ratio(
        values,
        maximum_lag=spec.maximum_lag,
    )
    iid_factor = math.sqrt(periods_per_year)
    full_lo_horizon = spec.maximum_lag == periods_per_year - 1

    if not math.isfinite(return_ratio) or return_ratio <= 0.0:
        return _result(
            status=(SerialAdjustmentStatus.NON_POSITIVE_RETURN_LONG_RUN_VARIANCE),
            observation_count=observation_count,
            spec=spec,
            periods_per_year=periods_per_year,
            return_autocorrelations=return_estimates,
            return_long_run_variance_ratio=return_ratio,
            iid_annualization_factor=iid_factor,
            full_lo_annual_horizon=full_lo_horizon,
            iid_annualized_sharpe_ratio=(annualized.annualized_sharpe_ratio),
        )

    hac_factor = math.sqrt(periods_per_year / return_ratio)
    period_sharpe = annualized.annualized_sharpe_ratio / iid_factor
    hac_annualized_sharpe = period_sharpe * hac_factor

    point_fields: dict[str, Any] = {
        "return_autocorrelations": return_estimates,
        "return_long_run_variance_ratio": return_ratio,
        "iid_annualization_factor": iid_factor,
        "hac_annualization_factor": hac_factor,
        "full_lo_annual_horizon": full_lo_horizon,
        "iid_annualized_sharpe_ratio": (annualized.annualized_sharpe_ratio),
        "hac_adjusted_annualized_sharpe_ratio": (hac_annualized_sharpe),
    }

    if uncertainty is None or uncertainty.period_sharpe_standard_error is None:
        return _result(
            status=(SerialAdjustmentStatus.SHARPE_UNCERTAINTY_UNAVAILABLE),
            observation_count=observation_count,
            spec=spec,
            periods_per_year=periods_per_year,
            **point_fields,
        )

    if (
        psr_spec is not None
        and uncertainty.benchmark_annualized_sharpe_ratio
        != psr_spec.benchmark_annualized_sharpe_ratio
    ):
        raise ValueError(
            "PSR specification benchmark must match the benchmark "
            "used by the Sharpe uncertainty result."
        )

    influence_values = _sharpe_influence_values(
        values,
        period_sharpe_ratio=uncertainty.period_sharpe_ratio,
    )
    if (
        has_zero_sample_variation(influence_values)
        or float(np.var(influence_values)) <= _NUMERICALLY_ZERO_INFLUENCE_VARIANCE
    ):
        return _result(
            status=SerialAdjustmentStatus.ZERO_INFLUENCE_VARIANCE,
            observation_count=observation_count,
            spec=spec,
            periods_per_year=periods_per_year,
            iid_sharpe_variance_adjustment=(uncertainty.sharpe_variance_adjustment),
            iid_period_sharpe_standard_error=(uncertainty.period_sharpe_standard_error),
            benchmark_period_sharpe_ratio=(uncertainty.benchmark_period_sharpe_ratio),
            iid_probabilistic_sharpe_ratio=(uncertainty.probabilistic_sharpe_ratio),
            **point_fields,
        )

    influence_estimates, sharpe_ratio = calculate_bartlett_hac_ratio(
        influence_values,
        maximum_lag=spec.maximum_lag,
    )
    if not math.isfinite(sharpe_ratio) or sharpe_ratio <= 0.0:
        return _result(
            status=(SerialAdjustmentStatus.NON_POSITIVE_SHARPE_LONG_RUN_VARIANCE),
            observation_count=observation_count,
            spec=spec,
            periods_per_year=periods_per_year,
            influence_autocorrelations=influence_estimates,
            sharpe_long_run_variance_ratio=sharpe_ratio,
            iid_sharpe_variance_adjustment=(uncertainty.sharpe_variance_adjustment),
            iid_period_sharpe_standard_error=(uncertainty.period_sharpe_standard_error),
            benchmark_period_sharpe_ratio=(uncertainty.benchmark_period_sharpe_ratio),
            iid_probabilistic_sharpe_ratio=(uncertainty.probabilistic_sharpe_ratio),
            **point_fields,
        )

    adjusted_variance = uncertainty.sharpe_variance_adjustment * sharpe_ratio
    adjusted_standard_error = math.sqrt(adjusted_variance / (observation_count - 1))
    effective_observations = 1.0 + (observation_count - 1) / sharpe_ratio

    adjusted_psr: float | None = None
    confidence_level: float | None = None
    confidence_met: bool | None = None
    minimum_length: float | None = None
    minimum_observations: int | None = None
    minimum_years: float | None = None
    additional_observations: int | None = None
    observations_above_minimum: int | None = None

    benchmark_period = uncertainty.benchmark_period_sharpe_ratio
    if benchmark_period is not None:
        test_statistic = (
            uncertainty.period_sharpe_ratio - benchmark_period
        ) / adjusted_standard_error
        adjusted_psr = NormalDist().cdf(test_statistic)

    if (
        psr_spec is not None
        and psr_spec.required_psr_confidence_level is not None
        and adjusted_psr is not None
        and benchmark_period is not None
    ):
        confidence_level = psr_spec.required_psr_confidence_level
        confidence_met = adjusted_psr >= confidence_level
        sharpe_difference = uncertainty.period_sharpe_ratio - benchmark_period

        if sharpe_difference > 0.0:
            critical_value = NormalDist().inv_cdf(confidence_level)
            try:
                candidate = (
                    1.0 + adjusted_variance * (critical_value / sharpe_difference) ** 2
                )
            except OverflowError:
                candidate = math.inf

            if math.isfinite(candidate):
                minimum_length = candidate
                minimum_observations = max(
                    MINIMUM_MOMENT_OBSERVATIONS,
                    math.ceil(candidate),
                )
                minimum_years = candidate / periods_per_year
                additional_observations = max(
                    0,
                    minimum_observations - observation_count,
                )
                observations_above_minimum = max(
                    0,
                    observation_count - minimum_observations,
                )

    return _result(
        status=SerialAdjustmentStatus.ELIGIBLE,
        observation_count=observation_count,
        spec=spec,
        periods_per_year=periods_per_year,
        influence_autocorrelations=influence_estimates,
        sharpe_long_run_variance_ratio=sharpe_ratio,
        iid_sharpe_variance_adjustment=(uncertainty.sharpe_variance_adjustment),
        hac_sharpe_variance_adjustment=adjusted_variance,
        iid_period_sharpe_standard_error=(uncertainty.period_sharpe_standard_error),
        hac_period_sharpe_standard_error=(adjusted_standard_error),
        effective_observation_count=effective_observations,
        benchmark_period_sharpe_ratio=benchmark_period,
        iid_probabilistic_sharpe_ratio=(uncertainty.probabilistic_sharpe_ratio),
        hac_probabilistic_sharpe_ratio=adjusted_psr,
        required_psr_confidence_level=confidence_level,
        hac_confidence_requirement_met=confidence_met,
        hac_minimum_track_record_length_observations=(minimum_length),
        hac_minimum_required_observations=minimum_observations,
        hac_minimum_track_record_length_years=minimum_years,
        hac_additional_observations_required=(additional_observations),
        hac_observations_above_minimum=(observations_above_minimum),
        **point_fields,
    )


def calculate_bartlett_hac_ratio(
    values: np.ndarray,
    *,
    maximum_lag: int,
) -> tuple[tuple[HACAutocorrelationEstimate, ...], float]:
    """Estimate a Bartlett-weighted long-run variance ratio."""

    centered = values - np.mean(values)
    denominator = float(np.dot(centered, centered))
    if has_zero_sample_variation(values) or denominator == 0.0:
        return (), 0.0

    estimates: list[HACAutocorrelationEstimate] = []
    weighted_sum = 0.0
    for lag in range(1, maximum_lag + 1):
        autocorrelation = float(np.dot(centered[lag:], centered[:-lag]) / denominator)
        kernel_weight = 1.0 - lag / (maximum_lag + 1)
        contribution = kernel_weight * autocorrelation
        weighted_sum += contribution
        estimates.append(
            HACAutocorrelationEstimate(
                lag=lag,
                autocorrelation=autocorrelation,
                kernel_weight=kernel_weight,
                weighted_contribution=contribution,
            )
        )

    return tuple(estimates), 1.0 + 2.0 * weighted_sum


def _sharpe_influence_values(
    values: np.ndarray,
    *,
    period_sharpe_ratio: float,
) -> np.ndarray:
    centered = values - np.mean(values)
    sample_volatility = float(np.std(values, ddof=1))
    standardized = centered / sample_volatility
    return standardized - 0.5 * period_sharpe_ratio * (standardized**2 - 1.0)


def _result(
    *,
    status: SerialAdjustmentStatus,
    observation_count: int,
    spec: SerialAdjustmentSpec,
    periods_per_year: int | None,
    return_autocorrelations: tuple[HACAutocorrelationEstimate, ...] = (),
    return_long_run_variance_ratio: float | None = None,
    iid_annualization_factor: float | None = None,
    hac_annualization_factor: float | None = None,
    full_lo_annual_horizon: bool | None = None,
    iid_annualized_sharpe_ratio: float | None = None,
    hac_adjusted_annualized_sharpe_ratio: float | None = None,
    influence_autocorrelations: tuple[HACAutocorrelationEstimate, ...] = (),
    sharpe_long_run_variance_ratio: float | None = None,
    iid_sharpe_variance_adjustment: float | None = None,
    hac_sharpe_variance_adjustment: float | None = None,
    iid_period_sharpe_standard_error: float | None = None,
    hac_period_sharpe_standard_error: float | None = None,
    effective_observation_count: float | None = None,
    benchmark_period_sharpe_ratio: float | None = None,
    iid_probabilistic_sharpe_ratio: float | None = None,
    hac_probabilistic_sharpe_ratio: float | None = None,
    required_psr_confidence_level: float | None = None,
    hac_confidence_requirement_met: bool | None = None,
    hac_minimum_track_record_length_observations: (float | None) = None,
    hac_minimum_required_observations: int | None = None,
    hac_minimum_track_record_length_years: float | None = None,
    hac_additional_observations_required: int | None = None,
    hac_observations_above_minimum: int | None = None,
) -> SerialAdjustmentResult:
    return SerialAdjustmentResult(
        status=status,
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        maximum_lag=spec.maximum_lag,
        kernel=spec.kernel,
        periods_per_year=periods_per_year,
        return_autocorrelations=return_autocorrelations,
        return_long_run_variance_ratio=(return_long_run_variance_ratio),
        iid_annualization_factor=iid_annualization_factor,
        hac_annualization_factor=hac_annualization_factor,
        full_lo_annual_horizon=full_lo_annual_horizon,
        iid_annualized_sharpe_ratio=iid_annualized_sharpe_ratio,
        hac_adjusted_annualized_sharpe_ratio=(hac_adjusted_annualized_sharpe_ratio),
        influence_autocorrelations=influence_autocorrelations,
        sharpe_long_run_variance_ratio=(sharpe_long_run_variance_ratio),
        iid_sharpe_variance_adjustment=(iid_sharpe_variance_adjustment),
        hac_sharpe_variance_adjustment=(hac_sharpe_variance_adjustment),
        iid_period_sharpe_standard_error=(iid_period_sharpe_standard_error),
        hac_period_sharpe_standard_error=(hac_period_sharpe_standard_error),
        effective_observation_count=effective_observation_count,
        benchmark_period_sharpe_ratio=(benchmark_period_sharpe_ratio),
        iid_probabilistic_sharpe_ratio=(iid_probabilistic_sharpe_ratio),
        hac_probabilistic_sharpe_ratio=(hac_probabilistic_sharpe_ratio),
        required_psr_confidence_level=(required_psr_confidence_level),
        hac_confidence_requirement_met=(hac_confidence_requirement_met),
        hac_minimum_track_record_length_observations=(
            hac_minimum_track_record_length_observations
        ),
        hac_minimum_required_observations=(hac_minimum_required_observations),
        hac_minimum_track_record_length_years=(hac_minimum_track_record_length_years),
        hac_additional_observations_required=(hac_additional_observations_required),
        hac_observations_above_minimum=(hac_observations_above_minimum),
    )
