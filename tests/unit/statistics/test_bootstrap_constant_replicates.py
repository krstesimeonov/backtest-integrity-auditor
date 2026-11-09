import math

import numpy as np
import pandas as pd

from backtest_auditor.domain.assumptions import BootstrapSpec, SharpeRatioSpec
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    BootstrapMetric,
    FrequencyStatus,
    ReturnConvention,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import (
    calculate_annualized_statistics,
)
from backtest_auditor.statistics.bootstrap import (
    calculate_bootstrap_confidence_intervals,
)
from backtest_auditor.statistics.sampling import assess_sampling


def test_constant_replicates_do_not_enter_the_sharpe_interval() -> None:
    # Nine returns of 0.001 then one of 0.002, blocks of two. A replicate is
    # five blocks, and only the last block holds the 0.002, so a replicate has
    # k = 0..5 copies of it. k = 0 is bit-identical: zero sample variation, an
    # undefined Sharpe, excluded per README Part I. For k = 1..5,
    #   mean = 0.001 * (1 + k / 10), sd = 0.001 * sqrt(k * (10 - k) / 90)
    #   SR(k) = (1 + k / 10) * sqrt(90 / (k * (10 - k)))
    #         = 3.479, 2.846, 2.691, 2.711, 2.846
    # so no valid replicate has a period Sharpe above 1.1 * sqrt(10).
    values = [0.001] * 9 + [0.002]
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=np.asarray(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(
            status=FrequencyStatus.DECLARED,
            declared_frequency="D",
            periods_per_year=252,
        ),
    )
    sampling = assess_sampling(series)
    annualized = calculate_annualized_statistics(
        series,
        sampling,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )

    result = calculate_bootstrap_confidence_intervals(
        series,
        sampling,
        annualized,
        None,
        spec=BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=2000,
            confidence_level=0.95,
            block_length=2,
            random_seed=42,
        ),
    )

    assert result is not None
    sharpe = next(
        item
        for item in result.metrics
        if item.metric is BootstrapMetric.PERIOD_SHARPE_RATIO
    )
    assert sharpe.upper_bound is not None
    assert sharpe.upper_bound <= 1.1 * math.sqrt(10) * (1 + 1e-12)
    assert sharpe.successful_replications < sharpe.attempted_replications
