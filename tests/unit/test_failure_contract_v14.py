"""The 48731d1 failure contract, carried to the 1.4.0 advanced-risk statistics.

advanced_risk recomputes the compounded wealth path for the Ulcer index. With
the wealth path overflowing float64 that produced a nan which aborted the whole
report; this is what the advanced-risk case below exercises. The Calmar ratio
reads the now-optional performance_path.maximum_drawdown; its `is not None`
guard is for type correctness only, since CAGR is already None whenever the
drawdown is, so the `calmar_ratio is None` assertion does not test that guard.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backtest_auditor.reporting.schema_catalog import (
    PUBLIC_SCHEMA_FILES,
    load_public_schema,
)

REPO = Path(__file__).resolve().parents[2]
OVERFLOW = (
    "timestamp,return\n"
    "2026-01-01,1e308\n2026-01-02,1e308\n2026-01-03,1e308\n2026-01-04,1e308\n"
)


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backtest_auditor.cli", *arguments],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def _validate_single_run_2_5(payload: dict) -> None:
    schemas = [load_public_schema(name) for name in PUBLIC_SCHEMA_FILES]
    registry = Registry().with_resources(
        [(schema["$id"], Resource.from_contents(schema)) for schema in schemas]
    )
    Draft202012Validator(
        load_public_schema("single_run_report_2_5"),
        registry=registry,
    ).validate(payload)


@pytest.mark.parametrize(
    "extra",
    [
        (),
        ("--minimum-acceptable-period-return", "0", "--tail-confidence-level", "0.95"),
    ],
    ids=["no_advanced_risk", "advanced_risk"],
)
def test_overflowing_wealth_path_still_yields_a_valid_2_5_report(
    tmp_path: Path,
    extra: tuple[str, ...],
) -> None:
    path = tmp_path / "overflow.csv"
    path.write_text(OVERFLOW)

    result = _run(str(path), "--run-id", "overflow", "--format", "json", *extra)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    _validate_single_run_2_5(payload)
    if extra:
        advanced = payload["advanced_risk_statistics"]
        assert advanced["ulcer_index"] is None
        assert advanced["calmar_ratio"] is None
