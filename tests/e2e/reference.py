"""Independent reference for the end-to-end toy strategy.

Everything here follows ``tests/e2e/strategy_spec.md`` using plain pandas,
numpy and ``decimal`` only. It imports nothing from ``backtest_auditor`` and
nothing from any backtest engine, so an engine test that agrees with it is
agreeing with an independent computation, not with itself.

Run ``python tests/e2e/reference.py`` to print the expected trade list, and
``python tests/e2e/reference.py --write-prices`` to regenerate the checked-in
price file from the seed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261062
BARS = 400
FIRST_SESSION = "2024-01-02"
EXCHANGE_TIMEZONE = "America/New_York"
SESSION_CLOSE = time(16, 0)
INSTRUMENT = "SYN"
CURRENCY = "USD"
FAST = 20
SLOW = 50
QUANTITY = 100
FEE = Decimal("1.00")
INITIAL_CASH = Decimal("100000.00")
EXECUTION_LAG_BARS = 1
# The deliberate short period, as signal sessions (inclusive). It lies inside
# a stretch where the moving-average signal is flat, so the short never meets
# a long position (strategy_spec.md, "Short window").
SHORT_FIRST_SIGNAL_SESSION = pd.Timestamp("2025-02-06")
SHORT_LAST_SIGNAL_SESSION = pd.Timestamp("2025-03-05")

PRICES_CSV = Path(__file__).resolve().parent / "data" / "syn_daily.csv"
PRICE_COLUMNS = ("open", "high", "low", "close")


def generate_prices(seed: int = SEED, bars: int = BARS) -> pd.DataFrame:
    """Daily OHLCV bars from the seed, prices rounded to cents.

    The index is each session's close instant, 16:00 America/New_York, in UTC.
    """

    rng = np.random.default_rng(seed)
    log_returns = rng.normal(0.0004, 0.015, bars)
    gaps = rng.normal(0.0, 0.004, bars)
    high_wicks = np.abs(rng.normal(0.0, 0.005, bars))
    low_wicks = np.abs(rng.normal(0.0, 0.005, bars))
    log_returns[0] = 0.0
    gaps[0] = 0.0
    close = np.round(100.0 * np.exp(np.cumsum(log_returns)), 2)
    previous_close = np.concatenate(([100.0], close[:-1]))
    open_ = np.round(previous_close * np.exp(gaps), 2)
    high = np.round(np.maximum(open_, close) * (1.0 + high_wicks), 2)
    low = np.round(np.minimum(open_, close) * (1.0 - low_wicks), 2)
    sessions = pd.bdate_range(FIRST_SESSION, periods=bars)
    index = session_close_index(sessions)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(bars, 1_000_000.0),
        },
        index=index,
    )


def session_close_index(sessions: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = pd.DatetimeIndex(
        [pd.Timestamp.combine(item.date(), SESSION_CLOSE) for item in sessions]
    ).tz_localize(EXCHANGE_TIMEZONE)
    return local.tz_convert("UTC").rename("timestamp")


def write_prices(path: Path = PRICES_CSV) -> None:
    frame = generate_prices()
    text = frame.copy()
    for column in PRICE_COLUMNS:
        text[column] = text[column].map(lambda value: f"{value:.2f}")
    text["volume"] = text["volume"].map(lambda value: f"{value:.0f}")
    text.index = text.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    text.to_csv(path, lineterminator="\n")


def load_prices(path: Path = PRICES_CSV) -> pd.DataFrame:
    """The checked-in bars as floats, indexed by UTC session-close instants."""

    frame = pd.read_csv(path, dtype={"timestamp": str})
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    frame.index.name = "timestamp"
    return frame.astype(float)


def load_decimal_closes(path: Path = PRICES_CSV) -> pd.Series:
    """The checked-in closes as exact ``Decimal`` cents."""

    frame = pd.read_csv(path, dtype=str)
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    return pd.Series([Decimal(item) for item in frame["close"]], index=index)


def signals(prices: pd.DataFrame, *, lag: int = EXECUTION_LAG_BARS) -> pd.DataFrame:
    """Moving averages, the signal, and the held quantity for every bar.

    ``lag=1`` is the specification. ``lag=0`` is the injected look-ahead
    defect: the position follows a signal that uses the same bar's close.
    """

    close = prices["close"]
    fast = close.rolling(FAST).mean()
    slow = close.rolling(SLOW).mean()
    moving_average = (fast > slow).astype(int)
    sessions = close.index.tz_convert(EXCHANGE_TIMEZONE).normalize().tz_localize(None)
    in_short = (sessions >= SHORT_FIRST_SIGNAL_SESSION) & (
        sessions <= SHORT_LAST_SIGNAL_SESSION
    )
    signal = moving_average.where(~in_short, -1)
    target = (signal.shift(lag).fillna(0).astype(int) * QUANTITY).astype(int)
    return pd.DataFrame(
        {
            "sma_fast": fast,
            "sma_slow": slow,
            "moving_average_signal": moving_average,
            "signal": signal,
            "position": target,
        },
        index=close.index,
    )


@dataclass(frozen=True)
class ExpectedRun:
    fills: pd.DataFrame
    trades: pd.DataFrame
    ledger: pd.DataFrame

    @property
    def final_equity(self) -> Decimal:
        return Decimal(self.ledger["equity"].iloc[-1])


def expected_run(*, lag: int = EXECUTION_LAG_BARS) -> ExpectedRun:
    """The exact fills, round trips and per-bar ledger for the strategy."""

    prices = load_prices()
    closes = load_decimal_closes()
    held = signals(prices, lag=lag)["position"]
    change = held.diff().fillna(held.iloc[0]).astype(int)

    fill_rows = []
    for timestamp, delta in change[change != 0].items():
        if abs(delta) != QUANTITY:
            raise AssertionError(f"position change of {delta} at {timestamp}")
        fill_rows.append(
            {
                "timestamp": timestamp,
                "side": "buy" if delta > 0 else "sell",
                "quantity": Decimal(abs(int(delta))),
                "price": closes[timestamp],
                "fee": FEE,
            }
        )
    fills = pd.DataFrame(fill_rows)

    trade_rows = []
    for opening, closing in zip(fill_rows[0::2], fill_rows[1::2], strict=True):
        direction = "long" if opening["side"] == "buy" else "short"
        sign = Decimal(1) if direction == "long" else Decimal(-1)
        gross = sign * (closing["price"] - opening["price"]) * opening["quantity"]
        trade_rows.append(
            {
                "direction": direction,
                "opened_at": opening["timestamp"],
                "entry_price": opening["price"],
                "closed_at": closing["timestamp"],
                "exit_price": closing["price"],
                "quantity": opening["quantity"],
                "gross_pnl": gross,
                "net_pnl": gross - opening["fee"] - closing["fee"],
            }
        )
    trades = pd.DataFrame(trade_rows)

    cash = INITIAL_CASH
    ledger_rows = []
    for timestamp, quantity in held.items():
        delta = int(change[timestamp])
        if delta:
            cash -= Decimal(delta) * closes[timestamp] + FEE
        ledger_rows.append(
            {
                "timestamp": timestamp,
                "position": int(quantity),
                "close": closes[timestamp],
                "cash": cash,
                "equity": cash + Decimal(int(quantity)) * closes[timestamp],
            }
        )
    ledger = pd.DataFrame(ledger_rows).set_index("timestamp")
    return ExpectedRun(fills=fills, trades=trades, ledger=ledger)


def main(arguments: list[str]) -> None:
    if arguments == ["--write-prices"]:
        write_prices()
        return
    for lag in (EXECUTION_LAG_BARS, 0):
        run = expected_run(lag=lag)
        label = "specification" if lag == EXECUTION_LAG_BARS else "look-ahead defect"
        print(f"## {label} (lag={lag})")
        print(run.fills.to_string(index=False))
        print(run.trades.to_string(index=False))
        print("final equity", run.final_equity)


if __name__ == "__main__":
    main(sys.argv[1:])
