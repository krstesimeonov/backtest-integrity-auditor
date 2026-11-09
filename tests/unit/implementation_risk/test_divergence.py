from dataclasses import replace

import pytest

from backtest_auditor.implementation_risk.application.divergence_errors import (
    DivergenceError,
    DivergenceErrorCode,
)
from backtest_auditor.implementation_risk.application.divergence_service import (
    DivergenceMeasurementService,
)
from backtest_auditor.implementation_risk.domain import (
    AlignmentMode,
    CandidateComparison,
    ComparisonLevel,
    DivergenceFamily,
    DivergenceFieldRule,
    DivergenceMeasurementPolicy,
    DivergenceObservation,
    DivergenceStatus,
    EngineRunReference,
    FamilyDivergence,
    FieldDifference,
    LevelComparison,
    LevelComparisonStatus,
    ReconciliationComparison,
    ReconciliationScope,
    RecordComparison,
    RecordComparisonStatus,
    divergence_policy_sha256,
    divergence_policy_to_json,
)


def _record(field: str, delta: str) -> RecordComparison:
    return RecordComparison(
        f"key-{field}",
        RecordComparisonStatus.MATCHED_DIFFERENT,
        ("reference",),
        ("candidate",),
        (
            FieldDifference(
                field,
                '{"type":"decimal","value":"1"}',
                '{"type":"decimal","value":"2"}',
                delta,
            ),
        ),
    )


def _comparison() -> ReconciliationComparison:
    reference = EngineRunReference("reference", "engine-a", "1", "a" * 64)
    candidate = EngineRunReference("candidate", "engine-b", "1", "b" * 64)
    levels = (
        ComparisonLevel.ORDER,
        ComparisonLevel.COST,
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    scope = ReconciliationScope("reconciliation-g", reference, (candidate,), levels)
    results = (
        LevelComparison(
            ComparisonLevel.ORDER,
            LevelComparisonStatus.COMPARED,
            AlignmentMode.SEMANTIC,
            (_record("quantity", "1"),),
        ),
        LevelComparison(
            ComparisonLevel.COST,
            LevelComparisonStatus.COMPARED,
            AlignmentMode.SEMANTIC,
            (
                RecordComparison(
                    "cost-key",
                    RecordComparisonStatus.REFERENCE_ONLY,
                    ("reference",),
                    (),
                ),
            ),
        ),
        LevelComparison(
            ComparisonLevel.EQUITY,
            LevelComparisonStatus.CANDIDATE_UNAVAILABLE,
            AlignmentMode.SEMANTIC,
            (),
        ),
        LevelComparison(
            ComparisonLevel.RETURN,
            LevelComparisonStatus.COMPARED,
            AlignmentMode.SEMANTIC,
            (_record("value", "0.01"),),
        ),
    )
    return ReconciliationComparison(
        scope, "c" * 64, "d" * 64, (CandidateComparison(candidate, results),)
    )


def _policy() -> DivergenceMeasurementPolicy:
    return DivergenceMeasurementPolicy(
        "reconciliation-g",
        (
            DivergenceFieldRule(
                DivergenceFamily.TRANSACTION_COST,
                ComparisonLevel.COST,
                "amount",
                "Canonical cost amount.",
            ),
            DivergenceFieldRule(
                DivergenceFamily.SIZING,
                ComparisonLevel.ORDER,
                "quantity",
                "Submitted quantity.",
            ),
            DivergenceFieldRule(
                DivergenceFamily.ACCOUNTING,
                ComparisonLevel.EQUITY,
                "total_equity",
                "Account equity.",
            ),
            DivergenceFieldRule(
                DivergenceFamily.RETURN,
                ComparisonLevel.RETURN,
                "value",
                "Period return.",
            ),
        ),
    )


def test_measurement_preserves_measured_partial_and_unavailable_states() -> None:
    result = DivergenceMeasurementService().measure(_comparison(), _policy())
    families = {item.family: item for item in result.candidates[0].families}

    assert families[DivergenceFamily.SIZING].status is DivergenceStatus.MEASURED
    assert families[DivergenceFamily.SIZING].observations[0].decimal_delta == "1"
    assert families[DivergenceFamily.RETURN].observations[0].decimal_delta == "0.01"
    assert (
        families[DivergenceFamily.TRANSACTION_COST].status is DivergenceStatus.PARTIAL
    )
    assert families[DivergenceFamily.TRANSACTION_COST].one_sided_record_count == 1
    assert families[DivergenceFamily.ACCOUNTING].status is DivergenceStatus.UNAVAILABLE
    assert result.normalization_plan_sha256 == "c" * 64
    assert result.comparison_policy_sha256 == "d" * 64


def test_absent_family_rules_are_explicitly_not_requested() -> None:
    policy = DivergenceMeasurementPolicy(
        "reconciliation-g",
        (
            DivergenceFieldRule(
                DivergenceFamily.RETURN,
                ComparisonLevel.RETURN,
                "value",
                "Period return.",
            ),
        ),
    )
    result = DivergenceMeasurementService().measure(_comparison(), policy)
    assert result.candidates[0].families[0].status is DivergenceStatus.NOT_REQUESTED


def test_policy_serialization_is_canonical_and_hashed() -> None:
    policy = _policy()
    assert divergence_policy_to_json(policy) == divergence_policy_to_json(policy)
    assert len(divergence_policy_sha256(policy)) == 64
    with pytest.raises(ValueError, match="policy"):
        divergence_policy_to_json("bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        replace(policy, rules=(policy.rules[0], policy.rules[0]))


def test_service_fails_closed_for_invalid_scope_or_levels() -> None:
    service = DivergenceMeasurementService()
    with pytest.raises(DivergenceError) as invalid:
        service.measure("bad", _policy())  # type: ignore[arg-type]
    assert invalid.value.code is DivergenceErrorCode.INVALID_INPUT
    with pytest.raises(DivergenceError) as scope:
        service.measure(_comparison(), replace(_policy(), reconciliation_id="other"))
    assert scope.value.code is DivergenceErrorCode.SCOPE_MISMATCH
    foreign = DivergenceMeasurementPolicy(
        "reconciliation-g",
        (
            DivergenceFieldRule(
                DivergenceFamily.SIZING,
                ComparisonLevel.FILL,
                "quantity",
                "Fill quantity.",
            ),
        ),
    )
    with pytest.raises(DivergenceError) as mismatch:
        service.measure(_comparison(), foreign)
    assert mismatch.value.code is DivergenceErrorCode.POLICY_MISMATCH


def test_impaired_record_kinds_remain_explicit() -> None:
    base = _comparison()
    order = LevelComparison(
        ComparisonLevel.ORDER,
        LevelComparisonStatus.COMPARED,
        AlignmentMode.SEMANTIC,
        (
            RecordComparison("a", RecordComparisonStatus.MATCHED_EQUAL, ("r",), ("c",)),
            RecordComparison(
                "b", RecordComparisonStatus.AMBIGUOUS, ("r1", "r2"), ("c",)
            ),
            RecordComparison(
                "c",
                RecordComparisonStatus.MATCHED_DIFFERENT,
                ("r",),
                ("c",),
                (
                    FieldDifference(
                        "status",
                        '{"type":"enum","value":"filled"}',
                        '{"type":"enum","value":"canceled"}',
                    ),
                ),
            ),
        ),
    )
    levels = (order, *base.candidates[0].levels[1:])
    comparison = replace(
        base,
        candidates=(CandidateComparison(base.candidates[0].candidate_run, levels),),
    )
    policy = DivergenceMeasurementPolicy(
        "reconciliation-g",
        (
            DivergenceFieldRule(
                DivergenceFamily.SIZING,
                ComparisonLevel.ORDER,
                "status",
                "Lifecycle evidence.",
            ),
        ),
    )
    family = (
        DivergenceMeasurementService()
        .measure(comparison, policy)
        .candidates[0]
        .families[1]
    )
    assert family.status is DivergenceStatus.PARTIAL
    assert (
        family.equal_record_count,
        family.non_numeric_difference_count,
        family.ambiguous_record_count,
    ) == (1, 1, 1)


def test_contracts_reject_inconsistent_evidence() -> None:
    with pytest.raises(ValueError, match="iterable"):
        replace(_policy(), rules=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid record"):
        replace(_policy(), rules=("bad",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="family"):
        replace(_policy().rules[0], family="bad")  # type: ignore[arg-type]
    with pytest.raises(DivergenceError) as invalid_policy:
        DivergenceMeasurementService().measure(_comparison(), "bad")  # type: ignore[arg-type]
    assert invalid_policy.value.code is DivergenceErrorCode.INVALID_INPUT
    with pytest.raises(ValueError, match="message"):
        DivergenceError(DivergenceErrorCode.INVALID_INPUT, " ")
    observation = DivergenceObservation(
        DivergenceFamily.RETURN,
        ComparisonLevel.RETURN,
        "key",
        "value",
        "one",
        "two",
        "1",
    )
    with pytest.raises(ValueError, match="declared family"):
        FamilyDivergence(
            DivergenceFamily.SIZING,
            DivergenceStatus.MEASURED,
            (observation,),
            0,
            0,
            0,
            0,
            0,
        )
    with pytest.raises(ValueError, match="non-negative"):
        FamilyDivergence(
            DivergenceFamily.RETURN,
            DivergenceStatus.MEASURED,
            (),
            -1,
            0,
            0,
            0,
            0,
        )
