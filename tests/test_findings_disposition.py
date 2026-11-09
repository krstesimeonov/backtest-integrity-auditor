"""FINDINGS_DISPOSITION.md and the strict xfails in tests/ must agree exactly.

The disposition file has a "Fixed" table (markers removed, tests unchanged), the
list of the twelve tests that were strict xfails in 1.5.1, and a "Kept" table
(marker stays, with the verdict). Two independent checks:

- static: the ``@pytest.mark.xfail(...)`` decorators in every test module are
  exactly the kept rows, by finding id and node;
- runtime: a collection-only pytest run (tests/_marker_inventory_plugin.py) lists
  the markers pytest actually applies, so module-level ``pytestmark``, aliases
  and skip markers count, and a renamed test shows up as missing. Each of the
  twelve tests must be collected with no xfail/skip/skipif marker; the only
  xfails are the kept rows. A module skipped at collection for a missing
  optional dependency (statsmodels, arch) excuses its tests.

The F05 row's evidence (the documented sessions-CSV route) is tested here too.
E01 and E02 are the two strict xfails `wave3/adapter-e2e` added in tests/e2e; they
were registered in the Kept table when that branch was merged (W5-J1, MERGE_LOG.md).
(The runtime check was added after the W2-J6 adversarial review hid four fixed
tests from the static check alone.)
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_auditor.cli import main as cli_main

REPO = Path(__file__).resolve().parents[1]
DISPOSITION = REPO / "FINDINGS_DISPOSITION.md"
FINDING_ID = re.compile(r"^(F\d{2}|N\d{2}|E\d{2})\b")


def _table_rows(section: str) -> list[list[str]]:
    text = DISPOSITION.read_text(encoding="utf-8")
    body = text.split(f"## {section}", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in body.splitlines():
        if line.startswith("|") and not set(line) <= set("|- "):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if FINDING_ID.match(cells[0]):
                rows.append(cells)
    return rows


def _strict_xfails() -> set[tuple[str, str]]:
    found = set()
    for path in sorted((REPO / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and ast.unparse(decorator.func) == "pytest.mark.xfail"
                ):
                    continue
                keywords = {k.arg: k.value for k in decorator.keywords}
                strict = keywords.get("strict")
                assert isinstance(strict, ast.Constant) and strict.value is True, (
                    f"{path}::{node.name}: every xfail in this suite is strict"
                )
                reason = ast.literal_eval(keywords["reason"])
                match = FINDING_ID.match(reason)
                assert match, f"{path}::{node.name}: reason must start with an id"
                nodeid = f"{path.relative_to(REPO).as_posix()}::{node.name}"
                found.add((match.group(1), nodeid))
    return found


def test_the_strict_xfails_are_exactly_the_kept_findings():
    kept = {(row[0], row[1].strip("`")) for row in _table_rows("Kept")}
    assert kept == _strict_xfails()
    assert sorted(finding for finding, _ in kept) == [
        "E01",
        "E02",
        "F01",
        "F02",
        "F05",
        "F07",
    ]


def test_no_fixed_finding_keeps_a_marker():
    fixed = {row[0] for row in _table_rows("Fixed")}
    assert fixed == {"N18", "N21", "N13", "N14", "N15", "F06", "F04", "F03"}
    still_marked = {finding for finding, _ in _strict_xfails()} & fixed
    assert not still_marked


def _flipped_tests() -> list[tuple[str, str]]:
    text = DISPOSITION.read_text(encoding="utf-8")
    block = text.split("### The twelve tests that were strict xfails", 1)[1]
    block = block.split("```text", 1)[1].split("```", 1)[0]
    return [tuple(line.split(" ", 1)) for line in block.strip().splitlines()]


def _collected_markers(tmp_path: Path) -> dict:
    output = tmp_path / "markers.json"
    environment = dict(os.environ)
    environment["MARKER_INVENTORY"] = str(output)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "tests"), str(REPO / "src"), environment.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "_marker_inventory_plugin",
            "tests",
        ],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        completed.stdout[-2000:] + completed.stderr[-2000:]
    )
    return json.loads(output.read_text(encoding="utf-8"))


def _excused(nodeid: str, skipped_modules: dict[str, str]) -> bool:
    module = nodeid.split("::", 1)[0]
    reason = skipped_modules.get(module, "")
    return "could not import" in reason


def test_at_runtime_the_flipped_tests_are_collected_and_unmarked(tmp_path):
    inventory = _collected_markers(tmp_path)
    marks = {item["nodeid"]: item["marks"] for item in inventory["items"]}
    flipped = _flipped_tests()
    assert len(flipped) == 12
    fixed = {row[0] for row in _table_rows("Fixed")}
    assert {finding for finding, _ in flipped} == fixed
    problems = []
    for finding, nodeid in flipped:
        if nodeid not in marks:
            if not _excused(nodeid, inventory["skipped_modules"]):
                problems.append(f"{finding} {nodeid}: not collected")
        elif marks[nodeid]:
            problems.append(f"{finding} {nodeid}: marked {marks[nodeid]}")
    assert not problems, problems


def test_at_runtime_the_only_xfails_are_the_kept_rows(tmp_path):
    inventory = _collected_markers(tmp_path)
    kept = {row[1].strip("`"): row[0] for row in _table_rows("Kept")}
    xfails = {}
    for item in inventory["items"]:
        for mark in item["marks"]:
            if mark["name"] == "xfail":
                xfails[item["nodeid"]] = mark
            elif FINDING_ID.match(mark["reason"]):
                raise AssertionError(f"{item['nodeid']} carries {mark}")
    expected = {
        nodeid for nodeid in kept if not _excused(nodeid, inventory["skipped_modules"])
    }
    assert set(xfails) == expected
    for nodeid, mark in xfails.items():
        assert mark["strict"] is True, (nodeid, mark)
        assert mark["reason"].startswith(kept[nodeid]), (nodeid, mark)


def test_f05_a_sessions_csv_without_the_holiday_makes_the_same_series_eligible(
    tmp_path,
):
    """The xfail's series (Presidents' Day missing from 120 business days) with
    a session list that leaves the holiday out: calendar_verified, eligible for
    annualization, Sharpe ratio published, no frequency conflict finding."""

    timestamps = pd.date_range("2024-01-02", periods=120, freq="B").drop(
        pd.Timestamp("2024-02-19")
    )
    returns = 0.01 * np.random.default_rng(2).standard_normal(len(timestamps))
    days = [t.date().isoformat() for t in timestamps]
    pd.DataFrame({"timestamp": days, "return": returns}).to_csv(
        tmp_path / "returns.csv", index=False
    )
    pd.DataFrame({"session": days}).to_csv(tmp_path / "sessions.csv", index=False)
    output = tmp_path / "report.json"
    code = cli_main(
        [
            str(tmp_path / "returns.csv"),
            "--run-id",
            "f05",
            "--declared-frequency",
            "B",
            "--periods-per-year",
            "252",
            "--annual-risk-free-rate",
            "0.0",
            "--observation-calendar",
            "XNYS",
            "--calendar-timezone",
            "America/New_York",
            "--calendar-sessions-csv",
            str(tmp_path / "sessions.csv"),
            "--calendar-session-column",
            "session",
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )
    assert code == 0
    report = json.loads(output.read_text())
    assert report["observation_calendar"]["status"] == "verified"
    assert report["sampling_assessment"]["status"] == "calendar_verified"
    assert report["sampling_assessment"]["annualization_eligible"] is True
    assert report["annualized_statistics"]["annualized_sharpe_ratio"] is not None
    codes = {finding["code"] for finding in report["findings"]}
    assert "DECLARED_FREQUENCY_CONFLICT" not in codes
    assert "PERIODS_PER_YEAR_SAMPLING_MISMATCH" not in codes
