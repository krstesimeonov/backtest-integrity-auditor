"""Build the sample audit end to end: synthetic inputs -> edge-audit -> report.

    .venv/bin/python docs/edge_audit/SAMPLE_AUDIT/make_sample.py [OUTPUT_DIR]

Writes OUTPUT_DIR/inputs/{trades,prices}.csv and OUTPUT_DIR/output/edge_audit_report.{json,md}
(default OUTPUT_DIR: this folder). Fully deterministic: re-running reproduces every byte.

The client is synthetic ("Synthetic Swing Trader A"): no real person, account or
instrument. What was planted, so the audit can be checked against it:

* two instruments, ALPHA and BETA, zero-drift random walks (0.1 % per bar),
  30-minute bars, 13 bars per session (14:30-21:00 UTC), 300 sessions from 2025-01-06;
* 420 swing trades held 1-2 sessions, side by coin flip (no directional skill);
* entry skill until session 200: the entry is the best of 6 random bars of the
  entry day (lowest for a long, highest for a short); from session 200 on,
  entries are random bars -> the edge decays (exit-order trades 295-420);
* exits at random bars (no exit skill); quantity log-normal, independent of
  everything (no sizing skill);
* fills 1 bp worse than the bar price on each side (execution cost) and fees
  of 1.5 bps of notional on each side;
* the client declares 12 strategy variants tried (--trials 12).

The four skill/volatility parameters were picked from four tried variants so
that every report section has something to show; the sample demonstrates the
report, it is not calibration evidence (that is tests/edge_audit, TEST_RESULTS).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_auditor.edge_audit.cli import main as edge_audit
from backtest_auditor.edge_audit.schema import PRICES_SCHEMA, TRADES_SCHEMA
from backtest_auditor.edge_audit.synthetic import random_walk_bars, write_csv

SEED = 20251106
SESSIONS = 300
BARS_PER_SESSION = 13
SKILL_UNTIL_SESSION = 200
TRADES = 420
TRIALS = 12
SKILL_PROBABILITY = 1.0
ENTRY_CANDIDATES = 6
VOLATILITY_PER_BAR = 0.001
MAX_HOLD_SESSIONS = 2


def build_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    instruments = ("ALPHA", "BETA")
    bars = {
        name: random_walk_bars(
            SEED + index,
            days=SESSIONS,
            bars_per_day=BARS_PER_SESSION,
            minutes_per_bar=30,
            volatility_per_bar=VOLATILITY_PER_BAR,
            instrument=name,
        )
        for index, name in enumerate(instruments)
    }
    rows = []
    for number in range(1, TRADES + 1):
        name = instruments[int(rng.integers(0, 2))]
        frame = bars[name]
        price = frame["price"].to_numpy().reshape(SESSIONS, BARS_PER_SESSION)
        stamps = pd.DatetimeIndex(frame["timestamp"]).as_unit("ns")
        stamps = stamps.asi8.reshape(SESSIONS, BARS_PER_SESSION)
        entry_day = int(rng.integers(0, SESSIONS - 4))
        exit_day = entry_day + int(rng.integers(1, MAX_HOLD_SESSIONS + 1))
        side = 1 if rng.random() < 0.5 else -1
        skilled = entry_day < SKILL_UNTIL_SESSION and rng.random() < SKILL_PROBABILITY
        if skilled:
            candidates = rng.integers(0, BARS_PER_SESSION, ENTRY_CANDIDATES)
            values = price[entry_day, candidates]
            entry_bar = int(
                candidates[np.argmin(values) if side > 0 else np.argmax(values)]
            )
        else:
            entry_bar = int(rng.integers(0, BARS_PER_SESSION))
        exit_bar = int(rng.integers(0, BARS_PER_SESSION))
        quantity = float(np.round(np.exp(rng.normal(np.log(100.0), 0.4))))
        entry_fill = price[entry_day, entry_bar] * (1.0 + side * 1e-4)
        exit_fill = price[exit_day, exit_bar] * (1.0 - side * 1e-4)
        fees = 1.5e-4 * quantity * (entry_fill + exit_fill)
        rows.append(
            {
                "trade_id": f"SA-{number:04d}",
                "instrument": name,
                "side": "long" if side > 0 else "short",
                "quantity": quantity,
                "entry_time": pd.Timestamp(stamps[entry_day, entry_bar], tz="UTC"),
                "entry_price": round(entry_fill, 4),
                "exit_time": pd.Timestamp(stamps[exit_day, exit_bar], tz="UTC"),
                "exit_price": round(exit_fill, 4),
                "fees": round(fees, 2),
                "currency": "USD",
            }
        )
    trades = pd.DataFrame(rows).sort_values(["exit_time", "entry_time", "trade_id"])
    for column in ("entry_time", "exit_time"):
        trades[column] = trades[column].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    prices = pd.concat([bars[name] for name in instruments], ignore_index=True)
    prices["price"] = prices["price"].round(4)
    return trades.reset_index(drop=True), prices


def build(output_dir: Path) -> int:
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    trades, prices = build_inputs()
    trades_path = write_csv(trades, inputs / "trades.csv", TRADES_SCHEMA)
    prices_path = write_csv(prices, inputs / "prices.csv", PRICES_SCHEMA)
    return edge_audit(
        [
            "run",
            str(trades_path),
            "--trials",
            str(TRIALS),
            "--prices",
            str(prices_path),
            "--out",
            str(output_dir / "output"),
        ]
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    raise SystemExit(build(target))
