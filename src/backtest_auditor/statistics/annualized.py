import math

import numpy as np

from backtest_auditor.domain.assumptions import SharpeRatioSpec
from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.results import (
    AnnualizedStatisticsResult,
    SamplingAssessmentResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.return_basis import (
    annual_to_period_rate,
    to_simple_returns,
)


def calculate_annualized_statistics(
    series: ReturnSeries,
    sampling: SamplingAssessmentResult,
    *,
    sharpe_spec: SharpeRatioSpec | None = None,
) -> AnnualizedStatisticsResult | None:
    """Calculate annualized point estimates only when sampling is eligible."""

    if not sampling.annualization_eligible:
        return None

    periods_per_year = sampling.periods_per_year
    if periods_per_year is None or periods_per_year <= 0:
        raise ValueError("eligible sampling must have positive periods_per_year.")

    simple_returns = to_simple_returns(series)
    if len(simple_returns) < 2:
        raise ValueError("annualized volatility requires at least two observations.")

    period_mean = float(np.mean(simple_returns))
    period_sample_volatility = (
        0.0
        if has_zero_sample_variation(simple_returns)
        else float(np.std(simple_returns, ddof=1))
    )
    square_root_of_periods = math.sqrt(periods_per_year)

    annualized_arithmetic_mean_return = period_mean * periods_per_year
    annualized_sample_volatility = period_sample_volatility * square_root_of_periods

    annual_risk_free_rate: float | None = None
    period_risk_free_rate: float | None = None
    annualized_sharpe_ratio: float | None = None

    if sharpe_spec is not None:
        annual_risk_free_rate = sharpe_spec.annual_risk_free_rate
        period_risk_free_rate = annual_to_period_rate(
            annual_risk_free_rate,
            periods_per_year,
        )

        if not has_zero_sample_variation(simple_returns):
            annualized_sharpe_ratio = (
                (period_mean - period_risk_free_rate)
                / period_sample_volatility
                * square_root_of_periods
            )

    return AnnualizedStatisticsResult(
        periods_per_year=periods_per_year,
        return_basis=ReturnConvention.SIMPLE,
        annualized_arithmetic_mean_return=(annualized_arithmetic_mean_return),
        annualized_sample_volatility=(annualized_sample_volatility),
        annual_risk_free_rate=annual_risk_free_rate,
        period_risk_free_rate=period_risk_free_rate,
        annualized_sharpe_ratio=annualized_sharpe_ratio,
    )
