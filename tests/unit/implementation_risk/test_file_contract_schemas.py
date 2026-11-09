import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backtest_auditor.implementation_risk import (
    CANONICAL_BUNDLE_SCHEMA_FILES,
    CanonicalArtifactFileBundleAdapter,
    CanonicalRunArtifacts,
    build_v1_5d2_service,
    engine_export_envelope_to_json,
    load_canonical_bundle_schema,
)
from scripts.generate_v1_5c_bundle_example import build_example_bundle
from scripts.generate_v1_5d1_engine_export_example import build_example_export


def test_file_contract_schemas_are_valid_and_validate_written_json(
    tmp_path: Path,
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    directory = CanonicalArtifactFileBundleAdapter().write(
        canonical_file_bundle,
        tmp_path / "bundle",
    )
    cases = {
        "canonical_artifact_bundle_manifest_1_0": "manifest.json",
        "canonical_run_specification_1_0": "specification.json",
    }

    assert set(cases).issubset(CANONICAL_BUNDLE_SCHEMA_FILES)
    for schema_name, file_name in cases.items():
        schema = load_canonical_bundle_schema(schema_name)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(
            json.loads((directory / file_name).read_text())
        )


def test_engine_export_envelope_schema_is_valid_and_matches_runtime(
    verified_engine_export,
) -> None:
    schema = load_canonical_bundle_schema("engine_export_envelope_1_0")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        engine_export_envelope_to_json(verified_engine_export.envelope)
    )


def test_file_contract_catalog_contains_all_four_v1_5_contracts() -> None:
    assert set(CANONICAL_BUNDLE_SCHEMA_FILES) == {
        "canonical_artifact_bundle_manifest_1_0",
        "canonical_run_specification_1_0",
        "engine_export_envelope_1_0",
        "engine_adapter_metadata_1_0",
    }


def test_engine_adapter_metadata_schema_matches_d2_examples() -> None:
    schema = load_canonical_bundle_schema("engine_adapter_metadata_1_0")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for engine in ("vectorbt", "bt", "backtrader"):
        metadata = Path(
            "examples/v1_5d2_engine_exports",
            engine,
            "adapter-metadata.json",
        )
        assert metadata.is_file()
        validator.validate(json.loads(metadata.read_text()))


@pytest.mark.parametrize("engine", ("vectorbt", "bt", "backtrader"))
def test_committed_d2_examples_map_without_engine_sdks(engine: str) -> None:
    result = build_v1_5d2_service().adapt(
        Path("examples/v1_5d2_engine_exports", engine)
    )

    assert result.export.engine.value == engine
    assert result.artifacts.run.engine_name == engine


def test_file_contract_schema_catalog_rejects_unknown_name() -> None:
    with pytest.raises(KeyError, match="expected one of"):
        load_canonical_bundle_schema("unknown")


def test_committed_example_matches_domain_bundle() -> None:
    example = Path("examples/v1_5c_canonical_bundle")

    assert CanonicalArtifactFileBundleAdapter().read(example) == build_example_bundle()


def test_committed_engine_export_example_matches_domain_contract() -> None:
    from backtest_auditor.implementation_risk import EngineExportFileBundleAdapter

    example = Path("examples/v1_5d1_engine_export")

    assert EngineExportFileBundleAdapter().read(example) == build_example_export()
