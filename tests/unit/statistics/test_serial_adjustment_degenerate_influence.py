import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    HACKernel,
    ReturnConvention,
    SerialAdjustmentStatus,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import (
    calculate_annualized_statistics,
)
from backtest_auditor.statistics.distribution import (
    calculate_distribution_statistics,
)
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.serial_adjustment import (
    calculate_serial_adjustment,
)
from backtest_auditor.statistics.sharpe_uncertainty import (
    calculate_sharpe_uncertainty,
)


@pytest.mark.parametrize("small_return", [0.001, 2**-10, 3 * 2**-10])
def test_two_point_series_at_the_degenerate_sharpe_has_zero_influence_variance(
    small_return: float,
) -> None:
    # Returns [4b, b, b, b, b, b] with a zero risk-free rate. 4b is an exact
    # binary scaling of b, so the ratio is exactly 4 for every b:
    #   mean = 1.5b, deviations 2.5b and -0.5b, sample sd = sqrt(1.5) * b
    #   SR = 1.5 / sqrt(1.5) = sqrt(1.5)
    #   z = 2.5 / sqrt(1.5) and -0.5 / sqrt(1.5)
    #   psi = z - (SR / 2)(z**2 - 1) = 1 / (4 * sqrt(6)) for both values
    # The README Part H influence series is constant, so the Sharpe long-run
    # variance ratio is 0 / 0 and the result must be ZERO_INFLUENCE_VARIANCE
    # whatever b is; Sharpe and HAC are invariant to rescaling the returns.
    values = [4 * small_return] + [small_return] * 5
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=np.asarray(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(periods_per_year=252),
    )
    psr_spec = ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0)
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
        spec=SerialAdjustmentSpec(maximum_lag=1, kernel=HACKernel.BARTLETT),
        psr_spec=psr_spec,
    )

    assert uncertainty.period_sharpe_ratio == pytest.approx(1.5**0.5)
    assert result.status is SerialAdjustmentStatus.ZERO_INFLUENCE_VARIANCE
    assert result.hac_probabilistic_sharpe_ratio is None
