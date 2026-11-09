#!/usr/bin/env python3
"""Two checks CALIBRATION.md quotes besides the main study.

1. Interpolation: at a point between grid values (R = 500, δ = 0.25 or w = 45,
   N = 850, α = 5 %) the interpolated threshold is compared with one simulated
   directly at that point on 40,000 fresh paths (seed 777, not the table's),
   and the share of those paths whose maximum exceeds the interpolated
   threshold is reported (5 % if the interpolation is right).
2. Edge size: the false-alarm rate when nothing changes, with the default
   δ = SR0 estimated from the reference, for edges of SR 0.1 and 0.6 per trade
   (the main study uses 0.3), N = 1,000, R = 500, 2,000 logs each.

    .venv/bin/python docs/edge_audit/calibration/extra_checks.py
writes extra_checks.json next to this file.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from backtest_auditor.edge_audit.decay import DETECTORS, analyse_decay, threshold
from backtest_auditor.edge_audit.decay_calibration import (
    ALPHAS,
    simulate_null_maxima,
    thresholds_from_maxima,
)

HERE = Path(__file__).resolve().parent


def wilson(hits: int, count: int) -> list[float]:
    z = 1.959963984540054
    p = hits / count
    denominator = 1.0 + z * z / count
    centre = (p + z * z / (2 * count)) / denominator
    half = (
        z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    )
    return [centre - half, centre + half]


def interpolation_check() -> dict:
    out = {}
    for name in DETECTORS:
        parameter = 45.0 if name == "rolling_expectancy" else 0.25
        point = dict(
            alpha=0.05, horizon=850, reference_trades=500.0, parameter=parameter
        )
        interpolated = threshold(name, **point)
        maxima = simulate_null_maxima(
            name,
            reference_trades=500.0,
            parameters=(parameter,),
            horizons=(850,),
            paths=40_000,
            seed=777,
        )
        direct = float(thresholds_from_maxima(maxima, ALPHAS)[0, 0, ALPHAS.index(0.05)])
        exceed = int(np.sum(maxima[0, :, 0] > interpolated))
        out[name] = {
            "point": point,
            "interpolated_threshold": interpolated,
            "direct_threshold_fresh_paths": direct,
            "fresh_paths": 40_000,
            "share_above_interpolated": exceed / 40_000,
            "wilson95": wilson(exceed, 40_000),
        }
    return out


def edge_size_check(sharpe: float, logs: int = 2000) -> dict:
    horizon, reference = 1000, 500
    times = tuple(f"t{index}" for index in range(reference + horizon))
    hits = dict.fromkeys(DETECTORS, 0)
    ran = dict.fromkeys(DETECTORS, 0)
    not_run = 0
    for log in range(logs):
        rng = np.random.default_rng([41_000_000, int(sharpe * 100), log])
        pnl = sharpe + rng.standard_normal(reference + horizon)
        result = analyse_decay(
            pnl,
            times,
            reference_trades=None,
            shift_sigma=None,
            false_alarm_probability=0.05,
            horizon=horizon,
            rolling_window=None,
            bootstrap_replications=2,
            mean_block_length=1,
            confidence_level=0.95,
            seed=7,
        )
        if result.status != "computed":
            not_run += 1
            continue
        for item in result.detectors:
            if item.status == "computed":
                ran[item.name] += 1
                hits[item.name] += item.alarm_trade_number is not None
    return {
        "sharpe_per_trade": sharpe,
        "logs": logs,
        "no_reference_edge": not_run,
        "detectors": {
            name: {
                "ran": ran[name],
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
        "interpolation": interpolation_check(),
        "edge_size": [edge_size_check(0.1), edge_size_check(0.6)],
    }
    results["seconds"] = round(time.time() - started, 1)
    path = HERE / "extra_checks.json"
    path.write_text(
        json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name, entry in results["interpolation"].items():
        print(
            f"interpolation {name}: interpolated {entry['interpolated_threshold']:.4f}, "
            f"direct {entry['direct_threshold_fresh_paths']:.4f}, share above "
            f"{100 * entry['share_above_interpolated']:.2f} %"
        )
    for block in results["edge_size"]:
        rates = ", ".join(
            f"{name} {100 * entry['rate']:.2f} % ({entry['false_alarms']}/{entry['ran']})"
            for name, entry in block["detectors"].items()
        )
        print(
            f"edge SR {block['sharpe_per_trade']}: {rates}; not run {block['no_reference_edge']}"
        )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
