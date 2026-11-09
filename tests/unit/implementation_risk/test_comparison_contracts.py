from dataclasses import replace

import pytest

from backtest_auditor.implementation_risk.domain import (
    AlignmentMode,
    ComparisonLevel,
    FieldDifference,
    LevelComparison,
    LevelComparisonPolicy,
    LevelComparisonStatus,
    ReconciliationComparisonPolicy,
    RecordComparison,
    RecordComparisonStatus,
    comparison_policy_sha256,
    comparison_policy_to_json,
)


def test_policy_is_canonical_and_hashable() -> None:
    policy = ReconciliationComparisonPolicy(
        "reconciliation-f",
        (
            LevelComparisonPolicy(
                ComparisonLevel.RETURN, AlignmentMode.SEMANTIC, "Periods."
            ),
            LevelComparisonPolicy(
                ComparisonLevel.ORDER, AlignmentMode.SOURCE_ID, "Stable IDs."
            ),
        ),
    )
    assert tuple(item.level for item in policy.levels) == (
        ComparisonLevel.ORDER,
        ComparisonLevel.RETURN,
    )
    assert len(comparison_policy_sha256(policy)) == 64
    assert comparison_policy_to_json(policy) == comparison_policy_to_json(policy)
    with pytest.raises(ValueError, match="policy"):
        comparison_policy_to_json("bad")  # type: ignore[arg-type]


def test_policy_rejects_duplicates_and_unsupported_source_ids() -> None:
    item = LevelComparisonPolicy(ComparisonLevel.FILL, AlignmentMode.SEMANTIC, "why")
    with pytest.raises(ValueError, match="duplicate"):
        ReconciliationComparisonPolicy("r", (item, item))
    with pytest.raises(ValueError, match="not supported"):
        LevelComparisonPolicy(ComparisonLevel.EQUITY, AlignmentMode.SOURCE_ID, "why")


def test_record_and_level_contracts_enforce_typed_states() -> None:
    difference = FieldDifference("price", '"1"', '"2"', "1")
    changed = RecordComparison(
        "key",
        RecordComparisonStatus.MATCHED_DIFFERENT,
        ("reference",),
        ("candidate",),
        (difference,),
    )
    level = LevelComparison(
        ComparisonLevel.FILL,
        LevelComparisonStatus.COMPARED,
        AlignmentMode.SEMANTIC,
        (changed,),
    )
    assert level.exact_match is False
    assert level.count(RecordComparisonStatus.MATCHED_DIFFERENT) == 1
    with pytest.raises(ValueError, match="differences"):
        replace(changed, differences=())
    with pytest.raises(ValueError, match="unavailable"):
        replace(level, status=LevelComparisonStatus.BOTH_UNAVAILABLE)
