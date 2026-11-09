"""Position-sizing contribution: actual P&L vs a fixed-size counterfactual.

Each trade keeps its net return r_i = net_i / notional_i but is resized to
the average entry notional N̄:

    fixed_i                 = r_i · N̄
    sizing contribution     = mean(net) - mean(fixed)
                            = mean((N_i - N̄) · r_i)          (exactly)
                            = population covariance of size and return.

If size carries no information about the outcome the contribution is zero on
average; a positive value means larger positions went into better trades.
Tested by permutation (H0: sizes exchangeable across trades):
p = (1 + #{|shuffled| >= |observed|}) / (draws + 1), two-sided.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.edge_audit.metrics import Interval, percentile_interval
from backtest_auditor.edge_audit.skill import assess_luck_vs_skill


@dataclass(frozen=True, slots=True)
class SizingResult:
    mean_notional: float
    notional_cv: float
    size_return_correlation: float | None
    actual_expectancy: Interval
    fixed_size_expectancy: Interval
    sizing_contribution_per_trade: Interval
    sizing_contribution_total: float
    permutation_draws: int
    permutation_p_value: float
    fixed_size_dsr: float | None
    fixed_size_verdict: str
    finding: str


def fixed_size_pnl(
    net_return: NDArray[np.float64], notional: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Each trade's net return applied to the average notional.

    [HAND-WRITE] Then prove mean(net) - mean(fixed) = cov(N, r) (population).
    """

    return net_return * float(np.mean(notional))


def analyse_sizing(
    net_pnl: NDArray[np.float64],
    notional: NDArray[np.float64],
    *,
    span_years: float,
    declared_trials: int,
    confidence_level: float,
    trial_sharpe_std: float | None,
    bootstrap: dict[str, NDArray[np.float64]],
    actual_expectancy: Interval,
    permutation_draws: int,
    seed: int,
) -> SizingResult:
    """``bootstrap`` holds the shared resamples' 'fixed_size' and 'sizing' means."""

    net_return = net_pnl / notional
    fixed = fixed_size_pnl(net_return, notional)
    contribution = float(np.mean(net_pnl) - np.mean(fixed))
    rng = np.random.default_rng(seed)
    mean_return = float(np.mean(net_return))
    mean_notional = float(np.mean(notional))
    exceed = 0
    for _ in range(permutation_draws):
        shuffled = rng.permutation(notional)
        value = float(np.mean(shuffled * net_return)) - mean_notional * mean_return
        if abs(value) >= abs(contribution):
            exceed += 1
    p_value = (1.0 + exceed) / (permutation_draws + 1.0)
    skill = assess_luck_vs_skill(
        fixed,
        span_years=span_years,
        declared_trials=declared_trials,
        confidence_level=confidence_level,
        trial_sharpe_std=trial_sharpe_std,
    )
    correlation = None
    if np.ptp(notional) > 0.0 and np.ptp(net_return) > 0.0:
        correlation = float(np.corrcoef(notional, net_return)[0, 1])
    significance = 1.0 - confidence_level
    if p_value >= significance:
        finding = "sizing neither adds nor costs P&L detectably"
    elif contribution > 0.0:
        finding = "larger positions went into better trades (sizing adds P&L)"
    else:
        finding = "larger positions went into worse trades (sizing costs P&L)"
    return SizingResult(
        mean_notional=mean_notional,
        notional_cv=float(np.std(notional, ddof=1) / mean_notional)
        if notional.size > 1
        else 0.0,
        size_return_correlation=correlation,
        actual_expectancy=actual_expectancy,
        fixed_size_expectancy=percentile_interval(
            float(np.mean(fixed)),
            bootstrap["fixed_size"],
            confidence_level=confidence_level,
        ),
        sizing_contribution_per_trade=percentile_interval(
            contribution, bootstrap["sizing"], confidence_level=confidence_level
        ),
        sizing_contribution_total=contribution * net_pnl.size,
        permutation_draws=permutation_draws,
        permutation_p_value=p_value,
        fixed_size_dsr=skill.dsr,
        fixed_size_verdict=skill.verdict,
        finding=finding,
    )
