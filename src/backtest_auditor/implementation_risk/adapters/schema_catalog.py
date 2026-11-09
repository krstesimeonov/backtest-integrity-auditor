"""Access the JSON Schemas that document the V1.5C hybrid file contract."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


CANONICAL_BUNDLE_SCHEMA_FILES = {
    "canonical_artifact_bundle_manifest_1_0": (
        "canonical-artifact-bundle-manifest-1.0.schema.json"
    ),
    "canonical_run_specification_1_0": ("canonical-run-specification-1.0.schema.json"),
    "engine_export_envelope_1_0": "engine-export-envelope-1.0.schema.json",
    "engine_adapter_metadata_1_0": "engine-adapter-metadata-1.0.schema.json",
}


def load_canonical_bundle_schema(name: str) -> dict[str, Any]:
    """Load one bundled V1.5 file-contract schema by stable catalog name."""

    try:
        file_name = CANONICAL_BUNDLE_SCHEMA_FILES[name]
    except KeyError as error:
        supported = ", ".join(sorted(CANONICAL_BUNDLE_SCHEMA_FILES))
        raise KeyError(
            f"unknown canonical bundle schema {name!r}; expected one of: {supported}."
        ) from error
    resource = files("backtest_auditor.implementation_risk").joinpath(
        "schemas",
        file_name,
    )
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"bundled schema {file_name!r} must be a JSON object.")
    return value
