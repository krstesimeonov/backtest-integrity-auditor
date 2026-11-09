"""Deterministic V1.5F alignment and exact field comparison service."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import NoReturn

from backtest_auditor.implementation_risk.application.comparison_errors import (
    ComparisonError,
    ComparisonErrorCode,
)
from backtest_auditor.implementation_risk.domain import (
    AlignmentMode,
    CandidateComparison,
    CanonicalRunArtifacts,
    ComparisonLevel,
    FieldDifference,
    LevelComparison,
    LevelComparisonPolicy,
    LevelComparisonStatus,
    NormalizedReconciliation,
    ReconciliationComparison,
    ReconciliationComparisonPolicy,
    RecordComparison,
    RecordComparisonStatus,
    comparison_policy_sha256,
)


def _fail(
    code: ComparisonErrorCode,
    message: str,
    *,
    candidate_run_id: str | None = None,
    level: ComparisonLevel | None = None,
) -> NoReturn:
    raise ComparisonError(code, message, candidate_run_id, level)


def _utc_text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _typed_value(value: object) -> object:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": format(value, "f")}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": _utc_text(value)}
    if isinstance(value, StrEnum):
        return {"type": "enum", "value": value.value}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    if isinstance(value, tuple):
        return [_typed_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _typed_value(getattr(value, item.name)) for item in fields(value)
        }
    raise TypeError(f"unsupported canonical comparison value: {type(value).__name__}")


def _json(value: object) -> str:
    return json.dumps(
        _typed_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _flatten(value: object, *, path: str = "") -> dict[str, object]:
    if is_dataclass(value) and not isinstance(value, type):
        flattened: dict[str, object] = {}
        for item in fields(value):
            child = item.name if not path else f"{path}.{item.name}"
            flattened.update(_flatten(getattr(value, item.name), path=child))
        return flattened
    if isinstance(value, tuple):
        flattened = {}
        for index, item in enumerate(value):
            child = f"{path}[{index}]"
            flattened.update(_flatten(item, path=child))
        if not value:
            flattened[path] = value
        return flattened
    return {path: value}


@dataclass(frozen=True, slots=True)
class _RecordView:
    kind: str
    record: object
    source_id: str | None


def _semantic_key(view: _RecordView) -> tuple[object, ...]:
    record = view.record
    level_fields: dict[str, tuple[str, ...]] = {
        "strategy_specification": (),
        "market_data": ("event_timestamp", "instrument_id", "field"),
        "signal": ("timestamp", "instrument_id"),
        "order": ("created_at", "instrument_id", "side"),
        "fill": ("timestamp", "instrument_id", "side"),
        "trade": ("opened_at", "instrument_id", "direction"),
        "position": ("timestamp", "instrument_id"),
        "cash_balance": ("timestamp", "currency"),
        "cash_movement": ("timestamp", "currency"),
        "cost": ("timestamp", "currency"),
        "equity": ("timestamp", "currency"),
        "return": ("start_timestamp", "end_timestamp"),
    }
    return tuple(getattr(record, name) for name in level_fields[view.kind])


def _alignment_key(view: _RecordView, mode: AlignmentMode) -> str:
    if mode is AlignmentMode.SOURCE_ID and view.source_id is not None:
        values: tuple[object, ...] = (view.source_id,)
        key_mode = AlignmentMode.SOURCE_ID.value
    else:
        values = _semantic_key(view)
        key_mode = AlignmentMode.SEMANTIC.value
    return json.dumps(
        {
            "kind": view.kind,
            "mode": key_mode,
            "values": [_typed_value(item) for item in values],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _record_views(
    bundle: CanonicalRunArtifacts,
    level: ComparisonLevel,
) -> tuple[_RecordView, ...]:
    if level is ComparisonLevel.STRATEGY_SPECIFICATION:
        return (
            ()
            if bundle.specification is None
            else (
                _RecordView(
                    ComparisonLevel.STRATEGY_SPECIFICATION.value,
                    bundle.specification,
                    None,
                ),
            )
        )
    if level is ComparisonLevel.CASH:
        if bundle.cash is None:
            return ()
        balances = () if bundle.cash.balances is None else bundle.cash.balances
        movements = () if bundle.cash.movements is None else bundle.cash.movements
        return (
            *(_RecordView("cash_balance", item, None) for item in balances),
            *(
                _RecordView("cash_movement", item, item.movement_id)
                for item in movements
            ),
        )
    records_by_level: dict[ComparisonLevel, tuple[object, ...] | None] = {
        ComparisonLevel.MARKET_DATA: bundle.market_data,
        ComparisonLevel.SIGNAL: bundle.signals,
        ComparisonLevel.ORDER: bundle.orders,
        ComparisonLevel.FILL: bundle.fills,
        ComparisonLevel.TRADE: bundle.trades,
        ComparisonLevel.POSITION: bundle.positions,
        ComparisonLevel.COST: bundle.costs,
        ComparisonLevel.EQUITY: bundle.equity,
        ComparisonLevel.RETURN: bundle.returns,
    }
    records = records_by_level[level]
    if records is None:
        return ()
    id_fields = {
        ComparisonLevel.MARKET_DATA: "observation_id",
        ComparisonLevel.SIGNAL: "signal_id",
        ComparisonLevel.ORDER: "order_id",
        ComparisonLevel.FILL: "fill_id",
        ComparisonLevel.TRADE: "trade_id",
        ComparisonLevel.COST: "cost_id",
    }
    id_field = id_fields.get(level)
    return tuple(
        _RecordView(
            level.value,
            item,
            None if id_field is None else getattr(item, id_field),
        )
        for item in records
    )


def _comparison_values(view: _RecordView) -> dict[str, object]:
    excluded_by_kind = {
        "market_data": frozenset({"observation_id"}),
        "signal": frozenset({"signal_id"}),
        "order": frozenset({"order_id", "signal_id", "parent_order_id"}),
        "fill": frozenset({"fill_id", "order_id"}),
        "trade": frozenset({"trade_id", "fill_ids"}),
        "cash_movement": frozenset({"movement_id", "related_artifact_id"}),
        "cost": frozenset({"cost_id", "order_id", "fill_id", "trade_id"}),
    }
    excluded = excluded_by_kind.get(view.kind, frozenset())
    if not is_dataclass(view.record) or isinstance(view.record, type):
        raise TypeError("canonical records must be dataclass instances")
    flattened: dict[str, object] = {}
    for item in fields(view.record):
        if item.name not in excluded:
            flattened.update(_flatten(getattr(view.record, item.name), path=item.name))
    return flattened


def _elapsed_microseconds(reference: datetime, candidate: datetime) -> int:
    value = candidate - reference
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds


def _equal(reference: object, candidate: object) -> bool:
    if isinstance(reference, Decimal) and isinstance(candidate, Decimal):
        return reference == candidate
    if isinstance(reference, datetime) and isinstance(candidate, datetime):
        return reference == candidate
    return _json(reference) == _json(candidate)


def _differences(
    reference: _RecordView, candidate: _RecordView
) -> tuple[FieldDifference, ...]:
    reference_values = _comparison_values(reference)
    candidate_values = _comparison_values(candidate)
    names = sorted(set(reference_values) | set(candidate_values))
    differences: list[FieldDifference] = []
    missing = object()
    for name in names:
        reference_value = reference_values.get(name, missing)
        candidate_value = candidate_values.get(name, missing)
        if (
            reference_value is not missing
            and candidate_value is not missing
            and _equal(
                reference_value,
                candidate_value,
            )
        ):
            continue
        reference_json = (
            json.dumps({"type": "missing", "value": None}, separators=(",", ":"))
            if reference_value is missing
            else _json(reference_value)
        )
        candidate_json = (
            json.dumps({"type": "missing", "value": None}, separators=(",", ":"))
            if candidate_value is missing
            else _json(candidate_value)
        )
        decimal_delta = None
        temporal_delta = None
        if isinstance(reference_value, Decimal) and isinstance(
            candidate_value, Decimal
        ):
            decimal_delta = format(candidate_value - reference_value, "f")
        elif isinstance(reference_value, datetime) and isinstance(
            candidate_value, datetime
        ):
            temporal_delta = _elapsed_microseconds(reference_value, candidate_value)
        differences.append(
            FieldDifference(
                name,
                reference_json,
                candidate_json,
                decimal_delta,
                temporal_delta,
            )
        )
    return tuple(differences)


def _record_comparisons(
    reference: tuple[_RecordView, ...],
    candidate: tuple[_RecordView, ...],
    mode: AlignmentMode,
) -> tuple[RecordComparison, ...]:
    reference_groups: dict[str, list[_RecordView]] = defaultdict(list)
    candidate_groups: dict[str, list[_RecordView]] = defaultdict(list)
    for item in reference:
        reference_groups[_alignment_key(item, mode)].append(item)
    for item in candidate:
        candidate_groups[_alignment_key(item, mode)].append(item)
    comparisons: list[RecordComparison] = []
    for key in sorted(set(reference_groups) | set(candidate_groups)):
        reference_items = reference_groups[key]
        candidate_items = candidate_groups[key]
        reference_json = tuple(_json(item.record) for item in reference_items)
        candidate_json = tuple(_json(item.record) for item in candidate_items)
        if max(len(reference_items), len(candidate_items)) > 1:
            status = RecordComparisonStatus.AMBIGUOUS
            differences: tuple[FieldDifference, ...] = ()
        elif not candidate_items:
            status = RecordComparisonStatus.REFERENCE_ONLY
            differences = ()
        elif not reference_items:
            status = RecordComparisonStatus.CANDIDATE_ONLY
            differences = ()
        else:
            differences = _differences(reference_items[0], candidate_items[0])
            status = (
                RecordComparisonStatus.MATCHED_EQUAL
                if not differences
                else RecordComparisonStatus.MATCHED_DIFFERENT
            )
        comparisons.append(
            RecordComparison(
                key,
                status,
                reference_json,
                candidate_json,
                differences,
            )
        )
    return tuple(comparisons)


def _availability_status(
    reference: CanonicalRunArtifacts,
    candidate: CanonicalRunArtifacts,
    level: ComparisonLevel,
) -> LevelComparisonStatus:
    reference_available = level in reference.available_levels
    candidate_available = level in candidate.available_levels
    if reference_available and candidate_available:
        return LevelComparisonStatus.COMPARED
    if reference_available:
        return LevelComparisonStatus.CANDIDATE_UNAVAILABLE
    if candidate_available:
        return LevelComparisonStatus.REFERENCE_UNAVAILABLE
    return LevelComparisonStatus.BOTH_UNAVAILABLE


class ReconciliationComparisonService:
    """Compare requested layers without tolerance, materiality, or attribution."""

    def compare(
        self,
        normalized: NormalizedReconciliation,
        policy: ReconciliationComparisonPolicy,
    ) -> ReconciliationComparison:
        if not isinstance(normalized, NormalizedReconciliation):
            _fail(
                ComparisonErrorCode.INVALID_INPUT,
                "normalized must be a NormalizedReconciliation.",
            )
        if not isinstance(policy, ReconciliationComparisonPolicy):
            _fail(
                ComparisonErrorCode.INVALID_INPUT,
                "policy must be a ReconciliationComparisonPolicy.",
            )
        scope = normalized.scope
        if policy.reconciliation_id != scope.reconciliation_id:
            _fail(
                ComparisonErrorCode.SCOPE_MISMATCH,
                "policy reconciliation_id must match the normalized scope.",
            )
        policy_levels = tuple(item.level for item in policy.levels)
        if policy_levels != scope.requested_levels:
            _fail(
                ComparisonErrorCode.POLICY_MISMATCH,
                "comparison policy must cover exactly the requested levels.",
            )
        if len(normalized.runs) != len(scope.candidate_runs) + 1:
            _fail(
                ComparisonErrorCode.NORMALIZED_INPUT_MISMATCH,
                "normalized runs must contain the reference and every candidate.",
            )
        reference = normalized.runs[0]
        if reference.source_run != scope.reference_run:
            _fail(
                ComparisonErrorCode.NORMALIZED_INPUT_MISMATCH,
                "normalized reference run must exactly match the scope.",
            )
        policy_by_level = {item.level: item for item in policy.levels}
        candidates: list[CandidateComparison] = []
        for expected, candidate in zip(
            scope.candidate_runs,
            normalized.runs[1:],
            strict=True,
        ):
            if candidate.source_run != expected:
                _fail(
                    ComparisonErrorCode.NORMALIZED_INPUT_MISMATCH,
                    "normalized candidate run must exactly match the scope.",
                    candidate_run_id=expected.run_id,
                )
            levels = tuple(
                self._compare_level(
                    reference.artifacts,
                    candidate.artifacts,
                    policy_by_level[level],
                    candidate_run_id=expected.run_id,
                )
                for level in scope.requested_levels
            )
            candidates.append(CandidateComparison(expected, levels))
        return ReconciliationComparison(
            scope,
            normalized.plan_sha256,
            comparison_policy_sha256(policy),
            tuple(candidates),
        )

    @staticmethod
    def _compare_level(
        reference: CanonicalRunArtifacts,
        candidate: CanonicalRunArtifacts,
        policy: LevelComparisonPolicy,
        *,
        candidate_run_id: str,
    ) -> LevelComparison:
        status = _availability_status(reference, candidate, policy.level)
        if status is not LevelComparisonStatus.COMPARED:
            return LevelComparison(policy.level, status, policy.alignment_mode, ())
        try:
            records = _record_comparisons(
                _record_views(reference, policy.level),
                _record_views(candidate, policy.level),
                policy.alignment_mode,
            )
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise ComparisonError(
                ComparisonErrorCode.ALIGNMENT_FAILED,
                "canonical evidence could not be aligned deterministically.",
                candidate_run_id,
                policy.level,
            ) from error
        return LevelComparison(
            policy.level,
            status,
            policy.alignment_mode,
            records,
        )


__all__ = ["ReconciliationComparisonService"]
