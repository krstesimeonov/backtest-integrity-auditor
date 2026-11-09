import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from backtest_auditor.cli import main
from backtest_auditor.domain.reproducibility import AuditRunSpec
from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditResult,
    ImplementationRiskAuditService,
    ImplementationRiskFindingKind,
    PolicyContractError,
    comparison_policy_from_json,
    comparison_policy_to_json,
    divergence_policy_from_json,
    divergence_policy_to_json,
    implementation_risk_audit_to_dict,
    load_implementation_risk_schema,
    normalization_plan_from_json,
    normalization_plan_to_json,
    parse_policy_json,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_from_json,
    risk_policy_to_json,
)
from backtest_auditor.presentation.streamlit_controller import (
    ImplementationRiskRequest,
    UploadedInput,
    run_implementation_risk_audit,
)
from scripts.generate_v1_5i_report_example import (
    _bundle,
    build_policies,
    generate_example,
)


def _result(*, manifested: bool = True) -> ImplementationRiskAuditResult:
    reference = _bundle(candidate=False)
    candidate = _bundle(candidate=True)
    policies = build_policies(reference, candidate)
    return ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
        (reference, candidate),
        *policies,
        run_manifest_spec=(
            AuditRunSpec(
                "unit-audit",
                datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc),
                "unit-revision",
            )
            if manifested
            else None
        ),
    )


def test_end_to_end_report_preserves_evidence_without_global_verdict() -> None:
    result = _result()
    payload = implementation_risk_audit_to_dict(result)
    candidate = payload["candidates"][0]

    assert candidate["implementation_risk_score"] == "87.5"
    assert candidate["uncertainty"] == "low"
    assert payload["overall_status"] is None
    assert payload["run_manifest"]["report_schema_version"] == "1.0"
    public_manifest = dict(payload["run_manifest"])
    manifest_sha256 = public_manifest.pop("manifest_sha256")
    canonical_manifest = json.dumps(
        public_manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert hashlib.sha256(canonical_manifest.encode()).hexdigest() == manifest_sha256
    canonical_findings = json.dumps(
        payload["findings"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert (
        hashlib.sha256(canonical_findings.encode()).hexdigest()
        == payload["run_manifest"]["findings_sha256"]
    )
    assert [
        item["materiality"]
        for family in candidate["families"]
        for item in family["assessments"]
    ] == [
        "extreme",
        "material",
        "below_threshold",
        "extreme",
    ]
    assert {item.kind for item in result.findings} >= {
        ImplementationRiskFindingKind.ADVERSE,
        ImplementationRiskFindingKind.SUPPORTING,
        ImplementationRiskFindingKind.ATTRIBUTION_HYPOTHESIS,
    }
    assert "Overall status: not produced" in render_implementation_risk_markdown(result)
    assert json.loads(render_implementation_risk_json(result)) == payload


def test_report_and_manifest_validate_against_independent_public_schemas() -> None:
    payload = implementation_risk_audit_to_dict(_result())
    report_schema = load_implementation_risk_schema("implementation_risk_report_1_0")
    manifest_schema = load_implementation_risk_schema(
        "implementation_risk_run_manifest_1_0"
    )
    for schema in (report_schema, manifest_schema):
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resource(
        manifest_schema["$id"], Resource.from_contents(manifest_schema)
    )
    Draft202012Validator(report_schema, registry=registry).validate(payload)
    Draft202012Validator(manifest_schema).validate(payload["run_manifest"])

    invalid = dict(payload, overall_status="passed")
    with pytest.raises(ValidationError):
        Draft202012Validator(report_schema, registry=registry).validate(invalid)


def test_policy_json_round_trips_and_rejects_ambiguous_documents() -> None:
    reference = _bundle(candidate=False)
    candidate = _bundle(candidate=True)
    normalization, comparison, measurement, assessment = build_policies(
        reference, candidate
    )
    payloads = (
        (
            json.loads(normalization_plan_to_json(normalization)),
            normalization_plan_from_json,
            normalization,
        ),
        (
            json.loads(comparison_policy_to_json(comparison)),
            comparison_policy_from_json,
            comparison,
        ),
        (
            json.loads(divergence_policy_to_json(measurement)),
            divergence_policy_from_json,
            measurement,
        ),
        (
            json.loads(risk_policy_to_json(assessment)),
            risk_policy_from_json,
            assessment,
        ),
    )
    for payload, decoder, expected in payloads:
        assert decoder(payload) == expected

    with pytest.raises(PolicyContractError, match="duplicate"):
        parse_policy_json('{"x":1,"x":2}')
    with pytest.raises(PolicyContractError, match="exact canonical"):
        comparison_policy_from_json({**payloads[1][0], "invented": True})
    with pytest.raises(PolicyContractError, match="must be a JSON object"):
        parse_policy_json("[]")


def test_incomplete_candidate_withholds_score_and_generates_gap_findings() -> None:
    reference = _bundle(candidate=False)
    candidate = replace(_bundle(candidate=True), equity=None)
    normalization, comparison, measurement, assessment = build_policies(
        reference, candidate
    )
    result = ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
        (reference, candidate), normalization, comparison, measurement, assessment
    )

    assert result.assessment.candidates[0].implementation_risk_score is None
    assert any(
        item.code == "IMPLEMENTATION_LEVEL_EVIDENCE_UNAVAILABLE"
        for item in result.findings
    )
    assert any(
        item.code == "IMPLEMENTATION_RISK_SCORE_WITHHELD" for item in result.findings
    )
    assert implementation_risk_audit_to_dict(result)["run_manifest"] is None


def test_cli_and_streamlit_controller_run_the_committed_file_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    example = tmp_path / "example"
    generate_example(example)
    output = tmp_path / "cli-report.json"
    arguments = [
        "implementation-risk",
        str(example / "reference-bundle.zip"),
        str(example / "candidate-bundle.zip"),
        "--normalization-plan",
        str(example / "normalization-plan.json"),
        "--comparison-policy",
        str(example / "comparison-policy.json"),
        "--measurement-policy",
        str(example / "measurement-policy.json"),
        "--assessment-policy",
        str(example / "assessment-policy.json"),
        "--output",
        str(output),
    ]
    assert main(arguments) == 0
    assert json.loads(output.read_text())["report_type"] == "implementation_risk"
    assert capsys.readouterr().err == ""

    def upload(name: str) -> UploadedInput:
        path = example / name
        return UploadedInput(path.name, path.read_bytes())

    presentation = run_implementation_risk_audit(
        ImplementationRiskRequest(
            upload("reference-bundle.zip"),
            (upload("candidate-bundle.zip"),),
            upload("normalization-plan.json"),
            upload("comparison-policy.json"),
            upload("measurement-policy.json"),
            upload("assessment-policy.json"),
        )
    )
    assert presentation.reconciliation_id == "v1-5i-example"
    assert presentation.candidate_count == 1
    assert presentation.payload["schema_version"] == "1.0"


def test_fail_closed_validation_paths_are_public_and_stable() -> None:
    result = _result(manifested=False)
    with pytest.raises(ValueError, match="ImplementationRiskAuditResult"):
        implementation_risk_audit_to_dict("bad")
    with pytest.raises(ValueError, match="ImplementationRiskAuditResult"):
        render_implementation_risk_markdown("bad")
    with pytest.raises(KeyError, match="unknown implementation-risk schema"):
        load_implementation_risk_schema("unknown")
    with pytest.raises(ValueError, match="candidate bundle"):
        ImplementationRiskRequest(
            UploadedInput("reference.zip", b"x"),
            (),
            UploadedInput("n.json", b"{}"),
            UploadedInput("c.json", b"{}"),
            UploadedInput("m.json", b"{}"),
            UploadedInput("a.json", b"{}"),
        )
    with pytest.raises(ValueError, match="share one scope"):
        ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
            (_bundle(candidate=False), _bundle(candidate=True)),
            *(
                replace(policy, reconciliation_id="other") if index == 1 else policy
                for index, policy in enumerate(
                    build_policies(_bundle(candidate=False), _bundle(candidate=True))
                )
            ),
        )
    assert result.report_schema_version == "1.0"
