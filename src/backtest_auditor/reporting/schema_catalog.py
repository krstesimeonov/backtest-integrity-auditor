"""Access the versioned public JSON Schemas bundled with the package."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


PUBLIC_SCHEMA_FILES = {
    "audit_run_manifest_1_0": "audit-run-manifest-1.0.schema.json",
    "audit_run_manifest_1_1": "audit-run-manifest-1.1.schema.json",
    "evidence_profile_1_0": "evidence-profile-1.0.schema.json",
    "experiment_family_report_2_4": ("experiment-family-report-2.4.schema.json"),
    "experiment_family_report_2_5": ("experiment-family-report-2.5.schema.json"),
    "single_run_report_2_4": "single-run-report-2.4.schema.json",
    "single_run_report_2_5": "single-run-report-2.5.schema.json",
}


def load_public_schema(name: str) -> dict[str, Any]:
    """Load one bundled schema by its stable catalog name."""

    try:
        file_name = PUBLIC_SCHEMA_FILES[name]
    except KeyError as error:
        supported = ", ".join(sorted(PUBLIC_SCHEMA_FILES))
        raise KeyError(
            f"unknown public schema {name!r}; expected one of: {supported}."
        ) from error
    resource = files("backtest_auditor").joinpath("schemas", file_name)
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"bundled schema {file_name!r} must be a JSON object.")
    return value
