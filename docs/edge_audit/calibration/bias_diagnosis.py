#!/usr/bin/env python3
"""Where does the residual false-alarm bias at N = 1,000 come from?

No-change logs (i.i.d. normal, edge SR 0.3, N = 1,000 monitored trades,
horizon 1,000, α = 5 %), 4,000 logs per setting on fresh seeds:

* grid / declared δ: R = 400 and δ declared as 0.3, both grid values, so the
  threshold is a stored cell (no interpolation) and δ does not depend on the
  reference: the only error left is the table's Monte Carlo error;
* grid / estimated δ: R = 400, δ = SR0 estimated from the same reference
  (the audit's default): adds the coupling between δ and the reference error;
* off-grid / estimated δ: R = 500 (the ±1.5 pp test's geometry): adds the
  interpolation in R.

    .venv/bin/python docs/edge_audit/calibration/bias_diagnosis.py
writes bias_diagnosis.json next to this file.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from backtest_auditor.edge_audit.decay import DETECTORS, analyse_decay

HERE = Path(__file__).resolve().parent
LOGS = 4000
HORIZON = 1000


def wilson(hits: int, count: int) -> list[float]:
    z = 1.959963984540054
    p = hits / count
    denominator = 1.0 + z * z / count
    centre = (p + z * z / (2 * count)) / denominator
    half = (
        z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    )
    return [centre - half, centre + half]


def setting(reference: int, shift: float | None, code: int) -> dict:
    times = tuple(f"t{index}" for index in range(reference + HORIZON))
    hits = dict.fromkeys(DETECTORS, 0)
    ran = dict.fromkeys(DETECTORS, 0)
    for log in range(LOGS):
        rng = np.random.default_rng([51_000_000, code, log])
        pnl = 0.3 + rng.standard_normal(reference + HORIZON)
        result = analyse_decay(
            pnl,
            times,
            reference_trades=reference,
            shift_sigma=shift,
            false_alarm_probability=0.05,
            horizon=HORIZON,
            rolling_window=50,
            bootstrap_replications=2,
            mean_block_length=1,
            confidence_level=0.95,
            seed=7,
        )
        if result.status != "computed":
            continue
        for item in result.detectors:
            if item.status == "computed":
                ran[item.name] += 1
                hits[item.name] += item.alarm_trade_number is not None
    return {
        "reference_trades": reference,
        "shift": "estimated SR0" if shift is None else shift,
        "detectors": {
            name: {
                "logs": ran[name],
                "false_alarms": hits[name],
                "rate": hits[name] / ran[name],
                "wilson95": wilson(hits[name], ran[name]),
            }
            for name in DETECTORS
        },
    }


def main() -> None:
    started = time.time()
    results = {
        "grid_declared": setting(400, 0.3, 1),
        "grid_estimated": setting(400, None, 2),
        "off_grid_estimated": setting(500, None, 3),
    }
    results["seconds"] = round(time.time() - started, 1)
    (HERE / "bias_diagnosis.json").write_text(
        json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    for label, block in results.items():
        if label == "seconds":
            continue
        rates = ", ".join(
            f"{name} {100 * entry['rate']:.2f} % ({entry['false_alarms']}/{entry['logs']}; "
            f"{100 * entry['wilson95'][0]:.2f}-{100 * entry['wilson95'][1]:.2f})"
            for name, entry in block["detectors"].items()
        )
        print(
            f"{label} (R = {block['reference_trades']}, δ = {block['shift']}): {rates}"
        )


if __name__ == "__main__":
    main()
