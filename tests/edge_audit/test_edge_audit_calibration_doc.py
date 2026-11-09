"""docs/edge_audit/CALIBRATION.md quotes the study's numbers exactly.

The tables are regenerated from docs/edge_audit/calibration/results_before.json
and results_after.json (written by evaluate_detectors.py) and every one must
appear in CALIBRATION.md verbatim; the four figures must exist.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs" / "edge_audit"
STUDY = DOCS / "calibration"


def load_tables_module():
    spec = importlib.util.spec_from_file_location(
        "edge_audit_report_tables", STUDY / "report_tables.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_every_table_in_calibration_md_matches_the_results():
    tables = load_tables_module()
    document = (DOCS / "CALIBRATION.md").read_text(encoding="utf-8")
    blocks = tables.table_blocks(STUDY)
    assert len(blocks) >= 9
    for block in blocks:
        assert block in document, block.splitlines()[0]


def test_the_study_used_at_least_2000_logs_per_cell_and_both_runs_match():
    before = json.loads((STUDY / "results_before.json").read_text(encoding="utf-8"))
    after = json.loads((STUDY / "results_after.json").read_text(encoding="utf-8"))
    assert before["horizons"] == after["horizons"] == [100, 400, 1000, 4000]
    assert before["seeds_per_scenario"] >= 2000 and after["seeds_per_scenario"] >= 2000
    assert set(before["scenarios"]) == set(after["scenarios"])
    assert all(check["identical"] for check in before["cached_threshold_check"])
    for key, entry in after["scenarios"].items():
        assert entry["logs"] >= 2000, key


def test_one_figure_per_detector():
    for name in ("rolling_expectancy", "cusum", "page_hinkley", "mixture_sprt"):
        figure = DOCS / "figures" / f"{name}.png"
        assert figure.is_file() and figure.stat().st_size > 10_000, figure
        assert f"figures/{name}.png" in (DOCS / "CALIBRATION.md").read_text(
            encoding="utf-8"
        )


def _rates(results, null, names, horizons=(100, 400, 1000, 4000)):
    return [
        100.0 * results["scenarios"][f"{null}/{n}"]["detectors"][name]["rate"]
        for name in names
        for n in horizons
    ]


def _span(values):
    return f"{min(values):.1f}–{max(values):.1f} %"


def test_the_summary_ranges_are_computed_from_the_results():
    before = json.loads((STUDY / "results_before.json").read_text(encoding="utf-8"))
    after = json.loads((STUDY / "results_after.json").read_text(encoding="utf-8"))
    text = " ".join((DOCS / "CALIBRATION.md").read_text(encoding="utf-8").split())
    calibrated = ("rolling_expectancy", "cusum", "page_hinkley", "mixture_sprt")
    expected = [
        _span(_rates(after, "iid_normal", calibrated)),
        _span(_rates(after, "student_t3", calibrated)),
        _span(_rates(after, "ar1_t3", calibrated)),
        _span(_rates(after, "student_t3", ["mixture_sprt"])),
        _span(_rates(after, "ar1_t3", ["mixture_sprt"])),
        _span(_rates(before, "iid_normal", ["cusum", "page_hinkley"])),
        _span(_rates(before, "iid_normal", ["rolling_rule"])),
        _span(_rates(after, "iid_normal", ["rolling_expectancy"])),
        ", ".join(f"{v:.1f}" for v in _rates(before, "iid_normal", ["sprt"])[:3])
        + f" and {_rates(before, 'iid_normal', ['sprt'])[3]:.1f} %",
        ", ".join(f"{v:.1f}" for v in _rates(after, "iid_normal", ["mixture_sprt"])[:3])
        + f" and {_rates(after, 'iid_normal', ['mixture_sprt'])[3]:.1f} %",
    ]
    for fragment in expected:
        assert fragment in text, fragment


def _delay(results, change, name, horizon, key="delay_median"):
    value = results["scenarios"][f"{change}/{horizon}"]["detectors"][name][key]
    return "not reached" if value is None else f"{value:.0f}"


def test_the_prose_numbers_are_computed_from_the_evidence():
    before = json.loads((STUDY / "results_before.json").read_text(encoding="utf-8"))
    after = json.loads((STUDY / "results_after.json").read_text(encoding="utf-8"))
    evidence = DOCS / "job_calibration" / "evidence"
    tests = json.loads((evidence / "detector_calibration.json").read_text())
    extra = json.loads((STUDY / "extra_checks.json").read_text(encoding="utf-8"))
    bias = json.loads((STUDY / "bias_diagnosis.json").read_text(encoding="utf-8"))
    text = " ".join((DOCS / "CALIBRATION.md").read_text(encoding="utf-8").split())
    label = {
        "rolling_expectancy": "rolling expectancy",
        "cusum": "CUSUM",
        "page_hinkley": "Page–Hinkley",
        "mixture_sprt": "mixture SPRT",
    }
    expected = [
        f"the SPRT's median delay at N = 400 is {_delay(after, 'to_zero', 'mixture_sprt', 400)} "
        f"trades instead of {_delay(before, 'to_zero', 'sprt', 400)}",
        "(median "
        + ", ".join(_delay(after, "to_zero", "cusum", n) for n in (400, 1000))
        + f" and {_delay(after, 'to_zero', 'cusum', 4000)} trades at",
        f"CUSUM's median is {_delay(after, 'halving', 'cusum', 1000)} trades and the mixture "
        f"SPRT's {_delay(after, 'halving', 'mixture_sprt', 1000)}",
        f"median {_delay(after, 'to_zero', 'mixture_sprt', 4000)} trades against CUSUM's "
        f"{_delay(after, 'to_zero', 'cusum', 4000)}",
    ]
    for key in ("iid_normal/400", "iid_normal/1000", "student_t3/1000", "ar1_t3/1000"):
        expected += [
            f"{label[name]} {100 * tests[key][name]['rate']:.2f} %" for name in label
        ]
    for name, entry in extra["interpolation"].items():
        expected.append(
            f"{100 * entry['share_above_interpolated']:.2f} % ({label[name]})"
        )
    for block in bias.values():
        if isinstance(block, dict):
            expected += [
                f"{label[name]} {100 * entry['rate']:.2f} %"
                for name, entry in block["detectors"].items()
            ]
    for fragment in expected:
        assert fragment in text, fragment
