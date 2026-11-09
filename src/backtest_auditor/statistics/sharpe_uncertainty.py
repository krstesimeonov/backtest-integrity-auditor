import math
from statistics import NormalDist

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
)
from backtest_auditor.domain.results import (
    AnnualizedStatisticsResult,
    DistributionStatisticsResult,
    SharpeUncertaintyResult,
)


def calculate_sharpe_uncertainty(
    annualized: AnnualizedStatisticsResult | None,
    distribution: DistributionStatisticsResult,
    *,
    psr_spec: ProbabilisticSharpeRatioSpec | None = None,
) -> SharpeUncertaintyResult | None:
    """Estimate Sharpe uncertainty and, when specified, PSR."""

    if (
        annualized is None
        or annualized.annualized_sharpe_ratio is None
        or distribution.sample_skewness is None
        or distribution.sample_pearson_kurtosis is None
    ):
        return None

    observation_count = distribution.observation_count
    if observation_count < 4:
        return None

    periods_per_year = annualized.periods_per_year
    square_root_of_periods = math.sqrt(periods_per_year)
    annualized_sharpe_ratio = annualized.annualized_sharpe_ratio
    period_sharpe_ratio = annualized_sharpe_ratio / square_root_of_periods

    skewness = distribution.sample_skewness
    pearson_kurtosis = distribution.sample_pearson_kurtosis
    variance_adjustment = (
        1.0
        - skewness * period_sharpe_ratio
        + (pearson_kurtosis - 1.0) / 4.0 * period_sharpe_ratio**2
    )

    period_standard_error: float | None = None
    annualized_standard_error: float | None = None
    benchmark_period: float | None = None
    benchmark_annualized: float | None = None
    probabilistic_sharpe_ratio: float | None = None

    if psr_spec is not None:
        benchmark_annualized = psr_spec.benchmark_annualized_sharpe_ratio
        benchmark_period = benchmark_annualized / square_root_of_periods

    if math.isfinite(variance_adjustment) and variance_adjustment > 0.0:
        period_standard_error = math.sqrt(variance_adjustment / (observation_count - 1))
        annualized_standard_error = period_standard_error * square_root_of_periods

        if benchmark_period is not None:
            test_statistic = (
                period_sharpe_ratio - benchmark_period
            ) / period_standard_error
            probabilistic_sharpe_ratio = NormalDist().cdf(test_statistic)

    return SharpeUncertaintyResult(
        observation_count=observation_count,
        periods_per_year=periods_per_year,
        period_sharpe_ratio=period_sharpe_ratio,
        annualized_sharpe_ratio=annualized_sharpe_ratio,
        sharpe_variance_adjustment=variance_adjustment,
        period_sharpe_standard_error=period_standard_error,
        annualized_sharpe_standard_error=(annualized_standard_error),
        benchmark_period_sharpe_ratio=benchmark_period,
        benchmark_annualized_sharpe_ratio=(benchmark_annualized),
        probabilistic_sharpe_ratio=(probabilistic_sharpe_ratio),
    )
