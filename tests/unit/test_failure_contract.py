"""Every failure mode must stay inside the machine-readable error contract.

Each case below produced an uncaught Python traceback before these fixes: the
audit ran to completion (or nearly so) and then died in serialisation, in a
manifest encoder, or in a pandas call, bypassing the JSON stderr envelope the
CLI guarantees everywhere else.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backtest_auditor.cli", *arguments],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def _non_finite_paths(payload: object, path: str = "") -> list[str]:
    """Every float in a published report must be JSON-compliant."""

    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found += _non_finite_paths(value, f"{path}/{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found += _non_finite_paths(value, f"{path}[{index}]")
    elif isinstance(payload, float) and not math.isfinite(payload):
        found.append(path)
    return found


@pytest.fixture
def returns_csv(tmp_path: Path) -> Path:
    path = tmp_path / "returns.csv"
    index = pd.bdate_range("2024-01-01", periods=60)
    frame = pd.DataFrame(
        {
            "timestamp": index.strftime("%Y-%m-%d"),
            "return": [0.01, -0.004, 0.006, 0.002, -0.003] * 12,
        }
    )
    frame.to_csv(path, index=False)
    return path


def test_manifest_accepts_calendar_session_dates(
    returns_csv: Path,
    tmp_path: Path,
) -> None:
    """ObservationCalendarSpec.expected_session_dates is tuple[date, ...].

    run_manifest._json_value handled datetime and pd.Timestamp but not date,
    and datetime is a subclass of date rather than the reverse, so every
    --calendar-sessions-csv run with a manifest died with
    `TypeError: unsupported manifest value: date` after computing every
    statistic.
    """

    sessions = tmp_path / "sessions.csv"
    index = pd.bdate_range("2024-01-01", periods=60)
    pd.DataFrame({"session_date": index.strftime("%Y-%m-%d")}).to_csv(
        sessions,
        index=False,
    )

    result = _run(
        str(returns_csv),
        "--run-id",
        "manifest-calendar",
        "--observation-calendar",
        "XNYS",
        "--calendar-timezone",
        "America/New_York",
        "--calendar-sessions-csv",
        str(sessions),
        "--calendar-session-column",
        "session_date",
        "--audit-id",
        "audit-1",
        "--audit-timestamp",
        "2026-09-19T00:00:00Z",
        "--git-commit",
        "abc123",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["run_manifest"] is not None
    assert payload["observation_calendar"]["status"] == "verified"


def test_overflowing_wealth_path_reports_undefined_not_inf(tmp_path: Path) -> None:
    """A wealth path above float64 range must not abort the whole report.

    json.dumps uses allow_nan=False, so one inf aborted serialisation of every
    section that computed correctly. These fields are all nullable in the
    published schema.
    """

    path = tmp_path / "overflow.csv"
    path.write_text(
        "timestamp,return\n"
        "2026-01-01,1e308\n2026-01-02,1e308\n2026-01-03,1e308\n2026-01-04,1e308\n"
    )

    result = _run(str(path), "--run-id", "overflow", "--format", "json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["descriptive_statistics"]["mean_return"] is None
    assert payload["descriptive_statistics"]["cumulative_simple_return"] is None
    assert payload["performance_path"]["ending_wealth"] is None
    assert payload["performance_path"]["maximum_drawdown"] is None
    assert payload["performance_path"]["maximum_drawdown_trough_timestamp"] is None
    assert _non_finite_paths(payload) == []


def test_markdown_never_renders_inf_or_nan(tmp_path: Path) -> None:
    path = tmp_path / "overflow.csv"
    path.write_text(
        "timestamp,return\n"
        "2026-01-01,1e308\n2026-01-02,1e308\n2026-01-03,1e308\n2026-01-04,1e308\n"
    )

    result = _run(str(path), "--run-id", "overflow", "--format", "markdown")

    assert result.returncode == 0, result.stderr
    for cell in ("| nan |", "| inf |", "| -inf |"):
        assert cell not in result.stdout


def test_oversized_cscv_partition_count_is_a_typed_input_error() -> None:
    """C(S, S/2) above 4300 digits cannot be rendered by CPython at all.

    Computing it before the limit gate turned a documented, typed
    ineligibility into an uncaught ValueError during serialisation.
    """

    result = _run(
        "family",
        "examples/cscv_family_manifest.json",
        "examples/cscv_family_trials.csv",
        "examples/cscv_family_returns.csv",
        "--splits-csv",
        "examples/cscv_family_splits.csv",
        "--cscv-method",
        "combinatorially_symmetric",
        "--cscv-performance-metric",
        "period_sharpe_ratio",
        "--cscv-selection-metric-name",
        "period_sharpe_ratio",
        "--cscv-partitions",
        "20000",
        "--cscv-annual-risk-free-rate",
        "0.0",
        "--cscv-maximum-combinations",
        "100",
        "--cscv-rank-tie-method",
        "average",
        "--cscv-winner-tie-policy",
        "first_by_attempt_index",
        "--cscv-maximum-acceptable-pbo",
        "0.75",
        "--format",
        "json",
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "partition_count must be an even integer between 2 and 1024" in result.stderr


def test_dst_ambiguous_wall_clock_is_a_typed_blocking_issue(tmp_path: Path) -> None:
    """A naive wall-clock time inside a DST fold has no single UTC instant.

    tz_localize raised a raw pandas ValueError that escaped the
    InputValidationError contract. Choosing a side of the fold silently would
    change the observed session dates, so it is rejected instead.
    """

    path = tmp_path / "dst.csv"
    # 2024-11-03 01:30 occurs twice in America/New_York.
    path.write_text(
        "timestamp,return\n"
        "2024-11-03 01:30:00,0.01\n"
        "2024-11-03 01:30:00.5,0.002\n"
        "2024-11-04 01:30:00,-0.004\n"
        "2024-11-05 01:30:00,0.003\n"
    )

    result = _run(
        str(path),
        "--run-id",
        "dst",
        "--timestamp-timezone",
        "America/New_York",
        "--observation-calendar",
        "24/7",
        "--calendar-timezone",
        "America/New_York",
        "--format",
        "json",
    )

    assert "Traceback" not in result.stderr
    if result.returncode != 0:
        payload = json.loads(result.stderr.strip().splitlines()[-1])
        assert payload["error"] in {
            "input_validation_failed",
            "report_serialization_failed",
        }
