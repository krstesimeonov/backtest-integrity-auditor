import numpy as np

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.results import (
    DistributionStatisticsResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.return_basis import (
    to_simple_returns,
)


def calculate_distribution_statistics(
    series: ReturnSeries,
) -> DistributionStatisticsResult:
    """Estimate finite-sample-corrected skewness and kurtosis."""

    values = to_simple_returns(series)
    observation_count = len(values)
    centered = values - np.mean(values)
    second_central_moment = float(np.mean(centered**2))

    sample_skewness: float | None = None
    sample_excess_kurtosis: float | None = None
    sample_pearson_kurtosis: float | None = None

    if not has_zero_sample_variation(values) and second_central_moment > 0.0:
        if observation_count >= 3:
            biased_skewness = float(np.mean(centered**3) / second_central_moment**1.5)
            sample_skewness = float(
                np.sqrt(observation_count * (observation_count - 1))
                / (observation_count - 2)
                * biased_skewness
            )

        if observation_count >= 4:
            biased_pearson_kurtosis = float(
                np.mean(centered**4) / second_central_moment**2
            )
            sample_excess_kurtosis = float(
                (observation_count - 1)
                / ((observation_count - 2) * (observation_count - 3))
                * (
                    (observation_count + 1) * biased_pearson_kurtosis
                    - 3 * (observation_count - 1)
                )
            )
            sample_pearson_kurtosis = sample_excess_kurtosis + 3.0

    return DistributionStatisticsResult(
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        sample_skewness=sample_skewness,
        sample_excess_kurtosis=sample_excess_kurtosis,
        sample_pearson_kurtosis=sample_pearson_kurtosis,
    )
