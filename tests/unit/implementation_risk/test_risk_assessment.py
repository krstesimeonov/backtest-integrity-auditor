from dataclasses import replace
from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk.application.risk_assessment_errors import (
    RiskAssessmentError,
    RiskAssessmentErrorCode,
)
from backtest_auditor.implementation_risk.application.risk_assessment_service import (
    ImplementationRiskAssessmentService,
)
from backtest_auditor.implementation_risk.domain import (
    AssessmentUncertainty,
    AttributionRule,
    AttributionStatus,
    CandidateDivergence,
    ComparisonLevel,
    DivergenceFamily,
    DivergenceObservation,
    DivergenceStatus,
    EngineRunReference,
    FamilyDivergence,
    FamilyRiskAssessment,
    FamilyWeight,
    MaterialityClass,
    MaterialityRule,
    ReconciliationDivergence,
    ReconciliationScope,
    RiskAssessmentPolicy,
    risk_policy_sha256,
    risk_policy_to_json,
)


def _family(
    family: DivergenceFamily,
    level: ComparisonLevel,
    field: str,
    delta: str,
    status: DivergenceStatus = DivergenceStatus.MEASURED,
) -> FamilyDivergence:
    observation = DivergenceObservation(
        family, level, f"{family.value}-key", field, "reference", "candidate", delta
    )
    return FamilyDivergence(family, status, (observation,), 0, 0, 0, 0, 0)


def _divergence() -> ReconciliationDivergence:
    reference = EngineRunReference("reference", "engine-a", "1", "a" * 64)
    candidate = EngineRunReference("candidate", "engine-b", "1", "b" * 64)
    scope = ReconciliationScope(
        "reconciliation-h",
        reference,
        (candidate,),
        (
            ComparisonLevel.ORDER,
            ComparisonLevel.COST,
            ComparisonLevel.EQUITY,
            ComparisonLevel.RETURN,
        ),
    )
    families = (
        _family(
            DivergenceFamily.TRANSACTION_COST, ComparisonLevel.COST, "amount", "0.25"
        ),
        _family(DivergenceFamily.SIZING, ComparisonLevel.ORDER, "quantity", "2"),
        _family(
            DivergenceFamily.ACCOUNTING, ComparisonLevel.EQUITY, "total_equity", "-2.5"
        ),
        _family(DivergenceFamily.RETURN, ComparisonLevel.RETURN, "value", "-0.000025"),
    )
    return ReconciliationDivergence(
        scope, "c" * 64, "d" * 64, "e" * 64, (CandidateDivergence(candidate, families),)
    )


def _policy(*, complete: bool = True) -> RiskAssessmentPolicy:
    return RiskAssessmentPolicy(
        "reconciliation-h",
        (
            MaterialityRule(
                DivergenceFamily.TRANSACTION_COST,
                ComparisonLevel.COST,
                "amount",
                Decimal("0.1"),
                Decimal(2),
                "Cost threshold.",
            ),
            MaterialityRule(
                DivergenceFamily.SIZING,
                ComparisonLevel.ORDER,
                "quantity",
                Decimal(1),
                Decimal(3),
                "Sizing threshold.",
            ),
            MaterialityRule(
                DivergenceFamily.ACCOUNTING,
                ComparisonLevel.EQUITY,
                "total_equity",
                Decimal(5),
                Decimal(2),
                "Equity threshold.",
            ),
            MaterialityRule(
                DivergenceFamily.RETURN,
                ComparisonLevel.RETURN,
                "value",
                Decimal("0.00001"),
                Decimal(2),
                "Return threshold.",
            ),
        ),
        tuple(FamilyWeight(family, Decimal(25)) for family in DivergenceFamily),
        (
            AttributionRule(
                "cost_may_explain_return",
                DivergenceFamily.TRANSACTION_COST,
                DivergenceFamily.RETURN,
                "Material cost and return divergence co-occur.",
            ),
            AttributionRule(
                "accounting_may_explain_return",
                DivergenceFamily.ACCOUNTING,
                DivergenceFamily.RETURN,
                "Material accounting and return divergence co-occur.",
            ),
        ),
        complete,
    )


def test_assessment_classifies_scores_and_bounds_attribution() -> None:
    result = ImplementationRiskAssessmentService().assess(_divergence(), _policy())
    candidate = result.candidates[0]
    classes = [item.assessments[0].materiality for item in candidate.families]
    assert classes == [
        MaterialityClass.EXTREME,
        MaterialityClass.MATERIAL,
        MaterialityClass.BELOW_THRESHOLD,
        MaterialityClass.EXTREME,
    ]
    assert candidate.implementation_risk_score == "87.5"
    assert candidate.uncertainty is AssessmentUncertainty.LOW
    assert [item.status for item in candidate.attributions] == [
        AttributionStatus.NOT_SUPPORTED,
        AttributionStatus.SUPPORTED_COOCCURRENCE,
    ]
    assert result.assessment_policy_sha256 == risk_policy_sha256(_policy())


def test_incomplete_evidence_withholds_score_and_attribution() -> None:
    divergence = _divergence()
    candidate = divergence.candidates[0]
    partial = replace(
        candidate.families[0], status=DivergenceStatus.PARTIAL, one_sided_record_count=1
    )
    divergence = replace(
        divergence,
        candidates=(replace(candidate, families=(partial, *candidate.families[1:])),),
    )

    result = (
        ImplementationRiskAssessmentService()
        .assess(divergence, _policy())
        .candidates[0]
    )

    assert result.implementation_risk_score is None
    assert result.score_withheld_reason is not None
    assert result.uncertainty is AssessmentUncertainty.HIGH
    assert result.attributions[1].status is AttributionStatus.INSUFFICIENT_EVIDENCE


def test_policy_is_canonical_hashable_and_fail_closed() -> None:
    policy = _policy()
    assert risk_policy_to_json(policy) == risk_policy_to_json(policy)
    assert len(risk_policy_sha256(policy)) == 64
    with pytest.raises(ValueError, match="sum exactly"):
        replace(
            policy,
            family_weights=tuple(
                FamilyWeight(family, Decimal(1)) for family in DivergenceFamily
            ),
        )
    with pytest.raises(ValueError, match="differ"):
        AttributionRule("bad", DivergenceFamily.RETURN, DivergenceFamily.RETURN, "bad")
    with pytest.raises(ValueError, match="policy"):
        risk_policy_to_json("bad")  # type: ignore[arg-type]


def test_service_rejects_invalid_scope_and_unruled_observation() -> None:
    service = ImplementationRiskAssessmentService()
    with pytest.raises(RiskAssessmentError) as invalid:
        service.assess("bad", _policy())  # type: ignore[arg-type]
    assert invalid.value.code is RiskAssessmentErrorCode.INVALID_INPUT
    with pytest.raises(RiskAssessmentError) as scope:
        service.assess(_divergence(), replace(_policy(), reconciliation_id="other"))
    assert scope.value.code is RiskAssessmentErrorCode.SCOPE_MISMATCH
    with pytest.raises(RiskAssessmentError) as mismatch:
        service.assess(
            _divergence(),
            replace(_policy(), materiality_rules=_policy().materiality_rules[:-1]),
        )
    assert mismatch.value.code is RiskAssessmentErrorCode.POLICY_MISMATCH
    with pytest.raises(RiskAssessmentError) as invalid_policy:
        service.assess(_divergence(), "bad")  # type: ignore[arg-type]
    assert invalid_policy.value.code is RiskAssessmentErrorCode.INVALID_INPUT


def test_output_contracts_reject_inconsistent_assessments() -> None:
    result = ImplementationRiskAssessmentService().assess(_divergence(), _policy())
    candidate = result.candidates[0]
    family = candidate.families[0]
    assessment = family.assessments[0]
    attribution = candidate.attributions[0]

    invalid = [
        lambda: replace(assessment, observation="bad"),  # type: ignore[arg-type]
        lambda: replace(assessment, threshold_ratio="99"),
        lambda: replace(assessment, materiality="bad"),  # type: ignore[arg-type]
        lambda: FamilyRiskAssessment(
            DivergenceFamily.SIZING,
            family.assessments,
            family.maximum_threshold_ratio,
            family.score_contribution,
        ),
        lambda: replace(family, score_contribution=None),
        lambda: replace(attribution, target_family=attribution.source_family),
        lambda: replace(candidate, implementation_risk_score="101"),
        lambda: replace(candidate, uncertainty="bad"),  # type: ignore[arg-type]
        lambda: replace(candidate, implementation_risk_score=None),
        lambda: replace(result, risk_assessment_schema_version="bad"),
    ]
    for factory in invalid:
        with pytest.raises(ValueError):
            factory()


def test_policy_contract_rejects_unsafe_configuration() -> None:
    policy = _policy()
    with pytest.raises(ValueError, match="iterable"):
        replace(policy, materiality_rules=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid record"):
        replace(policy, materiality_rules=("bad",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="family and level"):
        replace(policy.materiality_rules[0], family="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="family must"):
        FamilyWeight("bad", Decimal(25))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one"):
        replace(policy.materiality_rules[0], extreme_multiple=Decimal("0.5"))
    with pytest.raises(ValueError, match="unique"):
        replace(
            policy,
            attribution_rules=(
                policy.attribution_rules[0],
                policy.attribution_rules[0],
            ),
        )
    with pytest.raises(ValueError, match="boolean"):
        replace(policy, require_complete_evidence_for_score=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="message"):
        RiskAssessmentError(RiskAssessmentErrorCode.INVALID_INPUT, " ")
