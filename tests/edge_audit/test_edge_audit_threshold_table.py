"""The decay thresholds come from the generated table and nowhere else.

These tests fail if anyone changes a threshold without regenerating the table
(python -m backtest_auditor.edge_audit.decay_calibration --write):

* a number edited in decay_thresholds.py: the content hash no longer matches
  and the audit refuses the table;
* a detector or the null simulation changed in code: re-simulating cells of
  the table (same seed and paths) no longer reproduces the stored text;
* the grid or path count in decay_calibration.py changed: it no longer
  matches the table's;
* a fudge between table and report: the audit's threshold at a grid point is
  not the stored number.
"""

from __future__ import annotations

import importlib
import math
import types

import numpy as np
import pytest

from backtest_auditor.edge_audit import decay, decay_calibration
from backtest_auditor.edge_audit import decay_thresholds as table_module


def test_the_table_loads_and_its_content_hash_matches():
    decay.threshold_table.cache_clear()
    table = decay.threshold_table()
    assert table.values["cusum"].shape == (
        len(table_module.REFERENCE_TRADES),
        len(table_module.PARAMETERS["cusum"]),
        len(table_module.HORIZONS),
        len(table_module.ALPHAS),
    )
    assert np.all(np.isfinite(table.values["cusum"]))


def test_a_hand_edited_threshold_is_refused(monkeypatch):
    edited = types.ModuleType("edited_thresholds")
    for name in dir(table_module):
        setattr(edited, name, getattr(table_module, name))
    text = table_module.THRESHOLDS["cusum"]
    first = text.split()[0]
    edited.THRESHOLDS = dict(table_module.THRESHOLDS)
    edited.THRESHOLDS["cusum"] = text.replace(first, f"{float(first) * 1.01:.6g}", 1)
    real_import = importlib.import_module
    monkeypatch.setattr(
        decay.importlib,
        "import_module",
        lambda name: edited if name == decay.TABLE_MODULE else real_import(name),
    )
    decay.threshold_table.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="edited by hand"):
            decay.threshold_table()
    finally:
        decay.threshold_table.cache_clear()


def test_the_table_was_generated_with_the_current_grid_and_full_path_count():
    assert table_module.ALPHAS == decay_calibration.ALPHAS
    assert table_module.HORIZONS == decay_calibration.HORIZONS
    assert table_module.REFERENCE_TRADES == decay_calibration.REFERENCE_TRADES
    assert table_module.PARAMETERS == decay_calibration.PARAMETERS
    assert table_module.SEED == decay_calibration.SEED
    assert table_module.NULL == decay_calibration.NULL == decay.CALIBRATION_NULL
    assert table_module.PATHS == decay_calibration.PATHS == 40_000
    assert tuple(table_module.THRESHOLDS) == decay.DETECTORS


@pytest.mark.edge_audit_calibration
def test_re_simulated_cells_reproduce_the_stored_table():
    problems = decay_calibration.spot_check(
        decay_calibration.SPOT_CELLS, decay_calibration.SPOT_HORIZONS
    )
    assert problems == [], problems[:5]


def test_a_changed_detector_no_longer_matches_the_table(monkeypatch):
    original = decay.cusum_lower
    monkeypatch.setattr(decay, "cusum_lower", lambda z, k: original(z, k * 1.01))
    problems = decay_calibration.spot_check([("cusum", 50.0)], (30, 50))
    assert problems, "a 1 % change of the CUSUM allowance went unnoticed"


def test_the_audit_reports_the_stored_threshold_at_grid_points():
    table = decay.threshold_table()
    r = list(table_module.REFERENCE_TRADES).index(200.0)
    p = list(table_module.PARAMETERS["cusum"]).index(0.3)
    n = list(table_module.HORIZONS).index(400)
    a = list(table_module.ALPHAS).index(0.05)
    stored = {
        name: float(table.values[name][r, p, n, a]) for name in DETECTORS_AT_SHIFT
    }
    for name, value in stored.items():
        assert (
            decay.threshold(
                name, alpha=0.05, horizon=400, reference_trades=200, parameter=0.3
            )
            == value
        )
    pnl = 0.3 + np.random.default_rng(3).standard_normal(600)
    result = decay.analyse_decay(
        pnl,
        tuple(str(index) for index in range(600)),
        reference_trades=200,
        shift_sigma=0.3,
        false_alarm_probability=0.05,
        horizon=400,
        rolling_window=50,
        bootstrap_replications=2,
        mean_block_length=1,
        confidence_level=0.95,
        seed=1,
    )
    reported = {item.name: item.threshold for item in result.detectors}
    for name, value in stored.items():
        assert reported[name] == value, name
    w = list(table_module.PARAMETERS["rolling_expectancy"]).index(50.0)
    assert reported["rolling_expectancy"] == float(
        table.values["rolling_expectancy"][r, w, n, a]
    )


DETECTORS_AT_SHIFT = ("cusum", "page_hinkley", "mixture_sprt")


def test_interpolation_is_between_neighbours_and_monotone():
    common = dict(alpha=0.05, reference_trades=200.0, parameter=0.3)
    low = decay.threshold("cusum", horizon=400, **common)
    high = decay.threshold("cusum", horizon=500, **common)
    middle = decay.threshold("cusum", horizon=450, **common)
    assert low < middle < high
    # R between grid points (400 and 1000) and R = inf (known μ0, σ0).
    values = [
        decay.threshold(
            "cusum", alpha=0.05, horizon=1000, reference_trades=r, parameter=0.3
        )
        for r in (400.0, 500.0, 1000.0, math.inf)
    ]
    assert values[0] > values[1] > values[2] > values[3]
