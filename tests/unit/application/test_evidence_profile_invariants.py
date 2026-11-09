"""The evidence profile must not contradict the report it summarises.

Each ladder below tested whether a RESULT OBJECT was None rather than whether
the underlying FACT held. The statistics modules return populated result
objects in their ineligible states, so "the object exists" and "the evidence
exists" are different questions, and the profile answered the wrong one. The
profile is the section the report leads with, so a contradiction there is the
most visible failure the tool can have.
"""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

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


def _dimension(payload: dict, name: str) -> dict:
    return next(
        item
        for item in payload["evidence_profile"]["dimensions"]
        if item["dimension"] == name
    )


def _all_codes(dimension: dict) -> set[str]:
    return set(dimension["supporting_evidence_codes"]) | set(
        dimension["adverse_evidence_codes"]
    )


@pytest.fixture
def constant_csv(tmp_path: Path) -> Path:
    path = tmp_path / "constant.csv"
    index = pd.bdate_range("2024-01-01", periods=300)
    pd.DataFrame(
        {"timestamp": index.strftime("%Y-%m-%d"), "return": [0.001] * 300}
    ).to_csv(path, index=False)
    return path


def test_psr_is_not_claimed_available_when_its_value_is_null() -> None:
    payload = _audit(
        "examples/sample_returns.csv",
        "--run-id",
        "psr-null",
        "--declared-frequency",
        "D",
        "--periods-per-year",
        "252",
        "--annual-risk-free-rate",
        "0.0",
    )

    uncertainty = payload.get("sharpe_uncertainty") or {}
    dimension = _dimension(payload, "statistical_evidence")

    if uncertainty.get("probabilistic_sharpe_ratio") is None:
        assert "PROBABILISTIC_SHARPE_RATIO_AVAILABLE" not in _all_codes(dimension)


def test_undeclared_return_construction_is_not_called_fragile() -> None:
    """Nothing declared is not the same as declarations carrying risk flags."""

    payload = _audit(
        "examples/sample_returns.csv",
        "--run-id",
        "no-methodology",
    )

    assert payload["return_construction"]["supplied"] is False
    dimension = _dimension(payload, "return_methodology")
    assert dimension["status"] == "insufficient_evidence"
    assert "Declared" not in dimension["summary"]
    assert "RETURN_CONSTRUCTION_NOT_SUPPLIED" in dimension["unavailable_evidence_codes"]


def test_serial_diagnostic_is_not_claimed_available_when_ineligible(
    constant_csv: Path,
) -> None:
    payload = _audit(
        str(constant_csv),
        "--run-id",
        "serial-ineligible",
        "--periods-per-year",
        "252",
        "--annual-risk-free-rate",
        "0.0",
        "--serial-max-lag",
        "5",
        "--serial-significance-level",
        "0.05",
    )

    assert payload["serial_dependence"]["status"] != "eligible"
    dimension = _dimension(payload, "serial_robustness")
    assert "SERIAL_DIAGNOSTIC_AVAILABLE" not in _all_codes(dimension)
    assert dimension["status"] == "ineligible"


def test_serial_diagnostic_is_still_claimed_when_genuinely_eligible() -> None:
    """The fix must not suppress a legitimately available diagnostic."""

    payload = _audit(
        "examples/sample_returns.csv",
        "--run-id",
        "serial-eligible",
        "--declared-frequency",
        "D",
        "--periods-per-year",
        "252",
        "--annual-risk-free-rate",
        "0.0",
        "--serial-max-lag",
        "1",
        "--serial-significance-level",
        "0.05",
    )

    assert payload["serial_dependence"]["status"] == "eligible"
    dimension = _dimension(payload, "serial_robustness")
    assert "SERIAL_DIAGNOSTIC_AVAILABLE" in _all_codes(dimension)


@pytest.mark.parametrize(
    "arguments",
    [
        ("examples/sample_returns.csv", "--run-id", "inv-1"),
        (
            "examples/sample_returns.csv",
            "--run-id",
            "inv-2",
            "--declared-frequency",
            "D",
            "--periods-per-year",
            "252",
            "--annual-risk-free-rate",
            "0.0",
            "--benchmark-annualized-sharpe-ratio",
            "0.0",
            "--required-psr-confidence-level",
            "0.95",
        ),
        (
            "examples/sample_returns.csv",
            "--run-id",
            "inv-3",
            "--declared-frequency",
            "D",
            "--periods-per-year",
            "252",
            "--annual-risk-free-rate",
            "0.0",
            "--serial-max-lag",
            "1",
            "--serial-significance-level",
            "0.05",
            "--hac-max-lag",
            "1",
            "--hac-kernel",
            "bartlett",
        ),
    ],
)
def test_availability_codes_never_contradict_a_null_value(
    arguments: tuple[str, ...],
) -> None:
    """A dimension may not claim a statistic is available when it is null.

    This is the general invariant behind the three specific ladders above.
    """

    payload = _audit(*arguments)
    claims = {
        "PROBABILISTIC_SHARPE_RATIO_AVAILABLE": (
            (payload.get("sharpe_uncertainty") or {}).get("probabilistic_sharpe_ratio")
        ),
        "HAC_ADJUSTMENT_ELIGIBLE": (
            (payload.get("serial_adjustment") or {}).get(
                "hac_adjusted_annualized_sharpe_ratio"
            )
        ),
    }

    published: set[str] = set()
    for dimension in payload["evidence_profile"]["dimensions"]:
        published |= _all_codes(dimension)

    for code, value in claims.items():
        if code in published:
            assert value is not None, (
                f"{code} is published while its underlying value is null"
            )


def test_overall_status_is_null_by_contract() -> None:
    """No global verdict, ever. The frontend must not invent one."""

    payload = _audit("examples/sample_returns.csv", "--run-id", "no-verdict")
    assert payload["evidence_profile"]["overall_status"] is None
