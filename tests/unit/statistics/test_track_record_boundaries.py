import math
from statistics import NormalDist

import numpy as np
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
) -> SharpeUncertaintyResult:
    scale = math.sqrt(periods_per_year)
    period_sharpe = annualized_sharpe / scale
    period_benchmark = annualized_benchmark / scale
    adjustment = 1.0 + 0.5 * period_sharpe**2
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
    confidence: float,
    *,
    benchmark: float = 1.0,
) -> ProbabilisticSharpeRatioSpec:
    return ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=benchmark,
        required_psr_confidence_level=confidence,
    )


def test_requirement_is_met_when_psr_equals_the_required_level() -> None:
    # The PSR_CONFIDENCE_REQUIREMENT_NOT_MET finding says PSR "is below" the
    # required level, so reaching it meets it. MinTRL is where PSR reaches c:
    # with c = Phi(d / SE) and SE = sqrt(A / (n - 1)),
    #   MinTRL = 1 + A * (Phi^-1(c) / d)**2 = 1 + (n - 1) = n.
    uncertainty = _uncertainty(observation_count=500)
    achieved = uncertainty.probabilistic_sharpe_ratio
    assert 0.5 < achieved < 1.0

    at_level = calculate_track_record_length(uncertainty, psr_spec=_spec(achieved))
    above_level = calculate_track_record_length(
        uncertainty,
        psr_spec=_spec(float(np.nextafter(achieved, 1.0))),
    )

    assert at_level is not None
    assert at_level.confidence_requirement_met is True
    assert at_level.minimum_track_record_length_observations == pytest.approx(
        500, rel=1e-9
    )
    assert above_level is not None
    assert above_level.confidence_requirement_met is False


def test_sharpe_equal_to_benchmark_has_no_finite_mintrl() -> None:
    # README Part F: "If the observed Sharpe does not exceed the selected
    # benchmark, no finite MinTRL is reported." Equality does not exceed.
    result = calculate_track_record_length(
        _uncertainty(
            observation_count=100,
            annualized_sharpe=1.0,
            annualized_benchmark=1.0,
        ),
        psr_spec=_spec(0.95),
    )

    assert result is not None
    assert result.observed_period_sharpe_difference == 0.0
    assert result.observed_probabilistic_sharpe_ratio == pytest.approx(0.5)
    assert not result.confidence_requirement_met
    assert result.minimum_track_record_length_observations is None
    assert result.minimum_required_observations is None
    assert result.minimum_track_record_length_years is None
    assert result.additional_observations_required is None
    assert result.observations_above_minimum is None
