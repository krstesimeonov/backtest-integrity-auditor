"""Immutable V1.5H materiality, attribution, uncertainty, and score evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar, cast

from backtest_auditor.implementation_risk.domain.divergence import (
    DivergenceFamily,
    DivergenceObservation,
)
from backtest_auditor.implementation_risk.domain.enums import ComparisonLevel
from backtest_auditor.implementation_risk.domain.scope import (
    EngineRunReference,
    ReconciliationScope,
)
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_decimal,
    normalize_sha256,
    normalize_text,
)


RISK_ASSESSMENT_SCHEMA_VERSION = "1.0"
_T = TypeVar("_T")


class MaterialityClass(StrEnum):
    EXACT_ZERO = "exact_zero"
    BELOW_THRESHOLD = "below_threshold"
    MATERIAL = "material"
    EXTREME = "extreme"


class AssessmentUncertainty(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    NOT_ASSESSED = "not_assessed"


class AttributionStatus(StrEnum):
    SUPPORTED_COOCCURRENCE = "supported_cooccurrence"
    NOT_SUPPORTED = "not_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


def _items(values: Iterable[object], kind: type[_T], field: str) -> tuple[_T, ...]:
    try:
        result = tuple(values)
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable.") from error
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{field} contains an invalid record type.")
    return cast(tuple[_T, ...], result)


def _text(value: object, field: str) -> str:
    return normalize_text(value, field=field, maximum_length=16_384)


@dataclass(frozen=True, slots=True)
class MaterialityRule:
    family: DivergenceFamily
    level: ComparisonLevel
    field: str
    absolute_threshold: Decimal
    extreme_multiple: Decimal
    rationale: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "family", DivergenceFamily(self.family))
            object.__setattr__(self, "level", ComparisonLevel(self.level))
        except (TypeError, ValueError) as error:
            raise ValueError("family and level must be supported values.") from error
        object.__setattr__(self, "field", _text(self.field, "field"))
        object.__setattr__(
            self,
            "absolute_threshold",
            normalize_decimal(
                self.absolute_threshold, field="absolute_threshold", positive=True
            ),
        )
        multiple = normalize_decimal(
            self.extreme_multiple, field="extreme_multiple", positive=True
        )
        if multiple < 1:
            raise ValueError("extreme_multiple must be at least one.")
        object.__setattr__(self, "extreme_multiple", multiple)
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale"))


@dataclass(frozen=True, slots=True)
class FamilyWeight:
    family: DivergenceFamily
    weight: Decimal

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "family", DivergenceFamily(self.family))
        except (TypeError, ValueError) as error:
            raise ValueError("family must be supported.") from error
        object.__setattr__(
            self,
            "weight",
            normalize_decimal(self.weight, field="weight", non_negative=True),
        )


@dataclass(frozen=True, slots=True)
class AttributionRule:
    hypothesis_code: str
    source_family: DivergenceFamily
    target_family: DivergenceFamily
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hypothesis_code", _text(self.hypothesis_code, "hypothesis_code")
        )
        try:
            source = DivergenceFamily(self.source_family)
            target = DivergenceFamily(self.target_family)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "source_family and target_family must be supported."
            ) from error
        if source is target:
            raise ValueError("attribution source and target families must differ.")
        object.__setattr__(self, "source_family", source)
        object.__setattr__(self, "target_family", target)
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale"))


@dataclass(frozen=True, slots=True)
class RiskAssessmentPolicy:
    reconciliation_id: str
    materiality_rules: tuple[MaterialityRule, ...]
    family_weights: tuple[FamilyWeight, ...]
    attribution_rules: tuple[AttributionRule, ...]
    require_complete_evidence_for_score: bool = True
    risk_assessment_schema_version: str = RISK_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_id",
            _text(self.reconciliation_id, "reconciliation_id"),
        )
        rules = _items(self.materiality_rules, MaterialityRule, "materiality_rules")
        keys = tuple((item.family, item.level, item.field) for item in rules)
        if not rules or len(keys) != len(set(keys)):
            raise ValueError("materiality_rules must be non-empty and unique.")
        weights = _items(self.family_weights, FamilyWeight, "family_weights")
        if tuple(item.family for item in weights) != tuple(DivergenceFamily):
            raise ValueError(
                "family_weights must contain every family in canonical order."
            )
        if sum((item.weight for item in weights), Decimal(0)) != Decimal(100):
            raise ValueError("family weights must sum exactly to 100.")
        attributions = _items(
            self.attribution_rules, AttributionRule, "attribution_rules"
        )
        codes = tuple(item.hypothesis_code for item in attributions)
        if len(codes) != len(set(codes)):
            raise ValueError("attribution hypothesis codes must be unique.")
        if not isinstance(self.require_complete_evidence_for_score, bool):
            raise ValueError("require_complete_evidence_for_score must be boolean.")
        if self.risk_assessment_schema_version != RISK_ASSESSMENT_SCHEMA_VERSION:
            raise ValueError(
                f"risk_assessment_schema_version must equal {RISK_ASSESSMENT_SCHEMA_VERSION!r}."
            )
        object.__setattr__(
            self,
            "materiality_rules",
            tuple(
                sorted(
                    rules,
                    key=lambda item: (item.family.value, item.level.value, item.field),
                )
            ),
        )
        object.__setattr__(self, "family_weights", weights)
        object.__setattr__(
            self,
            "attribution_rules",
            tuple(sorted(attributions, key=lambda item: item.hypothesis_code)),
        )


@dataclass(frozen=True, slots=True)
class MaterialityAssessment:
    observation: DivergenceObservation
    absolute_delta: str
    threshold: str
    threshold_ratio: str
    materiality: MaterialityClass

    def __post_init__(self) -> None:
        if not isinstance(self.observation, DivergenceObservation):
            raise ValueError("observation must be a DivergenceObservation.")
        absolute = normalize_decimal(
            self.absolute_delta, field="absolute_delta", non_negative=True
        )
        threshold = normalize_decimal(self.threshold, field="threshold", positive=True)
        ratio = normalize_decimal(
            self.threshold_ratio, field="threshold_ratio", non_negative=True
        )
        if ratio != absolute / threshold:
            raise ValueError("threshold_ratio must equal absolute_delta / threshold.")
        try:
            materiality = MaterialityClass(self.materiality)
        except (TypeError, ValueError) as error:
            raise ValueError("materiality must be supported.") from error
        object.__setattr__(self, "absolute_delta", format(absolute, "f"))
        object.__setattr__(self, "threshold", format(threshold, "f"))
        object.__setattr__(self, "threshold_ratio", format(ratio, "f"))
        object.__setattr__(self, "materiality", materiality)


@dataclass(frozen=True, slots=True)
class FamilyRiskAssessment:
    family: DivergenceFamily
    assessments: tuple[MaterialityAssessment, ...]
    maximum_threshold_ratio: str | None
    score_contribution: str | None

    def __post_init__(self) -> None:
        try:
            family = DivergenceFamily(self.family)
        except (TypeError, ValueError) as error:
            raise ValueError("family must be supported.") from error
        assessments = _items(self.assessments, MaterialityAssessment, "assessments")
        if any(item.observation.family is not family for item in assessments):
            raise ValueError("assessments must belong to the declared family.")
        maximum = (
            None
            if self.maximum_threshold_ratio is None
            else normalize_decimal(
                self.maximum_threshold_ratio,
                field="maximum_threshold_ratio",
                non_negative=True,
            )
        )
        contribution = (
            None
            if self.score_contribution is None
            else normalize_decimal(
                self.score_contribution, field="score_contribution", non_negative=True
            )
        )
        if (maximum is None) != (contribution is None):
            raise ValueError(
                "maximum ratio and contribution must be available together."
            )
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "assessments", assessments)
        object.__setattr__(
            self,
            "maximum_threshold_ratio",
            None if maximum is None else format(maximum, "f"),
        )
        object.__setattr__(
            self,
            "score_contribution",
            None if contribution is None else format(contribution, "f"),
        )


@dataclass(frozen=True, slots=True)
class AttributionAssessment:
    hypothesis_code: str
    source_family: DivergenceFamily
    target_family: DivergenceFamily
    status: AttributionStatus
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hypothesis_code", _text(self.hypothesis_code, "hypothesis_code")
        )
        try:
            source = DivergenceFamily(self.source_family)
            target = DivergenceFamily(self.target_family)
            status = AttributionStatus(self.status)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "attribution assessment values must be supported."
            ) from error
        if source is target:
            raise ValueError("attribution source and target families must differ.")
        object.__setattr__(self, "source_family", source)
        object.__setattr__(self, "target_family", target)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale"))


@dataclass(frozen=True, slots=True)
class CandidateRiskAssessment:
    candidate_run: EngineRunReference
    families: tuple[FamilyRiskAssessment, ...]
    attributions: tuple[AttributionAssessment, ...]
    implementation_risk_score: str | None
    uncertainty: AssessmentUncertainty
    score_withheld_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_run, EngineRunReference):
            raise ValueError("candidate_run must be an EngineRunReference.")
        families = _items(self.families, FamilyRiskAssessment, "families")
        if tuple(item.family for item in families) != tuple(DivergenceFamily):
            raise ValueError("families must contain every family in canonical order.")
        attributions = _items(self.attributions, AttributionAssessment, "attributions")
        if attributions != tuple(
            sorted(attributions, key=lambda item: item.hypothesis_code)
        ):
            raise ValueError("attributions must be in canonical hypothesis order.")
        score = (
            None
            if self.implementation_risk_score is None
            else normalize_decimal(
                self.implementation_risk_score,
                field="implementation_risk_score",
                non_negative=True,
            )
        )
        if score is not None and score > 100:
            raise ValueError("implementation_risk_score must not exceed 100.")
        try:
            uncertainty = AssessmentUncertainty(self.uncertainty)
        except (TypeError, ValueError) as error:
            raise ValueError("uncertainty must be supported.") from error
        reason = (
            None
            if self.score_withheld_reason is None
            else _text(self.score_withheld_reason, "score_withheld_reason")
        )
        assessed_but_missing = (
            score is None and uncertainty is not AssessmentUncertainty.NOT_ASSESSED
        )
        if assessed_but_missing != (reason is not None):
            raise ValueError("a withheld assessed score requires exactly one reason.")
        object.__setattr__(self, "families", families)
        object.__setattr__(self, "attributions", attributions)
        object.__setattr__(
            self,
            "implementation_risk_score",
            None if score is None else format(score, "f"),
        )
        object.__setattr__(self, "uncertainty", uncertainty)
        object.__setattr__(self, "score_withheld_reason", reason)


@dataclass(frozen=True, slots=True)
class ReconciliationRiskAssessment:
    scope: ReconciliationScope
    normalization_plan_sha256: str
    comparison_policy_sha256: str
    measurement_policy_sha256: str
    assessment_policy_sha256: str
    candidates: tuple[CandidateRiskAssessment, ...]
    risk_assessment_schema_version: str = RISK_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ReconciliationScope):
            raise ValueError("scope must be a ReconciliationScope.")
        for name in (
            "normalization_plan_sha256",
            "comparison_policy_sha256",
            "measurement_policy_sha256",
            "assessment_policy_sha256",
        ):
            object.__setattr__(
                self, name, normalize_sha256(getattr(self, name), field=name)
            )
        candidates = _items(self.candidates, CandidateRiskAssessment, "candidates")
        if (
            tuple(item.candidate_run for item in candidates)
            != self.scope.candidate_runs
        ):
            raise ValueError("candidates must follow exact reconciliation scope order.")
        if self.risk_assessment_schema_version != RISK_ASSESSMENT_SCHEMA_VERSION:
            raise ValueError(
                f"risk_assessment_schema_version must equal {RISK_ASSESSMENT_SCHEMA_VERSION!r}."
            )
        object.__setattr__(self, "candidates", candidates)


def risk_policy_to_json(policy: RiskAssessmentPolicy) -> str:
    if not isinstance(policy, RiskAssessmentPolicy):
        raise ValueError("policy must be a RiskAssessmentPolicy.")
    payload = {
        "risk_assessment_schema_version": policy.risk_assessment_schema_version,
        "reconciliation_id": policy.reconciliation_id,
        "require_complete_evidence_for_score": policy.require_complete_evidence_for_score,
        "materiality_rules": [
            {
                "family": item.family.value,
                "level": item.level.value,
                "field": item.field,
                "absolute_threshold": format(item.absolute_threshold, "f"),
                "extreme_multiple": format(item.extreme_multiple, "f"),
                "rationale": item.rationale,
            }
            for item in policy.materiality_rules
        ],
        "family_weights": [
            {"family": item.family.value, "weight": format(item.weight, "f")}
            for item in policy.family_weights
        ],
        "attribution_rules": [
            {
                "hypothesis_code": item.hypothesis_code,
                "source_family": item.source_family.value,
                "target_family": item.target_family.value,
                "rationale": item.rationale,
            }
            for item in policy.attribution_rules
        ],
    }
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def risk_policy_sha256(policy: RiskAssessmentPolicy) -> str:
    return hashlib.sha256(risk_policy_to_json(policy).encode()).hexdigest()


__all__ = [
    "RISK_ASSESSMENT_SCHEMA_VERSION",
    "AssessmentUncertainty",
    "AttributionAssessment",
    "AttributionRule",
    "AttributionStatus",
    "CandidateRiskAssessment",
    "FamilyRiskAssessment",
    "FamilyWeight",
    "MaterialityAssessment",
    "MaterialityClass",
    "MaterialityRule",
    "ReconciliationRiskAssessment",
    "RiskAssessmentPolicy",
    "risk_policy_sha256",
    "risk_policy_to_json",
]
