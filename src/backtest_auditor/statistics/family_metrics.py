import math

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.statistics.degeneracy import (
    columns_with_zero_sample_variation,
)


def period_sharpe_scores(
    values: NDArray[np.float64],
    *,
    period_risk_free_rate_value: float,
) -> NDArray[np.float64]:
    """Calculate column-wise sample period Sharpe ratios without filtering."""

    means = np.mean(values, axis=0) - period_risk_free_rate_value
    volatility = np.std(values, axis=0, ddof=1)
    # np.std of a flat trial is a rounding residue, not 0.0 (2.29e-19 for a
    # constant 0.001), so `volatility != 0.0` alone scored such a trial near
    # +-4e15: it won every CSCV split and every robustness comparison. Its
    # Sharpe is undefined, which every caller already treats as unavailable.
    return np.divide(
        means,
        volatility,
        out=np.full_like(means, np.nan, dtype=float),
        where=~columns_with_zero_sample_variation(values) & (volatility != 0.0),
    )


def average_ranks(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return one-based ascending ranks with average ranks for exact ties."""

    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(order):
        stop = start + 1
        while stop < len(order) and values[order[stop]] == values[order[start]]:
            stop += 1
        average_rank = (start + 1 + stop) / 2.0
        ranks[order[start:stop]] = average_rank
        start = stop
    return ranks


def relative_rank_and_logit(rank: float, trial_count: int) -> tuple[float, float]:
    relative_rank = rank / (trial_count + 1.0)
    return relative_rank, math.log(relative_rank / (1.0 - relative_rank))
