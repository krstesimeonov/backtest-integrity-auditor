import math

import numpy as np

from backtest_auditor.domain.enums import (
    BenchmarkAlignmentStatus,
    ReturnConvention,
)
from backtest_auditor.domain.results import (
    BenchmarkAlignmentResult,
    BenchmarkComparisonResult,
    SamplingAssessmentResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.return_basis import to_simple_returns


def assess_benchmark_alignment(
    strategy: ReturnSeries,
    benchmark: ReturnSeries,
) -> BenchmarkAlignmentResult:
    strategy_only = strategy.timestamps.difference(benchmark.timestamps)
    benchmark_only = benchmark.timestamps.difference(strategy.timestamps)
    eligible = strategy.timestamps.equals(benchmark.timestamps)

    return BenchmarkAlignmentResult(
        status=(
            BenchmarkAlignmentStatus.ELIGIBLE
            if eligible
            else BenchmarkAlignmentStatus.TIMESTAMP_MISMATCH
        ),
        strategy_observation_count=len(strategy.timestamps),
        benchmark_observation_count=len(benchmark.timestamps),
        aligned_observation_count=(
            len(strategy.timestamps.intersection(benchmark.timestamps))
        ),
        strategy_only_timestamps=tuple(item.isoformat() for item in strategy_only),
        benchmark_only_timestamps=tuple(item.isoformat() for item in benchmark_only),
    )


def calculate_benchmark_comparison(
    strategy: ReturnSeries,
    benchmark: ReturnSeries,
    alignment: BenchmarkAlignmentResult,
    sampling: SamplingAssessmentResult,
    *,
    benchmark_id: str,
) -> BenchmarkComparisonResult | None:
    """Calculate benchmark evidence only after exact alignment."""

    if alignment.status is not BenchmarkAlignmentStatus.ELIGIBLE:
        return None

    strategy_returns = to_simple_returns(strategy)
    benchmark_returns = to_simple_returns(benchmark)
    active_returns = strategy_returns - benchmark_returns
    observation_count = len(active_returns)
    periods_per_year = (
        sampling.periods_per_year if sampling.annualization_eligible else None
    )

    strategy_wealth = float(np.prod(1.0 + strategy_returns))
    benchmark_wealth = float(np.prod(1.0 + benchmark_returns))
    relative_wealth_return = (
        None if benchmark_wealth <= 0.0 else strategy_wealth / benchmark_wealth - 1.0
    )

    mean_active = float(np.mean(active_returns))
    tracking_error = None
    annualized_tracking_error = None
    period_information_ratio = None
    annualized_information_ratio = None
    correlation = None
    beta = None
    period_alpha = None
    annualized_alpha = None

    if observation_count >= 2:
        tracking_error = float(np.std(active_returns, ddof=1))
        if tracking_error > 0.0:
            period_information_ratio = mean_active / tracking_error

        strategy_volatility = float(np.std(strategy_returns, ddof=1))
        benchmark_variance = float(np.var(benchmark_returns, ddof=1))
        if strategy_volatility > 0.0 and benchmark_variance > 0.0:
            correlation = float(np.corrcoef(strategy_returns, benchmark_returns)[0, 1])
        if benchmark_variance > 0.0:
            covariance = float(
                np.cov(
                    strategy_returns,
                    benchmark_returns,
                    ddof=1,
                )[0, 1]
            )
            beta = covariance / benchmark_variance
            period_alpha = float(
                np.mean(strategy_returns) - beta * np.mean(benchmark_returns)
            )

        if periods_per_year is not None:
            annualization_factor = math.sqrt(periods_per_year)
            annualized_tracking_error = tracking_error * annualization_factor
            if period_information_ratio is not None:
                annualized_information_ratio = (
                    period_information_ratio * annualization_factor
                )
            if period_alpha is not None:
                annualized_alpha = period_alpha * periods_per_year

    return BenchmarkComparisonResult(
        benchmark_id=benchmark_id,
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        periods_per_year=periods_per_year,
        strategy_cumulative_simple_return=strategy_wealth - 1.0,
        benchmark_cumulative_simple_return=benchmark_wealth - 1.0,
        relative_wealth_return=relative_wealth_return,
        mean_period_active_return=mean_active,
        period_tracking_error=tracking_error,
        annualized_tracking_error=annualized_tracking_error,
        period_information_ratio=period_information_ratio,
        annualized_information_ratio=annualized_information_ratio,
        return_correlation=correlation,
        beta=beta,
        period_arithmetic_alpha=period_alpha,
        annualized_arithmetic_alpha=annualized_alpha,
    )
