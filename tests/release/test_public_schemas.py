import importlib.metadata
import json
import tomllib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from backtest_auditor.reporting.schema_catalog import (
    PUBLIC_SCHEMA_FILES,
    load_public_schema,
)
import backtest_auditor
from backtest_auditor import PACKAGE_VERSION
from backtest_auditor.reporting import schema_catalog
from scripts.release_contracts import build_runtime_examples


@pytest.fixture(scope="module")
def schemas() -> dict[str, dict]:
    return {name: load_public_schema(name) for name in PUBLIC_SCHEMA_FILES}


@pytest.fixture(scope="module")
def registry(schemas: dict[str, dict]) -> Registry:
    return Registry().with_resources(
        [(schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()]
    )


@pytest.fixture(scope="module")
def examples() -> dict[str, dict]:
    return build_runtime_examples()


def _validate(
    instance: dict,
    schema: dict,
    registry: Registry,
) -> None:
    Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(instance)


def test_every_bundled_schema_is_valid_draft_2020_12(
    schemas: dict[str, dict],
) -> None:
    assert len(schemas) == 7
    assert len({schema["$id"] for schema in schemas.values()}) == 7
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)


def test_runtime_and_distribution_versions_match() -> None:
    """The version has one source, PACKAGE_VERSION; pyproject reads it from there."""
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "version" not in project["project"]
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "backtest_auditor.PACKAGE_VERSION"
    }
    assert backtest_auditor.__version__ == PACKAGE_VERSION
    # The installed distribution's metadata comes from the same constant
    # (stale only if the package was not reinstalled after a version change).
    assert importlib.metadata.version("backtest-integrity-auditor") == PACKAGE_VERSION


def test_complete_and_minimal_reports_validate_against_public_schemas(
    schemas: dict[str, dict],
    registry: Registry,
    examples: dict[str, dict],
) -> None:
    for name in ("single_full", "single_minimal"):
        _validate(
            examples[name],
            schemas["single_run_report_2_5"],
            registry,
        )
    for name in ("family_full", "family_minimal"):
        _validate(
            examples[name],
            schemas["experiment_family_report_2_5"],
            registry,
        )


def test_profiles_and_manifests_validate_as_independent_public_objects(
    schemas: dict[str, dict],
    registry: Registry,
    examples: dict[str, dict],
) -> None:
    for name in ("single_full", "family_full"):
        _validate(
            examples[name]["evidence_profile"],
            schemas["evidence_profile_1_0"],
            registry,
        )
    for name in ("single_manifest", "family_manifest"):
        _validate(
            examples[name],
            schemas["audit_run_manifest_1_1"],
            registry,
        )


def test_report_schema_rejects_unknown_or_missing_top_level_fields(
    schemas: dict[str, dict],
    registry: Registry,
    examples: dict[str, dict],
) -> None:
    unexpected = dict(examples["single_full"], invented_score=99)
    missing = dict(examples["single_full"])
    del missing["schema_version"]

    with pytest.raises(ValidationError):
        _validate(
            unexpected,
            schemas["single_run_report_2_5"],
            registry,
        )
    with pytest.raises(ValidationError):
        _validate(
            missing,
            schemas["single_run_report_2_5"],
            registry,
        )


def test_evidence_and_manifest_constraints_reject_invalid_semantics(
    schemas: dict[str, dict],
    registry: Registry,
    examples: dict[str, dict],
) -> None:
    profile = json.loads(json.dumps(examples["single_full"]["evidence_profile"]))
    profile["dimensions"][0]["status"] = "passed"
    manifest = json.loads(json.dumps(examples["single_manifest"]))
    manifest["manifest_sha256"] = "not-a-sha256"

    with pytest.raises(ValidationError):
        _validate(profile, schemas["evidence_profile_1_0"], registry)
    with pytest.raises(ValidationError):
        _validate(manifest, schemas["audit_run_manifest_1_1"], registry)


def test_complete_golden_reports_are_valid_and_present(
    schemas: dict[str, dict],
    registry: Registry,
) -> None:
    # This test's name promised validity while it checked only that the files
    # existed. The committed goldens are what users compare their own output
    # against, so a golden the published schema rejects would be a contract
    # contradicting itself.
    golden = Path("tests/fixtures/golden")
    for name, schema_name in (
        ("v1_single_run_complete.json", "single_run_report_2_5"),
        ("v1_experiment_family_complete.json", "experiment_family_report_2_5"),
    ):
        report = json.loads((golden / name).read_text(encoding="utf-8"))
        _validate(report, schemas[schema_name], registry)

    for name in ("v1_single_run_complete.md", "v1_experiment_family_complete.md"):
        path = golden / name
        assert path.is_file()
        assert path.stat().st_size > 1_000


def test_schema_catalog_rejects_unknown_name() -> None:
    with pytest.raises(KeyError, match="unknown public schema"):
        load_public_schema("unversioned_report")


def test_schema_catalog_rejects_non_object_bundled_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_directory = tmp_path / "schemas"
    schema_directory.mkdir()
    file_name = PUBLIC_SCHEMA_FILES["single_run_report_2_4"]
    (schema_directory / file_name).write_text("[]", encoding="utf-8")
    monkeypatch.setattr(schema_catalog, "files", lambda _package: tmp_path)

    with pytest.raises(ValueError, match="must be a JSON object"):
        load_public_schema("single_run_report_2_4")
