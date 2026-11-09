import math
from statistics import NormalDist

import pytest

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
)
from backtest_auditor.domain.results import SharpeUncertaintyResult
from backtest_auditor.statistics.track_record import (
    calculate_track_record_length,
)


def _uncertainty(
    *,
    observation_count: int,
    periods_per_year: int = 252,
    annualized_sharpe: float = 2.0,
    annualized_benchmark: float = 1.0,
    variance_adjustment: float | None = None,
) -> SharpeUncertaintyResult:
    scale = math.sqrt(periods_per_year)
    period_sharpe = annualized_sharpe / scale
    period_benchmark = annualized_benchmark / scale
    adjustment = (
        1.0 + 0.5 * period_sharpe**2
        if variance_adjustment is None
        else variance_adjustment
    )
    standard_error = math.sqrt(adjustment / (observation_count - 1))
    psr = NormalDist().cdf((period_sharpe - period_benchmark) / standard_error)
    return SharpeUncertaintyResult(
        observation_count=observation_count,
        periods_per_year=periods_per_year,
        period_sharpe_ratio=period_sharpe,
        annualized_sharpe_ratio=annualized_sharpe,
        sharpe_variance_adjustment=adjustment,
        period_sharpe_standard_error=standard_error,
        annualized_sharpe_standard_error=standard_error * scale,
        benchmark_period_sharpe_ratio=period_benchmark,
        benchmark_annualized_sharpe_ratio=annualized_benchmark,
        probabilistic_sharpe_ratio=psr,
    )


def _spec(
    confidence: float | None = 0.95,
    *,
    benchmark: float = 1.0,
) -> ProbabilisticSharpeRatioSpec:
    return ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=benchmark,
        required_psr_confidence_level=confidence,
    )


def test_reproduces_known_daily_normal_mintrl_example() -> None:
    result = calculate_track_record_length(
        _uncertainty(observation_count=500),
        psr_spec=_spec(),
    )

    assert result is not None
    assert result.normal_critical_value == pytest.approx(1.6448536269514715)
    assert result.minimum_track_record_length_observations == pytest.approx(
        688.2080373402346
    )
    assert result.minimum_required_observations == 689
    assert result.minimum_track_record_length_years == pytest.approx(2.730984275159661)
    assert result.additional_observations_required == 189
    assert result.observations_above_minimum == 0
    assert not result.confidence_requirement_met


def test_satisfied_requirement_reports_observation_surplus() -> None:
    result = calculate_track_record_length(
        _uncertainty(observation_count=700),
        psr_spec=_spec(),
    )

    assert result is not None
    assert result.confidence_requirement_met
    assert result.additional_observations_required == 0
    assert result.observations_above_minimum == 11


def test_sharpe_not_above_benchmark_has_no_finite_mintrl() -> None:
    result = calculate_track_record_length(
        _uncertainty(
            observation_count=100,
            annualized_sharpe=0.5,
            annualized_benchmark=1.0,
        ),
        psr_spec=_spec(),
    )

    assert result is not None
    assert result.observed_period_sharpe_difference < 0.0
    assert not result.confidence_requirement_met
    assert result.minimum_track_record_length_observations is None
    assert result.minimum_required_observations is None
    assert result.additional_observations_required is None


def test_operational_minimum_respects_moment_estimation_floor() -> None:
    result = calculate_track_record_length(
        _uncertainty(
            observation_count=20,
            periods_per_year=1,
            annualized_sharpe=10.0,
            annualized_benchmark=0.0,
            variance_adjustment=0.01,
        ),
        psr_spec=_spec(0.95, benchmark=0.0),
    )

    assert result is not None
    assert result.minimum_track_record_length_observations is not None
    assert result.minimum_track_record_length_observations < 4.0
    assert result.minimum_required_observations == 4


def test_missing_psr_or_confidence_refuses_track_record_result() -> None:
    uncertainty = _uncertainty(observation_count=500)

    assert calculate_track_record_length(None, psr_spec=_spec()) is None
    assert calculate_track_record_length(uncertainty) is None
    assert (
        calculate_track_record_length(
            uncertainty,
            psr_spec=_spec(None),
        )
        is None
    )


def test_mismatched_benchmark_is_rejected() -> None:
    with pytest.raises(ValueError, match="benchmark must match"):
        calculate_track_record_length(
            _uncertainty(observation_count=500),
            psr_spec=_spec(benchmark=0.0),
        )
