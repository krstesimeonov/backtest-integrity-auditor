#!/usr/bin/env python3
"""J9's scenario (c) no-change control (seeds 70000-70199, 600 trades, SR 0.3)
through J9's frozen decay code, called directly on the P&L as the harness does.
J9 reported 37/200 = 18.5 % SPRT alarms (scenario_results.json)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_detectors as harness  # noqa: E402
from backtest_auditor.edge_audit.synthetic import decaying_edge_log  # noqa: E402

counts = {"cusum": 0, "page_hinkley": 0, "sprt": 0}
for seed in range(200):
    log = decaying_edge_log(seed + 70_000, trades=600, change_at=600, sharpe_before=0.3)
    pnl = (log.trades["exit_price"] - log.trades["entry_price"]).to_numpy(np.float64)
    result = harness._j9_analyse(pnl)
    for item in result.detectors:
        counts[item.name] += item.alarm_trade_number is not None
print("J9 control seeds 70000-70199, alarms out of 200:", counts)
