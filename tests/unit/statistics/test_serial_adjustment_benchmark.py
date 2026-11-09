import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import HACKernel, ReturnConvention
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import calculate_annualized_statistics
from backtest_auditor.statistics.distribution import calculate_distribution_statistics
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.serial_adjustment import calculate_serial_adjustment
from backtest_auditor.statistics.sharpe_uncertainty import calculate_sharpe_uncertainty

# A mildly autocorrelated series with a clearly positive Sharpe, so the HAC
# path is eligible and the benchmark can sit on either side of the estimate.
VALUES = [
    0.012,
    0.004,
    0.009,
    -0.003,
    0.011,
    0.006,
    -0.001,
    0.008,
    0.010,
    0.002,
    0.007,
    -0.004,
    0.013,
    0.005,
    0.003,
    0.009,
    -0.002,
    0.006,
    0.011,
    0.001,
]


def _hac_psr(benchmark_annualized_sharpe_ratio: float):
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(VALUES), freq="D"),
        values=np.asarray(VALUES),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(periods_per_year=252),
    )
    psr_spec = ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=benchmark_annualized_sharpe_ratio,
    )
    annualized = calculate_annualized_statistics(
        series,
        assess_sampling(series),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )
    uncertainty = calculate_sharpe_uncertainty(
        annualized,
        calculate_distribution_statistics(series),
        psr_spec=psr_spec,
    )
    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(maximum_lag=2, kernel=HACKernel.BARTLETT),
        psr_spec=psr_spec,
    )
    return annualized, uncertainty, result


def test_hac_psr_is_one_half_when_the_benchmark_equals_the_estimate() -> None:
    # PSR = Phi((SR - SR*) / SE). At SR* = SR the statistic is zero for ANY
    # standard error, so this holds however the HAC variance is estimated.
    annualized, _, _ = _hac_psr(0.0)
    _, uncertainty, result = _hac_psr(annualized.annualized_sharpe_ratio)

    assert uncertainty.benchmark_period_sharpe_ratio == pytest.approx(
        uncertainty.period_sharpe_ratio
    )
    assert result.hac_probabilistic_sharpe_ratio == pytest.approx(0.5)


def test_hac_psr_falls_as_the_benchmark_rises() -> None:
    # A higher bar is harder to clear. Every existing test used a benchmark of
    # 0.0, where SR - SR* and SR + SR* coincide, so the sign was unverified.
    psrs = [
        _hac_psr(b)[2].hac_probabilistic_sharpe_ratio for b in (-1.0, 0.0, 0.5, 1.0)
    ]

    assert all(p is not None for p in psrs)
    assert psrs == sorted(psrs, reverse=True)
    assert len(set(psrs)) == len(psrs)
