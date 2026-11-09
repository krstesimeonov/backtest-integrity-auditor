import math

import pytest

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
)
from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.results import (
    AnnualizedStatisticsResult,
    DistributionStatisticsResult,
)
from backtest_auditor.statistics.sharpe_uncertainty import (
    calculate_sharpe_uncertainty,
)


def _annualized(
    annualized_sharpe_ratio: float | None,
) -> AnnualizedStatisticsResult:
    return AnnualizedStatisticsResult(
        periods_per_year=12,
        return_basis=ReturnConvention.SIMPLE,
        annualized_arithmetic_mean_return=0.10,
        annualized_sample_volatility=0.20,
        annual_risk_free_rate=0.0,
        period_risk_free_rate=0.0,
        annualized_sharpe_ratio=annualized_sharpe_ratio,
    )


def _distribution(
    *,
    observation_count: int = 24,
    skewness: float | None = -2.448,
    pearson_kurtosis: float | None = 10.164,
) -> DistributionStatisticsResult:
    return DistributionStatisticsResult(
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        sample_skewness=skewness,
        sample_excess_kurtosis=(
            None if pearson_kurtosis is None else pearson_kurtosis - 3.0
        ),
        sample_pearson_kurtosis=pearson_kurtosis,
    )


def test_known_non_normal_psr_example() -> None:
    period_sharpe = 0.458
    result = calculate_sharpe_uncertainty(
        _annualized(period_sharpe * math.sqrt(12)),
        _distribution(),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0),
    )

    assert result is not None
    assert result.period_sharpe_ratio == pytest.approx(0.458)
    assert result.sharpe_variance_adjustment == pytest.approx(2.601753324)
    assert result.period_sharpe_standard_error == pytest.approx(0.33633273664502306)
    assert result.probabilistic_sharpe_ratio == pytest.approx(0.913361083860933)


def test_annualized_benchmark_is_converted_to_period_basis() -> None:
    result = calculate_sharpe_uncertainty(
        _annualized(1.5),
        _distribution(skewness=0.0, pearson_kurtosis=3.0),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=1.0),
    )

    assert result is not None
    assert result.benchmark_period_sharpe_ratio == pytest.approx(1.0 / math.sqrt(12))
    assert result.benchmark_annualized_sharpe_ratio == 1.0
    assert result.probabilistic_sharpe_ratio is not None


def test_uncertainty_exists_without_psr_benchmark() -> None:
    result = calculate_sharpe_uncertainty(
        _annualized(1.0),
        _distribution(skewness=0.0, pearson_kurtosis=3.0),
    )

    assert result is not None
    assert result.period_sharpe_standard_error is not None
    assert result.benchmark_period_sharpe_ratio is None
    assert result.probabilistic_sharpe_ratio is None


def test_missing_point_sharpe_or_shape_refuses_uncertainty() -> None:
    assert (
        calculate_sharpe_uncertainty(
            _annualized(None),
            _distribution(),
        )
        is None
    )
    assert (
        calculate_sharpe_uncertainty(
            _annualized(1.0),
            _distribution(pearson_kurtosis=None),
        )
        is None
    )


def test_non_positive_variance_adjustment_is_exposed() -> None:
    result = calculate_sharpe_uncertainty(
        _annualized(math.sqrt(12) * 0.1),
        _distribution(skewness=20.0, pearson_kurtosis=3.0),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0),
    )

    assert result is not None
    assert result.sharpe_variance_adjustment < 0.0
    assert result.period_sharpe_standard_error is None
    assert result.benchmark_annualized_sharpe_ratio == 0.0
    assert result.probabilistic_sharpe_ratio is None
