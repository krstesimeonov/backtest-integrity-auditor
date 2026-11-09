from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk import (
    AssetClass,
    CanonicalFrequency,
    CanonicalParameter,
    CanonicalRunArtifacts,
    ComparisonLevel,
    CurrencyNormalizationRule,
    EngineRunReference,
    FrequencyKind,
    FrequencyNormalizationRule,
    InstrumentIdentityRule,
    InstrumentReference,
    NormalizationChange,
    NormalizationDimension,
    NormalizationError,
    NormalizedReconciliation,
    NormalizedRunArtifacts,
    ReconciliationNormalizationPlan,
    ReconciliationScope,
    RunNormalizationPolicy,
    StrategyIdentityRule,
    TimestampNormalizationRule,
    normalization_plan_sha256,
    normalization_plan_to_json,
)


def _run(run_id: str, digest: str = "a") -> EngineRunReference:
    return EngineRunReference(run_id, "engine", "1.0", digest * 64)


def _instrument(
    instrument_id: str = "AAPL",
    *,
    symbol: str = "AAPL",
    currency: str = "USD",
) -> InstrumentReference:
    return InstrumentReference(
        instrument_id,
        AssetClass.EQUITY,
        symbol,
        currency,
        "XNAS",
        Decimal(1),
        (
            CanonicalParameter("multiplier_source", Decimal("1.0")),
            CanonicalParameter("vendor", "AAPL"),
        ),
    )


def _frequency() -> CanonicalFrequency:
    return CanonicalFrequency("PT1M", FrequencyKind.FIXED, 60_000_000)


def _policy(
    run: EngineRunReference | None = None,
    *,
    target: InstrumentReference | None = None,
    canonical_strategy_id: str = "canonical-strategy",
    frequency: CanonicalFrequency | None = None,
) -> RunNormalizationPolicy:
    source_run = run or _run("run-1")
    return RunNormalizationPolicy(
        source_run,
        StrategyIdentityRule("source-strategy", canonical_strategy_id, "same code"),
        (InstrumentIdentityRule("source-id", target or _instrument(), "same asset"),),
        (CurrencyNormalizationRule("usd", "USD", "same denomination"),),
        (TimestampNormalizationRule(ComparisonLevel.FILL, 1, "clock evidence"),),
        FrequencyNormalizationRule(
            frequency or _frequency(),
            "same sampling contract",
            "one minute",
        ),
    )


def _plan(*policies: RunNormalizationPolicy) -> ReconciliationNormalizationPlan:
    return ReconciliationNormalizationPlan("reconciliation-1", policies or (_policy(),))


def test_frequency_contracts_distinguish_fixed_and_calendar_semantics() -> None:
    fixed = _frequency()
    calendar = CanonicalFrequency(
        "XNYS-SESSION",
        "calendar",  # type: ignore[arg-type]
        calendar="XNYS",
        calendar_timezone="America/New_York",
    )

    assert fixed.kind is FrequencyKind.FIXED
    assert calendar.kind is FrequencyKind.CALENDAR

    invalid_values = (
        {"kind": "unknown", "interval_microseconds": 1},
        {"kind": FrequencyKind.FIXED, "interval_microseconds": None},
        {"kind": FrequencyKind.FIXED, "interval_microseconds": True},
        {
            "kind": FrequencyKind.FIXED,
            "interval_microseconds": 1,
            "calendar": "XNYS",
        },
        {"kind": FrequencyKind.CALENDAR, "interval_microseconds": 1},
        {"kind": FrequencyKind.CALENDAR},
        {
            "kind": FrequencyKind.CALENDAR,
            "calendar": "XNYS",
            "calendar_timezone": "Not/AZone",
        },
    )
    for values in invalid_values:
        with pytest.raises(ValueError):
            CanonicalFrequency("frequency", **values)  # type: ignore[arg-type]


def test_rule_contracts_normalize_values_and_reject_unsupported_inputs() -> None:
    target = _instrument()
    strategy = StrategyIdentityRule(" source ", " target ", " exact ")
    instrument = InstrumentIdentityRule(" source ", target, " exact ")
    currency = CurrencyNormalizationRule("usd", "eur", " relabel ")
    timestamp = TimestampNormalizationRule("fill", -12, " offset ")  # type: ignore[arg-type]
    frequency = FrequencyNormalizationRule(_frequency(), " exact ", " 1m ")

    assert strategy.source_strategy_id == "source"
    assert instrument.canonical_instrument is target
    assert (currency.source_currency, currency.canonical_currency) == ("USD", "EUR")
    assert timestamp.level is ComparisonLevel.FILL
    assert frequency.source_frequency == "1m"

    invalid_factories = (
        lambda: InstrumentIdentityRule("id", "bad", "why"),  # type: ignore[arg-type]
        lambda: TimestampNormalizationRule("bad", 0, "why"),  # type: ignore[arg-type]
        lambda: TimestampNormalizationRule(
            ComparisonLevel.STRATEGY_SPECIFICATION, 0, "why"
        ),
        lambda: TimestampNormalizationRule(ComparisonLevel.FILL, True, "why"),
        lambda: TimestampNormalizationRule(
            ComparisonLevel.FILL, 7 * 24 * 60 * 60 * 1_000_000 + 1, "why"
        ),
        lambda: FrequencyNormalizationRule("bad", "why"),  # type: ignore[arg-type]
    )
    for factory in invalid_factories:
        with pytest.raises(ValueError):
            factory()


def test_run_policy_canonicalizes_rule_order_and_rejects_ambiguous_rules() -> None:
    run = _run("run")
    first = InstrumentIdentityRule("b", _instrument("B"), "why")
    second = InstrumentIdentityRule("a", _instrument("A"), "why")
    usd = CurrencyNormalizationRule("USD", "USD", "why")
    eur = CurrencyNormalizationRule("EUR", "EUR", "why")
    order = TimestampNormalizationRule(ComparisonLevel.ORDER, 0, "why")
    fill = TimestampNormalizationRule(ComparisonLevel.FILL, 0, "why")
    policy = RunNormalizationPolicy(
        run,
        instruments=(first, second),
        currencies=(usd, eur),
        timestamps=(fill, order),
    )

    assert tuple(item.source_instrument_id for item in policy.instruments) == ("a", "b")
    assert tuple(item.source_currency for item in policy.currencies) == ("EUR", "USD")
    assert tuple(item.level for item in policy.timestamps) == (
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
    )

    with pytest.raises(ValueError, match="run"):
        RunNormalizationPolicy("bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="strategy_identity"):
        RunNormalizationPolicy(run, strategy_identity="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="iterable"):
        RunNormalizationPolicy(run, instruments=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid rule"):
        RunNormalizationPolicy(run, currencies=("bad",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="source instrument"):
        RunNormalizationPolicy(run, instruments=(first, first))
    with pytest.raises(ValueError, match="canonical instrument"):
        RunNormalizationPolicy(
            run,
            instruments=(
                first,
                InstrumentIdentityRule("other", _instrument("B"), "why"),
            ),
        )
    with pytest.raises(ValueError, match="source currency"):
        RunNormalizationPolicy(run, currencies=(usd, usd))
    with pytest.raises(ValueError, match="canonical currency"):
        RunNormalizationPolicy(
            run,
            currencies=(usd, CurrencyNormalizationRule("EUR", "USD", "why")),
        )
    with pytest.raises(ValueError, match="timestamp level"):
        RunNormalizationPolicy(run, timestamps=(fill, fill))
    with pytest.raises(ValueError, match="frequency"):
        RunNormalizationPolicy(run, frequency="bad")  # type: ignore[arg-type]


def test_plan_is_globally_consistent_canonical_and_deterministic() -> None:
    reference = _policy(_run("reference", "a"))
    candidate = _policy(_run("candidate", "b"))
    plan = _plan(reference, candidate)
    reverse = _plan(candidate, reference)
    payload = json.loads(normalization_plan_to_json(plan))

    assert tuple(item.run.run_id for item in plan.policies) == (
        "candidate",
        "reference",
    )
    assert normalization_plan_to_json(plan) == normalization_plan_to_json(reverse)
    assert normalization_plan_sha256(plan) == normalization_plan_sha256(reverse)
    assert payload["normalization_schema_version"] == "1.0"
    assert payload["policies"][0]["frequency"]["canonical_frequency"] == {
        "calendar": None,
        "calendar_timezone": None,
        "frequency_id": "PT1M",
        "interval_microseconds": 60_000_000,
        "kind": "fixed",
    }
    with pytest.raises(ValueError, match="plan"):
        normalization_plan_to_json("bad")  # type: ignore[arg-type]


def test_plan_rejects_incomplete_duplicate_or_inconsistent_policy_sets() -> None:
    run = _run("run")
    policy = _policy(run)
    with pytest.raises(ValueError, match="iterable"):
        ReconciliationNormalizationPlan("id", None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one"):
        ReconciliationNormalizationPlan("id", ())
    with pytest.raises(ValueError, match="at least one"):
        ReconciliationNormalizationPlan("id", ("bad",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="duplicate"):
        ReconciliationNormalizationPlan("id", (policy, policy))
    with pytest.raises(ValueError, match="schema"):
        replace(_plan(policy), normalization_schema_version="2.0")

    changed_metadata = _policy(
        _run("other", "b"),
        target=replace(_instrument(), symbol="OTHER"),
    )
    with pytest.raises(ValueError, match="metadata"):
        _plan(policy, changed_metadata)
    with pytest.raises(ValueError, match="canonical_strategy_id"):
        _plan(policy, _policy(_run("other", "b"), canonical_strategy_id="different"))
    with pytest.raises(ValueError, match="CanonicalFrequency"):
        _plan(
            policy,
            _policy(
                _run("other", "b"),
                frequency=CanonicalFrequency("PT2M", FrequencyKind.FIXED, 120_000_000),
            ),
        )


def test_change_and_error_evidence_are_typed_and_contextual() -> None:
    change = NormalizationChange(
        " run ",
        "timestamp",  # type: ignore[arg-type]
        " UTC ",
        " UTC+1us ",
        " evidence ",
        "fill",  # type: ignore[arg-type]
    )
    error = NormalizationError(
        "frequency_mismatch",  # type: ignore[arg-type]
        " mismatch ",
        " run ",
        "return",  # type: ignore[arg-type]
        " data_frequency ",
    )

    assert change.dimension is NormalizationDimension.TIMESTAMP
    assert change.sort_key == ("timestamp", "fill", "UTC", "UTC+1us")
    assert str(error) == (
        "frequency_mismatch: mismatch (run=run, level=return, field=data_frequency)"
    )

    invalid_changes = (
        lambda: replace(change, dimension="bad"),
        lambda: replace(change, level="bad"),
    )
    for factory in invalid_changes:
        with pytest.raises(ValueError):
            factory()
    with pytest.raises(ValueError, match="code"):
        replace(error, code="bad")
    with pytest.raises(ValueError, match="message"):
        replace(error, message=" ")
    with pytest.raises(ValueError, match="level"):
        replace(error, level="bad")
    with pytest.raises(ValueError, match="run_id"):
        replace(error, run_id=" ")


def test_normalized_outputs_preserve_run_identity_scope_order_and_hashes() -> None:
    reference = _run("reference")
    candidate = _run("candidate", "b")
    scope = ReconciliationScope(
        "reconciliation-1",
        reference,
        (candidate,),
        (ComparisonLevel.RETURN,),
    )
    reference_output = NormalizedRunArtifacts(
        reference,
        CanonicalRunArtifacts(reference),
        "c" * 64,
        None,
        [],  # type: ignore[arg-type]
    )
    candidate_output = NormalizedRunArtifacts(
        candidate,
        CanonicalRunArtifacts(candidate),
        "d" * 64,
        None,
        (),
    )
    result = NormalizedReconciliation(
        scope,
        "e" * 64,
        (reference_output, candidate_output),
    )

    assert result.runs == (reference_output, candidate_output)
    assert reference_output.changes == ()

    with pytest.raises(ValueError, match="source_run"):
        replace(reference_output, source_run="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="artifacts"):
        replace(reference_output, artifacts="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="preserve"):
        replace(reference_output, artifacts=CanonicalRunArtifacts(candidate))
    with pytest.raises(ValueError, match="canonical_frequency"):
        replace(reference_output, canonical_frequency="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="iterable"):
        replace(reference_output, changes=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid record"):
        replace(reference_output, changes=("bad",))  # type: ignore[arg-type]
    foreign = NormalizationChange(
        "other", NormalizationDimension.CURRENCY, "USD", "USD", "why"
    )
    with pytest.raises(ValueError, match="source_run"):
        replace(reference_output, changes=(foreign,))
    later = NormalizationChange(
        "reference", NormalizationDimension.TIMESTAMP, "a", "b", "why"
    )
    earlier = NormalizationChange(
        "reference", NormalizationDimension.CURRENCY, "a", "b", "why"
    )
    with pytest.raises(ValueError, match="canonical order"):
        replace(reference_output, changes=(later, earlier))

    with pytest.raises(ValueError, match="scope"):
        replace(result, scope="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="iterable"):
        replace(result, runs=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid"):
        replace(result, runs=("bad",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="reference-then-candidate"):
        replace(result, runs=(candidate_output, reference_output))
