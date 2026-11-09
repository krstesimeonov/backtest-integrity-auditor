from dataclasses import replace
from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk.application.comparison_errors import (
    ComparisonError,
    ComparisonErrorCode,
)
from backtest_auditor.implementation_risk.application.comparison_service import (
    ReconciliationComparisonService,
)
from backtest_auditor.implementation_risk.domain import (
    AlignmentMode,
    CanonicalRunArtifacts,
    ComparisonLevel,
    EngineRunReference,
    LevelComparisonPolicy,
    LevelComparisonStatus,
    NormalizedReconciliation,
    NormalizedRunArtifacts,
    ReconciliationComparisonPolicy,
    ReconciliationScope,
    RecordComparisonStatus,
)


def _normalized(
    reference: CanonicalRunArtifacts,
    candidate: CanonicalRunArtifacts,
    levels: tuple[ComparisonLevel, ...],
) -> NormalizedReconciliation:
    scope = ReconciliationScope(
        "reconciliation-f", reference.run, (candidate.run,), levels
    )
    return NormalizedReconciliation(
        scope,
        "e" * 64,
        (
            NormalizedRunArtifacts(reference.run, reference, "a" * 64, None, ()),
            NormalizedRunArtifacts(candidate.run, candidate, "b" * 64, None, ()),
        ),
    )


def _policy(
    levels: tuple[ComparisonLevel, ...],
    mode: AlignmentMode = AlignmentMode.SEMANTIC,
) -> ReconciliationComparisonPolicy:
    return ReconciliationComparisonPolicy(
        "reconciliation-f",
        tuple(
            LevelComparisonPolicy(level, mode, "Explicit comparison rule.")
            for level in levels
        ),
    )


def _candidate(bundle: CanonicalRunArtifacts) -> CanonicalRunArtifacts:
    run = EngineRunReference("candidate", "other-engine", "2", "f" * 64)
    return replace(bundle, run=run)


def test_all_requested_levels_compare_as_exact_equal(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    levels = tuple(ComparisonLevel)
    normalized = _normalized(
        canonical_file_bundle, _candidate(canonical_file_bundle), levels
    )

    result = ReconciliationComparisonService().compare(normalized, _policy(levels))

    assert result.normalization_plan_sha256 == "e" * 64
    assert len(result.candidates[0].levels) == len(levels)
    assert all(
        level.status is LevelComparisonStatus.COMPARED
        for level in result.candidates[0].levels
    )
    assert all(level.exact_match is True for level in result.candidates[0].levels)
    assert all(
        record.status is RecordComparisonStatus.MATCHED_EQUAL
        for level in result.candidates[0].levels
        for record in level.records
    )


def test_exact_difference_contains_decimal_delta(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    candidate = _candidate(canonical_file_bundle)
    assert candidate.equity is not None
    point = replace(
        candidate.equity[0],
        total_equity=candidate.equity[0].total_equity + Decimal("2.50"),
    )
    candidate = replace(candidate, equity=(point, *candidate.equity[1:]))
    levels = (ComparisonLevel.EQUITY,)

    level = (
        ReconciliationComparisonService()
        .compare(_normalized(canonical_file_bundle, candidate, levels), _policy(levels))
        .candidates[0]
        .levels[0]
    )

    assert level.exact_match is False
    record = level.records[0]
    assert record.status is RecordComparisonStatus.MATCHED_DIFFERENT
    difference = next(
        item for item in record.differences if item.field == "total_equity"
    )
    assert difference.decimal_delta == "2.5"


def test_semantic_alignment_ignores_engine_local_ids_but_preserves_evidence(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    candidate = _candidate(canonical_file_bundle)
    assert candidate.fills is not None
    candidate = replace(candidate, trades=None, costs=None)
    candidate = replace(
        candidate, fills=(replace(candidate.fills[0], fill_id="foreign-fill"),)
    )
    reference = replace(canonical_file_bundle, trades=None, costs=None)
    levels = (ComparisonLevel.FILL,)

    record = (
        ReconciliationComparisonService()
        .compare(_normalized(reference, candidate, levels), _policy(levels))
        .candidates[0]
        .levels[0]
        .records[0]
    )

    assert record.status is RecordComparisonStatus.MATCHED_EQUAL
    assert "fill-1" in record.reference_records[0]
    assert "foreign-fill" in record.candidate_records[0]


def test_source_id_alignment_reports_side_only_records(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    candidate = _candidate(canonical_file_bundle)
    assert candidate.fills is not None
    candidate = replace(candidate, trades=None, costs=None)
    candidate = replace(
        candidate, fills=(replace(candidate.fills[0], fill_id="foreign-fill"),)
    )
    reference = replace(canonical_file_bundle, trades=None, costs=None)
    levels = (ComparisonLevel.FILL,)

    records = (
        ReconciliationComparisonService()
        .compare(
            _normalized(reference, candidate, levels),
            _policy(levels, AlignmentMode.SOURCE_ID),
        )
        .candidates[0]
        .levels[0]
        .records
    )

    assert {item.status for item in records} == {
        RecordComparisonStatus.REFERENCE_ONLY,
        RecordComparisonStatus.CANDIDATE_ONLY,
    }


def test_duplicate_semantic_keys_are_ambiguous_not_guessed(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    candidate = _candidate(canonical_file_bundle)
    assert candidate.orders is not None
    duplicate = replace(candidate.orders[0], order_id="order-duplicate")
    candidate = replace(candidate, fills=None, trades=None, costs=None)
    candidate = replace(candidate, orders=(*candidate.orders, duplicate))
    reference = replace(canonical_file_bundle, fills=None, trades=None, costs=None)
    levels = (ComparisonLevel.ORDER,)

    records = (
        ReconciliationComparisonService()
        .compare(_normalized(reference, candidate, levels), _policy(levels))
        .candidates[0]
        .levels[0]
        .records
    )

    assert len(records) == 1
    assert records[0].status is RecordComparisonStatus.AMBIGUOUS
    assert len(records[0].candidate_records) == 2
    assert not records[0].differences


@pytest.mark.parametrize(
    ("reference_available", "candidate_available", "expected"),
    [
        (True, False, LevelComparisonStatus.CANDIDATE_UNAVAILABLE),
        (False, True, LevelComparisonStatus.REFERENCE_UNAVAILABLE),
        (False, False, LevelComparisonStatus.BOTH_UNAVAILABLE),
    ],
)
def test_unavailable_is_distinct_from_available_empty(
    canonical_file_bundle: CanonicalRunArtifacts,
    reference_available: bool,
    candidate_available: bool,
    expected: LevelComparisonStatus,
) -> None:
    reference = replace(
        canonical_file_bundle, returns=() if reference_available else None
    )
    candidate = replace(
        _candidate(canonical_file_bundle), returns=() if candidate_available else None
    )
    levels = (ComparisonLevel.RETURN,)

    level = (
        ReconciliationComparisonService()
        .compare(_normalized(reference, candidate, levels), _policy(levels))
        .candidates[0]
        .levels[0]
    )

    assert level.status is expected
    assert level.exact_match is None
    assert level.records == ()


def test_available_empty_is_an_exact_compared_level(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    reference = replace(canonical_file_bundle, returns=())
    candidate = replace(_candidate(canonical_file_bundle), returns=())
    levels = (ComparisonLevel.RETURN,)
    level = (
        ReconciliationComparisonService()
        .compare(_normalized(reference, candidate, levels), _policy(levels))
        .candidates[0]
        .levels[0]
    )
    assert level.status is LevelComparisonStatus.COMPARED
    assert level.exact_match is True


def test_service_rejects_invalid_or_mismatched_inputs(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    candidate = _candidate(canonical_file_bundle)
    levels = (ComparisonLevel.RETURN,)
    normalized = _normalized(canonical_file_bundle, candidate, levels)
    service = ReconciliationComparisonService()

    cases = [
        ("bad", _policy(levels), ComparisonErrorCode.INVALID_INPUT),
        (normalized, "bad", ComparisonErrorCode.INVALID_INPUT),
        (
            normalized,
            replace(_policy(levels), reconciliation_id="other"),
            ComparisonErrorCode.SCOPE_MISMATCH,
        ),
        (
            normalized,
            _policy((ComparisonLevel.EQUITY,)),
            ComparisonErrorCode.POLICY_MISMATCH,
        ),
    ]
    for value, policy, code in cases:
        with pytest.raises(ComparisonError) as caught:
            service.compare(value, policy)  # type: ignore[arg-type]
        assert caught.value.code is code
