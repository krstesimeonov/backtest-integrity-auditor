"""Timing decomposition: entry vs exit vs holding vs execution.

For trade i with signed scale k_i = side·quantity·multiplier, fills P_e, P_x,
bar prices in force at entry/exit B_e, B_x, and the average bar price over an
entry window W_e and an exit window W_x (Ē_e, Ē_x):

    gross P&L_i = k_i (P_x - P_e)
                = k_i (Ē_x - Ē_e)            holding   (direction between windows)
                + k_i (Ē_e - B_e)            entry timing
                + k_i (B_x - Ē_x)            exit timing
                + k_i [(B_e - P_e) + (P_x - B_x)]   execution (fill vs bar)

The identity is exact. Ē_e is the expected bar price of a uniformly random
entry time in W_e, so "entry timing" is the P&L the actual entry time earned
over a random entry time; likewise for exits. Holding is what a trade with
both times randomised would still earn: the directional call.

Windows (``mode``):
* ``day``     — W_e: the entry day's bars up to the bar in force at exit;
                W_x: the exit day's bars from the bar in force at entry.
                A trade whose bar in force at entry (or exit) is from an
                earlier day — entered or exited before that day's first bar —
                is excluded: its actual time could never be one of the
                random draws, and the overnight gap would be credited to
                timing.
* ``holding`` — W_e = W_x = the bars in force during the trade. Holding is then
                zero by construction; entry/exit become "efficiency" inside the
                trade, and a trend inside the trade is credited to timing.

Randomisation tests: entry and exit timing are tested by redrawing that time
uniformly in its window (Monte Carlo, ``draws`` times); holding by flipping
the sign of each trade's holding component (H0: direction independent of the
move, symmetric moves). p = (1 + #{draw >= actual}) / (draws + 1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from backtest_auditor.edge_audit.metrics import (
    Interval,
    bootstrap_distributions,
    percentile_interval,
)
from backtest_auditor.edge_audit.schema import PriceTable, TradeLog

COMPONENTS = ("holding", "entry_timing", "exit_timing", "execution")
TIMING_MODES = ("day", "holding")


@dataclass(frozen=True, slots=True)
class TimingComponents:
    """Per-trade components for the trades that have price coverage."""

    trade_index: NDArray[np.int64]  # positions in the TradeLog
    scale: NDArray[np.float64]  # k_i = side x quantity x multiplier
    bar_entry: NDArray[np.float64]
    bar_exit: NDArray[np.float64]
    window_entry: tuple[NDArray[np.int64], NDArray[np.int64]]  # lo, hi inclusive
    window_exit: tuple[NDArray[np.int64], NDArray[np.int64]]
    values: dict[str, NDArray[np.float64]]  # component -> per-trade value
    excluded: dict[str, int]  # reason -> trade count


@dataclass(frozen=True, slots=True)
class ComponentResult:
    name: str
    total: float
    share_of_gross: float | None
    mean_per_trade: Interval
    p_value_positive: float | None
    p_value_negative: float | None
    test: str
    finding: str


@dataclass(frozen=True, slots=True)
class TimingResult:
    status: str
    reason: str | None
    mode: str
    day_timezone: str
    covered_trades: int
    excluded: dict[str, int]
    gross_pnl_covered: float
    draws: int
    significance_level: float
    components: tuple[ComponentResult, ...]
    counterfactual_quantiles: dict[str, dict[str, float]]


def decompose_trade_timing(
    trades: TradeLog,
    prices: PriceTable,
    *,
    mode: str = "day",
    day_timezone: str = "UTC",
) -> TimingComponents:
    """Exact four-way split of each covered trade's gross P&L.

    [HAND-WRITE] The heart of the timing analysis. Write the four components
    for one trade by hand, check they sum to the gross P&L, then vectorise.
    """

    if mode not in TIMING_MODES:
        raise ValueError(f"mode must be one of {TIMING_MODES}.")
    flat_prices, offsets = _flatten(prices)
    excluded = {
        "no_prices_for_instrument": 0,
        "no_bar_at_or_before_entry": 0,
        "price_in_force_from_an_earlier_day": 0,
    }
    positions: list[int] = []
    entry_bar: list[int] = []
    exit_bar: list[int] = []
    entry_lo: list[int] = []
    entry_hi: list[int] = []
    exit_lo: list[int] = []
    exit_hi: list[int] = []

    entry_ns = trades.entry_time.asi8
    exit_ns = trades.exit_time.asi8
    entry_day = _day_bounds(trades.entry_time, day_timezone)
    exit_day = _day_bounds(trades.exit_time, day_timezone)
    empty_window = 0
    for position, instrument in enumerate(trades.instrument):
        stamps = prices.timestamps.get(instrument)
        if stamps is None:
            excluded["no_prices_for_instrument"] += 1
            continue
        base = offsets[instrument]
        j_e = int(np.searchsorted(stamps, entry_ns[position], side="right")) - 1
        j_x = int(np.searchsorted(stamps, exit_ns[position], side="right")) - 1
        if j_e < 0:
            excluded["no_bar_at_or_before_entry"] += 1
            continue
        if mode == "day":
            entry_first = int(
                np.searchsorted(stamps, entry_day[0][position], side="left")
            )
            exit_first = int(
                np.searchsorted(stamps, exit_day[0][position], side="left")
            )
            if j_e < entry_first or j_x < exit_first:
                excluded["price_in_force_from_an_earlier_day"] += 1
                continue
            e_lo = entry_first
            e_hi = min(
                int(np.searchsorted(stamps, entry_day[1][position], side="left")) - 1,
                j_x,
            )
            x_lo = max(exit_first, j_e)
            x_hi = int(np.searchsorted(stamps, exit_day[1][position], side="left")) - 1
        else:
            e_lo, e_hi, x_lo, x_hi = j_e, j_x, j_e, j_x
        if e_hi < e_lo or x_hi < x_lo:  # a guard: unreachable after the checks above
            empty_window += 1
            continue
        positions.append(position)
        entry_bar.append(base + j_e)
        exit_bar.append(base + j_x)
        entry_lo.append(base + e_lo)
        entry_hi.append(base + e_hi)
        exit_lo.append(base + x_lo)
        exit_hi.append(base + x_hi)
    excluded["empty_window"] = empty_window

    index = np.asarray(positions, dtype=np.int64)
    scale = (trades.side * trades.quantity * trades.multiplier)[index]
    bar_e = flat_prices[np.asarray(entry_bar, dtype=np.int64)]
    bar_x = flat_prices[np.asarray(exit_bar, dtype=np.int64)]
    window_e = (
        np.asarray(entry_lo, dtype=np.int64),
        np.asarray(entry_hi, dtype=np.int64),
    )
    window_x = (
        np.asarray(exit_lo, dtype=np.int64),
        np.asarray(exit_hi, dtype=np.int64),
    )
    mean_e = _window_means(flat_prices, *window_e)
    mean_x = _window_means(flat_prices, *window_x)
    fill_e = trades.entry_price[index]
    fill_x = trades.exit_price[index]
    values = {
        "holding": scale * (mean_x - mean_e),
        "entry_timing": scale * (mean_e - bar_e),
        "exit_timing": scale * (bar_x - mean_x),
        "execution": scale * ((bar_e - fill_e) + (fill_x - bar_x)),
    }
    return TimingComponents(
        trade_index=index,
        scale=scale,
        bar_entry=bar_e,
        bar_exit=bar_x,
        window_entry=window_e,
        window_exit=window_x,
        values=values,
        excluded={key: value for key, value in excluded.items() if value},
    )


def analyse_timing(
    trades: TradeLog,
    prices: PriceTable | None,
    *,
    mode: str,
    day_timezone: str,
    draws: int,
    bootstrap_replications: int,
    mean_block_length: int,
    confidence_level: float,
    seed: int,
) -> TimingResult:
    """Decompose, then test each component against its randomisation null."""

    significance = 1.0 - confidence_level
    if prices is None:
        return _unavailable(mode, day_timezone, draws, significance, "no price file")
    parts = decompose_trade_timing(trades, prices, mode=mode, day_timezone=day_timezone)
    covered = int(parts.trade_index.size)
    if covered < 2:
        return _unavailable(
            mode,
            day_timezone,
            draws,
            significance,
            f"{covered} trade(s) have price coverage; at least 2 are needed",
            excluded=parts.excluded,
        )

    entry_seed, exit_seed, sign_seed, boot_seed = np.random.SeedSequence(seed).spawn(4)
    flat_prices, _ = _flatten(prices)
    k = parts.scale
    actual_bar = float(np.sum(k * (parts.bar_exit - parts.bar_entry)))
    entry_draws = _random_window_prices(
        flat_prices, *parts.window_entry, draws, np.random.default_rng(entry_seed)
    )
    exit_draws = _random_window_prices(
        flat_prices, *parts.window_exit, draws, np.random.default_rng(exit_seed)
    )
    entry_only = (k * (parts.bar_exit - entry_draws)).sum(axis=1)
    exit_only = (k * (exit_draws - parts.bar_entry)).sum(axis=1)
    both = (k * (exit_draws - entry_draws)).sum(axis=1)

    holding = parts.values["holding"]
    signs = np.random.default_rng(sign_seed).choice(
        np.array([-1.0, 1.0]), size=(draws, covered)
    )
    holding_flips = (signs * holding).sum(axis=1)
    holding_total = float(holding.sum())

    statistics = {
        name: (lambda idx, v=parts.values[name]: float(np.mean(v[idx])))
        for name in COMPONENTS
    }
    distributions = bootstrap_distributions(
        covered,
        statistics,
        replications=bootstrap_replications,
        mean_block_length=mean_block_length,
        seed=int(boot_seed.generate_state(1)[0]),
    )
    gross_covered = float(sum(float(np.sum(v)) for v in parts.values.values()))

    def p_values(simulated: NDArray[np.float64], actual: float) -> tuple[float, float]:
        positive = (1.0 + float(np.sum(simulated >= actual))) / (draws + 1.0)
        negative = (1.0 + float(np.sum(simulated <= actual))) / (draws + 1.0)
        return positive, negative

    tests = {
        "entry_timing": (
            p_values(entry_only, actual_bar),
            "random entry time in the entry window, actual exit",
        ),
        "exit_timing": (
            p_values(exit_only, actual_bar),
            "random exit time in the exit window, actual entry",
        ),
        "holding": (
            p_values(holding_flips, holding_total),
            "sign flip of each trade's holding component",
        ),
    }
    components = []
    for name in COMPONENTS:
        total = float(np.sum(parts.values[name]))
        interval = percentile_interval(
            float(np.mean(parts.values[name])),
            distributions[name],
            confidence_level=confidence_level,
        )
        p_pos: float | None = None
        p_neg: float | None = None
        if name in tests:
            (positive, negative), description = tests[name]
            if mode == "holding" and name == "holding":
                finding = "zero by construction in holding-window mode"
            else:
                p_pos, p_neg = positive, negative
                if positive < significance:
                    finding = "adds P&L (significant)"
                elif negative < significance:
                    finding = "costs P&L (significant)"
                else:
                    finding = "not distinguishable from random"
        else:
            description = "fill price vs bar price in force (no randomisation)"
            finding = (
                "costs P&L"
                if interval.upper is not None and interval.upper < 0.0
                else "adds P&L"
                if interval.lower is not None and interval.lower > 0.0
                else "not distinguishable from zero"
            )
        components.append(
            ComponentResult(
                name=name,
                total=total,
                share_of_gross=(
                    total / gross_covered if gross_covered != 0.0 else None
                ),
                mean_per_trade=interval,
                p_value_positive=p_pos,
                p_value_negative=p_neg,
                test=description,
                finding=finding,
            )
        )

    def quantiles(values: NDArray[np.float64]) -> dict[str, float]:
        levels = (0.05, 0.25, 0.5, 0.75, 0.95)
        return {
            f"q{int(level * 100):02d}": float(np.quantile(values, level))
            for level in levels
        }

    return TimingResult(
        status="computed",
        reason=None,
        mode=mode,
        day_timezone=day_timezone,
        covered_trades=covered,
        excluded=parts.excluded,
        gross_pnl_covered=gross_covered,
        draws=draws,
        significance_level=significance,
        components=tuple(components),
        counterfactual_quantiles={
            "actual_bar_price_total": {"value": actual_bar},
            "random_entry_total": quantiles(entry_only),
            "random_exit_total": quantiles(exit_only),
            "random_entry_and_exit_total": quantiles(both),
        },
    )


def _unavailable(
    mode: str,
    day_timezone: str,
    draws: int,
    significance: float,
    reason: str,
    *,
    excluded: dict[str, int] | None = None,
) -> TimingResult:
    return TimingResult(
        status="unavailable",
        reason=reason,
        mode=mode,
        day_timezone=day_timezone,
        covered_trades=0,
        excluded=excluded or {},
        gross_pnl_covered=0.0,
        draws=draws,
        significance_level=significance,
        components=(),
        counterfactual_quantiles={},
    )


def _flatten(prices: PriceTable) -> tuple[NDArray[np.float64], dict[str, int]]:
    offsets: dict[str, int] = {}
    chunks: list[NDArray[np.float64]] = []
    cursor = 0
    for name in prices.instruments():
        offsets[name] = cursor
        chunks.append(prices.prices[name])
        cursor += prices.prices[name].size
    return np.concatenate(chunks), offsets


def _day_bounds(
    times: pd.DatetimeIndex, day_timezone: str
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """UTC ns of the first instant of each timestamp's local day and of the next.

    Built from the local calendar date, not by normalising the zoned time:
    where clocks jump at midnight (Africa/Cairo, America/Santiago, ...) local
    00:00 does not exist on that date and ``normalize()`` raises. A midnight
    that does not exist is moved forward to the first instant that does; a
    midnight that occurs twice takes its first occurrence.
    """

    midnight = times.tz_convert(day_timezone).tz_localize(None).normalize()
    first = np.ones(len(times), dtype=bool)

    def to_utc(naive: pd.DatetimeIndex) -> NDArray[np.int64]:
        zoned = naive.tz_localize(
            day_timezone, ambiguous=first, nonexistent="shift_forward"
        )
        return np.asarray(zoned.tz_convert("UTC").as_unit("ns").asi8, dtype=np.int64)

    return to_utc(midnight), to_utc(midnight + pd.Timedelta(days=1))


def _window_means(
    flat: NDArray[np.float64], lo: NDArray[np.int64], hi: NDArray[np.int64]
) -> NDArray[np.float64]:
    if lo.size == 0:
        return np.zeros(0, dtype=np.float64)
    padded = np.append(flat, 0.0)
    bounds = np.empty(2 * lo.size, dtype=np.int64)
    bounds[0::2] = lo
    bounds[1::2] = hi + 1
    sums = np.add.reduceat(padded, bounds)[0::2]
    return sums / (hi - lo + 1)


def _random_window_prices(
    flat: NDArray[np.float64],
    lo: NDArray[np.int64],
    hi: NDArray[np.int64],
    draws: int,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """(draws, trades) prices at uniformly random bars inside each window."""

    width = hi - lo + 1
    offsets = np.floor(rng.random((draws, lo.size)) * width).astype(np.int64)
    return flat[lo + np.minimum(offsets, width - 1)]
