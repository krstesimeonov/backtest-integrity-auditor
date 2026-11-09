"""eee64e0's "nothing declared" branch next to 1.4.0's gross/net evidence.

The port makes an undeclared return construction insufficient_evidence
instead of fragile. A misaligned gross/net pair is an observed fact rather
than a declaration, so it must stay adverse in that branch.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _audit(*arguments: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "backtest_auditor.cli", *arguments, "--format", "json"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _return_methodology(payload: dict) -> dict:
    return next(
        item
        for item in payload["evidence_profile"]["dimensions"]
        if item["dimension"] == "return_methodology"
    )


def test_undeclared_run_with_misaligned_gross_returns_stays_fragile(
    tmp_path: Path,
) -> None:
    shifted = tmp_path / "gross_shifted.csv"
    shifted.write_text(
        "timestamp,return\n"
        "2026-01-02,0.0105\n2026-01-03,-0.0045\n2026-01-04,0.0085\n"
        "2026-01-05,0.0035\n2026-01-06,-0.0015\n",
        encoding="utf-8",
    )

    payload = _audit(
        "examples/sample_returns.csv",
        "--run-id",
        "undeclared-misaligned-gross",
        "--gross-returns-csv",
        str(shifted),
    )

    assert payload["return_construction"]["supplied"] is False
    dimension = _return_methodology(payload)
    assert dimension["status"] == "fragile"
    assert dimension["adverse_evidence_codes"] == ["GROSS_NET_TIMESTAMP_MISMATCH"]
    assert "RETURN_CONSTRUCTION_NOT_SUPPLIED" in dimension["unavailable_evidence_codes"]


def test_undeclared_run_with_aligned_gross_returns_is_insufficient() -> None:
    payload = _audit(
        "examples/sample_returns.csv",
        "--run-id",
        "undeclared-aligned-gross",
        "--gross-returns-csv",
        "examples/sample_gross_returns.csv",
    )

    dimension = _return_methodology(payload)
    assert dimension["status"] == "insufficient_evidence"
    assert dimension["adverse_evidence_codes"] == []
