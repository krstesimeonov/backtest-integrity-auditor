"""Synthetic trade logs and price paths with a known truth.

Used by the calibration tests and the sample audit. Every generator returns
plain DataFrames in the input schemas (string-ready), so the tests exercise
the same parsing path as a user's CSV, plus the true values the audit should
recover.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_auditor.edge_audit.schema import PRICES_SCHEMA, TRADES_SCHEMA

SESSION_OPEN_UTC = pd.Timedelta(hours=14, minutes=30)


@dataclass(frozen=True)
class SyntheticLog:
    trades: pd.DataFrame
    prices: pd.DataFrame | None
    truth: dict[str, float]


def write_csv(frame: pd.DataFrame, path: str | Path, schema: str) -> Path:
    """Write with the ``# schema: <id>`` first line the loader understands."""

    path = Path(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"# schema: {schema}\n")
        frame.to_csv(handle, index=False, float_format="%.10g")
    return path


def write_log(
    log: SyntheticLog, directory: str | Path, stem: str = "trades"
) -> tuple[Path, Path | None]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    trades = write_csv(log.trades, directory / f"{stem}.csv", TRADES_SCHEMA)
    prices = (
        None
        if log.prices is None
        else write_csv(log.prices, directory / f"{stem}_prices.csv", PRICES_SCHEMA)
    )
    return trades, prices


def _iso(stamps: pd.DatetimeIndex | pd.Series) -> list[str]:
    return [stamp.strftime("%Y-%m-%dT%H:%M:%SZ") for stamp in pd.DatetimeIndex(stamps)]


def pnl_trade_log(
    pnl_per_unit: np.ndarray,
    *,
    seed: int,
    sizes: np.ndarray | None = None,
    entry_prices: np.ndarray | None = None,
    fees: np.ndarray | None = None,
    start: str = "2025-01-02",
    trades_per_day: float = 2.0,
    instrument: str = "SYN",
) -> pd.DataFrame:
    """Trades whose gross P&L per unit of quantity is ``pnl_per_unit``.

    Long trades with exit = entry + pnl_per_unit, so the gross P&L of trade i
    is exactly sizes[i] x pnl_per_unit[i]. Times are spaced
    ``1/trades_per_day`` days apart in exit order, held 1-6 hours.
    """

    rng = np.random.default_rng(seed)
    count = pnl_per_unit.size
    sizes = np.ones(count) if sizes is None else sizes
    entry_prices = np.full(count, 100.0) if entry_prices is None else entry_prices
    fees = np.zeros(count) if fees is None else fees
    exit_prices = entry_prices + pnl_per_unit
    if np.any(exit_prices <= 0.0):
        raise ValueError("pnl_per_unit drives an exit price to <= 0")
    offsets = pd.to_timedelta(np.arange(1, count + 1) / trades_per_day, unit="D")
    exit_times = (pd.Timestamp(start, tz="UTC") + SESSION_OPEN_UTC + offsets).round("s")
    holding = pd.to_timedelta(rng.uniform(1.0, 6.0, count), unit="h").round("s")
    entry_times = exit_times - holding
    return pd.DataFrame(
        {
            "trade_id": [f"T{index:05d}" for index in range(1, count + 1)],
            "instrument": instrument,
            "side": "long",
            "quantity": sizes,
            "entry_time": _iso(entry_times),
            "entry_price": entry_prices,
            "exit_time": _iso(exit_times),
            "exit_price": exit_prices,
            "fees": fees,
        }
    )


def noise_log(
    seed: int,
    *,
    trades: int = 250,
    volatility: float = 0.01,
    tail_df: float | None = 5.0,
) -> SyntheticLog:
    """Zero-expectancy trades: random side, random size, symmetric moves.

    Moves are Student-t (``tail_df``) scaled to ``volatility`` (fat tails on
    purpose), sides are coin flips and sizes are log-normal and independent
    of everything else, so E[net P&L] = 0 exactly and there are no fees.
    """

    rng = np.random.default_rng(seed)
    if tail_df is None:
        moves = rng.standard_normal(trades) * volatility
    else:
        scale = np.sqrt((tail_df - 2.0) / tail_df)
        moves = rng.standard_t(tail_df, trades) * scale * volatility
        moves = np.clip(moves, -0.5, 0.5)  # symmetric: the mean stays zero
    sides = rng.choice(np.array(["long", "short"]), trades)
    sizes = np.round(rng.lognormal(mean=4.0, sigma=0.5, size=trades), 0) + 1.0
    entry = 100.0 * np.exp(rng.normal(0.0, 0.1, trades))
    frame = pnl_trade_log(np.zeros(trades), seed=seed, sizes=sizes, entry_prices=entry)
    frame["side"] = sides
    frame["exit_price"] = entry * (1.0 + moves)
    return SyntheticLog(trades=frame, prices=None, truth={"expectancy": 0.0})


def decaying_edge_log(
    seed: int,
    *,
    trades: int = 600,
    change_at: int = 300,
    sharpe_before: float = 0.3,
    sharpe_after: float = 0.0,
    pnl_sd: float = 1.0,
) -> SyntheticLog:
    """Normal per-trade P&L whose mean drops after trade ``change_at``."""

    rng = np.random.default_rng(seed)
    means = (
        np.where(np.arange(trades) < change_at, sharpe_before, sharpe_after) * pnl_sd
    )
    pnl = means + rng.standard_normal(trades) * pnl_sd
    return SyntheticLog(
        trades=pnl_trade_log(pnl, seed=seed),
        prices=None,
        truth={
            "change_after_trade": float(change_at),
            "sharpe_before": sharpe_before,
            "sharpe_after": sharpe_after,
        },
    )


def cost_log(
    seed: int,
    *,
    trades: int = 400,
    gross_edge_bps: float = 8.0,
    fee_bps: float = 2.0,
    noise_bps: float = 40.0,
) -> SyntheticLog:
    """Per-trade gross return = edge + noise (bps), fees = ``fee_bps`` of notional.

    Notional varies (independent of returns). True added-cost break-even:
    gross_edge_bps - fee_bps.
    """

    rng = np.random.default_rng(seed)
    sizes = np.round(rng.uniform(50.0, 150.0, trades), 0)
    entry = np.full(trades, 100.0)
    returns = (gross_edge_bps + noise_bps * rng.standard_normal(trades)) * 1e-4
    notional = sizes * entry
    fees = fee_bps * 1e-4 * notional
    frame = pnl_trade_log(
        entry * returns, seed=seed, sizes=sizes, entry_prices=entry, fees=fees
    )
    return SyntheticLog(
        trades=frame,
        prices=None,
        truth={"break_even_added_cost_bps": gross_edge_bps - fee_bps},
    )


def sizing_log(
    seed: int,
    *,
    trades: int = 400,
    signal_return_bps: float = 30.0,
    noise_bps: float = 30.0,
    size_tilt: float = 0.8,
    mean_quantity: float = 100.0,
) -> SyntheticLog:
    """Zero-mean returns; quantity tilts towards the trades that pay.

    A signal u ~ U(-1, 1) is known at entry. Return r = a·u + noise (mean 0),
    quantity = q̄(1 + κu). Fixed-size expectancy is 0; the realised edge
    E[q·P·r] = q̄·P·κ·a/3 comes entirely from sizing.
    """

    rng = np.random.default_rng(seed)
    signal = rng.uniform(-1.0, 1.0, trades)
    returns = (
        signal_return_bps * signal + noise_bps * rng.standard_normal(trades)
    ) * 1e-4
    quantity = mean_quantity * (1.0 + size_tilt * signal)
    entry = np.full(trades, 100.0)
    frame = pnl_trade_log(
        entry * returns, seed=seed, sizes=quantity, entry_prices=entry
    )
    contribution = mean_quantity * 100.0 * size_tilt * signal_return_bps * 1e-4 / 3.0
    return SyntheticLog(
        trades=frame,
        prices=None,
        truth={
            "fixed_size_expectancy": 0.0,
            "sizing_contribution_per_trade": contribution,
        },
    )


def random_walk_bars(
    seed: int,
    *,
    days: int = 120,
    bars_per_day: int = 78,
    minutes_per_bar: int = 5,
    volatility_per_bar: float = 0.001,
    start: str = "2025-01-06",
    instrument: str = "SYN",
) -> pd.DataFrame:
    """Zero-drift geometric random walk on weekday sessions (14:30 UTC open)."""

    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range(start, periods=days, tz="UTC") + SESSION_OPEN_UTC
    session_ns = sessions.as_unit("ns").asi8
    offset_ns = (
        np.arange(bars_per_day, dtype=np.int64) * minutes_per_bar * 60_000_000_000
    )
    stamps = (session_ns[:, None] + offset_ns[None, :]).ravel()
    steps = rng.standard_normal(stamps.size) * volatility_per_bar
    steps -= volatility_per_bar**2 / 2.0  # driftless in price, not in log price
    prices = 100.0 * np.exp(np.cumsum(steps))
    return pd.DataFrame(
        {
            "instrument": instrument,
            "timestamp": _iso(pd.to_datetime(stamps, unit="ns", utc=True)),
            "price": prices,
        }
    )


def timing_log(
    seed: int,
    *,
    trades: int = 200,
    days: int = 120,
    bars_per_day: int = 78,
    entry_candidates: int = 1,
    exit_candidates: int = 1,
    direction_skill: float = 0.0,
    fee: float = 0.0,
) -> SyntheticLog:
    """Swing trades on a random-walk price path with injected timing skill.

    Each trade enters on day d and exits on day d+h (h = 1..5 sessions).
    ``entry_candidates`` = K > 1 injects entry-timing alpha: the entry bar is
    the best of K uniformly drawn bars of the entry day (lowest for a long,
    highest for a short). ``exit_candidates`` does the same for exits.
    ``direction_skill`` = probability that the side is set to the sign of the
    move between the two days' average prices (else a coin flip).
    Fills are at bar prices, so execution is zero.
    """

    rng = np.random.default_rng(seed)
    bars = random_walk_bars(seed + 1_000_003, days=days, bars_per_day=bars_per_day)
    price = bars["price"].to_numpy().reshape(days, bars_per_day)
    stamps = (
        pd.DatetimeIndex(bars["timestamp"])
        .as_unit("ns")
        .asi8.reshape(days, bars_per_day)
    )
    entry_day = rng.integers(0, days - 6, trades)
    exit_day = entry_day + rng.integers(1, 6, trades)
    direction_move = price[exit_day].mean(axis=1) - price[entry_day].mean(axis=1)
    informed = rng.random(trades) < direction_skill
    coin = rng.choice(np.array([1, -1]), trades)
    side = np.where(informed, np.where(direction_move >= 0.0, 1, -1), coin)

    def pick(day: np.ndarray, candidates: int, prefer_low: np.ndarray) -> np.ndarray:
        draws = rng.integers(0, bars_per_day, (trades, candidates))
        values = price[day[:, None], draws]
        best = np.where(prefer_low, values.argmin(axis=1), values.argmax(axis=1))
        return draws[np.arange(trades), best]

    entry_bar = pick(entry_day, entry_candidates, side > 0)
    exit_bar = pick(exit_day, exit_candidates, side < 0)
    entry_price = price[entry_day, entry_bar]
    exit_price = price[exit_day, exit_bar]
    entry_time = pd.to_datetime(stamps[entry_day, entry_bar], unit="ns", utc=True)
    exit_time = pd.to_datetime(stamps[exit_day, exit_bar], unit="ns", utc=True)
    frame = pd.DataFrame(
        {
            "trade_id": [f"T{index:05d}" for index in range(1, trades + 1)],
            "instrument": "SYN",
            "side": np.where(side > 0, "long", "short"),
            "quantity": 100.0,
            "entry_time": _iso(entry_time),
            "entry_price": entry_price,
            "exit_time": _iso(exit_time),
            "exit_price": exit_price,
            "fees": fee,
        }
    )
    return SyntheticLog(
        trades=frame,
        prices=bars,
        truth={
            "entry_candidates": float(entry_candidates),
            "exit_candidates": float(exit_candidates),
            "direction_skill": direction_skill,
        },
    )


def to_strings(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame as the CSV reader would see it (every cell a string)."""

    return frame.map(
        lambda value: f"{value:.10g}" if isinstance(value, float) else str(value)
    )
