from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditService,
    comparison_policy_from_json,
    divergence_policy_from_json,
    load_implementation_risk_schema,
    load_policy_json_file,
    normalization_plan_from_json,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_from_json,
)


ROOT = Path("tests/fixtures/v1_5j_golden")
CASE_NAMES = ("exact", "divergent", "incomplete")


def _audit(case_name: str):
    case = ROOT / case_name
    adapter = CanonicalArtifactFileBundleAdapter()
    return ImplementationRiskAuditService(adapter).audit(
        (
            adapter.read(case / "reference-bundle.zip"),
            adapter.read(case / "candidate-bundle.zip"),
        ),
        normalization_plan_from_json(
            load_policy_json_file(case / "normalization-plan.json")
        ),
        comparison_policy_from_json(
            load_policy_json_file(case / "comparison-policy.json")
        ),
        divergence_policy_from_json(
            load_policy_json_file(case / "measurement-policy.json")
        ),
        risk_policy_from_json(load_policy_json_file(case / "assessment-policy.json")),
    )


def test_golden_sha256_index_is_complete_and_exact() -> None:
    indexed: dict[Path, str] = {}
    for line in (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        indexed[Path(relative)] = digest
    actual = {
        item.relative_to(ROOT)
        for item in ROOT.rglob("*")
        if item.is_file() and item.name != "SHA256SUMS"
    }

    assert set(indexed) == actual
    for relative, expected in indexed.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("case_name", CASE_NAMES)
def test_golden_json_and_markdown_reproduce_byte_for_byte(case_name: str) -> None:
    case = ROOT / case_name
    result = _audit(case_name)

    assert (
        render_implementation_risk_json(result).encode()
        == (case / "report.json").read_bytes()
    )
    assert (
        render_implementation_risk_markdown(result).encode()
        == (case / "report.md").read_bytes()
    )


@pytest.mark.parametrize("case_name", CASE_NAMES)
def test_golden_report_validates_and_retains_non_verdict_boundary(
    case_name: str,
) -> None:
    report_schema = load_implementation_risk_schema("implementation_risk_report_1_0")
    manifest_schema = load_implementation_risk_schema(
        "implementation_risk_run_manifest_1_0"
    )
    registry = Registry().with_resource(
        manifest_schema["$id"], Resource.from_contents(manifest_schema)
    )
    report = json.loads((ROOT / case_name / "report.json").read_text(encoding="utf-8"))

    Draft202012Validator(report_schema, registry=registry).validate(report)
    assert report["overall_status"] is None
    assert report["run_manifest"] is None
    assert (
        "does not establish that any engine is correct"
        in (report["interpretation_boundary"])
    )
