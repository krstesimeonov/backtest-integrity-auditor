"""SPEC W5-J14 deliverable 3: the calibrated decay detectors hold their
false-alarm budget.

For every detector the audit runs, on logs where nothing changes (per-trade
edge SR 0.3, R = N/2 reference trades, N monitored trades, horizon N,
α = 0.05), the share of logs with any alarm must lie within ±1.5 percentage
points of 5 % at N = 400 and N = 1,000 under the calibration null (i.i.d.
normal trades). The same is measured, not asserted, under Student-t(3) and
AR(1) φ = 0.3 trades. 4,000 logs per cell from seed entropy
[31000000, null, N, log], used nowhere else (the table draws from seed
20261102 with (chunk, block) spawn keys, the CALIBRATION.md study from
[20261102, scenario, N, log]). The binomial standard error at 5 % is 0.34 pp,
so a calibrated detector misses the ±1.5 pp band with probability below 1e-4.

Set EDGE_AUDIT_EVIDENCE_DIR to write the measured rates to
detector_calibration.json there (TEST_RESULTS.txt quotes it).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from backtest_auditor.edge_audit.decay import DETECTORS, analyse_decay

pytestmark = pytest.mark.edge_audit_calibration

SHARPE = 0.3
ALPHA = 0.05
TOLERANCE = 0.015
LOGS = 4000
SEED_BASE = 31_000_000
MEASURED: dict[str, dict] = {}


@pytest.fixture(scope="module", autouse=True)
def write_evidence():
    yield
    directory = os.environ.get("EDGE_AUDIT_EVIDENCE_DIR")
    if directory and MEASURED:
        Path(directory).mkdir(parents=True, exist_ok=True)
        path = Path(directory) / "detector_calibration.json"
        path.write_text(json.dumps(MEASURED, indent=2, sort_keys=True) + "\n")


def unit_noise(kind: str, rng: np.random.Generator, size: int) -> np.ndarray:
    if kind == "iid_normal":
        return rng.standard_normal(size)
    scale = math.sqrt(3.0)
    if kind == "student_t3":
        return rng.standard_t(3.0, size) / scale
    shocks = rng.standard_t(3.0, size + 200) / scale
    values = np.empty_like(shocks)
    state = 0.0
    for index, shock in enumerate(shocks):
        state = 0.3 * state + shock
        values[index] = state
    return values[200:] * math.sqrt(1.0 - 0.09)


def wilson(hits: int, count: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = hits / count
    denominator = 1.0 + z * z / count
    centre = (p + z * z / (2 * count)) / denominator
    half = (
        z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    )
    return centre - half, centre + half


def false_alarm_rates(kind: str, horizon: int) -> dict[str, dict]:
    reference = horizon // 2
    total = reference + horizon
    times = tuple(f"t{index}" for index in range(total))
    hits = dict.fromkeys(DETECTORS, 0)
    ran = dict.fromkeys(DETECTORS, 0)
    code = {"iid_normal": 1, "student_t3": 2, "ar1_t3": 3}[kind]
    for log in range(LOGS):
        rng = np.random.default_rng([SEED_BASE, code, horizon, log])
        pnl = SHARPE + unit_noise(kind, rng, total)
        result = analyse_decay(
            pnl,
            times,
            reference_trades=None,
            shift_sigma=None,
            false_alarm_probability=ALPHA,
            horizon=horizon,
            rolling_window=None,
            bootstrap_replications=2,
            mean_block_length=1,
            confidence_level=0.95,
            seed=7,
        )
        if result.status != "computed":
            continue
        assert result.reference_trades == reference and result.horizon == horizon
        for item in result.detectors:
            if item.status != "computed":
                continue
            ran[item.name] += 1
            hits[item.name] += item.alarm_trade_number is not None
    out = {}
    for name in DETECTORS:
        low, high = wilson(hits[name], ran[name])
        out[name] = {
            "logs": ran[name],
            "false_alarms": hits[name],
            "rate": hits[name] / ran[name],
            "wilson95": [low, high],
        }
    return out


@pytest.mark.parametrize("horizon", [400, 1000])
def test_null_false_alarm_rate_is_within_1_5_pp_of_alpha(horizon):
    rates = false_alarm_rates("iid_normal", horizon)
    MEASURED[f"iid_normal/{horizon}"] = rates
    for name, entry in rates.items():
        print(
            f"iid_normal N={horizon} {name}: {entry['false_alarms']}/{entry['logs']} = "
            f"{100 * entry['rate']:.2f} % (Wilson {100 * entry['wilson95'][0]:.2f}-"
            f"{100 * entry['wilson95'][1]:.2f} %)"
        )
    for name, entry in rates.items():
        assert entry["logs"] >= 0.97 * LOGS, (name, entry["logs"])
        assert abs(entry["rate"] - ALPHA) <= TOLERANCE, (name, entry)


@pytest.mark.parametrize("kind", ["student_t3", "ar1_t3"])
@pytest.mark.parametrize("horizon", [400, 1000])
def test_false_alarm_rate_under_the_other_nulls_is_reported(kind, horizon):
    """Measured and printed only: the table is calibrated for i.i.d. normal trades."""

    rates = false_alarm_rates(kind, horizon)
    MEASURED[f"{kind}/{horizon}"] = rates
    for name, entry in rates.items():
        print(
            f"{kind} N={horizon} {name}: {entry['false_alarms']}/{entry['logs']} = "
            f"{100 * entry['rate']:.2f} % (Wilson {100 * entry['wilson95'][0]:.2f}-"
            f"{100 * entry['wilson95'][1]:.2f} %)"
        )
        assert entry["logs"] > 0
