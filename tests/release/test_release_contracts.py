import json
import math
from pathlib import Path

from scripts.release_contracts import _document_matches, _render_json


def _move_ulps(value: float, count: int) -> float:
    for _ in range(count):
        value = math.nextafter(value, math.inf)
    return value


def test_json_contract_accepts_at_most_eight_ulps() -> None:
    path = Path("report.json")
    expected = _render_json({"value": 1.0})

    assert _document_matches(
        path,
        expected,
        _render_json({"value": _move_ulps(1.0, 8)}),
    )
    assert not _document_matches(
        path,
        expected,
        _render_json({"value": _move_ulps(1.0, 9)}),
    )


def test_json_contract_keeps_structure_values_and_formatting_exact() -> None:
    path = Path("report.json")
    expected = _render_json({"count": 1, "label": "stable", "values": [2.0]})

    assert not _document_matches(
        path,
        expected,
        _render_json({"count": 2, "label": "stable", "values": [2.0]}),
    )
    assert not _document_matches(
        path,
        expected,
        json.dumps({"count": 1, "label": "stable", "values": [2.0]}),
    )


def test_non_json_contract_remains_byte_exact() -> None:
    path = Path("report.md")

    assert _document_matches(path, "exact\n", "exact\n")
    assert not _document_matches(path, "exact\n", "changed\n")
