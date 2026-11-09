"""Immutable V1.5I findings, manifest, and completed-audit contracts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar, cast

from backtest_auditor.implementation_risk.domain.comparison import (
    ReconciliationComparison,
)
from backtest_auditor.implementation_risk.domain.divergence import (
    DivergenceFamily,
    ReconciliationDivergence,
)
from backtest_auditor.implementation_risk.domain.normalization import (
    NormalizedReconciliation,
)
from backtest_auditor.implementation_risk.domain.risk_assessment import (
    ReconciliationRiskAssessment,
)
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_optional_text,
    normalize_sha256,
    normalize_text,
)


IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION = "1.0"
IMPLEMENTATION_RISK_MANIFEST_SCHEMA_VERSION = "1.0"
IMPLEMENTATION_RISK_INTERPRETATION_BOUNDARY = (
    "The report identifies implementation divergence against a declared reference "
    "baseline. It does not establish that any engine is correct, prove causation, "
    "certify strategy skill, or predict future performance."
)
_T = TypeVar("_T")


class ImplementationRiskFindingKind(StrEnum):
    SUPPORTING = "supporting"
    ADVERSE = "adverse"
    EVIDENCE_GAP = "evidence_gap"
    ATTRIBUTION_HYPOTHESIS = "attribution_hypothesis"


def _items(values: Iterable[object], kind: type[_T], field: str) -> tuple[_T, ...]:
    try:
        result = tuple(values)
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable.") from error
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{field} contains an invalid record type.")
    return cast(tuple[_T, ...], result)


def _text(value: object, field: str, maximum: int = 16_384) -> str:
    return normalize_text(value, field=field, maximum_length=maximum)


@dataclass(frozen=True, slots=True)
class ImplementationRiskFinding:
    code: str
    kind: ImplementationRiskFindingKind
    candidate_run_id: str
    summary: str
    evidence_path: str
    limitation: str
    family: DivergenceFamily | None = None
    recommended_action: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _text(self.code, "code", 256))
        object.__setattr__(
            self,
            "candidate_run_id",
            _text(self.candidate_run_id, "candidate_run_id", 128),
        )
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        object.__setattr__(
            self, "evidence_path", _text(self.evidence_path, "evidence_path")
        )
        object.__setattr__(self, "limitation", _text(self.limitation, "limitation"))
        try:
            object.__setattr__(self, "kind", ImplementationRiskFindingKind(self.kind))
            if self.family is not None:
                object.__setattr__(self, "family", DivergenceFamily(self.family))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "finding kind and family must be supported values."
            ) from error
        object.__setattr__(
            self,
            "recommended_action",
            normalize_optional_text(
                self.recommended_action,
                field="recommended_action",
                maximum_length=16_384,
            ),
        )


@dataclass(frozen=True, slots=True)
class ImplementationRiskInputArtifact:
    role: str
    run_id: str
    source_sha256: str
    canonical_bundle_sha256: str

    def __post_init__(self) -> None:
        if self.role not in {"reference", "candidate"}:
            raise ValueError("role must be reference or candidate.")
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id", 128))
        for name in ("source_sha256", "canonical_bundle_sha256"):
            object.__setattr__(
                self, name, normalize_sha256(getattr(self, name), field=name)
            )


@dataclass(frozen=True, slots=True)
class ImplementationRiskMethodVersion:
    name: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "name", 256))
        object.__setattr__(self, "version", _text(self.version, "version", 256))


@dataclass(frozen=True, slots=True)
class ImplementationRiskRunManifest:
    audit_id: str
    audit_timestamp_utc: str
    reconciliation_id: str
    package_version: str
    report_schema_version: str
    git_commit: str
    input_artifacts: tuple[ImplementationRiskInputArtifact, ...]
    normalization_plan_sha256: str
    comparison_policy_sha256: str
    measurement_policy_sha256: str
    assessment_policy_sha256: str
    findings_sha256: str
    method_versions: tuple[ImplementationRiskMethodVersion, ...]
    python_implementation: str
    python_version: str
    platform_system: str
    platform_machine: str
    manifest_sha256: str
    manifest_schema_version: str = IMPLEMENTATION_RISK_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "audit_id",
            "audit_timestamp_utc",
            "reconciliation_id",
            "package_version",
            "report_schema_version",
            "git_commit",
            "python_implementation",
            "python_version",
            "platform_system",
            "platform_machine",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        artifacts = _items(
            self.input_artifacts, ImplementationRiskInputArtifact, "input_artifacts"
        )
        if (
            len(artifacts) < 2
            or artifacts[0].role != "reference"
            or any(item.role != "candidate" for item in artifacts[1:])
        ):
            raise ValueError(
                "input_artifacts must contain one reference followed by candidates."
            )
        methods = _items(
            self.method_versions, ImplementationRiskMethodVersion, "method_versions"
        )
        if methods != tuple(sorted(methods, key=lambda item: item.name)):
            raise ValueError("method_versions must be in canonical name order.")
        for name in (
            "normalization_plan_sha256",
            "comparison_policy_sha256",
            "measurement_policy_sha256",
            "assessment_policy_sha256",
            "findings_sha256",
            "manifest_sha256",
        ):
            object.__setattr__(
                self, name, normalize_sha256(getattr(self, name), field=name)
            )
        if self.report_schema_version != IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION:
            raise ValueError("report_schema_version is not supported.")
        if self.manifest_schema_version != IMPLEMENTATION_RISK_MANIFEST_SCHEMA_VERSION:
            raise ValueError("manifest_schema_version is not supported.")
        object.__setattr__(self, "input_artifacts", artifacts)
        object.__setattr__(self, "method_versions", methods)


@dataclass(frozen=True, slots=True)
class ImplementationRiskAuditResult:
    normalized: NormalizedReconciliation
    comparison: ReconciliationComparison
    divergence: ReconciliationDivergence
    assessment: ReconciliationRiskAssessment
    findings: tuple[ImplementationRiskFinding, ...]
    run_manifest: ImplementationRiskRunManifest | None = None
    report_schema_version: str = IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION
    interpretation_boundary: str = IMPLEMENTATION_RISK_INTERPRETATION_BOUNDARY

    def __post_init__(self) -> None:
        if not isinstance(self.normalized, NormalizedReconciliation):
            raise ValueError("normalized must be a NormalizedReconciliation.")
        if not isinstance(self.comparison, ReconciliationComparison):
            raise ValueError("comparison must be a ReconciliationComparison.")
        if not isinstance(self.divergence, ReconciliationDivergence):
            raise ValueError("divergence must be a ReconciliationDivergence.")
        if not isinstance(self.assessment, ReconciliationRiskAssessment):
            raise ValueError("assessment must be a ReconciliationRiskAssessment.")
        scope = self.normalized.scope
        if not (
            self.comparison.scope
            == self.divergence.scope
            == self.assessment.scope
            == scope
        ):
            raise ValueError("all audit stages must share one exact scope.")
        if not (
            self.normalized.plan_sha256
            == self.comparison.normalization_plan_sha256
            == self.divergence.normalization_plan_sha256
            == self.assessment.normalization_plan_sha256
        ):
            raise ValueError("normalization identities must match across all stages.")
        if not (
            self.comparison.comparison_policy_sha256
            == self.divergence.comparison_policy_sha256
            == self.assessment.comparison_policy_sha256
        ):
            raise ValueError("comparison identities must match across all stages.")
        if (
            self.divergence.measurement_policy_sha256
            != self.assessment.measurement_policy_sha256
        ):
            raise ValueError("measurement identities must match across all stages.")
        findings = _items(self.findings, ImplementationRiskFinding, "findings")
        candidate_ids = {item.run_id for item in scope.candidate_runs}
        if any(item.candidate_run_id not in candidate_ids for item in findings):
            raise ValueError("every finding must reference a scoped candidate.")
        if self.run_manifest is not None and not isinstance(
            self.run_manifest, ImplementationRiskRunManifest
        ):
            raise ValueError("run_manifest must be an implementation-risk manifest.")
        if self.run_manifest is not None:
            manifest = self.run_manifest
            if manifest.reconciliation_id != scope.reconciliation_id or (
                manifest.normalization_plan_sha256,
                manifest.comparison_policy_sha256,
                manifest.measurement_policy_sha256,
                manifest.assessment_policy_sha256,
            ) != (
                self.assessment.normalization_plan_sha256,
                self.assessment.comparison_policy_sha256,
                self.assessment.measurement_policy_sha256,
                self.assessment.assessment_policy_sha256,
            ):
                raise ValueError("run_manifest identities must match the audit result.")
        if self.report_schema_version != IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION:
            raise ValueError("report_schema_version is not supported.")
        if self.interpretation_boundary != IMPLEMENTATION_RISK_INTERPRETATION_BOUNDARY:
            raise ValueError("interpretation_boundary must retain the frozen wording.")
        object.__setattr__(self, "findings", findings)


__all__ = [
    "IMPLEMENTATION_RISK_INTERPRETATION_BOUNDARY",
    "IMPLEMENTATION_RISK_MANIFEST_SCHEMA_VERSION",
    "IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION",
    "ImplementationRiskAuditResult",
    "ImplementationRiskFinding",
    "ImplementationRiskFindingKind",
    "ImplementationRiskInputArtifact",
    "ImplementationRiskMethodVersion",
    "ImplementationRiskRunManifest",
]
