"""eee64e0's rule for 1.4.0's advanced-risk availability code.

The statistical dimension listed ADVANCED_DOWNSIDE_TAIL_STATISTICS_AVAILABLE
whenever the advanced-risk result object existed, including its
downside_deviation_zero state, where Sortino and Omega are null. The port's
invariant is that an availability code is never published beside a null value.
"""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]


def _audit(csv: Path) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtest_auditor.cli",
            str(csv),
            "--run-id",
            "advanced-risk-availability",
            "--declared-frequency",
            "D",
            "--periods-per-year",
            "365",
            "--annual-risk-free-rate",
            "0",
            "--benchmark-annualized-sharpe-ratio",
            "0",
            "--required-psr-confidence-level",
            "0.6",
            "--minimum-acceptable-period-return",
            "0",
            "--tail-confidence-level",
            "0.95",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _write(tmp_path: Path, values: list[float]) -> Path:
    path = tmp_path / "returns.csv"
    timestamps = pd.date_range("2026-01-01", periods=len(values), freq="D")
    pd.DataFrame(
        {"timestamp": timestamps.strftime("%Y-%m-%d"), "return": values}
    ).to_csv(path, index=False)
    return path


def _statistical_codes(payload: dict) -> list[str]:
    dimension = next(
        item
        for item in payload["evidence_profile"]["dimensions"]
        if item["dimension"] == "statistical_evidence"
    )
    return dimension["supporting_evidence_codes"]


def test_no_availability_code_when_downside_deviation_is_zero(tmp_path: Path) -> None:
    payload = _audit(_write(tmp_path, [0.001, 0.002, 0.003, 0.0015, 0.0025] * 6))

    advanced = payload["advanced_risk_statistics"]
    assert advanced["status"] == "downside_deviation_zero"
    assert advanced["period_sortino_ratio"] is None
    assert "PSR_CONFIDENCE_REQUIREMENT_MET" in _statistical_codes(payload)
    assert "ADVANCED_DOWNSIDE_TAIL_STATISTICS_AVAILABLE" not in (
        _statistical_codes(payload)
    )


def test_availability_code_when_the_statistics_are_eligible(tmp_path: Path) -> None:
    payload = _audit(_write(tmp_path, [0.004, -0.001, 0.003, 0.002, -0.0005] * 6))

    assert payload["advanced_risk_statistics"]["status"] == "eligible"
    assert "ADVANCED_DOWNSIDE_TAIL_STATISTICS_AVAILABLE" in _statistical_codes(payload)
