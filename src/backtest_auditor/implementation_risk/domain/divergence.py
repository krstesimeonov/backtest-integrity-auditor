"""Typed V1.5G implementation-divergence measurements."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
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


DIVERGENCE_SCHEMA_VERSION = "1.0"
_MAX_TEXT = 16_384
_FAMILY_ORDER: dict[DivergenceFamily, int]
_T = TypeVar("_T")


class DivergenceFamily(StrEnum):
    TRANSACTION_COST = "transaction_cost"
    SIZING = "sizing"
    ACCOUNTING = "accounting"
    RETURN = "return"


_FAMILY_ORDER = {item: index for index, item in enumerate(DivergenceFamily)}


class DivergenceStatus(StrEnum):
    MEASURED = "measured"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_REQUESTED = "not_requested"


def _items(values: Iterable[object], kind: type[_T], field: str) -> tuple[_T, ...]:
    try:
        result = tuple(values)
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable.") from error
    if any(not isinstance(item, kind) for item in result):
        raise ValueError(f"{field} contains an invalid record type.")
    return cast(tuple[_T, ...], result)


def _text(value: object, field: str) -> str:
    return normalize_text(value, field=field, maximum_length=_MAX_TEXT)


@dataclass(frozen=True, slots=True)
class DivergenceFieldRule:
    family: DivergenceFamily
    level: ComparisonLevel
    field: str
    rationale: str

    def __post_init__(self) -> None:
        try:
            family = DivergenceFamily(self.family)
            level = ComparisonLevel(self.level)
        except (TypeError, ValueError) as error:
            raise ValueError("family and level must be supported values.") from error
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "field", _text(self.field, "field"))
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale"))


@dataclass(frozen=True, slots=True)
class DivergenceMeasurementPolicy:
    reconciliation_id: str
    rules: tuple[DivergenceFieldRule, ...]
    divergence_schema_version: str = DIVERGENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_id",
            _text(self.reconciliation_id, "reconciliation_id"),
        )
        rules = _items(self.rules, DivergenceFieldRule, "rules")
        keys = tuple((item.family, item.level, item.field) for item in rules)
        if not rules or len(keys) != len(set(keys)):
            raise ValueError("rules must be non-empty and unique.")
        if self.divergence_schema_version != DIVERGENCE_SCHEMA_VERSION:
            raise ValueError(
                f"divergence_schema_version must equal {DIVERGENCE_SCHEMA_VERSION!r}."
            )
        object.__setattr__(
            self,
            "rules",
            tuple(
                sorted(
                    rules,
                    key=lambda item: (
                        _FAMILY_ORDER[item.family],
                        item.level.value,
                        item.field,
                    ),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class DivergenceObservation:
    family: DivergenceFamily
    level: ComparisonLevel
    alignment_key: str
    field: str
    reference_value: str
    candidate_value: str
    decimal_delta: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "family", DivergenceFamily(self.family))
            object.__setattr__(self, "level", ComparisonLevel(self.level))
        except (TypeError, ValueError) as error:
            raise ValueError("family and level must be supported values.") from error
        for name in (
            "alignment_key",
            "field",
            "reference_value",
            "candidate_value",
            "decimal_delta",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.level.value, self.alignment_key, self.field


@dataclass(frozen=True, slots=True)
class FamilyDivergence:
    family: DivergenceFamily
    status: DivergenceStatus
    observations: tuple[DivergenceObservation, ...]
    equal_record_count: int
    non_numeric_difference_count: int
    one_sided_record_count: int
    ambiguous_record_count: int
    unavailable_level_count: int

    def __post_init__(self) -> None:
        try:
            family = DivergenceFamily(self.family)
            status = DivergenceStatus(self.status)
        except (TypeError, ValueError) as error:
            raise ValueError("family and status must be supported values.") from error
        observations = _items(self.observations, DivergenceObservation, "observations")
        if any(item.family is not family for item in observations):
            raise ValueError("observations must belong to the declared family.")
        if observations != tuple(sorted(observations, key=lambda item: item.sort_key)):
            raise ValueError("observations must be in canonical order.")
        counts = (
            self.equal_record_count,
            self.non_numeric_difference_count,
            self.one_sided_record_count,
            self.ambiguous_record_count,
            self.unavailable_level_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValueError("divergence counts must be non-negative integers.")
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True, slots=True)
class CandidateDivergence:
    candidate_run: EngineRunReference
    families: tuple[FamilyDivergence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_run, EngineRunReference):
            raise ValueError("candidate_run must be an EngineRunReference.")
        families = _items(self.families, FamilyDivergence, "families")
        if tuple(item.family for item in families) != tuple(DivergenceFamily):
            raise ValueError(
                "families must contain every divergence family in canonical order."
            )
        object.__setattr__(self, "families", families)


@dataclass(frozen=True, slots=True)
class ReconciliationDivergence:
    scope: ReconciliationScope
    normalization_plan_sha256: str
    comparison_policy_sha256: str
    measurement_policy_sha256: str
    candidates: tuple[CandidateDivergence, ...]
    divergence_schema_version: str = DIVERGENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ReconciliationScope):
            raise ValueError("scope must be a ReconciliationScope.")
        for name in (
            "normalization_plan_sha256",
            "comparison_policy_sha256",
            "measurement_policy_sha256",
        ):
            object.__setattr__(
                self, name, normalize_sha256(getattr(self, name), field=name)
            )
        candidates = _items(self.candidates, CandidateDivergence, "candidates")
        if (
            tuple(item.candidate_run for item in candidates)
            != self.scope.candidate_runs
        ):
            raise ValueError("candidates must follow exact reconciliation scope order.")
        if self.divergence_schema_version != DIVERGENCE_SCHEMA_VERSION:
            raise ValueError(
                f"divergence_schema_version must equal {DIVERGENCE_SCHEMA_VERSION!r}."
            )
        object.__setattr__(self, "candidates", candidates)


def divergence_policy_to_json(policy: DivergenceMeasurementPolicy) -> str:
    if not isinstance(policy, DivergenceMeasurementPolicy):
        raise ValueError("policy must be a DivergenceMeasurementPolicy.")
    payload = {
        "divergence_schema_version": policy.divergence_schema_version,
        "reconciliation_id": policy.reconciliation_id,
        "rules": [
            {
                "family": item.family.value,
                "level": item.level.value,
                "field": item.field,
                "rationale": item.rationale,
            }
            for item in policy.rules
        ],
    }
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def divergence_policy_sha256(policy: DivergenceMeasurementPolicy) -> str:
    return hashlib.sha256(divergence_policy_to_json(policy).encode()).hexdigest()


__all__ = [
    "DIVERGENCE_SCHEMA_VERSION",
    "CandidateDivergence",
    "DivergenceFamily",
    "DivergenceFieldRule",
    "DivergenceMeasurementPolicy",
    "DivergenceObservation",
    "DivergenceStatus",
    "FamilyDivergence",
    "ReconciliationDivergence",
    "divergence_policy_sha256",
    "divergence_policy_to_json",
]
