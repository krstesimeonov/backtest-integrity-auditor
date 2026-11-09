"""Immutable V1.5F alignment policies and exact comparison evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Iterable
from typing import TypeVar, cast

from backtest_auditor.implementation_risk.domain.enums import ComparisonLevel
from backtest_auditor.implementation_risk.domain.scope import (
    EngineRunReference,
    ReconciliationScope,
)
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_sha256,
    normalize_text,
)


COMPARISON_SCHEMA_VERSION = "1.0"
_MAX_IDENTIFIER_LENGTH = 128
_MAX_TEXT_LENGTH = 16_384
_MAX_RECORD_LENGTH = 1_000_000
_LEVEL_ORDER = {level: index for index, level in enumerate(ComparisonLevel)}
_SOURCE_ID_LEVELS = frozenset(
    {
        ComparisonLevel.MARKET_DATA,
        ComparisonLevel.SIGNAL,
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
        ComparisonLevel.TRADE,
        ComparisonLevel.CASH,
        ComparisonLevel.COST,
    }
)


class AlignmentMode(StrEnum):
    """How records receive a candidate-independent alignment key."""

    SEMANTIC = "semantic"
    SOURCE_ID = "source_id"


class LevelComparisonStatus(StrEnum):
    COMPARED = "compared"
    REFERENCE_UNAVAILABLE = "reference_unavailable"
    CANDIDATE_UNAVAILABLE = "candidate_unavailable"
    BOTH_UNAVAILABLE = "both_unavailable"


class RecordComparisonStatus(StrEnum):
    MATCHED_EQUAL = "matched_equal"
    MATCHED_DIFFERENT = "matched_different"
    REFERENCE_ONLY = "reference_only"
    CANDIDATE_ONLY = "candidate_only"
    AMBIGUOUS = "ambiguous"


def _text(value: object, *, field: str, maximum: int = _MAX_TEXT_LENGTH) -> str:
    return normalize_text(value, field=field, maximum_length=maximum)


_T = TypeVar("_T")


def _tuple_of(
    values: Iterable[object],
    item_type: type[_T],
    *,
    field: str,
) -> tuple[_T, ...]:
    try:
        items = tuple(values)
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable.") from error
    if any(not isinstance(item, item_type) for item in items):
        raise ValueError(f"{field} contains an invalid record type.")
    return cast(tuple[_T, ...], items)


@dataclass(frozen=True, slots=True)
class LevelComparisonPolicy:
    level: ComparisonLevel
    alignment_mode: AlignmentMode
    rationale: str

    def __post_init__(self) -> None:
        try:
            level = ComparisonLevel(self.level)
        except (TypeError, ValueError) as error:
            raise ValueError("level must be a supported ComparisonLevel.") from error
        try:
            mode = AlignmentMode(self.alignment_mode)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "alignment_mode must be a supported AlignmentMode."
            ) from error
        if mode is AlignmentMode.SOURCE_ID and level not in _SOURCE_ID_LEVELS:
            raise ValueError(f"source_id alignment is not supported for {level.value}.")
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "alignment_mode", mode)
        object.__setattr__(self, "rationale", _text(self.rationale, field="rationale"))


@dataclass(frozen=True, slots=True)
class ReconciliationComparisonPolicy:
    reconciliation_id: str
    levels: tuple[LevelComparisonPolicy, ...]
    comparison_schema_version: str = COMPARISON_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_id",
            _text(
                self.reconciliation_id,
                field="reconciliation_id",
                maximum=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        levels = _tuple_of(
            self.levels,
            LevelComparisonPolicy,
            field="levels",
        )
        if not levels:
            raise ValueError("levels must contain at least one policy.")
        names = tuple(item.level for item in levels)
        if len(names) != len(set(names)):
            raise ValueError("levels must not contain duplicate comparison levels.")
        if self.comparison_schema_version != COMPARISON_SCHEMA_VERSION:
            raise ValueError(
                f"comparison_schema_version must equal {COMPARISON_SCHEMA_VERSION!r}."
            )
        object.__setattr__(
            self,
            "levels",
            tuple(sorted(levels, key=lambda item: _LEVEL_ORDER[item.level])),
        )


@dataclass(frozen=True, slots=True)
class FieldDifference:
    field: str
    reference_value: str
    candidate_value: str
    decimal_delta: str | None = None
    temporal_delta_microseconds: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "field",
            _text(self.field, field="field", maximum=_MAX_TEXT_LENGTH),
        )
        object.__setattr__(
            self,
            "reference_value",
            _text(self.reference_value, field="reference_value"),
        )
        object.__setattr__(
            self,
            "candidate_value",
            _text(self.candidate_value, field="candidate_value"),
        )
        if self.reference_value == self.candidate_value:
            raise ValueError("a field difference requires unequal values.")
        if self.decimal_delta is not None:
            object.__setattr__(
                self,
                "decimal_delta",
                _text(self.decimal_delta, field="decimal_delta"),
            )
        temporal_delta = self.temporal_delta_microseconds
        if temporal_delta is not None and (
            isinstance(temporal_delta, bool) or not isinstance(temporal_delta, int)
        ):
            raise ValueError("temporal_delta_microseconds must be an integer or None.")
        if self.decimal_delta is not None and temporal_delta is not None:
            raise ValueError(
                "a difference cannot carry both decimal and temporal deltas."
            )

    @property
    def sort_key(self) -> str:
        return self.field


@dataclass(frozen=True, slots=True)
class RecordComparison:
    alignment_key: str
    status: RecordComparisonStatus
    reference_records: tuple[str, ...]
    candidate_records: tuple[str, ...]
    differences: tuple[FieldDifference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "alignment_key",
            _text(self.alignment_key, field="alignment_key"),
        )
        try:
            status = RecordComparisonStatus(self.status)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "status must be a supported RecordComparisonStatus."
            ) from error
        reference = tuple(
            _text(item, field="reference record", maximum=_MAX_RECORD_LENGTH)
            for item in _tuple_of(
                self.reference_records, str, field="reference_records"
            )
        )
        candidate = tuple(
            _text(item, field="candidate record", maximum=_MAX_RECORD_LENGTH)
            for item in _tuple_of(
                self.candidate_records, str, field="candidate_records"
            )
        )
        differences = _tuple_of(
            self.differences,
            FieldDifference,
            field="differences",
        )
        if differences != tuple(sorted(differences, key=lambda item: item.sort_key)):
            raise ValueError("differences must be in canonical field order.")
        counts = (len(reference), len(candidate))
        if status in {
            RecordComparisonStatus.MATCHED_EQUAL,
            RecordComparisonStatus.MATCHED_DIFFERENT,
        } and counts != (1, 1):
            raise ValueError("matched records require exactly one record on each side.")
        if status is RecordComparisonStatus.MATCHED_EQUAL and differences:
            raise ValueError("matched_equal records must not contain differences.")
        if status is RecordComparisonStatus.MATCHED_DIFFERENT and not differences:
            raise ValueError("matched_different records require differences.")
        if status is RecordComparisonStatus.REFERENCE_ONLY and counts != (1, 0):
            raise ValueError("reference_only requires exactly one reference record.")
        if status is RecordComparisonStatus.CANDIDATE_ONLY and counts != (0, 1):
            raise ValueError("candidate_only requires exactly one candidate record.")
        if status is RecordComparisonStatus.AMBIGUOUS and max(counts) <= 1:
            raise ValueError(
                "ambiguous requires more than one record on at least one side."
            )
        if (
            status
            not in {
                RecordComparisonStatus.MATCHED_DIFFERENT,
                RecordComparisonStatus.MATCHED_EQUAL,
            }
            and differences
        ):
            raise ValueError("only matched records may contain field differences.")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reference_records", tuple(sorted(reference)))
        object.__setattr__(self, "candidate_records", tuple(sorted(candidate)))
        object.__setattr__(self, "differences", differences)

    @property
    def sort_key(self) -> str:
        return self.alignment_key


@dataclass(frozen=True, slots=True)
class LevelComparison:
    level: ComparisonLevel
    status: LevelComparisonStatus
    alignment_mode: AlignmentMode
    records: tuple[RecordComparison, ...]

    def __post_init__(self) -> None:
        try:
            level = ComparisonLevel(self.level)
        except (TypeError, ValueError) as error:
            raise ValueError("level must be a supported ComparisonLevel.") from error
        try:
            status = LevelComparisonStatus(self.status)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "status must be a supported LevelComparisonStatus."
            ) from error
        try:
            mode = AlignmentMode(self.alignment_mode)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "alignment_mode must be a supported AlignmentMode."
            ) from error
        records = _tuple_of(self.records, RecordComparison, field="records")
        if status is not LevelComparisonStatus.COMPARED and records:
            raise ValueError("unavailable levels must not contain records.")
        if records != tuple(sorted(records, key=lambda item: item.sort_key)):
            raise ValueError("records must be in canonical alignment-key order.")
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "alignment_mode", mode)
        object.__setattr__(self, "records", records)

    @property
    def exact_match(self) -> bool | None:
        if self.status is not LevelComparisonStatus.COMPARED:
            return None
        return all(
            item.status is RecordComparisonStatus.MATCHED_EQUAL for item in self.records
        )

    def count(self, status: RecordComparisonStatus) -> int:
        return sum(item.status is status for item in self.records)


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    candidate_run: EngineRunReference
    levels: tuple[LevelComparison, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_run, EngineRunReference):
            raise ValueError("candidate_run must be an EngineRunReference.")
        levels = _tuple_of(self.levels, LevelComparison, field="levels")
        names = tuple(item.level for item in levels)
        if len(names) != len(set(names)):
            raise ValueError("levels must not contain duplicates.")
        if levels != tuple(sorted(levels, key=lambda item: _LEVEL_ORDER[item.level])):
            raise ValueError("levels must be in canonical comparison order.")
        object.__setattr__(self, "levels", levels)


@dataclass(frozen=True, slots=True)
class ReconciliationComparison:
    scope: ReconciliationScope
    normalization_plan_sha256: str
    comparison_policy_sha256: str
    candidates: tuple[CandidateComparison, ...]
    comparison_schema_version: str = COMPARISON_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ReconciliationScope):
            raise ValueError("scope must be a ReconciliationScope.")
        object.__setattr__(
            self,
            "normalization_plan_sha256",
            normalize_sha256(
                self.normalization_plan_sha256,
                field="normalization_plan_sha256",
            ),
        )
        object.__setattr__(
            self,
            "comparison_policy_sha256",
            normalize_sha256(
                self.comparison_policy_sha256,
                field="comparison_policy_sha256",
            ),
        )
        candidates = _tuple_of(
            self.candidates,
            CandidateComparison,
            field="candidates",
        )
        expected = self.scope.candidate_runs
        if tuple(item.candidate_run for item in candidates) != expected:
            raise ValueError("candidates must follow exact reconciliation scope order.")
        if any(
            tuple(item.level for item in candidate.levels)
            != self.scope.requested_levels
            for candidate in candidates
        ):
            raise ValueError("every candidate must contain every requested level.")
        if self.comparison_schema_version != COMPARISON_SCHEMA_VERSION:
            raise ValueError(
                f"comparison_schema_version must equal {COMPARISON_SCHEMA_VERSION!r}."
            )
        object.__setattr__(self, "candidates", candidates)


def comparison_policy_to_json(policy: ReconciliationComparisonPolicy) -> str:
    """Serialize one comparison policy canonically for evidence hashing."""

    if not isinstance(policy, ReconciliationComparisonPolicy):
        raise ValueError("policy must be a ReconciliationComparisonPolicy.")
    payload = {
        "comparison_schema_version": policy.comparison_schema_version,
        "reconciliation_id": policy.reconciliation_id,
        "levels": [
            {
                "level": item.level.value,
                "alignment_mode": item.alignment_mode.value,
                "rationale": item.rationale,
            }
            for item in policy.levels
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def comparison_policy_sha256(policy: ReconciliationComparisonPolicy) -> str:
    return hashlib.sha256(comparison_policy_to_json(policy).encode("utf-8")).hexdigest()


__all__ = [
    "COMPARISON_SCHEMA_VERSION",
    "AlignmentMode",
    "CandidateComparison",
    "FieldDifference",
    "LevelComparison",
    "LevelComparisonPolicy",
    "LevelComparisonStatus",
    "ReconciliationComparison",
    "ReconciliationComparisonPolicy",
    "RecordComparison",
    "RecordComparisonStatus",
    "comparison_policy_sha256",
    "comparison_policy_to_json",
]
