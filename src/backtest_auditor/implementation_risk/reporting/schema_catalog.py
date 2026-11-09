"""Access the public V1.5I report and manifest schemas."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


IMPLEMENTATION_RISK_SCHEMA_FILES = {
    "implementation_risk_report_1_0": "implementation-risk-report-1.0.schema.json",
    "implementation_risk_run_manifest_1_0": (
        "implementation-risk-run-manifest-1.0.schema.json"
    ),
}


def load_implementation_risk_schema(name: str) -> dict[str, Any]:
    try:
        file_name = IMPLEMENTATION_RISK_SCHEMA_FILES[name]
    except KeyError as error:
        supported = ", ".join(sorted(IMPLEMENTATION_RISK_SCHEMA_FILES))
        raise KeyError(
            f"unknown implementation-risk schema {name!r}; expected one of: {supported}."
        ) from error
    resource = files("backtest_auditor.implementation_risk").joinpath(
        "schemas", file_name
    )
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"bundled schema {file_name!r} must be a JSON object.")
    return value


__all__ = ["IMPLEMENTATION_RISK_SCHEMA_FILES", "load_implementation_risk_schema"]
