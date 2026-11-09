"""Explicit, immutable V1.5E cross-engine normalization policies and evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backtest_auditor.implementation_risk.domain.bundle import CanonicalRunArtifacts
from backtest_auditor.implementation_risk.domain.enums import ComparisonLevel
from backtest_auditor.implementation_risk.domain.scope import (
    EngineRunReference,
    ReconciliationScope,
)
from backtest_auditor.implementation_risk.domain.specification import (
    CanonicalParameter,
    InstrumentReference,
)
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_currency,
    normalize_optional_text,
    normalize_sha256,
    normalize_text,
)


NORMALIZATION_SCHEMA_VERSION = "1.0"
_MAX_IDENTIFIER_LENGTH = 128
_MAX_TEXT_LENGTH = 1024
_MAX_TIMESTAMP_OFFSET_MICROSECONDS = 7 * 24 * 60 * 60 * 1_000_000
_TIME_LEVEL_ORDER = {
    level: index
    for index, level in enumerate(ComparisonLevel)
    if level is not ComparisonLevel.STRATEGY_SPECIFICATION
}
_RuleT = TypeVar("_RuleT")


class FrequencyKind(StrEnum):
    """Whether periods have a fixed elapsed duration or calendar semantics."""

    FIXED = "fixed"
    CALENDAR = "calendar"


class NormalizationDimension(StrEnum):
    """Stable categories retained as normalization evidence."""

    STRATEGY_IDENTITY = "strategy_identity"
    INSTRUMENT_IDENTITY = "instrument_identity"
    SYMBOL = "symbol"
    CURRENCY = "currency"
    TIMESTAMP = "timestamp"
    FREQUENCY = "frequency"


def _identifier(value: object, *, field: str) -> str:
    return normalize_text(value, field=field, maximum_length=_MAX_IDENTIFIER_LENGTH)


def _rationale(value: object) -> str:
    return normalize_text(value, field="rationale", maximum_length=_MAX_TEXT_LENGTH)


@dataclass(frozen=True, slots=True)
class CanonicalFrequency:
    """One comparison frequency; this contract never resamples observations."""

    frequency_id: str
    kind: FrequencyKind
    interval_microseconds: int | None = None
    calendar: str | None = None
    calendar_timezone: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "frequency_id",
            _identifier(self.frequency_id, field="frequency_id"),
        )
        try:
            kind = FrequencyKind(self.kind)
        except (TypeError, ValueError) as error:
            raise ValueError("kind must be a supported FrequencyKind.") from error
        interval = self.interval_microseconds
        calendar = normalize_optional_text(
            self.calendar,
            field="calendar",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        timezone_name = normalize_optional_text(
            self.calendar_timezone,
            field="calendar_timezone",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        if kind is FrequencyKind.FIXED:
            if (
                isinstance(interval, bool)
                or not isinstance(interval, int)
                or interval <= 0
            ):
                raise ValueError(
                    "fixed frequencies require positive integer interval_microseconds."
                )
            if calendar is not None or timezone_name is not None:
                raise ValueError(
                    "fixed frequencies must not declare calendar metadata."
                )
        else:
            if interval is not None:
                raise ValueError(
                    "calendar frequencies must not declare interval_microseconds."
                )
            if calendar is None or timezone_name is None:
                raise ValueError(
                    "calendar frequencies require calendar and calendar_timezone."
                )
            try:
                ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as error:
                raise ValueError(
                    "calendar_timezone must be an IANA timezone."
                ) from error
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "calendar", calendar)
        object.__setattr__(self, "calendar_timezone", timezone_name)


@dataclass(frozen=True, slots=True)
class StrategyIdentityRule:
    source_strategy_id: str
    canonical_strategy_id: str
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_strategy_id",
            _identifier(self.source_strategy_id, field="source_strategy_id"),
        )
        object.__setattr__(
            self,
            "canonical_strategy_id",
            _identifier(self.canonical_strategy_id, field="canonical_strategy_id"),
        )
        object.__setattr__(self, "rationale", _rationale(self.rationale))


@dataclass(frozen=True, slots=True)
class InstrumentIdentityRule:
    source_instrument_id: str
    canonical_instrument: InstrumentReference
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_instrument_id",
            _identifier(self.source_instrument_id, field="source_instrument_id"),
        )
        if not isinstance(self.canonical_instrument, InstrumentReference):
            raise ValueError("canonical_instrument must be an InstrumentReference.")
        object.__setattr__(self, "rationale", _rationale(self.rationale))


@dataclass(frozen=True, slots=True)
class CurrencyNormalizationRule:
    source_currency: str
    canonical_currency: str
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_currency",
            normalize_currency(self.source_currency, field="source_currency"),
        )
        object.__setattr__(
            self,
            "canonical_currency",
            normalize_currency(self.canonical_currency, field="canonical_currency"),
        )
        object.__setattr__(self, "rationale", _rationale(self.rationale))


@dataclass(frozen=True, slots=True)
class TimestampNormalizationRule:
    level: ComparisonLevel
    offset_microseconds: int
    rationale: str

    def __post_init__(self) -> None:
        try:
            level = ComparisonLevel(self.level)
        except (TypeError, ValueError) as error:
            raise ValueError("level must be a supported ComparisonLevel.") from error
        if level is ComparisonLevel.STRATEGY_SPECIFICATION:
            raise ValueError("strategy_specification has no event timestamps to shift.")
        offset = self.offset_microseconds
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise ValueError("offset_microseconds must be an integer.")
        if abs(offset) > _MAX_TIMESTAMP_OFFSET_MICROSECONDS:
            raise ValueError("timestamp offsets must not exceed seven days.")
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "rationale", _rationale(self.rationale))


@dataclass(frozen=True, slots=True)
class FrequencyNormalizationRule:
    canonical_frequency: CanonicalFrequency
    rationale: str
    source_frequency: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_frequency, CanonicalFrequency):
            raise ValueError("canonical_frequency must be a CanonicalFrequency.")
        object.__setattr__(
            self,
            "source_frequency",
            normalize_optional_text(
                self.source_frequency,
                field="source_frequency",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )
        object.__setattr__(self, "rationale", _rationale(self.rationale))


@dataclass(frozen=True, slots=True)
class RunNormalizationPolicy:
    """All explicit normalization assertions for one immutable source run."""

    run: EngineRunReference
    strategy_identity: StrategyIdentityRule | None = None
    instruments: tuple[InstrumentIdentityRule, ...] = ()
    currencies: tuple[CurrencyNormalizationRule, ...] = ()
    timestamps: tuple[TimestampNormalizationRule, ...] = ()
    frequency: FrequencyNormalizationRule | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run, EngineRunReference):
            raise ValueError("run must be an EngineRunReference.")
        if self.strategy_identity is not None and not isinstance(
            self.strategy_identity,
            StrategyIdentityRule,
        ):
            raise ValueError(
                "strategy_identity must be a StrategyIdentityRule or None."
            )
        instruments = self._rules(
            self.instruments,
            InstrumentIdentityRule,
            field="instruments",
        )
        currencies = self._rules(
            self.currencies,
            CurrencyNormalizationRule,
            field="currencies",
        )
        timestamps = self._rules(
            self.timestamps,
            TimestampNormalizationRule,
            field="timestamps",
        )
        self._unique(
            instruments,
            lambda item: item.source_instrument_id,
            "source instrument",
        )
        self._unique(
            instruments,
            lambda item: item.canonical_instrument.instrument_id,
            "canonical instrument",
        )
        self._unique(
            currencies,
            lambda item: item.source_currency,
            "source currency",
        )
        self._unique(
            currencies,
            lambda item: item.canonical_currency,
            "canonical currency",
        )
        self._unique(timestamps, lambda item: item.level, "timestamp level")
        if self.frequency is not None and not isinstance(
            self.frequency,
            FrequencyNormalizationRule,
        ):
            raise ValueError("frequency must be a FrequencyNormalizationRule or None.")
        object.__setattr__(
            self,
            "instruments",
            tuple(sorted(instruments, key=lambda item: item.source_instrument_id)),
        )
        object.__setattr__(
            self,
            "currencies",
            tuple(sorted(currencies, key=lambda item: item.source_currency)),
        )
        object.__setattr__(
            self,
            "timestamps",
            tuple(sorted(timestamps, key=lambda item: _TIME_LEVEL_ORDER[item.level])),
        )

    @staticmethod
    def _rules(
        values: Iterable[_RuleT],
        item_type: type[_RuleT],
        *,
        field: str,
    ) -> tuple[_RuleT, ...]:
        try:
            rules = tuple(values)
        except TypeError as error:
            raise ValueError(f"{field} must be an iterable.") from error
        if any(not isinstance(item, item_type) for item in rules):
            raise ValueError(f"{field} contains an invalid rule type.")
        return rules

    @staticmethod
    def _unique(
        values: tuple[_RuleT, ...],
        key: Callable[[_RuleT], Hashable],
        field: str,
    ) -> None:
        identities = tuple(key(item) for item in values)
        if len(identities) != len(set(identities)):
            raise ValueError(f"{field} rules must be unique.")


@dataclass(frozen=True, slots=True)
class ReconciliationNormalizationPlan:
    reconciliation_id: str
    policies: tuple[RunNormalizationPolicy, ...]
    normalization_schema_version: str = NORMALIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_id",
            _identifier(self.reconciliation_id, field="reconciliation_id"),
        )
        try:
            policies = tuple(self.policies)
        except TypeError as error:
            raise ValueError("policies must be an iterable.") from error
        if not policies or any(
            not isinstance(item, RunNormalizationPolicy) for item in policies
        ):
            raise ValueError(
                "policies must contain at least one RunNormalizationPolicy."
            )
        run_ids = tuple(item.run.run_id for item in policies)
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("policies must not contain duplicate run_id values.")
        canonical_instruments: dict[str, InstrumentReference] = {}
        for policy in policies:
            for rule in policy.instruments:
                instrument = rule.canonical_instrument
                previous = canonical_instruments.setdefault(
                    instrument.instrument_id,
                    instrument,
                )
                if previous != instrument:
                    raise ValueError(
                        "one canonical instrument_id must have identical metadata "
                        "across all run policies."
                    )
        strategy_ids = {
            item.strategy_identity.canonical_strategy_id
            for item in policies
            if item.strategy_identity is not None
        }
        if len(strategy_ids) > 1:
            raise ValueError(
                "all strategy identity rules must use one canonical_strategy_id."
            )
        frequencies = {
            item.frequency.canonical_frequency
            for item in policies
            if item.frequency is not None
        }
        if len(frequencies) > 1:
            raise ValueError("all frequency rules must use one CanonicalFrequency.")
        if self.normalization_schema_version != NORMALIZATION_SCHEMA_VERSION:
            raise ValueError(
                "normalization_schema_version must equal "
                f"{NORMALIZATION_SCHEMA_VERSION!r}."
            )
        object.__setattr__(
            self,
            "policies",
            tuple(sorted(policies, key=lambda item: item.run.run_id)),
        )


@dataclass(frozen=True, slots=True)
class NormalizationChange:
    run_id: str
    dimension: NormalizationDimension
    source_value: str
    normalized_value: str
    rationale: str
    level: ComparisonLevel | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _identifier(self.run_id, field="run_id"))
        try:
            dimension = NormalizationDimension(self.dimension)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "dimension must be a supported NormalizationDimension."
            ) from error
        level = self.level
        if level is not None:
            try:
                level = ComparisonLevel(level)
            except (TypeError, ValueError) as error:
                raise ValueError("level must be a ComparisonLevel or None.") from error
        object.__setattr__(self, "dimension", dimension)
        object.__setattr__(self, "level", level)
        object.__setattr__(
            self,
            "source_value",
            normalize_text(
                self.source_value,
                field="source_value",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "normalized_value",
            normalize_text(
                self.normalized_value,
                field="normalized_value",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )
        object.__setattr__(self, "rationale", _rationale(self.rationale))

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.dimension.value,
            "" if self.level is None else self.level.value,
            self.source_value,
            self.normalized_value,
        )


@dataclass(frozen=True, slots=True)
class NormalizedRunArtifacts:
    source_run: EngineRunReference
    artifacts: CanonicalRunArtifacts
    canonical_bundle_sha256: str
    canonical_frequency: CanonicalFrequency | None
    changes: tuple[NormalizationChange, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_run, EngineRunReference):
            raise ValueError("source_run must be an EngineRunReference.")
        if not isinstance(self.artifacts, CanonicalRunArtifacts):
            raise ValueError("artifacts must be CanonicalRunArtifacts.")
        if self.artifacts.run != self.source_run:
            raise ValueError("normalization must preserve immutable run identity.")
        object.__setattr__(
            self,
            "canonical_bundle_sha256",
            normalize_sha256(
                self.canonical_bundle_sha256,
                field="canonical_bundle_sha256",
            ),
        )
        if self.canonical_frequency is not None and not isinstance(
            self.canonical_frequency,
            CanonicalFrequency,
        ):
            raise ValueError(
                "canonical_frequency must be a CanonicalFrequency or None."
            )
        try:
            changes = tuple(self.changes)
        except TypeError as error:
            raise ValueError("changes must be an iterable.") from error
        if any(not isinstance(item, NormalizationChange) for item in changes):
            raise ValueError("changes contains an invalid record type.")
        if any(item.run_id != self.source_run.run_id for item in changes):
            raise ValueError("every change must reference source_run.run_id.")
        if changes != tuple(sorted(changes, key=lambda item: item.sort_key)):
            raise ValueError("changes must be in canonical order.")
        object.__setattr__(self, "changes", changes)


@dataclass(frozen=True, slots=True)
class NormalizedReconciliation:
    scope: ReconciliationScope
    plan_sha256: str
    runs: tuple[NormalizedRunArtifacts, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ReconciliationScope):
            raise ValueError("scope must be a ReconciliationScope.")
        object.__setattr__(
            self,
            "plan_sha256",
            normalize_sha256(self.plan_sha256, field="plan_sha256"),
        )
        try:
            runs = tuple(self.runs)
        except TypeError as error:
            raise ValueError("runs must be an iterable.") from error
        if any(not isinstance(item, NormalizedRunArtifacts) for item in runs):
            raise ValueError("runs contains an invalid result type.")
        expected = (
            self.scope.reference_run.run_id,
            *(item.run_id for item in self.scope.candidate_runs),
        )
        if tuple(item.source_run.run_id for item in runs) != expected:
            raise ValueError("runs must follow exact reference-then-candidate order.")
        object.__setattr__(self, "runs", runs)


def _parameter_payload(parameter: CanonicalParameter) -> dict[str, object]:
    value = parameter.value
    if hasattr(value, "as_tuple"):
        value = format(value, "f")
    return {"name": parameter.name, "value": value, "unit": parameter.unit}


def _instrument_payload(instrument: InstrumentReference) -> dict[str, object]:
    return {
        "instrument_id": instrument.instrument_id,
        "asset_class": instrument.asset_class.value,
        "symbol": instrument.symbol,
        "currency": instrument.currency,
        "venue": instrument.venue,
        "contract_multiplier": format(instrument.contract_multiplier, "f"),
        "attributes": [_parameter_payload(item) for item in instrument.attributes],
    }


def normalization_plan_to_json(plan: ReconciliationNormalizationPlan) -> str:
    """Serialize one policy canonically for hashing and human inspection."""

    if not isinstance(plan, ReconciliationNormalizationPlan):
        raise ValueError("plan must be a ReconciliationNormalizationPlan.")
    policies: list[dict[str, object]] = []
    for policy in plan.policies:
        frequency = policy.frequency
        policies.append(
            {
                "run": {
                    "run_id": policy.run.run_id,
                    "engine_name": policy.run.engine_name,
                    "engine_version": policy.run.engine_version,
                    "source_sha256": policy.run.source_sha256,
                },
                "strategy_identity": (
                    None
                    if policy.strategy_identity is None
                    else {
                        "source_strategy_id": policy.strategy_identity.source_strategy_id,
                        "canonical_strategy_id": policy.strategy_identity.canonical_strategy_id,
                        "rationale": policy.strategy_identity.rationale,
                    }
                ),
                "instruments": [
                    {
                        "source_instrument_id": item.source_instrument_id,
                        "canonical_instrument": _instrument_payload(
                            item.canonical_instrument
                        ),
                        "rationale": item.rationale,
                    }
                    for item in policy.instruments
                ],
                "currencies": [
                    {
                        "source_currency": item.source_currency,
                        "canonical_currency": item.canonical_currency,
                        "rationale": item.rationale,
                    }
                    for item in policy.currencies
                ],
                "timestamps": [
                    {
                        "level": item.level.value,
                        "offset_microseconds": item.offset_microseconds,
                        "rationale": item.rationale,
                    }
                    for item in policy.timestamps
                ],
                "frequency": (
                    None
                    if frequency is None
                    else {
                        "source_frequency": frequency.source_frequency,
                        "canonical_frequency": {
                            "frequency_id": frequency.canonical_frequency.frequency_id,
                            "kind": frequency.canonical_frequency.kind.value,
                            "interval_microseconds": frequency.canonical_frequency.interval_microseconds,
                            "calendar": frequency.canonical_frequency.calendar,
                            "calendar_timezone": frequency.canonical_frequency.calendar_timezone,
                        },
                        "rationale": frequency.rationale,
                    }
                ),
            }
        )
    payload = {
        "normalization_schema_version": plan.normalization_schema_version,
        "reconciliation_id": plan.reconciliation_id,
        "policies": policies,
    }
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def normalization_plan_sha256(plan: ReconciliationNormalizationPlan) -> str:
    return hashlib.sha256(normalization_plan_to_json(plan).encode("utf-8")).hexdigest()


__all__ = [
    "NORMALIZATION_SCHEMA_VERSION",
    "CanonicalFrequency",
    "CurrencyNormalizationRule",
    "FrequencyKind",
    "FrequencyNormalizationRule",
    "InstrumentIdentityRule",
    "NormalizationChange",
    "NormalizationDimension",
    "NormalizedReconciliation",
    "NormalizedRunArtifacts",
    "ReconciliationNormalizationPlan",
    "RunNormalizationPolicy",
    "StrategyIdentityRule",
    "TimestampNormalizationRule",
    "normalization_plan_sha256",
    "normalization_plan_to_json",
]
