import math
from statistics import NormalDist

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


def test_psr_is_one_half_when_the_benchmark_equals_the_estimate() -> None:
    # PSR = Phi((SR - SR*) / SE): at SR* = SR the statistic is zero for any
    # standard error.
    result = calculate_sharpe_uncertainty(
        _annualized(1.5),
        _distribution(),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=1.5),
    )

    assert result is not None
    assert result.probabilistic_sharpe_ratio == pytest.approx(0.5)


def test_psr_against_a_non_zero_benchmark_matches_the_closed_form() -> None:
    # README "Sharpe uncertainty": with skewness 0 and Pearson kurtosis 3,
    #   A = 1 + (3 - 1) / 4 * SR**2 = 1 + SR**2 / 2
    #   SE = sqrt(A / (n - 1)), PSR = Phi((SR - SR*) / SE)
    # with SR = 1.5 / sqrt(12), SR* = 1.0 / sqrt(12), n = 24.
    period_sharpe = 1.5 / math.sqrt(12)
    period_benchmark = 1.0 / math.sqrt(12)
    standard_error = math.sqrt((1.0 + period_sharpe**2 / 2.0) / 23)
    expected = NormalDist().cdf((period_sharpe - period_benchmark) / standard_error)

    result = calculate_sharpe_uncertainty(
        _annualized(1.5),
        _distribution(skewness=0.0, pearson_kurtosis=3.0),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=1.0),
    )

    assert result is not None
    assert result.period_sharpe_standard_error == pytest.approx(standard_error)
    assert result.probabilistic_sharpe_ratio == pytest.approx(expected)


def test_zero_variance_adjustment_has_no_standard_error() -> None:
    # Skewness 2 with Pearson kurtosis 5 = 1 + skewness**2 is the two-point
    # boundary shape. At period SR = 1:
    #   A = 1 - 2 * 1 + (5 - 1) / 4 * 1**2 = 0
    # A zero plug-in variance is not a zero-uncertainty Sharpe; like a negative
    # one it leaves the standard error, and so PSR, undefined.
    result = calculate_sharpe_uncertainty(
        _annualized(math.sqrt(12)),
        _distribution(skewness=2.0, pearson_kurtosis=5.0),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0),
    )

    assert result is not None
    assert result.period_sharpe_ratio == 1.0
    assert result.sharpe_variance_adjustment == 0.0
    assert result.period_sharpe_standard_error is None
    assert result.annualized_sharpe_standard_error is None
    assert result.probabilistic_sharpe_ratio is None
