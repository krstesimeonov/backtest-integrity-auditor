"""pytest plugin for tests/test_findings_disposition.py (not a test module).

Run with ``pytest --collect-only -p _marker_inventory_plugin`` and the
MARKER_INVENTORY environment variable naming an output file. It writes, as
JSON, every collected test's node id with the xfail / skip / skipif markers
pytest applies to it (``item.iter_markers``, so module-level ``pytestmark``,
class marks and aliases such as ``from pytest import mark`` all count), and
every module skipped at collection with its reason (e.g. ``importorskip``).
"""

from __future__ import annotations

import json
import os

_SKIPPED_MODULES: dict[str, str] = {}


def pytest_collectreport(report):
    if report.skipped:
        reason = (
            report.longrepr[2]
            if isinstance(report.longrepr, tuple)
            else str(report.longrepr)
        )
        _SKIPPED_MODULES[report.nodeid] = reason


def pytest_collection_finish(session):
    items = []
    for item in session.items:
        marks = []
        for name in ("xfail", "skip", "skipif"):
            for mark in item.iter_markers(name):
                reason = mark.kwargs.get("reason")
                if reason is None and mark.args and isinstance(mark.args[-1], str):
                    reason = mark.args[-1]
                marks.append(
                    {
                        "name": name,
                        "reason": reason or "",
                        "strict": mark.kwargs.get("strict"),
                    }
                )
        items.append({"nodeid": item.nodeid, "marks": marks})
    with open(os.environ["MARKER_INVENTORY"], "w", encoding="utf-8") as handle:
        json.dump({"items": items, "skipped_modules": _SKIPPED_MODULES}, handle)
