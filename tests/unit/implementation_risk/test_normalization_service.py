from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk import (
    ArtifactReturnConvention,
    AssetClass,
    CanonicalArtifactFileBundleAdapter,
    CanonicalFrequency,
    CanonicalRunArtifacts,
    CashArtifacts,
    CashBalance,
    ComparisonLevel,
    CurrencyNormalizationRule,
    EngineRunReference,
    FrequencyKind,
    FrequencyNormalizationRule,
    InstrumentIdentityRule,
    InstrumentReference,
    NormalizationDimension,
    NormalizationError,
    NormalizationErrorCode,
    ReconciliationNormalizationPlan,
    ReconciliationNormalizationService,
    ReconciliationScope,
    ReturnPoint,
    RunNormalizationPolicy,
    StrategyIdentityRule,
    TimestampNormalizationRule,
)


def _candidate(bundle: CanonicalRunArtifacts) -> CanonicalRunArtifacts:
    return replace(
        bundle,
        run=EngineRunReference("candidate", "other-engine", "2.0", "b" * 64),
    )


def _canonical_instrument(currency: str = "EUR") -> InstrumentReference:
    return InstrumentReference(
        "AAPL.CANONICAL",
        AssetClass.EQUITY,
        "AAPL.US",
        currency,
        "XNAS",
    )


def _frequency(
    *,
    kind: FrequencyKind = FrequencyKind.FIXED,
    interval: int | None = 120_000_000,
) -> CanonicalFrequency:
    if kind is FrequencyKind.CALENDAR:
        return CanonicalFrequency(
            "XNYS-SESSION",
            kind,
            calendar="XNYS",
            calendar_timezone="America/New_York",
        )
    return CanonicalFrequency("PT2M", kind, interval)


def _policy(
    bundle: CanonicalRunArtifacts,
    *,
    shift_microseconds: int = 0,
    include_all_timestamps: bool = False,
    instrument_rules: tuple[InstrumentIdentityRule, ...] | None = None,
    currency_rules: tuple[CurrencyNormalizationRule, ...] | None = None,
    strategy_rule: StrategyIdentityRule | None = None,
    frequency_rule: FrequencyNormalizationRule | None | object = ...,
) -> RunNormalizationPolicy:
    if instrument_rules is None:
        instrument_rules = (
            InstrumentIdentityRule(
                "AAPL.XNAS",
                _canonical_instrument(),
                "vendor cross-reference",
            ),
        )
    if currency_rules is None:
        currency_rules = (
            CurrencyNormalizationRule("USD", "EUR", "same declared denomination"),
        )
    if strategy_rule is None and bundle.specification is not None:
        strategy_rule = StrategyIdentityRule(
            "strategy-1",
            "momentum-canonical",
            "same immutable strategy source",
        )
    if frequency_rule is ...:
        frequency_rule = (
            FrequencyNormalizationRule(
                _frequency(),
                "explicit two-minute comparison interval",
                "one minute" if bundle.specification is not None else None,
            )
            if bundle.specification is not None or bundle.returns is not None
            else None
        )
    levels = (
        tuple(
            level
            for level in bundle.available_levels
            if level is not ComparisonLevel.STRATEGY_SPECIFICATION
        )
        if include_all_timestamps
        else ()
    )
    return RunNormalizationPolicy(
        bundle.run,
        strategy_rule,
        instrument_rules,
        currency_rules,
        tuple(
            TimestampNormalizationRule(level, shift_microseconds, "UTC clock proof")
            for level in levels
        ),
        frequency_rule,  # type: ignore[arg-type]
    )


def _scope(
    reference: CanonicalRunArtifacts,
    candidate: CanonicalRunArtifacts,
) -> ReconciliationScope:
    return ReconciliationScope(
        "reconciliation-1",
        reference.run,
        (candidate.run,),
        tuple(ComparisonLevel),
    )


def _plan(
    reference: CanonicalRunArtifacts,
    candidate: CanonicalRunArtifacts,
    *,
    candidate_shift: int = 30_000_000,
) -> ReconciliationNormalizationPlan:
    return ReconciliationNormalizationPlan(
        "reconciliation-1",
        (
            _policy(reference),
            _policy(
                candidate,
                shift_microseconds=candidate_shift,
                include_all_timestamps=True,
            ),
        ),
    )


def _assert_error(
    code: NormalizationErrorCode,
    function,
) -> NormalizationError:
    with pytest.raises(NormalizationError) as captured:
        function()
    assert captured.value.code is code
    return captured.value


def test_service_normalizes_all_layers_without_mutating_values(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    reference = canonical_file_bundle
    candidate = _candidate(reference)
    scope = _scope(reference, candidate)
    plan = _plan(reference, candidate)
    service = ReconciliationNormalizationService(CanonicalArtifactFileBundleAdapter())

    result = service.normalize(scope, (candidate, reference), plan)
    repeated = service.normalize(scope, (reference, candidate), plan)

    assert result == repeated
    assert tuple(item.source_run.run_id for item in result.runs) == (
        "run-1",
        "candidate",
    )
    assert result.plan_sha256
    assert all(len(item.canonical_bundle_sha256) == 64 for item in result.runs)
    normalized = result.runs[1].artifacts
    assert normalized.run == candidate.run
    assert normalized.available_levels == candidate.available_levels
    assert normalized.specification is not None
    assert normalized.specification.strategy.strategy_id == "momentum-canonical"
    assert normalized.specification.strategy.data_frequency == "PT2M"
    assert normalized.specification.strategy.universe[0].instrument_id == (
        "AAPL.CANONICAL"
    )
    assert normalized.specification.simulation.base_currency == "EUR"
    assert normalized.fills is not None
    assert normalized.fills[0].instrument_id == "AAPL.CANONICAL"
    assert normalized.fills[0].currency == "EUR"
    assert normalized.fills[0].price == candidate.fills[0].price  # type: ignore[index]
    assert normalized.fills[0].timestamp == (
        candidate.fills[0].timestamp + timedelta(seconds=30)  # type: ignore[index]
    )
    assert normalized.market_data[0].available_timestamp == (  # type: ignore[index]
        candidate.market_data[0].available_timestamp + timedelta(seconds=30)  # type: ignore[index,operator]
    )
    assert normalized.signals[0].source_data_timestamp == (  # type: ignore[index]
        candidate.signals[0].source_data_timestamp + timedelta(seconds=30)  # type: ignore[index,operator]
    )
    assert normalized.orders[0].submitted_at == (  # type: ignore[index]
        candidate.orders[0].submitted_at + timedelta(seconds=30)  # type: ignore[index,operator]
    )
    assert normalized.trades[0].closed_at is None  # type: ignore[index]
    assert normalized.cash is not None
    assert normalized.cash.balances[0].currency == "EUR"  # type: ignore[index]
    assert normalized.costs[0].pnl_impact == candidate.costs[0].pnl_impact  # type: ignore[index]
    assert normalized.equity[0].total_equity == candidate.equity[0].total_equity  # type: ignore[index]
    assert normalized.returns[0].value == candidate.returns[0].value  # type: ignore[index]
    assert candidate.fills[0].currency == "USD"  # type: ignore[index]
    assert {item.dimension for item in result.runs[1].changes} == set(
        NormalizationDimension
    )
    assert result.runs[1].changes == tuple(
        sorted(result.runs[1].changes, key=lambda item: item.sort_key)
    )


def test_service_preserves_none_versus_available_empty() -> None:
    reference_run = EngineRunReference("reference", "engine", "1", "a" * 64)
    candidate_run = EngineRunReference("candidate", "engine", "1", "b" * 64)
    reference = CanonicalRunArtifacts(reference_run, orders=())
    candidate = CanonicalRunArtifacts(candidate_run, orders=())
    scope = ReconciliationScope(
        "reconciliation-1",
        reference_run,
        (candidate_run,),
        (ComparisonLevel.ORDER,),
    )
    plan = ReconciliationNormalizationPlan(
        "reconciliation-1",
        (
            _policy(reference, instrument_rules=(), currency_rules=()),
            _policy(candidate, instrument_rules=(), currency_rules=()),
        ),
    )

    result = ReconciliationNormalizationService(
        CanonicalArtifactFileBundleAdapter()
    ).normalize(scope, (reference, candidate), plan)

    assert result.runs[0].artifacts.orders == ()
    assert result.runs[0].artifacts.fills is None
    assert result.runs[0].canonical_frequency is None


def test_service_accepts_explicit_calendar_frequency_without_resampling() -> None:
    t0 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    run_a = EngineRunReference("reference", "engine", "1", "a" * 64)
    run_b = EngineRunReference("candidate", "engine", "1", "b" * 64)
    reference = CanonicalRunArtifacts(
        run_a,
        returns=(
            ReturnPoint(
                t0,
                t0 + timedelta(hours=23),
                Decimal("0.1"),
                ArtifactReturnConvention.SIMPLE,
            ),
        ),
    )
    candidate = replace(reference, run=run_b)
    calendar_rule = FrequencyNormalizationRule(
        _frequency(kind=FrequencyKind.CALENDAR, interval=None),
        "exchange session evidence",
    )
    policies = tuple(
        _policy(
            bundle,
            instrument_rules=(),
            currency_rules=(),
            frequency_rule=calendar_rule,
        )
        for bundle in (reference, candidate)
    )
    scope = ReconciliationScope(
        "reconciliation-1", run_a, (run_b,), (ComparisonLevel.RETURN,)
    )

    result = ReconciliationNormalizationService(
        CanonicalArtifactFileBundleAdapter()
    ).normalize(
        scope,
        (reference, candidate),
        ReconciliationNormalizationPlan("reconciliation-1", policies),
    )

    assert result.runs[0].artifacts.returns == reference.returns
    assert result.runs[0].canonical_frequency.kind is FrequencyKind.CALENDAR  # type: ignore[union-attr]


def test_service_rejects_invalid_top_level_inputs_and_scope_coverage(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    reference = canonical_file_bundle
    candidate = _candidate(reference)
    scope = _scope(reference, candidate)
    plan = _plan(reference, candidate)
    service = ReconciliationNormalizationService(CanonicalArtifactFileBundleAdapter())

    with pytest.raises(ValueError, match="canonical_identity"):
        ReconciliationNormalizationService(object())  # type: ignore[arg-type]
    _assert_error(
        NormalizationErrorCode.INVALID_INPUT,
        lambda: service.normalize("bad", (reference, candidate), plan),  # type: ignore[arg-type]
    )
    _assert_error(
        NormalizationErrorCode.INVALID_INPUT,
        lambda: service.normalize(scope, (reference, candidate), "bad"),  # type: ignore[arg-type]
    )
    _assert_error(
        NormalizationErrorCode.SCOPE_MISMATCH,
        lambda: service.normalize(
            scope, (reference, candidate), replace(plan, reconciliation_id="other")
        ),
    )
    _assert_error(
        NormalizationErrorCode.INVALID_INPUT,
        lambda: service.normalize(scope, None, plan),  # type: ignore[arg-type]
    )
    _assert_error(
        NormalizationErrorCode.INVALID_INPUT,
        lambda: service.normalize(scope, (reference, "bad"), plan),  # type: ignore[arg-type]
    )
    _assert_error(
        NormalizationErrorCode.SCOPE_MISMATCH,
        lambda: service.normalize(scope, (reference, reference), plan),
    )
    _assert_error(
        NormalizationErrorCode.SCOPE_MISMATCH,
        lambda: service.normalize(scope, (reference,), plan),
    )
    incomplete_plan = ReconciliationNormalizationPlan(
        "reconciliation-1", (_policy(reference),)
    )
    _assert_error(
        NormalizationErrorCode.POLICY_MISMATCH,
        lambda: service.normalize(scope, (reference, candidate), incomplete_plan),
    )

    mismatched_scope = replace(
        scope,
        reference_run=replace(reference.run, engine_version="different"),
    )
    _assert_error(
        NormalizationErrorCode.SCOPE_MISMATCH,
        lambda: service.normalize(mismatched_scope, (reference, candidate), plan),
    )
    mismatched_policy = replace(
        _policy(reference),
        run=replace(reference.run, engine_version="different"),
    )
    altered_plan = ReconciliationNormalizationPlan(
        "reconciliation-1", (mismatched_policy, _policy(candidate))
    )
    _assert_error(
        NormalizationErrorCode.POLICY_MISMATCH,
        lambda: service.normalize(scope, (reference, candidate), altered_plan),
    )


@pytest.mark.parametrize(
    ("field", "rules", "code"),
    [
        ("instruments", (), NormalizationErrorCode.MISSING_INSTRUMENT_RULE),
        (
            "instruments",
            (
                InstrumentIdentityRule(
                    "unused",
                    InstrumentReference("UNUSED", AssetClass.EQUITY, "UNUSED", "EUR"),
                    "why",
                ),
            ),
            NormalizationErrorCode.MISSING_INSTRUMENT_RULE,
        ),
        ("currencies", (), NormalizationErrorCode.MISSING_CURRENCY_RULE),
        (
            "currencies",
            (CurrencyNormalizationRule("GBP", "GBP", "why"),),
            NormalizationErrorCode.MISSING_CURRENCY_RULE,
        ),
    ],
)
def test_service_requires_exhaustive_identity_rules(
    canonical_file_bundle: CanonicalRunArtifacts,
    field: str,
    rules: tuple[object, ...],
    code: NormalizationErrorCode,
) -> None:
    policy = replace(_policy(canonical_file_bundle), **{field: rules})
    service = ReconciliationNormalizationService(CanonicalArtifactFileBundleAdapter())

    error = _assert_error(
        code,
        lambda: service._normalize_run(canonical_file_bundle, policy),
    )

    assert error.run_id == canonical_file_bundle.run.run_id


def test_service_rejects_unused_identity_rules(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    base = _policy(canonical_file_bundle)
    extra_instrument = InstrumentIdentityRule(
        "unused",
        InstrumentReference("UNUSED", AssetClass.EQUITY, "UNUSED", "EUR"),
        "why",
    )
    extra_currency = CurrencyNormalizationRule("GBP", "GBP", "why")
    service = ReconciliationNormalizationService(CanonicalArtifactFileBundleAdapter())

    _assert_error(
        NormalizationErrorCode.UNEXPECTED_INSTRUMENT_RULE,
        lambda: service._normalize_run(
            canonical_file_bundle,
            replace(base, instruments=(*base.instruments, extra_instrument)),
        ),
    )
    _assert_error(
        NormalizationErrorCode.UNEXPECTED_CURRENCY_RULE,
        lambda: service._normalize_run(
            canonical_file_bundle,
            replace(base, currencies=(*base.currencies, extra_currency)),
        ),
    )


def test_service_rejects_timestamp_and_frequency_policy_mismatches(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    run = EngineRunReference("minimal", "engine", "1", "c" * 64)
    minimal = CanonicalRunArtifacts(run)
    service = ReconciliationNormalizationService(CanonicalArtifactFileBundleAdapter())
    timestamp = TimestampNormalizationRule(ComparisonLevel.FILL, 0, "why")
    timestamp_policy = replace(
        _policy(
            minimal,
            instrument_rules=(),
            currency_rules=(),
            frequency_rule=None,
        ),
        timestamps=(timestamp,),
    )
    _assert_error(
        NormalizationErrorCode.POLICY_MISMATCH,
        lambda: service._normalize_run(minimal, timestamp_policy),
    )

    no_frequency = replace(_policy(canonical_file_bundle), frequency=None)
    _assert_error(
        NormalizationErrorCode.FREQUENCY_MISMATCH,
        lambda: service._normalize_run(canonical_file_bundle, no_frequency),
    )
    unexpected_frequency = _policy(
        minimal,
        instrument_rules=(),
        currency_rules=(),
        frequency_rule=FrequencyNormalizationRule(_frequency(), "why"),
    )
    _assert_error(
        NormalizationErrorCode.FREQUENCY_MISMATCH,
        lambda: service._normalize_run(minimal, unexpected_frequency),
    )
    wrong_source = replace(
        _policy(canonical_file_bundle).frequency,
        source_frequency="wrong",
    )
    _assert_error(
        NormalizationErrorCode.FREQUENCY_MISMATCH,
        lambda: service._normalize_run(
            canonical_file_bundle,
            replace(_policy(canonical_file_bundle), frequency=wrong_source),
        ),
    )
    return_only = CanonicalRunArtifacts(
        run,
        returns=(
            ReturnPoint(
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                Decimal(0),
                ArtifactReturnConvention.SIMPLE,
            ),
        ),
    )
    attested_source = FrequencyNormalizationRule(_frequency(), "why", "1m")
    _assert_error(
        NormalizationErrorCode.FREQUENCY_MISMATCH,
        lambda: service._normalize_run(
            return_only,
            _policy(
                return_only,
                instrument_rules=(),
                currency_rules=(),
                frequency_rule=attested_source,
            ),
        ),
    )
    _assert_error(
        NormalizationErrorCode.FREQUENCY_MISMATCH,
        lambda: service._normalize_run(
            return_only,
            _policy(return_only, instrument_rules=(), currency_rules=()),
        ),
    )


def test_service_rejects_strategy_and_instrument_metadata_mismatches(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    service = ReconciliationNormalizationService(CanonicalArtifactFileBundleAdapter())
    base = _policy(canonical_file_bundle)
    missing_identity = replace(base, strategy_identity=None)
    wrong_identity = replace(
        base,
        strategy_identity=StrategyIdentityRule("wrong", "canonical", "why"),
    )
    wrong_metadata = replace(
        base,
        instruments=(
            InstrumentIdentityRule(
                "AAPL.XNAS",
                replace(_canonical_instrument(), contract_multiplier=Decimal(2)),
                "why",
            ),
        ),
    )
    for policy in (missing_identity, wrong_identity):
        _assert_error(
            NormalizationErrorCode.STRATEGY_IDENTITY_MISMATCH,
            lambda policy=policy: service._normalize_run(canonical_file_bundle, policy),
        )
    _assert_error(
        NormalizationErrorCode.INSTRUMENT_METADATA_MISMATCH,
        lambda: service._normalize_run(canonical_file_bundle, wrong_metadata),
    )

    run = EngineRunReference("minimal", "engine", "1", "c" * 64)
    minimal = CanonicalRunArtifacts(run)
    identity_without_spec = _policy(
        minimal,
        instrument_rules=(),
        currency_rules=(),
        strategy_rule=StrategyIdentityRule("source", "canonical", "why"),
        frequency_rule=None,
    )
    _assert_error(
        NormalizationErrorCode.STRATEGY_IDENTITY_MISMATCH,
        lambda: service._normalize_run(minimal, identity_without_spec),
    )


def test_service_wraps_timestamp_contract_cash_and_identity_failures(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    service = ReconciliationNormalizationService(CanonicalArtifactFileBundleAdapter())
    with pytest.raises(NormalizationError) as overflow:
        service._shift_timestamp(
            datetime.max.replace(tzinfo=timezone.utc),
            1,
            run_id="run",
            level=ComparisonLevel.FILL,
        )
    assert overflow.value.code is NormalizationErrorCode.TIMESTAMP_OVERFLOW

    cash = CashArtifacts(
        balances=(
            CashBalance(datetime(2026, 1, 1, tzinfo=timezone.utc), "EUR", Decimal(1)),
            CashBalance(datetime(2026, 1, 1, tzinfo=timezone.utc), "USD", Decimal(1)),
        )
    )
    _assert_error(
        NormalizationErrorCode.NORMALIZED_CONTRACT_VIOLATION,
        lambda: service._normalize_cash(
            cash,
            {"EUR": "USD", "USD": "USD"},
            lambda value, _level: value,
        ),
    )

    base = _policy(canonical_file_bundle)
    broken_time = replace(
        base,
        timestamps=(
            TimestampNormalizationRule(
                ComparisonLevel.SIGNAL, 7 * 60 * 1_000_000, "why"
            ),
        ),
    )
    _assert_error(
        NormalizationErrorCode.NORMALIZED_CONTRACT_VIOLATION,
        lambda: service._normalize_run(canonical_file_bundle, broken_time),
    )

    class FailingIdentity:
        def content_sha256(self, bundle: CanonicalRunArtifacts) -> str:
            raise ValueError("failed")

    failing_service = ReconciliationNormalizationService(FailingIdentity())
    _assert_error(
        NormalizationErrorCode.IDENTITY_FAILED,
        lambda: failing_service._normalize_run(canonical_file_bundle, base),
    )
