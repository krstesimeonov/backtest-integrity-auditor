"""Fee/slippage sensitivity: expectancy as a function of extra cost per trade.

Cost unit: basis points of entry notional, per round trip, charged on top of
the fees already in the log. For an added cost c (bps):

    net_i(c)      = net_i - c · 1e-4 · notional_i
    expectancy(c) = mean(net) - c · 1e-4 · mean(notional)      (a straight line)
    break-even c* = mean(net) / mean(notional) · 1e4           (bps)

c* < 0 means the log already loses money and would need c* bps *less* cost.
The gross break-even (total cost the gross edge can carry) adds back the fees
already paid: c*_gross = mean(gross) / mean(notional) · 1e4.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.edge_audit.metrics import Interval, percentile_interval
from backtest_auditor.edge_audit.skill import (
    EVIDENCE,
    LuckVsSkill,
    assess_luck_vs_skill,
)

BPS = 1e-4


@dataclass(frozen=True, slots=True)
class CostPoint:
    added_cost_bps: float
    expectancy: float
    expectancy_lower: float | None
    expectancy_upper: float | None
    dsr: float | None
    verdict: str


@dataclass(frozen=True, slots=True)
class CostSensitivity:
    unit: str
    mean_notional: float
    fees_paid_bps: float
    break_even_added_cost_bps: Interval
    gross_break_even_cost_bps: float
    evidence_lost_at_added_cost_bps: float | None
    evidence_note: str
    curve: tuple[CostPoint, ...]


def with_added_cost(
    net_pnl: NDArray[np.float64], notional: NDArray[np.float64], cost_bps: float
) -> NDArray[np.float64]:
    return net_pnl - cost_bps * BPS * notional


def break_even_added_cost_bps(
    net_pnl: NDArray[np.float64], notional: NDArray[np.float64]
) -> float:
    """Extra round-trip cost (bps of notional) that takes expectancy to zero.

    [HAND-WRITE] Derive it from expectancy(c) = 0. Then ask: why is it the
    ratio of means and not the mean of per-trade ratios (net_return)?
    """

    return float(np.mean(net_pnl) / np.mean(notional) / BPS)


def analyse_costs(
    net_pnl: NDArray[np.float64],
    gross_pnl: NDArray[np.float64],
    notional: NDArray[np.float64],
    *,
    span_years: float,
    declared_trials: int,
    confidence_level: float,
    trial_sharpe_std: float | None,
    grid_bps: tuple[float, ...],
    bootstrap_pnl_means: NDArray[np.float64],
    bootstrap_notional_means: NDArray[np.float64],
) -> CostSensitivity:
    """Curve, break-even with a bootstrap interval, and where evidence ends.

    ``bootstrap_*_means`` are the resampled means from the audit's shared
    trade bootstrap, so the curve's intervals come from the same resamples as
    the expectancy interval.
    """

    mean_notional = float(np.mean(notional))
    break_even = break_even_added_cost_bps(net_pnl, notional)
    with np.errstate(divide="ignore", invalid="ignore"):
        break_even_draws = bootstrap_pnl_means / bootstrap_notional_means / BPS
    tail = (1.0 - confidence_level) / 2.0

    def verdict_at(cost: float) -> LuckVsSkill:
        return assess_luck_vs_skill(
            with_added_cost(net_pnl, notional, cost),
            span_years=span_years,
            declared_trials=declared_trials,
            confidence_level=confidence_level,
            trial_sharpe_std=trial_sharpe_std,
        )

    grid = sorted(set(float(value) for value in grid_bps) | {round(break_even, 6)})
    curve = []
    for cost in grid:
        shifted = bootstrap_pnl_means - cost * BPS * bootstrap_notional_means
        lower, upper = np.quantile(shifted, [tail, 1.0 - tail])
        skill = verdict_at(cost)
        curve.append(
            CostPoint(
                added_cost_bps=cost,
                expectancy=float(np.mean(net_pnl)) - cost * BPS * mean_notional,
                expectancy_lower=float(lower),
                expectancy_upper=float(upper),
                dsr=skill.dsr,
                verdict=skill.verdict,
            )
        )

    evidence_lost: float | None = None
    if verdict_at(0.0).verdict == EVIDENCE:
        low, high = 0.0, max(break_even, 0.0)
        # At c = break-even the Sharpe ratio is 0, so DSR < 0.5 < confidence.
        for _ in range(60):
            middle = (low + high) / 2.0
            if verdict_at(middle).verdict == EVIDENCE:
                low = middle
            else:
                high = middle
            if high - low < 1e-3:
                break
        evidence_lost = high
        note = (
            "smallest added cost (bps, to 0.001) at which the DSR test no "
            "longer shows evidence"
        )
    else:
        note = "no evidence of edge at the logged costs, so none to lose"

    return CostSensitivity(
        unit="bps of entry notional per round trip, on top of logged fees",
        mean_notional=mean_notional,
        fees_paid_bps=float(np.mean(gross_pnl - net_pnl) / mean_notional / BPS),
        break_even_added_cost_bps=percentile_interval(
            break_even, break_even_draws, confidence_level=confidence_level
        ),
        gross_break_even_cost_bps=float(np.mean(gross_pnl) / mean_notional / BPS),
        evidence_lost_at_added_cost_bps=evidence_lost,
        evidence_note=note,
        curve=tuple(curve),
    )
