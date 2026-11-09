import math

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import AdvancedRiskSpec
from backtest_auditor.domain.enums import AdvancedRiskStatus, ReturnConvention
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.advanced_risk import (
    calculate_advanced_risk_statistics,
)
from backtest_auditor.statistics.performance_path import calculate_performance_path
from backtest_auditor.statistics.sampling import assess_sampling


def _series(values: list[float]) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=np.asarray(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency="D", periods_per_year=4),
    )


def _calculate(values: list[float], confidence: float = 0.75):
    series = _series(values)
    sampling = assess_sampling(series)
    return calculate_advanced_risk_statistics(
        series,
        sampling,
        calculate_performance_path(series, sampling),
        spec=AdvancedRiskSpec(0.0, confidence),
    )


def test_advanced_risk_matches_empirical_reference_values() -> None:
    result = _calculate([0.10, -0.20, 0.05, -0.10])

    assert result is not None
    assert result.status is AdvancedRiskStatus.ELIGIBLE
    assert result.downside_observation_count == 2
    assert result.downside_deviation == pytest.approx(math.sqrt(0.05 / 4.0))
    assert result.period_sortino_ratio == pytest.approx(-0.0375 / math.sqrt(0.05 / 4.0))
    assert result.annualized_sortino_ratio == pytest.approx(
        2.0 * result.period_sortino_ratio
    )
    assert result.omega_ratio == pytest.approx(0.5)
    assert result.historical_value_at_risk == pytest.approx(0.10)
    assert result.historical_expected_shortfall == pytest.approx(0.20)
    assert result.calmar_ratio is not None
    assert result.ulcer_index > 0.0


def test_advanced_risk_preserves_zero_downside_and_small_sample_boundaries() -> None:
    no_downside = _calculate([0.01, 0.02, 0.03])
    one_observation = _calculate([-0.10], confidence=0.95)

    assert no_downside is not None
    assert no_downside.status is AdvancedRiskStatus.DOWNSIDE_DEVIATION_ZERO
    assert no_downside.period_sortino_ratio is None
    assert no_downside.omega_ratio is None
    assert one_observation is not None
    assert one_observation.status is AdvancedRiskStatus.INSUFFICIENT_OBSERVATIONS
    assert one_observation.historical_expected_shortfall == pytest.approx(0.10)


def test_advanced_risk_is_opt_in() -> None:
    series = _series([0.01, -0.01])
    sampling = assess_sampling(series)

    assert (
        calculate_advanced_risk_statistics(
            series,
            sampling,
            calculate_performance_path(series, sampling),
        )
        is None
    )
