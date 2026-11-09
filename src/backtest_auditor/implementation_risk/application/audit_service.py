"""End-to-end V1.5I orchestration over exported canonical evidence."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict

from backtest_auditor import PACKAGE_VERSION
from backtest_auditor.domain.reproducibility import AuditRunSpec
from backtest_auditor.implementation_risk.application.comparison_service import (
    ReconciliationComparisonService,
)
from backtest_auditor.implementation_risk.application.divergence_service import (
    DivergenceMeasurementService,
)
from backtest_auditor.implementation_risk.application.normalization_service import (
    ReconciliationNormalizationService,
)
from backtest_auditor.implementation_risk.application.ports import (
    CanonicalArtifactBundleIdentity,
)
from backtest_auditor.implementation_risk.application.risk_assessment_service import (
    ImplementationRiskAssessmentService,
)
from backtest_auditor.implementation_risk.domain import (
    AttributionStatus,
    CanonicalRunArtifacts,
    DivergenceFamily,
    DivergenceMeasurementPolicy,
    DivergenceStatus,
    MaterialityClass,
    ReconciliationComparisonPolicy,
    ReconciliationNormalizationPlan,
    ReconciliationScope,
    RiskAssessmentPolicy,
)
from backtest_auditor.implementation_risk.domain.reporting import (
    IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION,
    ImplementationRiskAuditResult,
    ImplementationRiskFinding,
    ImplementationRiskFindingKind,
    ImplementationRiskInputArtifact,
    ImplementationRiskMethodVersion,
    ImplementationRiskRunManifest,
)


_METHOD_VERSIONS = {
    "implementation_risk_comparison": "1.0",
    "implementation_risk_divergence": "1.0",
    "implementation_risk_findings": "1.0",
    "implementation_risk_manifest": "1.0",
    "implementation_risk_normalization": "1.0",
    "implementation_risk_reporting": "1.0",
    "implementation_risk_scoring": "1.0",
}
MAX_IMPLEMENTATION_RISK_CANDIDATES = 32


class ImplementationRiskAuditService:
    """Run normalization through reporting without executing a backtest."""

    def __init__(self, canonical_identity: CanonicalArtifactBundleIdentity) -> None:
        if not isinstance(canonical_identity, CanonicalArtifactBundleIdentity):
            raise ValueError(
                "canonical_identity must implement CanonicalArtifactBundleIdentity."
            )
        self._normalization = ReconciliationNormalizationService(canonical_identity)

    def audit(
        self,
        artifacts: tuple[CanonicalRunArtifacts, ...],
        normalization_plan: ReconciliationNormalizationPlan,
        comparison_policy: ReconciliationComparisonPolicy,
        measurement_policy: DivergenceMeasurementPolicy,
        assessment_policy: RiskAssessmentPolicy,
        *,
        run_manifest_spec: AuditRunSpec | None = None,
    ) -> ImplementationRiskAuditResult:
        try:
            bundles = tuple(artifacts)
        except TypeError as error:
            raise ValueError("artifacts must be an iterable.") from error
        if len(bundles) < 2 or any(
            not isinstance(item, CanonicalRunArtifacts) for item in bundles
        ):
            raise ValueError(
                "artifacts must contain one reference and at least one candidate bundle."
            )
        if len(bundles) - 1 > MAX_IMPLEMENTATION_RISK_CANDIDATES:
            raise ValueError(
                "artifacts exceed the maximum of "
                f"{MAX_IMPLEMENTATION_RISK_CANDIDATES} candidate bundles."
            )
        reconciliation_ids = {
            normalization_plan.reconciliation_id,
            comparison_policy.reconciliation_id,
            measurement_policy.reconciliation_id,
            assessment_policy.reconciliation_id,
        }
        if len(reconciliation_ids) != 1:
            raise ValueError("all implementation-risk policies must share one scope.")
        scope = ReconciliationScope(
            normalization_plan.reconciliation_id,
            bundles[0].run,
            tuple(item.run for item in bundles[1:]),
            tuple(item.level for item in comparison_policy.levels),
        )
        normalized = self._normalization.normalize(scope, bundles, normalization_plan)
        comparison = ReconciliationComparisonService().compare(
            normalized, comparison_policy
        )
        divergence = DivergenceMeasurementService().measure(
            comparison, measurement_policy
        )
        assessment = ImplementationRiskAssessmentService().assess(
            divergence, assessment_policy
        )
        findings = build_implementation_risk_findings(
            comparison, divergence, assessment
        )
        manifest = (
            None
            if run_manifest_spec is None
            else build_implementation_risk_manifest(
                run_manifest_spec, normalized, assessment, findings
            )
        )
        return ImplementationRiskAuditResult(
            normalized,
            comparison,
            divergence,
            assessment,
            findings,
            manifest,
        )


def build_implementation_risk_findings(
    comparison: object,
    divergence: object,
    assessment: object,
) -> tuple[ImplementationRiskFinding, ...]:
    """Project completed evidence into independent, non-verdict findings."""

    from backtest_auditor.implementation_risk.domain import (
        ReconciliationComparison,
        ReconciliationDivergence,
        ReconciliationRiskAssessment,
    )

    if not isinstance(comparison, ReconciliationComparison):
        raise ValueError("comparison must be a ReconciliationComparison.")
    if not isinstance(divergence, ReconciliationDivergence):
        raise ValueError("divergence must be a ReconciliationDivergence.")
    if not isinstance(assessment, ReconciliationRiskAssessment):
        raise ValueError("assessment must be a ReconciliationRiskAssessment.")
    if comparison.scope != divergence.scope or divergence.scope != assessment.scope:
        raise ValueError("finding inputs must share one exact scope.")

    findings: list[ImplementationRiskFinding] = []
    for compared, measured, assessed in zip(
        comparison.candidates,
        divergence.candidates,
        assessment.candidates,
        strict=True,
    ):
        candidate_id = compared.candidate_run.run_id
        for level in compared.levels:
            if level.exact_match is None:
                findings.append(
                    _finding(
                        "IMPLEMENTATION_LEVEL_EVIDENCE_UNAVAILABLE",
                        ImplementationRiskFindingKind.EVIDENCE_GAP,
                        candidate_id,
                        f"{level.level.value} evidence is {level.status.value}.",
                        f"/candidates/{candidate_id}/comparison/{level.level.value}",
                        "No conclusion is available for this comparison level.",
                        action="Supply bilateral canonical evidence for this level.",
                    )
                )
        for family, family_assessment in zip(
            measured.families, assessed.families, strict=True
        ):
            base = f"/candidates/{candidate_id}/families/{family.family.value}"
            if family.status in {
                DivergenceStatus.PARTIAL,
                DivergenceStatus.UNAVAILABLE,
            }:
                findings.append(
                    _finding(
                        "IMPLEMENTATION_FAMILY_EVIDENCE_IMPAIRED",
                        ImplementationRiskFindingKind.EVIDENCE_GAP,
                        candidate_id,
                        f"{family.family.value} evidence is {family.status.value}.",
                        base,
                        "Materiality and scoring are bounded by incomplete evidence.",
                        family=family.family,
                        action="Resolve unavailable, one-sided, ambiguous, or non-numeric evidence.",
                    )
                )
            for index, item in enumerate(family_assessment.assessments):
                materiality = item.materiality
                kind = (
                    ImplementationRiskFindingKind.SUPPORTING
                    if materiality
                    in {MaterialityClass.EXACT_ZERO, MaterialityClass.BELOW_THRESHOLD}
                    else ImplementationRiskFindingKind.ADVERSE
                )
                action = (
                    None
                    if kind is ImplementationRiskFindingKind.SUPPORTING
                    else "Review the canonical records and the declared materiality threshold."
                )
                findings.append(
                    _finding(
                        f"IMPLEMENTATION_DIVERGENCE_{materiality.value.upper()}",
                        kind,
                        candidate_id,
                        (
                            f"{family.family.value} {item.observation.field} divergence "
                            f"is {materiality.value} at {item.threshold_ratio}× threshold."
                        ),
                        f"{base}/assessments/{index}",
                        "The classification is conditional on the supplied field-specific threshold.",
                        family=family.family,
                        action=action,
                    )
                )
        for index, attribution in enumerate(assessed.attributions):
            if attribution.status is AttributionStatus.SUPPORTED_COOCCURRENCE:
                kind = ImplementationRiskFindingKind.ATTRIBUTION_HYPOTHESIS
                action = "Investigate the hypothesis with independent causal evidence."
            elif attribution.status is AttributionStatus.INSUFFICIENT_EVIDENCE:
                kind = ImplementationRiskFindingKind.EVIDENCE_GAP
                action = "Supply complete evidence for both named families."
            else:
                kind = ImplementationRiskFindingKind.SUPPORTING
                action = None
            findings.append(
                _finding(
                    f"IMPLEMENTATION_ATTRIBUTION_{attribution.status.value.upper()}",
                    kind,
                    candidate_id,
                    (
                        f"Attribution hypothesis {attribution.hypothesis_code} is "
                        f"{attribution.status.value}."
                    ),
                    f"/candidates/{candidate_id}/attributions/{index}",
                    "Co-occurrence is not causal proof, and non-support does not disprove causation.",
                    action=action,
                )
            )
        if assessed.score_withheld_reason is not None:
            findings.append(
                _finding(
                    "IMPLEMENTATION_RISK_SCORE_WITHHELD",
                    ImplementationRiskFindingKind.EVIDENCE_GAP,
                    candidate_id,
                    assessed.score_withheld_reason.capitalize() + ".",
                    f"/candidates/{candidate_id}/implementation_risk_score",
                    "No numeric score is reported when the configured evidence requirement fails.",
                    action="Complete the selected evidence before interpreting a score.",
                )
            )
    return tuple(findings)


def _finding(
    code: str,
    kind: ImplementationRiskFindingKind,
    candidate_run_id: str,
    summary: str,
    evidence_path: str,
    limitation: str,
    *,
    family: DivergenceFamily | None = None,
    action: str | None = None,
) -> ImplementationRiskFinding:
    return ImplementationRiskFinding(
        code,
        kind,
        candidate_run_id,
        summary,
        evidence_path,
        limitation,
        family,
        action,
    )


def build_implementation_risk_manifest(
    spec: AuditRunSpec,
    normalized: object,
    assessment: object,
    findings: tuple[ImplementationRiskFinding, ...],
) -> ImplementationRiskRunManifest:
    """Bind source, canonical, policy, environment, and finding identities."""

    from backtest_auditor.implementation_risk.domain import (
        NormalizedReconciliation,
        ReconciliationRiskAssessment,
    )

    if not isinstance(spec, AuditRunSpec):
        raise ValueError("spec must be an AuditRunSpec.")
    if not isinstance(normalized, NormalizedReconciliation):
        raise ValueError("normalized must be a NormalizedReconciliation.")
    if not isinstance(assessment, ReconciliationRiskAssessment):
        raise ValueError("assessment must be a ReconciliationRiskAssessment.")
    if normalized.scope != assessment.scope:
        raise ValueError("manifest inputs must share one exact scope.")
    normalized_findings = tuple(findings)
    if any(
        not isinstance(item, ImplementationRiskFinding) for item in normalized_findings
    ):
        raise ValueError("findings contains an invalid record type.")
    artifacts = tuple(
        ImplementationRiskInputArtifact(
            "reference" if index == 0 else "candidate",
            item.source_run.run_id,
            item.source_run.source_sha256,
            item.canonical_bundle_sha256,
        )
        for index, item in enumerate(normalized.runs)
    )
    methods = tuple(
        ImplementationRiskMethodVersion(name, version)
        for name, version in sorted(_METHOD_VERSIONS.items())
    )
    findings_sha256 = _sha256(
        _canonical_json([_finding_payload(item) for item in normalized_findings])
    )
    timestamp = spec.audit_timestamp.isoformat().replace("+00:00", "Z")
    body = {
        "manifest_schema_version": "1.0",
        "audit_id": spec.audit_id,
        "audit_timestamp_utc": timestamp,
        "reconciliation_id": assessment.scope.reconciliation_id,
        "package_version": PACKAGE_VERSION,
        "report_schema_version": IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION,
        "git_commit": spec.git_commit,
        "input_artifacts": [asdict(item) for item in artifacts],
        "policy_identity": {
            "normalization_plan_sha256": assessment.normalization_plan_sha256,
            "comparison_policy_sha256": assessment.comparison_policy_sha256,
            "measurement_policy_sha256": assessment.measurement_policy_sha256,
            "assessment_policy_sha256": assessment.assessment_policy_sha256,
        },
        "findings_sha256": findings_sha256,
        "method_versions": [asdict(item) for item in methods],
        "environment": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform_system": platform.system(),
            "platform_machine": platform.machine(),
        },
    }
    return ImplementationRiskRunManifest(
        spec.audit_id,
        timestamp,
        assessment.scope.reconciliation_id,
        PACKAGE_VERSION,
        IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION,
        spec.git_commit,
        artifacts,
        assessment.normalization_plan_sha256,
        assessment.comparison_policy_sha256,
        assessment.measurement_policy_sha256,
        assessment.assessment_policy_sha256,
        findings_sha256,
        methods,
        platform.python_implementation(),
        platform.python_version(),
        platform.system(),
        platform.machine(),
        _sha256(_canonical_json(body)),
    )


def _finding_payload(finding: ImplementationRiskFinding) -> dict[str, object]:
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


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "MAX_IMPLEMENTATION_RISK_CANDIDATES",
    "ImplementationRiskAuditService",
    "build_implementation_risk_findings",
    "build_implementation_risk_manifest",
]
