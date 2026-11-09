"""Does the edge depend on holding period or on the volatility regime?

Trades are split into equal-count terciles of a conditioning variable; each
tercile gets its expectancy with a bootstrap interval, and one permutation
test asks whether expectancy differs across terciles at all.

Statistic: between-tercile sum of squares, sum_g n_g (mean_g - mean)². Under
H0 (expectancy unrelated to the variable) tercile labels are exchangeable, so
shuffling labels gives its null distribution.
p = (1 + #{shuffled >= observed}) / (draws + 1).

Cut points use the whole sample, so tercile membership is descriptive (it
uses information from the future); the volatility measure itself uses only
bars strictly before the entry fill time.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.edge_audit.metrics import (
    Interval,
    bootstrap_distributions,
    percentile_interval,
    win_rate,
)
from backtest_auditor.edge_audit.schema import PriceTable, TradeLog

MINIMUM_TRADES_PER_TERCILE = 10


@dataclass(frozen=True, slots=True)
class TercileRow:
    label: str
    count: int
    variable_min: float
    variable_max: float
    expectancy: Interval
    win_rate: float


@dataclass(frozen=True, slots=True)
class TercileSplit:
    variable: str
    source: str
    status: str
    reason: str | None
    trades_with_value: int
    rows: tuple[TercileRow, ...]
    between_tercile_sum_of_squares: float | None
    permutation_draws: int
    permutation_p_value: float | None
    top_minus_bottom: float | None


def tercile_labels(values: NDArray[np.float64]) -> NDArray[np.int64]:
    """0, 1, 2 by rank; ties keep exit order. Group sizes differ by <= 1.

    [HAND-WRITE] Rank-based rather than quantile cut points, so a block of
    identical holding periods cannot leave a tercile empty.
    """

    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.int64)
    ranks[order] = np.arange(values.size)
    return (3 * ranks) // values.size


def between_sum_of_squares(
    pnl: NDArray[np.float64], labels: NDArray[np.int64]
) -> float:
    grand = float(np.mean(pnl))
    total = 0.0
    for group in range(3):
        member = pnl[labels == group]
        if member.size:
            total += member.size * (float(np.mean(member)) - grand) ** 2
    return total


def trailing_volatility(
    trades: TradeLog, prices: PriceTable, lookback_bars: int
) -> NDArray[np.float64]:
    """SD of log price changes over the last ``lookback_bars`` bars before entry.

    Uses bars with timestamp strictly before the entry time, so the measure
    is known when the trade is opened. ``nan`` without enough history.
    """

    result = np.full(len(trades), np.nan)
    entry_ns = trades.entry_time.asi8
    for position, instrument in enumerate(trades.instrument):
        stamps = prices.timestamps.get(instrument)
        if stamps is None:
            continue
        end = int(np.searchsorted(stamps, entry_ns[position], side="left"))
        start = max(0, end - lookback_bars - 1)
        window = prices.prices[instrument][start:end]
        if window.size >= 3:
            result[position] = float(np.std(np.diff(np.log(window)), ddof=1))
    return result


def split_by_terciles(
    pnl: NDArray[np.float64],
    variable: NDArray[np.float64],
    *,
    variable_name: str,
    source: str,
    labels_text: tuple[str, str, str],
    bootstrap_replications: int,
    mean_block_length: int,
    confidence_level: float,
    permutation_draws: int,
    seed: int,
) -> TercileSplit:
    usable = np.isfinite(variable)
    count = int(usable.sum())
    if count < 3 * MINIMUM_TRADES_PER_TERCILE:
        return TercileSplit(
            variable=variable_name,
            source=source,
            status="unavailable",
            reason=(
                f"{count} trades with a value; {3 * MINIMUM_TRADES_PER_TERCILE} "
                "are needed (10 per tercile)"
            ),
            trades_with_value=count,
            rows=(),
            between_tercile_sum_of_squares=None,
            permutation_draws=permutation_draws,
            permutation_p_value=None,
            top_minus_bottom=None,
        )
    values = pnl[usable]
    conditioning = variable[usable]
    labels = tercile_labels(conditioning)
    group_seeds = np.random.SeedSequence(seed).spawn(4)
    rows = []
    for group in range(3):
        member = labels == group
        member_pnl = values[member]

        def member_mean(
            idx: NDArray[np.int64], values: NDArray[np.float64] = member_pnl
        ) -> float:
            return float(np.mean(values[idx]))

        distribution = bootstrap_distributions(
            member_pnl.size,
            {"mean": member_mean},
            replications=bootstrap_replications,
            mean_block_length=mean_block_length,
            seed=int(group_seeds[group].generate_state(1)[0]),
        )["mean"]
        rows.append(
            TercileRow(
                label=labels_text[group],
                count=int(member.sum()),
                variable_min=float(np.min(conditioning[member])),
                variable_max=float(np.max(conditioning[member])),
                expectancy=percentile_interval(
                    float(np.mean(member_pnl)),
                    distribution,
                    confidence_level=confidence_level,
                ),
                win_rate=win_rate(member_pnl),
            )
        )
    observed = between_sum_of_squares(values, labels)
    rng = np.random.default_rng(group_seeds[3])
    exceed = 0
    for _ in range(permutation_draws):
        if between_sum_of_squares(values, rng.permutation(labels)) >= observed:
            exceed += 1
    return TercileSplit(
        variable=variable_name,
        source=source,
        status="computed",
        reason=None,
        trades_with_value=count,
        rows=tuple(rows),
        between_tercile_sum_of_squares=observed,
        permutation_draws=permutation_draws,
        permutation_p_value=(1.0 + exceed) / (permutation_draws + 1.0),
        top_minus_bottom=float(
            np.mean(values[labels == 2]) - np.mean(values[labels == 0])
        ),
    )
