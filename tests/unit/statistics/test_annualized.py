import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import SharpeRatioSpec
from backtest_auditor.domain.enums import ReturnConvention
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
    convention: ReturnConvention = ReturnConvention.SIMPLE,
    periods_per_year: int | None = 4,
) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range(
            "2026-01-01",
            periods=len(values),
            freq="D",
        ),
        values=np.asarray(values),
        convention=convention,
        sampling=SamplingSpec(periods_per_year=periods_per_year),
    )


def test_eligible_simple_returns_are_annualized() -> None:
    series = _series([0.01, 0.02, 0.03])

    result = calculate_annualized_statistics(
        series,
        assess_sampling(series),
    )

    assert result is not None
    assert result.return_basis is ReturnConvention.SIMPLE
    assert result.annualized_arithmetic_mean_return == (pytest.approx(0.08))
    assert result.annualized_sample_volatility == (pytest.approx(0.02))


def test_log_returns_are_converted_to_simple_return_basis() -> None:
    series = _series(
        np.log1p([0.01, 0.02, 0.03]).tolist(),
        convention=ReturnConvention.LOG,
    )

    result = calculate_annualized_statistics(
        series,
        assess_sampling(series),
    )

    assert result is not None
    assert result.return_basis is ReturnConvention.SIMPLE
    assert result.annualized_arithmetic_mean_return == (pytest.approx(0.08))
    assert result.annualized_sample_volatility == (pytest.approx(0.02))


def test_sharpe_uses_equivalent_period_risk_free_rate() -> None:
    series = _series([0.01, 0.03, 0.05])
    annual_risk_free_rate = (1.01**4) - 1.0

    result = calculate_annualized_statistics(
        series,
        assess_sampling(series),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=annual_risk_free_rate),
    )

    assert result is not None
    assert result.annual_risk_free_rate == pytest.approx(annual_risk_free_rate)
    assert result.period_risk_free_rate == pytest.approx(0.01)
    assert result.annualized_sharpe_ratio == pytest.approx(2.0)


def test_missing_sharpe_spec_leaves_rate_and_ratio_undefined() -> None:
    series = _series([0.01, 0.02, 0.03])

    result = calculate_annualized_statistics(
        series,
        assess_sampling(series),
    )

    assert result is not None
    assert result.annual_risk_free_rate is None
    assert result.period_risk_free_rate is None
    assert result.annualized_sharpe_ratio is None


def test_zero_volatility_leaves_sharpe_undefined() -> None:
    series = _series([0.02, 0.02, 0.02])

    result = calculate_annualized_statistics(
        series,
        assess_sampling(series),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )

    assert result is not None
    assert result.annualized_sample_volatility == 0.0
    assert result.annualized_sharpe_ratio is None


def test_ineligible_sampling_refuses_annualization() -> None:
    series = _series(
        [0.01, 0.02, 0.03],
        periods_per_year=None,
    )

    result = calculate_annualized_statistics(
        series,
        assess_sampling(series),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )

    assert result is None
