"""Trade-level metrics and trade-level bootstrap confidence intervals.

Resampling reuses V1's resampler
(:func:`backtest_auditor.statistics.resampling.stationary_bootstrap_indices`):
a mean block length of 1 makes every draw a fresh uniform index, i.e. the
ordinary i.i.d. trade bootstrap; a longer mean block keeps runs of
consecutive trades together when trade outcomes are serially dependent.
Intervals are V1's percentile intervals (``bootstrap._metric_result``: linear
interpolation, ddof = 1 bootstrap SE). The one exception is a distribution
containing +inf — a profit factor whose resamples include samples without a
losing trade — which V1 would drop; it gets the same linear rule with +inf kept.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.domain.enums import BootstrapMetric
from backtest_auditor.statistics.bootstrap import _metric_result
from backtest_auditor.statistics.resampling import stationary_bootstrap_indices

IndexStatistic = Callable[[NDArray[np.int64]], float]


def expectancy(pnl: NDArray[np.float64]) -> float:
    """Mean net P&L per trade.

    [HAND-WRITE] one line, but write it: the whole audit is about this number.
    """

    return float(np.mean(pnl))


def profit_factor(pnl: NDArray[np.float64]) -> float:
    """Gross profit / gross loss. ``inf`` with no losing trade, ``nan`` if flat.

    [HAND-WRITE] Decide what a zero-P&L trade is (here: neither win nor loss)
    and what the ratio is when nothing was lost (here: +inf, reported as
    "unbounded", never as a large finite number).
    """

    gross_profit = float(np.sum(pnl[pnl > 0.0]))
    gross_loss = float(-np.sum(pnl[pnl < 0.0]))
    if gross_loss == 0.0:
        return math.inf if gross_profit > 0.0 else math.nan
    return gross_profit / gross_loss


def win_rate(pnl: NDArray[np.float64]) -> float:
    """Share of trades with net P&L strictly above zero."""

    return float(np.mean(pnl > 0.0))


@dataclass(frozen=True, slots=True)
class Interval:
    """A point estimate with a two-sided percentile bootstrap interval.

    ``lower``/``upper`` are ``None`` when undefined; ``upper_unbounded`` marks
    an interval whose upper end is +inf (a profit factor whose resamples
    include samples without a losing trade); ``point_unbounded`` marks a
    point estimate of +inf (a profit factor with no losing trade at all).
    """

    point: float | None
    lower: float | None
    upper: float | None
    confidence_level: float
    standard_error: float | None
    replications: int
    valid_replications: int
    upper_unbounded: bool = False
    point_unbounded: bool = False

    def excludes_zero(self) -> bool:
        return (self.lower is not None and self.lower > 0.0) or (
            self.upper is not None and self.upper < 0.0 and not self.upper_unbounded
        )


def bootstrap_distributions(
    observation_count: int,
    statistics: Mapping[str, IndexStatistic],
    *,
    replications: int,
    mean_block_length: int,
    seed: int,
) -> dict[str, NDArray[np.float64]]:
    """Evaluate every statistic on the same resampled trade index paths.

    Sharing the paths keeps derived quantities consistent: the break-even
    cost and the expectancy in one replicate come from the same trades.

    [HAND-WRITE] The resampling loop is the bootstrap. Write it once by hand
    with ``rng.integers`` (the i.i.d. case), then compare with this version.
    """

    rng = np.random.default_rng(seed)
    output = {name: np.empty(replications, dtype=np.float64) for name in statistics}
    for replicate in range(replications):
        indices = stationary_bootstrap_indices(
            observation_count,
            mean_block_length=mean_block_length,
            rng=rng,
        )
        for name, statistic in statistics.items():
            output[name][replicate] = statistic(indices)
    return output


def percentile_interval(
    point: float | None,
    distribution: NDArray[np.float64],
    *,
    confidence_level: float,
) -> Interval:
    """Two-sided percentile interval; ``nan`` replicates are dropped.

    +inf replicates are kept (they are real outcomes, e.g. a resample without
    losses has an infinite profit factor) and can make the upper end unbounded.
    """

    replications = int(distribution.size)
    values = distribution[~np.isnan(distribution)]
    valid = int(values.size)
    point_unbounded = point is not None and math.isinf(point) and point > 0.0
    if point is None or math.isnan(point) or valid < 2:
        return Interval(
            point=None if point is None or not math.isfinite(point) else point,
            lower=None,
            upper=None,
            confidence_level=confidence_level,
            standard_error=None,
            replications=replications,
            valid_replications=valid,
            point_unbounded=point_unbounded,
        )
    tail = (1.0 - confidence_level) / 2.0
    if math.isfinite(point) and bool(np.all(np.isfinite(values))):
        # V1's percentile step. The metric label only names the result.
        v1 = _metric_result(
            BootstrapMetric.PERIOD_MEAN_RETURN,
            point_estimate=point,
            distribution=values.tolist(),
            attempted_replications=replications,
            lower_quantile=tail,
            upper_quantile=1.0 - tail,
        )
        return Interval(
            point=point,
            lower=v1.lower_bound,
            upper=v1.upper_bound,
            confidence_level=confidence_level,
            standard_error=v1.bootstrap_standard_error,
            replications=replications,
            valid_replications=v1.successful_replications,
        )
    lower = _quantile_allowing_inf(values, tail)
    upper = _quantile_allowing_inf(values, 1.0 - tail)
    finite = values[np.isfinite(values)]
    standard_error = (
        float(np.std(finite, ddof=1))
        if finite.size == values.size and finite.size >= 2
        else None
    )
    return Interval(
        point=None if not math.isfinite(point) else point,
        lower=lower if math.isfinite(lower) else None,
        upper=upper if math.isfinite(upper) else None,
        confidence_level=confidence_level,
        standard_error=standard_error,
        replications=replications,
        valid_replications=valid,
        upper_unbounded=math.isinf(upper) and upper > 0.0,
        point_unbounded=point_unbounded,
    )


def _quantile_allowing_inf(values: NDArray[np.float64], level: float) -> float:
    """numpy's default ("linear") quantile, except that a bracket touching
    +inf returns +inf instead of the ``inf - inf = nan`` numpy produces."""

    ordered = np.sort(values)
    position = level * (ordered.size - 1)
    below = int(math.floor(position))
    above = int(math.ceil(position))
    low, high = float(ordered[below]), float(ordered[above])
    if below == above or low == high:
        return low
    if math.isinf(high) or math.isinf(low):
        return high
    return low + (position - below) * (high - low)
