"""Evidence-bounded V1.5H materiality, attribution, and scoring."""

from decimal import Decimal

from backtest_auditor.implementation_risk.application.risk_assessment_errors import (
    RiskAssessmentError,
    RiskAssessmentErrorCode,
)
from backtest_auditor.implementation_risk.domain import (
    AssessmentUncertainty,
    AttributionAssessment,
    AttributionStatus,
    CandidateDivergence,
    CandidateRiskAssessment,
    DivergenceFamily,
    DivergenceStatus,
    FamilyRiskAssessment,
    MaterialityAssessment,
    MaterialityClass,
    MaterialityRule,
    ComparisonLevel,
    ReconciliationDivergence,
    ReconciliationRiskAssessment,
    RiskAssessmentPolicy,
    risk_policy_sha256,
)


class ImplementationRiskAssessmentService:
    """Interpret explicit divergence evidence without claiming causal proof."""

    def assess(
        self,
        divergence: ReconciliationDivergence,
        policy: RiskAssessmentPolicy,
    ) -> ReconciliationRiskAssessment:
        if not isinstance(divergence, ReconciliationDivergence):
            raise RiskAssessmentError(
                RiskAssessmentErrorCode.INVALID_INPUT,
                "divergence must be a ReconciliationDivergence.",
            )
        if not isinstance(policy, RiskAssessmentPolicy):
            raise RiskAssessmentError(
                RiskAssessmentErrorCode.INVALID_INPUT,
                "policy must be a RiskAssessmentPolicy.",
            )
        if policy.reconciliation_id != divergence.scope.reconciliation_id:
            raise RiskAssessmentError(
                RiskAssessmentErrorCode.SCOPE_MISMATCH,
                "policy reconciliation_id must match the divergence scope.",
            )
        rules = {
            (item.family, item.level, item.field): item
            for item in policy.materiality_rules
        }
        observed = {
            (item.family, observation.level, observation.field)
            for candidate in divergence.candidates
            for item in candidate.families
            for observation in item.observations
        }
        if not observed.issubset(rules):
            raise RiskAssessmentError(
                RiskAssessmentErrorCode.POLICY_MISMATCH,
                "every divergence observation requires an exact materiality rule.",
            )
        weights = {item.family: item.weight for item in policy.family_weights}
        candidates = tuple(
            self._candidate(item, policy, rules, weights)
            for item in divergence.candidates
        )
        return ReconciliationRiskAssessment(
            divergence.scope,
            divergence.normalization_plan_sha256,
            divergence.comparison_policy_sha256,
            divergence.measurement_policy_sha256,
            risk_policy_sha256(policy),
            candidates,
        )

    @staticmethod
    def _candidate(
        candidate: CandidateDivergence,
        policy: RiskAssessmentPolicy,
        rules: dict[tuple[DivergenceFamily, ComparisonLevel, str], MaterialityRule],
        weights: dict[DivergenceFamily, Decimal],
    ) -> CandidateRiskAssessment:
        families: list[FamilyRiskAssessment] = []
        material_by_family: dict[DivergenceFamily, bool] = {}
        incomplete = False
        assessed_count = 0
        total_score = Decimal(0)
        for family in candidate.families:
            assessments: list[MaterialityAssessment] = []
            ratios: list[Decimal] = []
            for observation in family.observations:
                rule = rules[(family.family, observation.level, observation.field)]
                delta = abs(Decimal(observation.decimal_delta))
                ratio = delta / rule.absolute_threshold
                if delta == 0:
                    classification = MaterialityClass.EXACT_ZERO
                elif ratio < 1:
                    classification = MaterialityClass.BELOW_THRESHOLD
                elif ratio >= rule.extreme_multiple:
                    classification = MaterialityClass.EXTREME
                else:
                    classification = MaterialityClass.MATERIAL
                ratios.append(ratio)
                assessments.append(
                    MaterialityAssessment(
                        observation,
                        format(delta, "f"),
                        format(rule.absolute_threshold, "f"),
                        format(ratio, "f"),
                        classification,
                    )
                )
            maximum = max(ratios) if ratios else None
            contribution = (
                None
                if maximum is None
                else weights[family.family] * min(maximum, Decimal(1))
            )
            if contribution is not None:
                total_score += contribution
                assessed_count += 1
            incomplete = incomplete or family.status in {
                DivergenceStatus.PARTIAL,
                DivergenceStatus.UNAVAILABLE,
            }
            material_by_family[family.family] = any(
                item.materiality
                in {MaterialityClass.MATERIAL, MaterialityClass.EXTREME}
                for item in assessments
            )
            families.append(
                FamilyRiskAssessment(
                    family.family,
                    tuple(assessments),
                    None if maximum is None else format(maximum, "f"),
                    None if contribution is None else format(contribution, "f"),
                )
            )
        uncertainty = (
            AssessmentUncertainty.NOT_ASSESSED
            if assessed_count == 0
            else (
                AssessmentUncertainty.HIGH if incomplete else AssessmentUncertainty.LOW
            )
        )
        withheld = None
        score = format(total_score, "f") if assessed_count else None
        if incomplete and assessed_count and policy.require_complete_evidence_for_score:
            score = None
            withheld = (
                "score withheld because selected divergence evidence is incomplete"
            )
        attributions = []
        for attribution_rule in policy.attribution_rules:
            source_available = next(
                item.status is DivergenceStatus.MEASURED
                for item in candidate.families
                if item.family is attribution_rule.source_family
            )
            target_available = next(
                item.status is DivergenceStatus.MEASURED
                for item in candidate.families
                if item.family is attribution_rule.target_family
            )
            if not source_available or not target_available:
                status = AttributionStatus.INSUFFICIENT_EVIDENCE
            elif (
                material_by_family[attribution_rule.source_family]
                and material_by_family[attribution_rule.target_family]
            ):
                status = AttributionStatus.SUPPORTED_COOCCURRENCE
            else:
                status = AttributionStatus.NOT_SUPPORTED
            attributions.append(
                AttributionAssessment(
                    attribution_rule.hypothesis_code,
                    attribution_rule.source_family,
                    attribution_rule.target_family,
                    status,
                    attribution_rule.rationale,
                )
            )
        return CandidateRiskAssessment(
            candidate.candidate_run,
            tuple(families),
            tuple(attributions),
            score,
            uncertainty,
            withheld,
        )


__all__ = ["ImplementationRiskAssessmentService"]
