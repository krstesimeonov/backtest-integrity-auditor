"""The toy strategy every notebook implements, and its independent reference.

One synthetic equity ``SYN`` (USD), 400 weekday bars from 2024-01-02, each
stamped at the 16:00 New York close in UTC (``data/syn_daily.csv``).

Rules:

1. Signal on each close: SMA20 > SMA50 -> +1 (long), else 0 (flat).
2. A deliberate short: for signal sessions 2025-02-06 ... 2025-03-05 the signal
   is -1.
3. One-bar execution lag: the position held at bar t is 100 x signal(t-1)
   shares, changed by one market order filled at the close of bar t.
4. A fixed USD 1.00 commission per fill; USD 100,000 initial cash; no
   slippage, interest or borrow cost.

``lag=0`` is the injected look-ahead defect: the position follows the signal
of the same bar, i.e. the strategy trades on a close it has not seen yet.

This module uses pandas, numpy and ``decimal`` only. It imports neither the
auditor nor any backtest engine, so an engine that agrees with it agrees with
an independent computation. It is adapted from W3-J12's
``tests/e2e/reference.py`` (branch ``wave3/adapter-e2e``): the data path points
next to the notebooks, the price generator, its seed and the command-line
options are removed (the bars are read from the checked-in file), and the
short-window test is a function.
``python toy_strategy.py`` prints the expected fills and round trips.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from pathlib import Path

import pandas as pd

BARS = 400
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
SHORT_FIRST_SIGNAL_SESSION = pd.Timestamp("2025-02-06")
SHORT_LAST_SIGNAL_SESSION = pd.Timestamp("2025-03-05")

PRICES_CSV = Path(__file__).resolve().parent / "data" / "syn_daily.csv"


def load_prices(path: Path = PRICES_CSV) -> pd.DataFrame:
    """The bars as floats, indexed by UTC session-close instants."""

    frame = pd.read_csv(path, dtype={"timestamp": str})
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    frame.index.name = "timestamp"
    return frame.astype(float)


def load_decimal_closes(path: Path = PRICES_CSV) -> pd.Series:
    """The closes as exact ``Decimal`` cents."""

    frame = pd.read_csv(path, dtype=str)
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    return pd.Series([Decimal(item) for item in frame["close"]], index=index)


def in_short_window(sessions: pd.DatetimeIndex) -> pd.Series:
    """True for New York sessions inside the scheduled short window."""

    return (sessions >= SHORT_FIRST_SIGNAL_SESSION) & (
        sessions <= SHORT_LAST_SIGNAL_SESSION
    )


def signals(prices: pd.DataFrame, *, lag: int = EXECUTION_LAG_BARS) -> pd.DataFrame:
    """Moving averages, the signal, and the held quantity for every bar."""

    close = prices["close"]
    fast = close.rolling(FAST).mean()
    slow = close.rolling(SLOW).mean()
    moving_average = (fast > slow).astype(int)
    sessions = close.index.tz_convert(EXCHANGE_TIMEZONE).normalize().tz_localize(None)
    signal = moving_average.where(~in_short_window(sessions), -1)
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
    """The exact fills, round trips and per-bar ledger of the strategy."""

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


if __name__ == "__main__":
    for lag in (EXECUTION_LAG_BARS, 0):
        run = expected_run(lag=lag)
        print(f"## lag={lag}")
        print(run.fills.to_string(index=False))
        print(run.trades.to_string(index=False))
        print("final equity", run.final_equity)
