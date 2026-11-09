"""Deterministic public serialization of completed V1.5I audit results."""

from __future__ import annotations

import json
from typing import Any

from backtest_auditor.implementation_risk.domain import (
    EngineRunReference,
    RecordComparisonStatus,
)
from backtest_auditor.implementation_risk.domain.reporting import (
    ImplementationRiskAuditResult,
    ImplementationRiskFinding,
    ImplementationRiskRunManifest,
)


def implementation_risk_audit_to_dict(
    result: ImplementationRiskAuditResult,
) -> dict[str, Any]:
    if not isinstance(result, ImplementationRiskAuditResult):
        raise ValueError("result must be an ImplementationRiskAuditResult.")
    scope = result.assessment.scope
    candidates: list[dict[str, Any]] = []
    for compared, measured, assessed in zip(
        result.comparison.candidates,
        result.divergence.candidates,
        result.assessment.candidates,
        strict=True,
    ):
        families = []
        for divergence_family, assessed_family in zip(
            measured.families, assessed.families, strict=True
        ):
            families.append(
                {
                    "family": divergence_family.family.value,
                    "status": divergence_family.status.value,
                    "evidence_counts": {
                        "equal_records": divergence_family.equal_record_count,
                        "non_numeric_differences": divergence_family.non_numeric_difference_count,
                        "one_sided_records": divergence_family.one_sided_record_count,
                        "ambiguous_records": divergence_family.ambiguous_record_count,
                        "unavailable_levels": divergence_family.unavailable_level_count,
                    },
                    "maximum_threshold_ratio": assessed_family.maximum_threshold_ratio,
                    "score_contribution": assessed_family.score_contribution,
                    "assessments": [
                        {
                            "level": item.observation.level.value,
                            "alignment_key": item.observation.alignment_key,
                            "field": item.observation.field,
                            "reference_value": item.observation.reference_value,
                            "candidate_value": item.observation.candidate_value,
                            "decimal_delta": item.observation.decimal_delta,
                            "absolute_delta": item.absolute_delta,
                            "threshold": item.threshold,
                            "threshold_ratio": item.threshold_ratio,
                            "materiality": item.materiality.value,
                        }
                        for item in assessed_family.assessments
                    ],
                }
            )
        candidates.append(
            {
                "candidate_run": _run(compared.candidate_run),
                "comparison_levels": [
                    {
                        "level": level.level.value,
                        "status": level.status.value,
                        "alignment_mode": level.alignment_mode.value,
                        "exact_match": level.exact_match,
                        "record_counts": {
                            status.value: level.count(status)
                            for status in RecordComparisonStatus
                        },
                    }
                    for level in compared.levels
                ],
                "families": families,
                "implementation_risk_score": assessed.implementation_risk_score,
                "uncertainty": assessed.uncertainty.value,
                "score_withheld_reason": assessed.score_withheld_reason,
                "attributions": [
                    {
                        "hypothesis_code": item.hypothesis_code,
                        "source_family": item.source_family.value,
                        "target_family": item.target_family.value,
                        "status": item.status.value,
                        "rationale": item.rationale,
                    }
                    for item in assessed.attributions
                ],
            }
        )
    return {
        "schema_version": result.report_schema_version,
        "report_type": "implementation_risk",
        "interpretation_boundary": result.interpretation_boundary,
        "reconciliation": {
            "reconciliation_id": scope.reconciliation_id,
            "reference_run": _run(scope.reference_run),
            "candidate_runs": [_run(item) for item in scope.candidate_runs],
            "requested_levels": [item.value for item in scope.requested_levels],
        },
        "policy_identity": {
            "normalization_plan_sha256": result.assessment.normalization_plan_sha256,
            "comparison_policy_sha256": result.assessment.comparison_policy_sha256,
            "measurement_policy_sha256": result.assessment.measurement_policy_sha256,
            "assessment_policy_sha256": result.assessment.assessment_policy_sha256,
        },
        "normalization": {
            "runs": [
                {
                    "run_id": item.source_run.run_id,
                    "canonical_bundle_sha256": item.canonical_bundle_sha256,
                    "canonical_frequency": (
                        None
                        if item.canonical_frequency is None
                        else {
                            "frequency_id": item.canonical_frequency.frequency_id,
                            "kind": item.canonical_frequency.kind.value,
                            "interval_microseconds": item.canonical_frequency.interval_microseconds,
                            "calendar": item.canonical_frequency.calendar,
                            "calendar_timezone": item.canonical_frequency.calendar_timezone,
                        }
                    ),
                    "changes": [
                        {
                            "dimension": change.dimension.value,
                            "level": None
                            if change.level is None
                            else change.level.value,
                            "source_value": change.source_value,
                            "normalized_value": change.normalized_value,
                            "rationale": change.rationale,
                        }
                        for change in item.changes
                    ],
                }
                for item in result.normalized.runs
            ]
        },
        "run_manifest": _manifest(result.run_manifest),
        "candidates": candidates,
        "findings": [_finding(item) for item in result.findings],
        "overall_status": None,
    }


def render_implementation_risk_json(result: ImplementationRiskAuditResult) -> str:
    """Render a result as implementation-risk report 1.0 JSON.

    The output is deterministic: sorted keys, two-space indentation, a final
    newline, and no non-finite numbers.
    """

    return (
        json.dumps(
            implementation_risk_audit_to_dict(result),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _run(run: EngineRunReference) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "engine_name": run.engine_name,
        "engine_version": run.engine_version,
        "source_sha256": run.source_sha256,
    }


def _finding(finding: ImplementationRiskFinding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "kind": finding.kind.value,
        "candidate_run_id": finding.candidate_run_id,
        "family": None if finding.family is None else finding.family.value,
        "summary": finding.summary,
        "evidence_path": finding.evidence_path,
        "limitation": finding.limitation,
        "recommended_action": finding.recommended_action,
    }


def _manifest(
    manifest: ImplementationRiskRunManifest | None,
) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        "manifest_schema_version": manifest.manifest_schema_version,
        "audit_id": manifest.audit_id,
        "audit_timestamp_utc": manifest.audit_timestamp_utc,
        "reconciliation_id": manifest.reconciliation_id,
        "package_version": manifest.package_version,
        "report_schema_version": manifest.report_schema_version,
        "git_commit": manifest.git_commit,
        "input_artifacts": [
            {
                "role": item.role,
                "run_id": item.run_id,
                "source_sha256": item.source_sha256,
                "canonical_bundle_sha256": item.canonical_bundle_sha256,
            }
            for item in manifest.input_artifacts
        ],
        "policy_identity": {
            "normalization_plan_sha256": manifest.normalization_plan_sha256,
            "comparison_policy_sha256": manifest.comparison_policy_sha256,
            "measurement_policy_sha256": manifest.measurement_policy_sha256,
            "assessment_policy_sha256": manifest.assessment_policy_sha256,
        },
        "findings_sha256": manifest.findings_sha256,
        "method_versions": [
            {"name": item.name, "version": item.version}
            for item in manifest.method_versions
        ],
        "environment": {
            "python_implementation": manifest.python_implementation,
            "python_version": manifest.python_version,
            "platform_system": manifest.platform_system,
            "platform_machine": manifest.platform_machine,
        },
        "manifest_sha256": manifest.manifest_sha256,
    }


__all__ = [
    "implementation_risk_audit_to_dict",
    "render_implementation_risk_json",
]
