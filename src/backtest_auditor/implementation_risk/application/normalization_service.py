"""Fail-closed V1.5E normalization of scoped canonical engine evidence."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, NoReturn, TypeVar

from backtest_auditor.implementation_risk.application.normalization_errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from backtest_auditor.implementation_risk.application.ports import (
    CanonicalArtifactBundleIdentity,
)
from backtest_auditor.implementation_risk.domain import (
    CanonicalRunArtifacts,
    CanonicalRunSpecification,
    CashArtifacts,
    ComparisonLevel,
    CurrencyNormalizationRule,
    FrequencyKind,
    InstrumentIdentityRule,
    NormalizationChange,
    NormalizationDimension,
    NormalizedReconciliation,
    NormalizedRunArtifacts,
    ReconciliationNormalizationPlan,
    ReconciliationScope,
    RunNormalizationPolicy,
    normalization_plan_sha256,
)


_TIME_LEVELS = frozenset(ComparisonLevel) - {ComparisonLevel.STRATEGY_SPECIFICATION}
_RecordT = TypeVar("_RecordT")


def _fail(
    code: NormalizationErrorCode,
    message: str,
    *,
    run_id: str | None = None,
    level: ComparisonLevel | None = None,
    field: str | None = None,
) -> NoReturn:
    raise NormalizationError(code, message, run_id, level, field)


def _exact_collection(
    supplied: set[str],
    required: set[str],
    *,
    missing_code: NormalizationErrorCode,
    unexpected_code: NormalizationErrorCode,
    noun: str,
    run_id: str,
) -> None:
    missing = sorted(required - supplied)
    if missing:
        _fail(
            missing_code,
            f"normalization rules are missing {noun}: {', '.join(missing)}.",
            run_id=run_id,
        )
    unexpected = sorted(supplied - required)
    if unexpected:
        _fail(
            unexpected_code,
            f"normalization rules contain unused {noun}: {', '.join(unexpected)}.",
            run_id=run_id,
        )


def _used_instruments(bundle: CanonicalRunArtifacts) -> set[str]:
    values: set[str] = set()
    if bundle.specification is not None:
        values.update(
            item.instrument_id for item in bundle.specification.strategy.universe
        )
    for records in (
        bundle.market_data,
        bundle.signals,
        bundle.orders,
        bundle.fills,
        bundle.trades,
        bundle.positions,
    ):
        if records is not None:
            values.update(item.instrument_id for item in records)
    return values


def _used_currencies(bundle: CanonicalRunArtifacts) -> set[str]:
    values: set[str] = set()
    if bundle.specification is not None:
        values.add(bundle.specification.simulation.base_currency)
        values.update(item.currency for item in bundle.specification.strategy.universe)
    for records in (
        bundle.fills,
        bundle.trades,
        bundle.positions,
        bundle.costs,
        bundle.equity,
    ):
        if records is not None:
            values.update(item.currency for item in records)
    if bundle.cash is not None:
        if bundle.cash.balances is not None:
            values.update(item.currency for item in bundle.cash.balances)
        if bundle.cash.movements is not None:
            values.update(item.currency for item in bundle.cash.movements)
    return values


def _elapsed_microseconds(start: datetime, end: datetime) -> int:
    value = end - start
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds


class ReconciliationNormalizationService:
    """Normalize exactly the runs declared by one reconciliation scope."""

    def __init__(self, canonical_identity: CanonicalArtifactBundleIdentity) -> None:
        if not isinstance(canonical_identity, CanonicalArtifactBundleIdentity):
            raise ValueError(
                "canonical_identity must implement CanonicalArtifactBundleIdentity."
            )
        self._canonical_identity = canonical_identity

    def normalize(
        self,
        scope: ReconciliationScope,
        artifacts: Iterable[CanonicalRunArtifacts],
        plan: ReconciliationNormalizationPlan,
    ) -> NormalizedReconciliation:
        if not isinstance(scope, ReconciliationScope):
            _fail(
                NormalizationErrorCode.INVALID_INPUT,
                "scope must be a ReconciliationScope.",
            )
        if not isinstance(plan, ReconciliationNormalizationPlan):
            _fail(
                NormalizationErrorCode.INVALID_INPUT,
                "plan must be a ReconciliationNormalizationPlan.",
            )
        if plan.reconciliation_id != scope.reconciliation_id:
            _fail(
                NormalizationErrorCode.SCOPE_MISMATCH,
                "plan reconciliation_id must match the scope.",
            )
        try:
            bundles = tuple(artifacts)
        except TypeError as error:
            raise NormalizationError(
                NormalizationErrorCode.INVALID_INPUT,
                "artifacts must be an iterable.",
            ) from error
        if any(not isinstance(item, CanonicalRunArtifacts) for item in bundles):
            _fail(
                NormalizationErrorCode.INVALID_INPUT,
                "artifacts must contain only CanonicalRunArtifacts.",
            )

        expected_runs = (scope.reference_run, *scope.candidate_runs)
        expected_ids = tuple(item.run_id for item in expected_runs)
        bundle_by_id = self._indexed_bundles(bundles)
        policy_by_id = {item.run.run_id: item for item in plan.policies}
        if set(bundle_by_id) != set(expected_ids):
            _fail(
                NormalizationErrorCode.SCOPE_MISMATCH,
                "artifacts must contain exactly the runs declared by the scope.",
            )
        if set(policy_by_id) != set(expected_ids):
            _fail(
                NormalizationErrorCode.POLICY_MISMATCH,
                "plan policies must cover exactly the runs declared by the scope.",
            )

        normalized: list[NormalizedRunArtifacts] = []
        for expected in expected_runs:
            bundle = bundle_by_id[expected.run_id]
            policy = policy_by_id[expected.run_id]
            if bundle.run != expected:
                _fail(
                    NormalizationErrorCode.SCOPE_MISMATCH,
                    "artifact run identity must exactly match the scope.",
                    run_id=expected.run_id,
                )
            if policy.run != expected:
                _fail(
                    NormalizationErrorCode.POLICY_MISMATCH,
                    "policy run identity must exactly match the scope.",
                    run_id=expected.run_id,
                )
            normalized.append(self._normalize_run(bundle, policy))
        return NormalizedReconciliation(
            scope=scope,
            plan_sha256=normalization_plan_sha256(plan),
            runs=tuple(normalized),
        )

    @staticmethod
    def _indexed_bundles(
        bundles: tuple[CanonicalRunArtifacts, ...],
    ) -> dict[str, CanonicalRunArtifacts]:
        indexed: dict[str, CanonicalRunArtifacts] = {}
        for bundle in bundles:
            run_id = bundle.run.run_id
            if run_id in indexed:
                _fail(
                    NormalizationErrorCode.SCOPE_MISMATCH,
                    "artifacts must not contain duplicate run_id values.",
                    run_id=run_id,
                )
            indexed[run_id] = bundle
        return indexed

    def _normalize_run(
        self,
        bundle: CanonicalRunArtifacts,
        policy: RunNormalizationPolicy,
    ) -> NormalizedRunArtifacts:
        run_id = bundle.run.run_id
        instrument_rules = {
            item.source_instrument_id: item for item in policy.instruments
        }
        currency_rules = {item.source_currency: item for item in policy.currencies}
        _exact_collection(
            set(instrument_rules),
            _used_instruments(bundle),
            missing_code=NormalizationErrorCode.MISSING_INSTRUMENT_RULE,
            unexpected_code=NormalizationErrorCode.UNEXPECTED_INSTRUMENT_RULE,
            noun="instrument IDs",
            run_id=run_id,
        )
        _exact_collection(
            set(currency_rules),
            _used_currencies(bundle),
            missing_code=NormalizationErrorCode.MISSING_CURRENCY_RULE,
            unexpected_code=NormalizationErrorCode.UNEXPECTED_CURRENCY_RULE,
            noun="currencies",
            run_id=run_id,
        )
        time_rules = {item.level: item for item in policy.timestamps}
        unexpected_time_levels = set(time_rules) - (
            set(bundle.available_levels) & _TIME_LEVELS
        )
        if unexpected_time_levels:
            _fail(
                NormalizationErrorCode.POLICY_MISMATCH,
                "timestamp rules may target only available timestamped levels.",
                run_id=run_id,
                level=sorted(
                    unexpected_time_levels,
                    key=lambda item: tuple(ComparisonLevel).index(item),
                )[0],
            )
        self._validate_frequency(bundle, policy)
        specification = self._normalize_specification(
            bundle,
            policy,
            instrument_rules,
            currency_rules,
        )

        instrument_id = {
            source: rule.canonical_instrument.instrument_id
            for source, rule in instrument_rules.items()
        }
        currency = {
            source: rule.canonical_currency for source, rule in currency_rules.items()
        }

        def shift(value: datetime, level: ComparisonLevel) -> datetime:
            return self._shift_timestamp(
                value,
                time_rules[level].offset_microseconds if level in time_rules else 0,
                run_id=run_id,
                level=level,
            )

        def optional_shift(
            value: datetime | None,
            level: ComparisonLevel,
        ) -> datetime | None:
            return None if value is None else shift(value, level)

        market_data = self._mapped(
            bundle.market_data,
            lambda item: replace(
                item,
                instrument_id=instrument_id[item.instrument_id],
                event_timestamp=shift(
                    item.event_timestamp,
                    ComparisonLevel.MARKET_DATA,
                ),
                available_timestamp=optional_shift(
                    item.available_timestamp,
                    ComparisonLevel.MARKET_DATA,
                ),
            ),
            key=lambda item: (
                item.event_timestamp,
                item.available_timestamp or item.event_timestamp,
                item.instrument_id,
                item.field,
                item.observation_id,
            ),
        )
        signals = self._mapped(
            bundle.signals,
            lambda item: replace(
                item,
                timestamp=shift(item.timestamp, ComparisonLevel.SIGNAL),
                source_data_timestamp=optional_shift(
                    item.source_data_timestamp,
                    ComparisonLevel.SIGNAL,
                ),
                instrument_id=instrument_id[item.instrument_id],
            ),
            key=lambda item: (item.timestamp, item.signal_id),
        )
        orders = self._mapped(
            bundle.orders,
            lambda item: replace(
                item,
                created_at=shift(item.created_at, ComparisonLevel.ORDER),
                submitted_at=optional_shift(
                    item.submitted_at,
                    ComparisonLevel.ORDER,
                ),
                last_updated_at=optional_shift(
                    item.last_updated_at,
                    ComparisonLevel.ORDER,
                ),
                expires_at=optional_shift(
                    item.expires_at,
                    ComparisonLevel.ORDER,
                ),
                instrument_id=instrument_id[item.instrument_id],
            ),
            key=lambda item: (item.created_at, item.order_id),
        )
        fills = self._mapped(
            bundle.fills,
            lambda item: replace(
                item,
                timestamp=shift(item.timestamp, ComparisonLevel.FILL),
                instrument_id=instrument_id[item.instrument_id],
                currency=currency[item.currency],
            ),
            key=lambda item: (item.timestamp, item.fill_id),
        )
        trades = self._mapped(
            bundle.trades,
            lambda item: replace(
                item,
                opened_at=shift(item.opened_at, ComparisonLevel.TRADE),
                closed_at=optional_shift(
                    item.closed_at,
                    ComparisonLevel.TRADE,
                ),
                instrument_id=instrument_id[item.instrument_id],
                currency=currency[item.currency],
            ),
            key=lambda item: (item.opened_at, item.trade_id),
        )
        positions = self._mapped(
            bundle.positions,
            lambda item: replace(
                item,
                timestamp=shift(item.timestamp, ComparisonLevel.POSITION),
                instrument_id=instrument_id[item.instrument_id],
                currency=currency[item.currency],
            ),
            key=lambda item: (item.timestamp, item.instrument_id),
        )
        cash = self._normalize_cash(bundle.cash, currency, shift)
        costs = self._mapped(
            bundle.costs,
            lambda item: replace(
                item,
                timestamp=shift(item.timestamp, ComparisonLevel.COST),
                currency=currency[item.currency],
            ),
            key=lambda item: (item.timestamp, item.cost_id),
        )
        equity = self._mapped(
            bundle.equity,
            lambda item: replace(
                item,
                timestamp=shift(item.timestamp, ComparisonLevel.EQUITY),
                currency=currency[item.currency],
            ),
            key=lambda item: item.timestamp,
        )
        returns = self._mapped(
            bundle.returns,
            lambda item: replace(
                item,
                start_timestamp=shift(
                    item.start_timestamp,
                    ComparisonLevel.RETURN,
                ),
                end_timestamp=shift(
                    item.end_timestamp,
                    ComparisonLevel.RETURN,
                ),
            ),
            key=lambda item: (item.end_timestamp, item.start_timestamp),
        )
        try:
            normalized = CanonicalRunArtifacts(
                run=bundle.run,
                specification=specification,
                market_data=market_data,
                signals=signals,
                orders=orders,
                fills=fills,
                trades=trades,
                positions=positions,
                cash=cash,
                costs=costs,
                equity=equity,
                returns=returns,
                artifact_schema_version=bundle.artifact_schema_version,
            )
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.NORMALIZED_CONTRACT_VIOLATION,
                "normalized artifacts violate the canonical cross-record contract.",
                run_id=run_id,
            ) from error
        try:
            canonical_sha256 = self._canonical_identity.content_sha256(normalized)
        except (TypeError, ValueError) as error:
            raise NormalizationError(
                NormalizationErrorCode.IDENTITY_FAILED,
                "normalized artifacts could not receive a deterministic identity.",
                run_id=run_id,
            ) from error
        changes = tuple(
            sorted(
                self._changes(bundle, policy),
                key=lambda item: item.sort_key,
            )
        )
        return NormalizedRunArtifacts(
            source_run=bundle.run,
            artifacts=normalized,
            canonical_bundle_sha256=canonical_sha256,
            canonical_frequency=(
                None
                if policy.frequency is None
                else policy.frequency.canonical_frequency
            ),
            changes=changes,
        )

    @staticmethod
    def _mapped(
        records: tuple[_RecordT, ...] | None,
        mapper: Callable[[_RecordT], _RecordT],
        *,
        key: Callable[[_RecordT], Any],
    ) -> tuple[_RecordT, ...] | None:
        if records is None:
            return None
        return tuple(sorted((mapper(item) for item in records), key=key))

    @staticmethod
    def _normalize_cash(
        cash: CashArtifacts | None,
        currency: Mapping[str, str],
        shift: Callable[[datetime, ComparisonLevel], datetime],
    ) -> CashArtifacts | None:
        if cash is None:
            return None
        balances = None
        if cash.balances is not None:
            balances = tuple(
                sorted(
                    (
                        replace(
                            item,
                            timestamp=shift(item.timestamp, ComparisonLevel.CASH),
                            currency=currency[item.currency],
                        )
                        for item in cash.balances
                    ),
                    key=lambda item: (item.timestamp, item.currency),
                )
            )
        movements = None
        if cash.movements is not None:
            movements = tuple(
                sorted(
                    (
                        replace(
                            item,
                            timestamp=shift(item.timestamp, ComparisonLevel.CASH),
                            currency=currency[item.currency],
                        )
                        for item in cash.movements
                    ),
                    key=lambda item: (item.timestamp, item.movement_id),
                )
            )
        try:
            return CashArtifacts(balances=balances, movements=movements)
        except ValueError as error:
            raise NormalizationError(
                NormalizationErrorCode.NORMALIZED_CONTRACT_VIOLATION,
                "cash normalization created duplicate or invalid records.",
                level=ComparisonLevel.CASH,
            ) from error

    @staticmethod
    def _shift_timestamp(
        timestamp: datetime,
        offset_microseconds: int,
        *,
        run_id: str,
        level: ComparisonLevel,
    ) -> datetime:
        try:
            return timestamp + timedelta(microseconds=offset_microseconds)
        except OverflowError as error:
            raise NormalizationError(
                NormalizationErrorCode.TIMESTAMP_OVERFLOW,
                "timestamp offset exceeds the datetime range.",
                run_id=run_id,
                level=level,
            ) from error

    @staticmethod
    def _validate_frequency(
        bundle: CanonicalRunArtifacts,
        policy: RunNormalizationPolicy,
    ) -> None:
        required = bundle.specification is not None or bundle.returns is not None
        if required and policy.frequency is None:
            _fail(
                NormalizationErrorCode.FREQUENCY_MISMATCH,
                "frequency-bearing evidence requires an explicit frequency rule.",
                run_id=bundle.run.run_id,
            )
        if not required and policy.frequency is not None:
            _fail(
                NormalizationErrorCode.FREQUENCY_MISMATCH,
                "a frequency rule requires strategy or return evidence.",
                run_id=bundle.run.run_id,
            )
        if policy.frequency is None:
            return
        source_frequency = policy.frequency.source_frequency
        if bundle.specification is not None:
            actual = bundle.specification.strategy.data_frequency
            if source_frequency != actual:
                _fail(
                    NormalizationErrorCode.FREQUENCY_MISMATCH,
                    "source_frequency must exactly match strategy data_frequency.",
                    run_id=bundle.run.run_id,
                    field="data_frequency",
                )
        elif source_frequency is not None:
            _fail(
                NormalizationErrorCode.FREQUENCY_MISMATCH,
                "source_frequency cannot be attested without strategy specification.",
                run_id=bundle.run.run_id,
            )
        canonical = policy.frequency.canonical_frequency
        if canonical.kind is FrequencyKind.FIXED and bundle.returns is not None:
            expected = canonical.interval_microseconds
            assert expected is not None
            if any(
                _elapsed_microseconds(item.start_timestamp, item.end_timestamp)
                != expected
                for item in bundle.returns
            ):
                _fail(
                    NormalizationErrorCode.FREQUENCY_MISMATCH,
                    "return intervals do not match the declared fixed frequency.",
                    run_id=bundle.run.run_id,
                    level=ComparisonLevel.RETURN,
                )

    @staticmethod
    def _normalize_specification(
        bundle: CanonicalRunArtifacts,
        policy: RunNormalizationPolicy,
        instrument_rules: Mapping[str, InstrumentIdentityRule],
        currency_rules: Mapping[str, CurrencyNormalizationRule],
    ) -> CanonicalRunSpecification | None:
        specification = bundle.specification
        if specification is None:
            if policy.strategy_identity is not None:
                _fail(
                    NormalizationErrorCode.STRATEGY_IDENTITY_MISMATCH,
                    "strategy identity cannot be asserted without specification evidence.",
                    run_id=bundle.run.run_id,
                )
            return None
        identity = policy.strategy_identity
        if (
            identity is None
            or identity.source_strategy_id != specification.strategy.strategy_id
        ):
            _fail(
                NormalizationErrorCode.STRATEGY_IDENTITY_MISMATCH,
                "strategy identity rule must match the source strategy_id.",
                run_id=bundle.run.run_id,
            )
        canonical_universe = []
        for source in specification.strategy.universe:
            target = instrument_rules[source.instrument_id].canonical_instrument
            mapped_currency = currency_rules[source.currency].canonical_currency
            if (
                source.asset_class is not target.asset_class
                or source.contract_multiplier != target.contract_multiplier
                or mapped_currency != target.currency
            ):
                _fail(
                    NormalizationErrorCode.INSTRUMENT_METADATA_MISMATCH,
                    "normalization cannot change asset class, multiplier, or denomination.",
                    run_id=bundle.run.run_id,
                    field=source.instrument_id,
                )
            canonical_universe.append(target)
        assert policy.frequency is not None
        strategy = replace(
            specification.strategy,
            strategy_id=identity.canonical_strategy_id,
            universe=tuple(canonical_universe),
            data_frequency=policy.frequency.canonical_frequency.frequency_id,
        )
        simulation = replace(
            specification.simulation,
            base_currency=currency_rules[
                specification.simulation.base_currency
            ].canonical_currency,
        )
        return replace(specification, strategy=strategy, simulation=simulation)

    @staticmethod
    def _changes(
        bundle: CanonicalRunArtifacts,
        policy: RunNormalizationPolicy,
    ) -> list[NormalizationChange]:
        run_id = bundle.run.run_id
        changes: list[NormalizationChange] = []
        if policy.strategy_identity is not None:
            strategy_rule = policy.strategy_identity
            changes.append(
                NormalizationChange(
                    run_id,
                    NormalizationDimension.STRATEGY_IDENTITY,
                    strategy_rule.source_strategy_id,
                    strategy_rule.canonical_strategy_id,
                    strategy_rule.rationale,
                )
            )
        source_instruments = (
            {}
            if bundle.specification is None
            else {
                item.instrument_id: item
                for item in bundle.specification.strategy.universe
            }
        )
        for instrument_rule in policy.instruments:
            target = instrument_rule.canonical_instrument
            changes.append(
                NormalizationChange(
                    run_id,
                    NormalizationDimension.INSTRUMENT_IDENTITY,
                    instrument_rule.source_instrument_id,
                    target.instrument_id,
                    instrument_rule.rationale,
                )
            )
            source = source_instruments.get(instrument_rule.source_instrument_id)
            if source is not None:
                changes.append(
                    NormalizationChange(
                        run_id,
                        NormalizationDimension.SYMBOL,
                        source.symbol,
                        target.symbol,
                        instrument_rule.rationale,
                    )
                )
        for currency_rule in policy.currencies:
            changes.append(
                NormalizationChange(
                    run_id,
                    NormalizationDimension.CURRENCY,
                    currency_rule.source_currency,
                    currency_rule.canonical_currency,
                    currency_rule.rationale,
                )
            )
        for timestamp_rule in policy.timestamps:
            changes.append(
                NormalizationChange(
                    run_id,
                    NormalizationDimension.TIMESTAMP,
                    f"{timestamp_rule.level.value}:UTC",
                    f"{timestamp_rule.level.value}:UTC{timestamp_rule.offset_microseconds:+d}us",
                    timestamp_rule.rationale,
                    timestamp_rule.level,
                )
            )
        if policy.frequency is not None:
            frequency_rule = policy.frequency
            changes.append(
                NormalizationChange(
                    run_id,
                    NormalizationDimension.FREQUENCY,
                    frequency_rule.source_frequency or "explicit interval evidence",
                    frequency_rule.canonical_frequency.frequency_id,
                    frequency_rule.rationale,
                )
            )
        return changes


__all__ = ["ReconciliationNormalizationService"]
