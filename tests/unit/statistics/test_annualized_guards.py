import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import SharpeRatioSpec
from backtest_auditor.domain.enums import FrequencyStatus, ReturnConvention
from backtest_auditor.domain.results import SamplingAssessmentResult
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)
from backtest_auditor.statistics.annualized import (
    calculate_annualized_statistics,
)
from backtest_auditor.statistics.sampling import assess_sampling


def _series(
    values: list[float],
    *,
    freq: str = "D",
    periods_per_year: int | None = 4,
) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range("2020-01-01", periods=len(values), freq=freq),
        values=np.asarray(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(periods_per_year=periods_per_year),
    )


def _eligible_sampling(
    observation_count: int,
    *,
    periods_per_year: int | None,
) -> SamplingAssessmentResult:
    # Built by hand: assess_sampling never grants eligibility below three
    # observations or without a positive periods_per_year, so these tests pin
    # the function's own guards against an inconsistent caller (as the n = 1
    # calendar-verified bug once was).
    return SamplingAssessmentResult(
        status=FrequencyStatus.DECLARED,
        observation_count=observation_count,
        interval_count=observation_count - 1,
        declared_frequency="D",
        inferred_frequency=None,
        periods_per_year=periods_per_year,
        minimum_interval_seconds=86400.0,
        maximum_interval_seconds=86400.0,
        annualization_eligible=True,
    )


def test_annual_data_is_its_own_annualization() -> None:
    # At periods_per_year = 1 every scaling factor is 1:
    #   mean([0.01, 0.02, 0.03]) = 0.02, sample sd = 0.01,
    #   period rf = (1 + 0.01) ** (1 / 1) - 1 = 0.01,
    #   Sharpe = (0.02 - 0.01) / 0.01 * sqrt(1) = 1.0.
    series = _series([0.01, 0.02, 0.03], freq="YS", periods_per_year=1)
    sampling = assess_sampling(series)
    assert sampling.annualization_eligible is True

    result = calculate_annualized_statistics(
        series,
        sampling,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.01),
    )

    assert result is not None
    assert result.periods_per_year == 1
    assert result.annualized_arithmetic_mean_return == pytest.approx(0.02)
    assert result.annualized_sample_volatility == pytest.approx(0.01)
    assert result.period_risk_free_rate == pytest.approx(0.01)
    assert result.annualized_sharpe_ratio == pytest.approx(1.0)


@pytest.mark.parametrize("periods_per_year", [None, 0, -4])
def test_eligible_sampling_without_positive_periods_per_year_is_rejected(
    periods_per_year: int | None,
) -> None:
    series = _series([0.01, 0.02, 0.03])

    with pytest.raises(ValueError, match="positive periods_per_year"):
        calculate_annualized_statistics(
            series,
            _eligible_sampling(3, periods_per_year=periods_per_year),
            sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
        )


def test_one_observation_cannot_be_annualized() -> None:
    series = _series([0.01])

    with pytest.raises(ValueError, match="at least two observations"):
        calculate_annualized_statistics(
            series,
            _eligible_sampling(1, periods_per_year=4),
        )
