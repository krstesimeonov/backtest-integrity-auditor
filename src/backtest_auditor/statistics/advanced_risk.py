import math

import numpy as np

from backtest_auditor.domain.assumptions import AdvancedRiskSpec
from backtest_auditor.domain.enums import AdvancedRiskStatus, ReturnConvention
from backtest_auditor.domain.results import (
    AdvancedRiskStatisticsResult,
    PerformancePathResult,
    SamplingAssessmentResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.return_basis import to_simple_returns


def calculate_advanced_risk_statistics(
    series: ReturnSeries,
    sampling: SamplingAssessmentResult,
    performance_path: PerformancePathResult,
    *,
    spec: AdvancedRiskSpec | None = None,
) -> AdvancedRiskStatisticsResult | None:
    """Calculate explicit downside, tail, drawdown, and distribution metrics."""

    if spec is None:
        return None

    values = to_simple_returns(series)
    observation_count = int(values.size)
    target = spec.minimum_acceptable_period_return
    shortfalls = np.minimum(values - target, 0.0)
    downside_count = int(np.count_nonzero(shortfalls < 0.0))
    downside_deviation = float(np.sqrt(np.mean(shortfalls**2)))

    period_sortino = None
    annualized_sortino = None
    if downside_deviation > 0.0:
        period_sortino = float(np.mean(values - target) / downside_deviation)
        if sampling.annualization_eligible and sampling.periods_per_year is not None:
            annualized_sortino = period_sortino * math.sqrt(sampling.periods_per_year)

    gains = float(np.sum(np.maximum(values - target, 0.0)))
    losses_below_target = float(np.sum(np.maximum(target - values, 0.0)))
    omega = None if losses_below_target == 0.0 else gains / losses_below_target

    loss_values = -values
    value_at_risk = float(
        np.quantile(loss_values, spec.tail_confidence_level, method="inverted_cdf")
    )
    expected_shortfall = _empirical_expected_shortfall(
        loss_values,
        confidence_level=spec.tail_confidence_level,
    )

    with np.errstate(over="ignore", invalid="ignore"):
        simple_wealth = np.cumprod(1.0 + values)
    ulcer_index: float | None = None
    if np.all(np.isfinite(simple_wealth)):
        # As in performance_path: an overflowing wealth path gives inf/inf =
        # nan drawdowns, and one nan aborts JSON serialisation of the whole
        # report, so the Ulcer index is reported as undefined instead.
        running_peaks = np.maximum.accumulate(np.concatenate(([1.0], simple_wealth)))
        drawdowns = simple_wealth / running_peaks[1:] - 1.0
        ulcer_index = float(np.sqrt(np.mean(drawdowns**2)))

    calmar = None
    if (
        performance_path.cagr is not None
        and performance_path.maximum_drawdown is not None
        and performance_path.maximum_drawdown < 0.0
    ):
        calmar = performance_path.cagr / abs(performance_path.maximum_drawdown)

    status = (
        AdvancedRiskStatus.INSUFFICIENT_OBSERVATIONS
        if observation_count < 2
        else (
            AdvancedRiskStatus.DOWNSIDE_DEVIATION_ZERO
            if downside_deviation == 0.0
            else AdvancedRiskStatus.ELIGIBLE
        )
    )
    return AdvancedRiskStatisticsResult(
        status=status,
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        minimum_acceptable_period_return=target,
        tail_confidence_level=spec.tail_confidence_level,
        downside_observation_count=downside_count,
        downside_deviation=downside_deviation,
        period_sortino_ratio=period_sortino,
        annualized_sortino_ratio=annualized_sortino,
        omega_ratio=omega,
        historical_value_at_risk=value_at_risk,
        historical_expected_shortfall=expected_shortfall,
        calmar_ratio=calmar,
        ulcer_index=ulcer_index,
    )


def _empirical_expected_shortfall(
    losses: np.ndarray,
    *,
    confidence_level: float,
) -> float:
    """Integrate the equal-weight empirical loss quantile over the tail."""

    descending = np.sort(losses)[::-1]
    tail_observations = (1.0 - confidence_level) * len(descending)
    whole = int(math.floor(tail_observations))
    fraction = tail_observations - whole
    numerator = float(np.sum(descending[:whole]))
    if fraction > 0.0:
        numerator += fraction * float(descending[whole])
    return numerator / tail_observations
