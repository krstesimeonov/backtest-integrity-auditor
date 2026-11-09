import math

import numpy as np

from backtest_auditor.domain.enums import PairedSeriesStatus, SeriesRole
from backtest_auditor.domain.results import (
    GrossNetCostDragResult,
    PairedSeriesAlignmentResult,
    RegimeAnalysisResult,
    RegimeSliceResult,
    RiskFreeSeriesResult,
    SamplingAssessmentResult,
)
from backtest_auditor.domain.series import RegimeSeries, ReturnSeries
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.return_basis import to_simple_returns


def assess_paired_alignment(
    strategy: ReturnSeries,
    paired: ReturnSeries,
    *,
    role: SeriesRole,
) -> PairedSeriesAlignmentResult:
    strategy_only = strategy.timestamps.difference(paired.timestamps)
    paired_only = paired.timestamps.difference(strategy.timestamps)
    eligible = strategy.timestamps.equals(paired.timestamps)
    return PairedSeriesAlignmentResult(
        role=role,
        status=(
            PairedSeriesStatus.ELIGIBLE
            if eligible
            else PairedSeriesStatus.TIMESTAMP_MISMATCH
        ),
        strategy_observation_count=len(strategy.timestamps),
        paired_observation_count=len(paired.timestamps),
        aligned_observation_count=len(
            strategy.timestamps.intersection(paired.timestamps)
        ),
        strategy_only_timestamps=tuple(item.isoformat() for item in strategy_only),
        paired_only_timestamps=tuple(item.isoformat() for item in paired_only),
    )


def calculate_risk_free_series_evidence(
    strategy: ReturnSeries,
    risk_free: ReturnSeries | None,
    sampling: SamplingAssessmentResult,
) -> RiskFreeSeriesResult | None:
    if risk_free is None:
        return None
    alignment = assess_paired_alignment(strategy, risk_free, role=SeriesRole.RISK_FREE)
    if alignment.status is not PairedSeriesStatus.ELIGIBLE:
        return RiskFreeSeriesResult(alignment, None, None, None, None, None, None)

    strategy_values = to_simple_returns(strategy)
    risk_free_values = to_simple_returns(risk_free)
    excess = strategy_values - risk_free_values
    if len(excess) < 2:
        volatility = None
    elif has_zero_sample_variation(excess):
        # A constant excess return has exactly zero sample variation; np.std
        # returns a rounding residue (2.8e-20 for 0.0 - 0.03/252).
        volatility = 0.0
    else:
        volatility = float(np.std(excess, ddof=1))
    period_sharpe = (
        None
        if volatility is None or volatility == 0.0
        else float(np.mean(excess) / volatility)
    )
    annualized_sharpe = None
    if (
        period_sharpe is not None
        and sampling.annualization_eligible
        and sampling.periods_per_year is not None
    ):
        annualized_sharpe = period_sharpe * math.sqrt(sampling.periods_per_year)
    return RiskFreeSeriesResult(
        alignment=alignment,
        mean_period_risk_free_return=float(np.mean(risk_free_values)),
        cumulative_risk_free_return=float(np.prod(1.0 + risk_free_values) - 1.0),
        mean_period_excess_return=float(np.mean(excess)),
        excess_return_sample_volatility=volatility,
        period_excess_sharpe_ratio=period_sharpe,
        annualized_excess_sharpe_ratio=annualized_sharpe,
    )


def calculate_gross_net_cost_drag(
    net_returns: ReturnSeries,
    gross_returns: ReturnSeries | None,
    sampling: SamplingAssessmentResult,
) -> GrossNetCostDragResult | None:
    if gross_returns is None:
        return None
    alignment = assess_paired_alignment(
        net_returns,
        gross_returns,
        role=SeriesRole.GROSS_STRATEGY,
    )
    if alignment.status is not PairedSeriesStatus.ELIGIBLE:
        return GrossNetCostDragResult(
            alignment, None, None, None, None, None, None, None
        )

    net = to_simple_returns(net_returns)
    gross = to_simple_returns(gross_returns)
    drag = gross - net
    annualized_drag = None
    if sampling.annualization_eligible and sampling.periods_per_year is not None:
        annualized_drag = float(np.mean(drag) * sampling.periods_per_year)
    gross_cumulative = float(np.prod(1.0 + gross) - 1.0)
    net_cumulative = float(np.prod(1.0 + net) - 1.0)
    return GrossNetCostDragResult(
        alignment=alignment,
        mean_period_cost_drag=float(np.mean(drag)),
        cumulative_gross_return=gross_cumulative,
        cumulative_net_return=net_cumulative,
        cumulative_cost_drag=gross_cumulative - net_cumulative,
        annualized_arithmetic_cost_drag=annualized_drag,
        periods_with_positive_cost_drag=int(np.count_nonzero(drag > 0.0)),
        periods_with_negative_cost_drag=int(np.count_nonzero(drag < 0.0)),
    )


def calculate_regime_analysis(
    strategy: ReturnSeries,
    regimes: RegimeSeries | None,
    *,
    risk_free: ReturnSeries | None = None,
) -> RegimeAnalysisResult | None:
    if regimes is None:
        return None
    strategy_only = strategy.timestamps.difference(regimes.timestamps)
    regime_only = regimes.timestamps.difference(strategy.timestamps)
    if not strategy.timestamps.equals(regimes.timestamps):
        return RegimeAnalysisResult(
            status=PairedSeriesStatus.TIMESTAMP_MISMATCH,
            observation_count=len(strategy.timestamps),
            regime_count=0,
            slices=(),
            strategy_only_timestamps=tuple(item.isoformat() for item in strategy_only),
            regime_only_timestamps=tuple(item.isoformat() for item in regime_only),
        )

    values = to_simple_returns(strategy)
    risk_free_values = None
    if risk_free is not None and strategy.timestamps.equals(risk_free.timestamps):
        risk_free_values = to_simple_returns(risk_free)

    slices: list[RegimeSliceResult] = []
    labels = np.asarray(regimes.labels, dtype=object)
    for regime in sorted(set(regimes.labels)):
        mask = labels == regime
        selected = values[mask]
        if len(selected) < 2:
            volatility = None
        elif has_zero_sample_variation(selected):
            volatility = 0.0
        else:
            volatility = float(np.std(selected, ddof=1))
        sharpe = None
        if risk_free_values is not None and len(selected) >= 2:
            excess = selected - risk_free_values[mask]
            if not has_zero_sample_variation(excess):
                excess_volatility = float(np.std(excess, ddof=1))
                if excess_volatility > 0.0:
                    sharpe = float(np.mean(excess) / excess_volatility)
        slices.append(
            RegimeSliceResult(
                regime=regime,
                observation_count=len(selected),
                mean_period_return=float(np.mean(selected)),
                sample_volatility=volatility,
                cumulative_simple_return=float(np.prod(1.0 + selected) - 1.0),
                period_sharpe_ratio=sharpe,
            )
        )
    return RegimeAnalysisResult(
        status=PairedSeriesStatus.ELIGIBLE,
        observation_count=len(values),
        regime_count=len(slices),
        slices=tuple(slices),
        strategy_only_timestamps=(),
        regime_only_timestamps=(),
    )
