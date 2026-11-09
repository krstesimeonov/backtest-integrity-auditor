"""Shared end-to-end checks for the five engine adapters.

Each ``test_<engine>.py`` runs the toy strategy natively, exports it, maps it
with the shipped adapter and then calls the functions here, so every engine is
held to the same assertions and the same implementation-risk policy:

* ``write_and_validate`` writes the canonical bundle (ZIP and directory),
  validates ``manifest.json`` against the published canonical-bundle 1.0 JSON
  Schema, and reads both containers back through the strict bundle reader;
* ``assert_fills_match`` / ``assert_costs_match`` / ``assert_trades_match`` /
  ``assert_final_equity`` compare the bundle with ``reference.expected_run``
  using the tolerances stated in ``strategy_spec.md``;
* ``implementation_risk`` runs the V1.5 implementation-risk audit with the
  reference bundle (built here from ``reference.py`` alone) as the baseline and
  the engine bundle as the candidate, and validates the JSON report against the
  published implementation-risk report 1.0 schema.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import jsonschema
import pandas as pd
from referencing import Registry, Resource

from backtest_auditor.implementation_risk import (
    AlignmentMode,
    ArtifactReturnConvention,
    AssetClass,
    AttributionRule,
    CanonicalArtifactFileBundleAdapter,
    CanonicalFrequency,
    CanonicalRunArtifacts,
    CashArtifacts,
    CashBalance,
    ComparisonLevel,
    CostRecord,
    CostType,
    CurrencyNormalizationRule,
    DivergenceFamily,
    DivergenceFieldRule,
    DivergenceMeasurementPolicy,
    EngineRunReference,
    EquityPoint,
    FamilyWeight,
    FillRecord,
    FrequencyKind,
    FrequencyNormalizationRule,
    IMPLEMENTATION_RISK_SCHEMA_FILES,
    ImplementationRiskAuditResult,
    ImplementationRiskAuditService,
    InstrumentIdentityRule,
    InstrumentReference,
    LevelComparisonPolicy,
    MaterialityRule,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    ReconciliationComparisonPolicy,
    ReconciliationNormalizationPlan,
    ReturnPoint,
    RiskAssessmentPolicy,
    RunNormalizationPolicy,
    TimeInForce,
    TradeDirection,
    TradeRecord,
    load_canonical_bundle_schema,
    load_implementation_risk_schema,
    render_implementation_risk_json,
)
from backtest_auditor.implementation_risk.domain import ImplementationRiskFindingKind

from e2e import reference

RECONCILIATION_ID = "w3-j12-toy-ma-cross"
REFERENCE_RUN_ID = "reference-pandas"

# Tolerances (strategy_spec.md, "Tolerances"). Quantities and sides are exact.
PRICE_TOLERANCE = Decimal("0.000001")
FEE_TOLERANCE = Decimal("0.000001")
EQUITY_TOLERANCE = Decimal("0.000001")


# --------------------------------------------------------------------------
# Reference bundle
# --------------------------------------------------------------------------


def _source_sha256() -> str:
    digest = hashlib.sha256()
    for path in (Path(reference.__file__), reference.PRICES_CSV):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _utc(value: pd.Timestamp) -> datetime:
    return value.tz_convert("UTC").to_pydatetime()


def reference_artifacts(
    *,
    lag: int = reference.EXECUTION_LAG_BARS,
    positions_at: str = "bar",
    cash_at: str = "bar",
    prestart: pd.Timestamp | None = None,
    equity_at: Iterable[pd.Timestamp] | None = None,
) -> CanonicalRunArtifacts:
    """The reference run as canonical artifacts, built from reference.py only.

    ``positions_at="bar"`` emits one position snapshot per bar (what the
    vectorbt, bt and Backtrader adapters emit); ``"fill"`` emits one snapshot
    after each fill (what the LEAN and NautilusTrader adapters document).
    ``cash_at="fill"`` likewise emits the initial balance at the first bar
    plus one balance after each fill (an event-driven account report).
    ``prestart`` adds the initial capital as one more observation at that
    instant, before the first bar (bt's virtual row one day before the data):
    position 0, cash and equity = initial cash, and a zero return into bar 0.
    ``equity_at`` samples equity (and the returns between samples) at the
    given instants instead of at each bar: the reference equity as of each
    instant, i.e. after the last bar at or before it, or the initial cash
    before the first bar (LEAN samples at every New York midnight and close).
    """

    run = reference.expected_run(lag=lag)
    instrument = reference.INSTRUMENT
    currency = reference.CURRENCY
    orders = []
    fills = []
    costs = []
    for number, row in enumerate(run.fills.itertuples(index=False), start=1):
        timestamp = _utc(row.timestamp)
        side = OrderSide(row.side)
        orders.append(
            OrderRecord(
                f"order-{number}",
                timestamp,
                instrument,
                side,
                row.quantity,
                OrderType.MARKET,
                TimeInForce.DAY,
                OrderStatus.FILLED,
                submitted_at=timestamp,
                last_updated_at=timestamp,
            )
        )
        fills.append(
            FillRecord(
                f"fill-{number}",
                f"order-{number}",
                timestamp,
                instrument,
                side,
                row.quantity,
                row.price,
                currency,
            )
        )
        costs.append(
            CostRecord(
                f"cost-{number}",
                timestamp,
                CostType.COMMISSION,
                -row.fee,
                currency,
                order_id=f"order-{number}",
                fill_id=f"fill-{number}",
            )
        )
    trades = []
    for number, row in enumerate(run.trades.itertuples(index=False), start=1):
        trades.append(
            TradeRecord(
                f"trade-{number}",
                instrument,
                TradeDirection(row.direction),
                _utc(row.opened_at),
                row.quantity,
                row.entry_price,
                currency,
                "reference-round-trip",
                closed_at=_utc(row.closed_at),
                exit_price=row.exit_price,
                realized_pnl=row.net_pnl,
                fill_ids=(f"fill-{2 * number - 1}", f"fill-{2 * number}"),
            )
        )
    ledger = run.ledger
    if prestart is not None:
        assert prestart < ledger.index[0]
        start = pd.DataFrame(
            {
                "position": [0],
                "close": [None],
                "cash": [reference.INITIAL_CASH],
                "equity": [reference.INITIAL_CASH],
            },
            index=pd.DatetimeIndex([prestart], name=ledger.index.name),
        )
        ledger = pd.concat([start, ledger])
    if positions_at == "bar":
        position_rows = ledger
    elif positions_at == "fill":
        position_rows = ledger.loc[[item for item in run.fills["timestamp"]]]
    else:
        raise ValueError(positions_at)
    positions = tuple(
        PositionSnapshot(
            _utc(timestamp),
            instrument,
            Decimal(int(row.position)),
            currency,
        )
        for timestamp, row in position_rows.iterrows()
    )
    if cash_at == "bar":
        cash_rows = ledger
    elif cash_at == "fill":
        cash_rows = ledger.loc[[ledger.index[0], *run.fills["timestamp"]]]
    else:
        raise ValueError(cash_at)
    balances = tuple(
        CashBalance(_utc(timestamp), currency, row.cash)
        for timestamp, row in cash_rows.iterrows()
    )
    if equity_at is None:
        equity_series = [
            (timestamp, row.equity) for timestamp, row in ledger.iterrows()
        ]
        cash_by_instant = dict(zip(ledger.index, ledger["cash"], strict=True))
    else:
        equity_series = [
            (instant, _equity_as_of(ledger, instant)) for instant in sorted(equity_at)
        ]
        cash_by_instant = {}
    equity = tuple(
        EquityPoint(
            _utc(timestamp), currency, value, cash=cash_by_instant.get(timestamp)
        )
        for timestamp, value in equity_series
    )
    returns = tuple(
        ReturnPoint(
            _utc(start),
            _utc(end),
            end_value / start_value - 1,
            ArtifactReturnConvention.SIMPLE,
        )
        for (start, start_value), (end, end_value) in zip(
            equity_series[:-1], equity_series[1:], strict=True
        )
    )
    return CanonicalRunArtifacts(
        run=EngineRunReference(
            REFERENCE_RUN_ID
            if lag == reference.EXECUTION_LAG_BARS
            else f"{REFERENCE_RUN_ID}-lag{lag}",
            "pandas-reference",
            pd.__version__,
            _source_sha256(),
        ),
        orders=tuple(orders),
        fills=tuple(fills),
        trades=tuple(trades),
        positions=positions,
        cash=CashArtifacts(balances=balances),
        costs=tuple(costs),
        equity=equity,
        returns=returns,
    )


def _equity_as_of(ledger: pd.DataFrame, instant: pd.Timestamp) -> Decimal:
    seen = ledger.loc[ledger.index <= instant]
    return reference.INITIAL_CASH if seen.empty else seen["equity"].iloc[-1]


def restrict(
    artifacts: CanonicalRunArtifacts, levels: Iterable[ComparisonLevel]
) -> CanonicalRunArtifacts:
    """Keep only the requested evidence levels (the others become unavailable)."""

    keep = set(levels)
    return CanonicalRunArtifacts(
        run=artifacts.run,
        orders=artifacts.orders if ComparisonLevel.ORDER in keep else None,
        fills=artifacts.fills if ComparisonLevel.FILL in keep else None,
        trades=artifacts.trades if ComparisonLevel.TRADE in keep else None,
        positions=artifacts.positions if ComparisonLevel.POSITION in keep else None,
        cash=artifacts.cash if ComparisonLevel.CASH in keep else None,
        costs=artifacts.costs if ComparisonLevel.COST in keep else None,
        equity=artifacts.equity if ComparisonLevel.EQUITY in keep else None,
        returns=artifacts.returns if ComparisonLevel.RETURN in keep else None,
    )


# --------------------------------------------------------------------------
# Bundle writing and schema validation
# --------------------------------------------------------------------------


def write_and_validate(
    artifacts: CanonicalRunArtifacts, directory: Path, name: str
) -> CanonicalRunArtifacts:
    """Write ZIP and directory bundles, schema-validate, and read both back."""

    adapter = CanonicalArtifactFileBundleAdapter()
    directory.mkdir(parents=True, exist_ok=True)
    zip_path = adapter.write(artifacts, directory / f"{name}.zip")
    dir_path = adapter.write(artifacts, directory / name)
    schema = load_canonical_bundle_schema("canonical_artifact_bundle_manifest_1_0")
    manifest = json.loads((Path(dir_path) / "manifest.json").read_text("utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(manifest)
    assert manifest["bundle_schema_version"] == "1.0"
    from_zip = adapter.read(zip_path)
    from_dir = adapter.read(dir_path)
    assert from_zip == from_dir == artifacts
    return from_zip


# --------------------------------------------------------------------------
# Direct comparison with the reference trade list
# --------------------------------------------------------------------------


def _close(actual: Decimal, expected: Decimal, tolerance: Decimal) -> bool:
    return abs(Decimal(actual) - Decimal(expected)) <= tolerance


def assert_fills_match(
    artifacts: CanonicalRunArtifacts,
    expected: reference.ExpectedRun,
    *,
    instrument_id: str = reference.INSTRUMENT,
) -> None:
    fills = sorted(artifacts.fills or (), key=lambda item: item.timestamp)
    rows = list(expected.fills.itertuples(index=False))
    assert len(fills) == len(rows), (len(fills), len(rows))
    for fill, row in zip(fills, rows, strict=True):
        where = f"fill at {fill.timestamp.isoformat()}"
        assert fill.timestamp == _utc(row.timestamp), (where, row.timestamp)
        assert fill.instrument_id == instrument_id, where
        assert fill.side is OrderSide(row.side), (where, fill.side, row.side)
        assert fill.quantity == row.quantity, (where, fill.quantity, row.quantity)
        assert _close(fill.price, row.price, PRICE_TOLERANCE), (
            where,
            fill.price,
            row.price,
        )
        assert fill.currency == reference.CURRENCY, where


def assert_costs_match(
    artifacts: CanonicalRunArtifacts,
    expected: reference.ExpectedRun,
    *,
    linked_to_fills: bool = True,
) -> None:
    """One commission of -FEE per reference fill, at the fill's timestamp."""

    costs = sorted(artifacts.costs or (), key=lambda item: item.timestamp)
    rows = list(expected.fills.itertuples(index=False))
    assert len(costs) == len(rows), (len(costs), len(rows))
    fills_by_id = {item.fill_id: item for item in artifacts.fills or ()}
    for cost, row in zip(costs, rows, strict=True):
        where = f"cost at {cost.timestamp.isoformat()}"
        assert cost.timestamp == _utc(row.timestamp), (where, row.timestamp)
        assert cost.cost_type is CostType.COMMISSION, (where, cost.cost_type)
        assert _close(cost.pnl_impact, -row.fee, FEE_TOLERANCE), (
            where,
            cost.pnl_impact,
            -row.fee,
        )
        assert cost.currency == reference.CURRENCY, where
        if linked_to_fills:
            assert cost.fill_id in fills_by_id, (where, cost.fill_id)
            assert fills_by_id[cost.fill_id].timestamp == cost.timestamp, where


def assert_trades_match(
    artifacts: CanonicalRunArtifacts,
    expected: reference.ExpectedRun,
    *,
    pnl: str = "net_pnl",
    instrument_id: str = reference.INSTRUMENT,
) -> None:
    trades = sorted(artifacts.trades or (), key=lambda item: item.opened_at)
    rows = list(expected.trades.itertuples(index=False))
    assert len(trades) == len(rows), (len(trades), len(rows))
    for trade, row in zip(trades, rows, strict=True):
        where = f"trade opened {trade.opened_at.isoformat()}"
        assert trade.instrument_id == instrument_id, where
        assert trade.direction is TradeDirection(row.direction), (
            where,
            trade.direction,
            row.direction,
        )
        assert trade.opened_at == _utc(row.opened_at), where
        assert trade.closed_at == _utc(row.closed_at), where
        assert trade.quantity == row.quantity, (where, trade.quantity)
        assert _close(trade.entry_price, row.entry_price, PRICE_TOLERANCE), where
        assert trade.exit_price is not None
        assert _close(trade.exit_price, row.exit_price, PRICE_TOLERANCE), where
        assert trade.realized_pnl is not None, where
        assert _close(trade.realized_pnl, getattr(row, pnl), EQUITY_TOLERANCE), (
            where,
            trade.realized_pnl,
            getattr(row, pnl),
        )


def assert_fills_imply_round_trips(
    artifacts: CanonicalRunArtifacts, expected: reference.ExpectedRun
) -> None:
    """For adapters without a trade level: the fills pair into the round trips.

    Consecutive fills open and close one position; its direction comes from
    the opening side, its net P&L from the two prices, the quantity and the
    two costs at those instants. This checks sign handling on the short.
    """

    fills = sorted(artifacts.fills or (), key=lambda item: item.timestamp)
    costs = {item.timestamp: item.pnl_impact for item in artifacts.costs or ()}
    rows = list(expected.trades.itertuples(index=False))
    assert len(fills) == 2 * len(rows), (len(fills), len(rows))
    for opening, closing, row in zip(fills[0::2], fills[1::2], rows, strict=True):
        where = f"round trip opened {opening.timestamp.isoformat()}"
        assert closing.side is not opening.side, where
        assert opening.quantity == closing.quantity == row.quantity, where
        direction = (
            TradeDirection.LONG
            if opening.side is OrderSide.BUY
            else TradeDirection.SHORT
        )
        assert direction is TradeDirection(row.direction), (where, direction)
        assert opening.timestamp == _utc(row.opened_at), where
        assert closing.timestamp == _utc(row.closed_at), where
        sign = 1 if direction is TradeDirection.LONG else -1
        gross = sign * (closing.price - opening.price) * opening.quantity
        net = gross + costs[opening.timestamp] + costs[closing.timestamp]
        assert _close(net, row.net_pnl, EQUITY_TOLERANCE), (where, net, row.net_pnl)


def assert_final_equity(
    artifacts: CanonicalRunArtifacts, expected: reference.ExpectedRun
) -> Decimal:
    """The last equity point equals the reference's final equity."""

    points = sorted(artifacts.equity or (), key=lambda item: item.timestamp)
    assert points, "bundle has no equity evidence"
    last = points[-1]
    assert last.timestamp == _utc(expected.ledger.index[-1]), last.timestamp
    assert _close(last.total_equity, expected.final_equity, EQUITY_TOLERANCE), (
        last.total_equity,
        expected.final_equity,
    )
    return last.total_equity


def assert_final_cash(
    artifacts: CanonicalRunArtifacts, expected: reference.ExpectedRun
) -> Decimal:
    """For cash-only bundles: the strategy ends flat, so final cash = equity."""

    assert expected.ledger["position"].iloc[-1] == 0
    balances = sorted(
        (artifacts.cash and artifacts.cash.balances) or (),
        key=lambda item: item.timestamp,
    )
    assert balances, "bundle has no cash balances"
    last = balances[-1]
    assert _close(last.total, expected.final_equity, EQUITY_TOLERANCE), (
        last.total,
        expected.final_equity,
    )
    return last.total


# --------------------------------------------------------------------------
# Implementation-risk run
# --------------------------------------------------------------------------

# (family, level, field, materiality threshold). Thresholds sit far above
# float noise (strategy_spec.md, "Implementation-risk policy") and far below
# the smallest economic effect of a one-bar shift.
MEASURED_FIELDS: tuple[tuple[DivergenceFamily, ComparisonLevel, str, Decimal], ...] = (
    (DivergenceFamily.SIZING, ComparisonLevel.FILL, "quantity", Decimal("0.5")),
    (DivergenceFamily.ACCOUNTING, ComparisonLevel.FILL, "price", Decimal("0.005")),
    (
        DivergenceFamily.TRANSACTION_COST,
        ComparisonLevel.COST,
        "pnl_impact",
        Decimal("0.005"),
    ),
    (DivergenceFamily.SIZING, ComparisonLevel.POSITION, "quantity", Decimal("0.5")),
    (DivergenceFamily.SIZING, ComparisonLevel.TRADE, "quantity", Decimal("0.5")),
    (
        DivergenceFamily.ACCOUNTING,
        ComparisonLevel.TRADE,
        "realized_pnl",
        Decimal("0.01"),
    ),
    (DivergenceFamily.ACCOUNTING, ComparisonLevel.CASH, "total", Decimal("0.01")),
    (
        DivergenceFamily.ACCOUNTING,
        ComparisonLevel.EQUITY,
        "total_equity",
        Decimal("0.01"),
    ),
    (DivergenceFamily.RETURN, ComparisonLevel.RETURN, "value", Decimal("0.00000001")),
)
EXTREME_MULTIPLE = Decimal(10)
BUSINESS_DAYS = CanonicalFrequency(
    "B",
    FrequencyKind.CALENDAR,
    calendar="weekdays-synthetic",
    calendar_timezone=reference.EXCHANGE_TIMEZONE,
)


_REPORT_SCHEMAS = Registry().with_resources(
    [
        (schema["$id"], Resource.from_contents(schema))
        for schema in (
            load_implementation_risk_schema(name)
            for name in IMPLEMENTATION_RISK_SCHEMA_FILES
        )
    ]
)


@dataclass(frozen=True)
class RiskRun:
    result: ImplementationRiskAuditResult
    report: dict

    def kinds(self) -> Counter[str]:
        return Counter(item.kind.value for item in self.result.findings)

    def codes(self, kind: ImplementationRiskFindingKind) -> list[str]:
        return [item.code for item in self.result.findings if item.kind is kind]

    @property
    def adverse(self) -> list[str]:
        return [
            f"{item.code}: {item.summary}"
            for item in self.result.findings
            if item.kind is ImplementationRiskFindingKind.ADVERSE
        ]

    @property
    def gaps(self) -> list[str]:
        return [
            f"{item.code}: {item.summary}"
            for item in self.result.findings
            if item.kind is ImplementationRiskFindingKind.EVIDENCE_GAP
        ]

    def adverse_families(self) -> set[str]:
        return {
            item.family.value
            for item in self.result.findings
            if item.kind is ImplementationRiskFindingKind.ADVERSE and item.family
        }

    def level(self, level: ComparisonLevel):  # -> LevelComparison
        candidate = self.result.comparison.candidates[0]
        return next(item for item in candidate.levels if item.level is level)


def _run_policy(
    artifacts: CanonicalRunArtifacts,
    instrument_ids: Iterable[str],
    timestamp_rules: tuple = (),
) -> RunNormalizationPolicy:
    canonical = InstrumentReference(
        reference.INSTRUMENT,
        AssetClass.EQUITY,
        reference.INSTRUMENT,
        reference.CURRENCY,
    )
    return RunNormalizationPolicy(
        artifacts.run,
        instruments=tuple(
            InstrumentIdentityRule(
                source,
                canonical,
                "The synthetic instrument under the engine's own identifier.",
            )
            for source in sorted(set(instrument_ids))
        ),
        currencies=(
            CurrencyNormalizationRule(
                reference.CURRENCY, reference.CURRENCY, "No FX conversion."
            ),
        ),
        timestamps=timestamp_rules,
        frequency=(
            FrequencyNormalizationRule(
                BUSINESS_DAYS, "Weekday session closes of the synthetic series."
            )
            if artifacts.returns is not None
            else None
        ),
    )


def _instrument_ids(artifacts: CanonicalRunArtifacts) -> set[str]:
    found: set[str] = set()
    for collection in (
        artifacts.orders,
        artifacts.fills,
        artifacts.trades,
        artifacts.positions,
    ):
        found.update(item.instrument_id for item in collection or ())
    return found


def implementation_risk(
    reference_bundle: CanonicalRunArtifacts,
    candidate_bundle: CanonicalRunArtifacts | Sequence[CanonicalRunArtifacts],
    levels: Iterable[ComparisonLevel],
    *,
    report_path: Path | None = None,
    candidate_timestamp_rules: tuple = (),
) -> RiskRun:
    """Run the V1.5 implementation-risk audit: reference vs. candidate(s)."""

    levels = tuple(levels)
    reference_bundle = restrict(reference_bundle, levels)
    candidates = (
        (candidate_bundle,)
        if isinstance(candidate_bundle, CanonicalRunArtifacts)
        else tuple(candidate_bundle)
    )
    candidates = tuple(restrict(item, levels) for item in candidates)
    normalization = ReconciliationNormalizationPlan(
        RECONCILIATION_ID,
        (
            _run_policy(reference_bundle, _instrument_ids(reference_bundle)),
            *(
                _run_policy(
                    item,
                    _instrument_ids(item),
                    candidate_timestamp_rules,
                )
                for item in candidates
            ),
        ),
    )
    comparison = ReconciliationComparisonPolicy(
        RECONCILIATION_ID,
        tuple(
            LevelComparisonPolicy(
                level,
                AlignmentMode.SEMANTIC,
                "Engine-local identifiers differ by design; align on economics.",
            )
            for level in levels
        ),
    )
    selected = tuple(item for item in MEASURED_FIELDS if item[1] in levels)
    measurement = DivergenceMeasurementPolicy(
        RECONCILIATION_ID,
        tuple(
            DivergenceFieldRule(family, level, field, "Toy-strategy e2e field.")
            for family, level, field, _ in selected
        ),
    )
    measured_families = {family for family, *_ in selected}
    attribution = (
        (
            AttributionRule(
                "cost_may_explain_accounting",
                DivergenceFamily.TRANSACTION_COST,
                DivergenceFamily.ACCOUNTING,
                "Co-occurrence supports investigation, not causal proof.",
            ),
        )
        if {DivergenceFamily.TRANSACTION_COST, DivergenceFamily.ACCOUNTING}
        <= measured_families
        else ()
    )
    assessment = RiskAssessmentPolicy(
        RECONCILIATION_ID,
        tuple(
            MaterialityRule(
                family,
                level,
                field,
                threshold,
                EXTREME_MULTIPLE,
                "Far above float noise, far below a one-bar shift.",
            )
            for family, level, field, threshold in selected
        ),
        tuple(FamilyWeight(family, Decimal(25)) for family in DivergenceFamily),
        attribution,
    )
    result = ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
        (reference_bundle, *candidates),
        normalization,
        comparison,
        measurement,
        assessment,
    )
    text = render_implementation_risk_json(result)
    report = json.loads(text)
    jsonschema.Draft202012Validator(
        load_implementation_risk_schema("implementation_risk_report_1_0"),
        registry=_REPORT_SCHEMAS,
    ).validate(report)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    return RiskRun(result, report)


def assert_no_implementation_defect(run: RiskRun) -> None:
    """A correct strategy: every compared record matches, nothing adverse."""

    assert run.report["schema_version"] == "1.0"
    for level in run.result.comparison.candidates[0].levels:
        statuses = Counter(item.status.value for item in level.records)
        assert level.status.value == "compared", (level.level, level.status)
        assert statuses, (level.level, "no records compared")
        assert set(statuses) <= {"matched_equal", "matched_different"}, (
            level.level,
            statuses,
        )
    assert not run.adverse, run.adverse
    assert not run.gaps, run.gaps
    assert set(run.kinds()) <= {"supporting"}, run.kinds()
    candidate = run.result.assessment.candidates[0]
    assert candidate.score_withheld_reason is None
    if any(family.assessments for family in candidate.families):
        assert candidate.implementation_risk_score is not None
        assert Decimal(candidate.implementation_risk_score) < 1, (
            candidate.implementation_risk_score
        )
    else:
        # Exact agreement on every measured field: V1.5H builds observations
        # only from records that differ, so it has nothing to classify and
        # reports no score (uncertainty not_assessed) rather than a score of 0.
        assert candidate.implementation_risk_score is None
        assert candidate.uncertainty.value == "not_assessed"


def assert_defect_flagged(run: RiskRun) -> None:
    """The look-ahead variant: the report names at least one adverse finding."""

    assert run.adverse, (run.kinds(), run.gaps)
