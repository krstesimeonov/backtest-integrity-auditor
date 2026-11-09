import math
from statistics import NormalDist

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
)
from backtest_auditor.domain.results import (
    SharpeUncertaintyResult,
    TrackRecordLengthResult,
)

MINIMUM_MOMENT_OBSERVATIONS = 4


def calculate_track_record_length(
    uncertainty: SharpeUncertaintyResult | None,
    *,
    psr_spec: ProbabilisticSharpeRatioSpec | None = None,
) -> TrackRecordLengthResult | None:
    """Estimate MinTRL for an explicit PSR confidence requirement."""

    if (
        uncertainty is None
        or uncertainty.probabilistic_sharpe_ratio is None
        or uncertainty.benchmark_period_sharpe_ratio is None
        or uncertainty.benchmark_annualized_sharpe_ratio is None
        or psr_spec is None
        or psr_spec.required_psr_confidence_level is None
    ):
        return None

    if (
        uncertainty.benchmark_annualized_sharpe_ratio
        != psr_spec.benchmark_annualized_sharpe_ratio
    ):
        raise ValueError(
            "PSR specification benchmark must match the benchmark "
            "used by the Sharpe uncertainty result."
        )

    confidence_level = psr_spec.required_psr_confidence_level
    critical_value = NormalDist().inv_cdf(confidence_level)
    sharpe_difference = (
        uncertainty.period_sharpe_ratio - uncertainty.benchmark_period_sharpe_ratio
    )
    observed_psr = uncertainty.probabilistic_sharpe_ratio

    minimum_length: float | None = None
    minimum_observations: int | None = None
    minimum_years: float | None = None
    additional_observations: int | None = None
    observations_above_minimum: int | None = None

    if sharpe_difference > 0.0:
        try:
            minimum_length_candidate = (
                1.0
                + uncertainty.sharpe_variance_adjustment
                * (critical_value / sharpe_difference) ** 2
            )
        except OverflowError:
            minimum_length_candidate = math.inf

        if math.isfinite(minimum_length_candidate):
            minimum_length = minimum_length_candidate
            minimum_observations = max(
                MINIMUM_MOMENT_OBSERVATIONS,
                math.ceil(minimum_length),
            )
            minimum_years = minimum_length / uncertainty.periods_per_year
            additional_observations = max(
                0,
                minimum_observations - uncertainty.observation_count,
            )
            observations_above_minimum = max(
                0,
                uncertainty.observation_count - minimum_observations,
            )

    return TrackRecordLengthResult(
        observation_count=uncertainty.observation_count,
        periods_per_year=uncertainty.periods_per_year,
        required_psr_confidence_level=confidence_level,
        observed_probabilistic_sharpe_ratio=observed_psr,
        confidence_requirement_met=(observed_psr >= confidence_level),
        normal_critical_value=critical_value,
        observed_period_sharpe_difference=sharpe_difference,
        minimum_track_record_length_observations=minimum_length,
        minimum_required_observations=minimum_observations,
        minimum_track_record_length_years=minimum_years,
        additional_observations_required=additional_observations,
        observations_above_minimum=observations_above_minimum,
    )
