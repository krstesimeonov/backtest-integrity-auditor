"""Shared steps of the example notebooks, after the engine has run.

* :func:`reference_artifacts` builds the reference run as canonical artifacts
  from ``toy_strategy`` alone (no engine, no adapter);
* :func:`write_bundle` writes canonical bundle 1.0 as a ZIP, validates its
  ``manifest.json`` against the published JSON Schema and reads it back;
* :func:`implementation_risk` runs the implementation-risk audit with the
  reference as the declared baseline and an engine bundle as the candidate;
* ``*_table`` helpers turn bundles and results into small DataFrames.

Adapted from W3-J12's ``tests/e2e/harness.py`` (branch ``wave3/adapter-e2e``):
the same reference construction and the same policy (materiality thresholds
far above float noise and far below the effect of a one-bar shift).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import jsonschema
import pandas as pd
from referencing import Registry, Resource

import toy_strategy as reference
from backtest_auditor.implementation_risk import (
    IMPLEMENTATION_RISK_SCHEMA_FILES,
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
    comparison_policy_to_json,
    divergence_policy_to_json,
    load_canonical_bundle_schema,
    load_implementation_risk_schema,
    normalization_plan_to_json,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_to_json,
)

RECONCILIATION_ID = "toy-ma-cross"
REFERENCE_RUN_ID = "reference-pandas"
OUTPUT = Path(__file__).resolve().parent / "_output"


def _utc(value: pd.Timestamp) -> datetime:
    return value.tz_convert("UTC").to_pydatetime()


def _source_sha256() -> str:
    digest = hashlib.sha256()
    for path in (Path(reference.__file__), reference.PRICES_CSV):
        digest.update(path.read_bytes())
    return digest.hexdigest()


# --------------------------------------------------------------------------
# The reference run
# --------------------------------------------------------------------------


def reference_artifacts(
    *,
    lag: int = reference.EXECUTION_LAG_BARS,
    positions_at: str = "bar",
    cash_at: str = "bar",
    prestart: pd.Timestamp | None = None,
    equity_at: Iterable[pd.Timestamp] | None = None,
    cash: Sequence[tuple[pd.Timestamp, Decimal]] | None = None,
) -> CanonicalRunArtifacts:
    """The reference run as canonical artifacts, built from toy_strategy only.

    Engines record evidence at different instants, so the reference can be
    sampled to match: ``positions_at="fill"`` gives one position snapshot after
    each fill instead of one per bar; ``cash_at="fill"`` gives the initial
    balance plus one balance after each fill; ``prestart`` adds the initial
    capital one instant before the first bar (bt's virtual first row);
    ``equity_at`` samples equity (and the returns between samples) at given
    instants (LEAN's chart points); ``cash`` replaces the cash balances
    outright (NautilusTrader's margin-account balance).
    """

    run = reference.expected_run(lag=lag)
    instrument, currency = reference.INSTRUMENT, reference.CURRENCY
    orders, fills, costs = [], [], []
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
    trades = [
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
        for number, row in enumerate(run.trades.itertuples(index=False), start=1)
    ]
    ledger = run.ledger
    if prestart is not None:
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
    fill_instants = list(run.fills["timestamp"])
    position_rows = ledger if positions_at == "bar" else ledger.loc[fill_instants]
    positions = tuple(
        PositionSnapshot(
            _utc(timestamp), instrument, Decimal(int(row.position)), currency
        )
        for timestamp, row in position_rows.iterrows()
    )
    if cash is not None:
        balances = tuple(
            CashBalance(_utc(timestamp), currency, value) for timestamp, value in cash
        )
    else:
        cash_rows = (
            ledger
            if cash_at == "bar"
            else ledger.loc[[ledger.index[0], *fill_instants]]
        )
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
            REFERENCE_RUN_ID if lag == 1 else f"{REFERENCE_RUN_ID}-lag{lag}",
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
    """Keep only the requested evidence levels; the others become unavailable."""

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
# Canonical bundle 1.0
# --------------------------------------------------------------------------


def write_bundle(artifacts: CanonicalRunArtifacts, path: Path) -> CanonicalRunArtifacts:
    """Write a bundle ZIP, schema-validate its manifest, and read it back."""

    adapter = CanonicalArtifactFileBundleAdapter()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    adapter.write(artifacts, path)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    schema = load_canonical_bundle_schema("canonical_artifact_bundle_manifest_1_0")
    jsonschema.Draft202012Validator(schema).validate(manifest)
    read_back = adapter.read(path)
    if read_back != artifacts:
        raise AssertionError("the bundle did not read back to the same artifacts")
    return read_back


def bundle_summary(path: Path) -> pd.DataFrame:
    """Files, record counts and SHA-256 prefixes from a bundle's manifest."""

    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    rows = [
        {
            "file": item["path"],
            "records": item.get("record_count"),
            "sha256": item["sha256"][:12] + "…",
        }
        for item in manifest["files"]
    ]
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Direct comparison with the reference
# --------------------------------------------------------------------------


def fills_table(artifacts: CanonicalRunArtifacts) -> pd.DataFrame:
    """The bundle's fills joined with its commissions, in time order."""

    costs = {item.fill_id: item.pnl_impact for item in artifacts.costs or ()}
    rows = [
        {
            "timestamp (UTC)": item.timestamp.strftime("%Y-%m-%d %H:%M"),
            "side": item.side.value,
            "quantity": f"{item.quantity:f}",
            "price": f"{item.price:f}",
            "commission": costs.get(item.fill_id),
        }
        for item in sorted(artifacts.fills or (), key=lambda fill: fill.timestamp)
    ]
    return pd.DataFrame(rows)


def compare_fills(
    artifacts: CanonicalRunArtifacts, expected: reference.ExpectedRun
) -> pd.DataFrame:
    """Engine fills next to reference fills; raises if any differ."""

    fills = sorted(artifacts.fills or (), key=lambda fill: fill.timestamp)
    rows = []
    for fill, row in zip(fills, expected.fills.itertuples(index=False), strict=True):
        same = (
            fill.timestamp == _utc(row.timestamp)
            and fill.side.value == row.side
            and fill.quantity == row.quantity
            and abs(fill.price - row.price) <= Decimal("0.000001")
        )
        rows.append(
            {
                "timestamp (UTC)": fill.timestamp.strftime("%Y-%m-%d %H:%M"),
                "engine": f"{fill.side.value} {fill.quantity:f} @ {fill.price:f}",
                "reference": f"{row.side} {row.quantity:f} @ {row.price:f}",
                "same": same,
            }
        )
    table = pd.DataFrame(rows)
    if len(fills) != len(expected.fills) or not table["same"].all():
        raise AssertionError(f"fills differ from the reference:\n{table}")
    return table


# --------------------------------------------------------------------------
# Implementation-risk audit
# --------------------------------------------------------------------------

# (family, level, field, materiality threshold); "extreme" at 10x.
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
WEEKDAYS = CanonicalFrequency(
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
    """One audit: the typed result, the JSON report and the Markdown report."""

    result: ImplementationRiskAuditResult
    report: dict
    markdown: str


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


def _run_policy(artifacts: CanonicalRunArtifacts) -> RunNormalizationPolicy:
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
                source, canonical, "The synthetic instrument under its engine-local id."
            )
            for source in sorted(_instrument_ids(artifacts))
        ),
        currencies=(
            CurrencyNormalizationRule(
                reference.CURRENCY, reference.CURRENCY, "No FX conversion."
            ),
        ),
        frequency=(
            FrequencyNormalizationRule(
                WEEKDAYS, "Weekday closes of the synthetic data."
            )
            if artifacts.returns is not None
            else None
        ),
    )


@dataclass(frozen=True)
class Policies:
    """The four explicit policies of one audit, as the package's own types."""

    normalization: ReconciliationNormalizationPlan
    comparison: ReconciliationComparisonPolicy
    measurement: DivergenceMeasurementPolicy
    assessment: RiskAssessmentPolicy

    def write(self, directory: Path) -> None:
        """Write the policies as the four JSON files the CLI reads."""

        directory.mkdir(parents=True, exist_ok=True)
        for name, text in (
            ("normalization-plan.json", normalization_plan_to_json(self.normalization)),
            ("comparison-policy.json", comparison_policy_to_json(self.comparison)),
            ("measurement-policy.json", divergence_policy_to_json(self.measurement)),
            ("assessment-policy.json", risk_policy_to_json(self.assessment)),
        ):
            (directory / name).write_text(text, encoding="utf-8")


def policies(
    baseline: CanonicalRunArtifacts,
    candidate: CanonicalRunArtifacts,
    levels: Iterable[ComparisonLevel],
) -> Policies:
    """The toy strategy's policies for one reference/candidate pair."""

    levels = tuple(levels)
    normalization = ReconciliationNormalizationPlan(
        RECONCILIATION_ID, (_run_policy(baseline), _run_policy(candidate))
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
            DivergenceFieldRule(family, level, field, "Toy-strategy field.")
            for family, level, field, _ in selected
        ),
    )
    families = {family for family, *_ in selected}
    attribution = (
        (
            AttributionRule(
                "cost_may_explain_accounting",
                DivergenceFamily.TRANSACTION_COST,
                DivergenceFamily.ACCOUNTING,
                "Co-occurrence supports investigation, not causal proof.",
            ),
        )
        if {DivergenceFamily.TRANSACTION_COST, DivergenceFamily.ACCOUNTING} <= families
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
    return Policies(normalization, comparison, measurement, assessment)


def implementation_risk(
    reference_bundle: CanonicalRunArtifacts,
    candidate_bundle: CanonicalRunArtifacts,
    levels: Iterable[ComparisonLevel],
    *,
    name: str,
) -> RiskRun:
    """Audit one candidate against the reference on the requested levels.

    Both bundles are first restricted to the requested levels. The JSON report
    is validated against the published implementation-risk report schema 1.0;
    both reports are written to ``_output/<name>.json`` and ``.md``.
    """

    levels = tuple(levels)
    baseline = restrict(reference_bundle, levels)
    candidate = restrict(candidate_bundle, levels)
    chosen = policies(baseline, candidate, levels)
    result = ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
        (baseline, candidate),
        chosen.normalization,
        chosen.comparison,
        chosen.measurement,
        chosen.assessment,
    )
    text = render_implementation_risk_json(result)
    report = json.loads(text)
    validate_report(report)
    markdown = render_implementation_risk_markdown(result)
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / f"{name}.json").write_text(text, encoding="utf-8")
    (OUTPUT / f"{name}.md").write_text(markdown, encoding="utf-8")
    return RiskRun(result, report, markdown)


def validate_report(report: dict) -> None:
    """Raise unless ``report`` is a valid implementation-risk report 1.0."""

    jsonschema.Draft202012Validator(
        load_implementation_risk_schema("implementation_risk_report_1_0"),
        registry=_REPORT_SCHEMAS,
    ).validate(report)


def margin_balances(
    *, lag: int = reference.EXECUTION_LAG_BARS
) -> list[tuple[pd.Timestamp, Decimal]]:
    """A margin-account balance for the reference run.

    It starts at the initial cash on the first bar and changes only at fills:
    minus the fee, plus the gross P&L of the round trip a fill closes. This is
    what a NautilusTrader MARGIN account reports as its balance.
    """

    run = reference.expected_run(lag=lag)
    gross_by_close = dict(zip(run.trades["closed_at"], run.trades["gross_pnl"]))
    balance = reference.INITIAL_CASH
    rows = [(run.ledger.index[0], balance)]
    for fill in run.fills.itertuples(index=False):
        balance = balance - fill.fee + gross_by_close.get(fill.timestamp, Decimal(0))
        rows.append((fill.timestamp, balance))
    return rows


def final_value_check(
    artifacts: CanonicalRunArtifacts, expected: reference.ExpectedRun
) -> pd.DataFrame:
    """Last equity point (or, without equity, last cash balance) vs. the reference."""

    if artifacts.equity:
        last = max(artifacts.equity, key=lambda item: item.timestamp)
        label, value = "final equity", last.total_equity
    else:
        balances = artifacts.cash.balances if artifacts.cash else ()
        last = max(balances, key=lambda item: item.timestamp)
        label, value = "final cash (the run ends flat)", last.total
    table = pd.DataFrame(
        [{"": label, "engine": value, "reference": expected.final_equity}]
    ).set_index("")
    if abs(Decimal(value) - expected.final_equity) > Decimal("0.000001"):
        raise AssertionError(f"final value differs from the reference:\n{table}")
    return table


def summary(run: RiskRun) -> pd.DataFrame:
    """Score, uncertainty and finding counts of the (single) candidate."""

    candidate = run.result.assessment.candidates[0]
    kinds = pd.Series([item.kind.value for item in run.result.findings]).value_counts()
    return pd.DataFrame(
        [
            {
                "candidate": candidate.candidate_run.run_id,
                "implementation_risk_score": candidate.implementation_risk_score,
                "uncertainty": candidate.uncertainty.value,
                "score_withheld_reason": candidate.score_withheld_reason,
                **{f"{kind} findings": int(count) for kind, count in kinds.items()},
            }
        ]
    ).set_index("candidate")


def levels_table(run: RiskRun) -> pd.DataFrame:
    """Per comparison level: status and how many records fell in each state."""

    rows = []
    for level in run.result.comparison.candidates[0].levels:
        statuses = pd.Series(
            [item.status.value for item in level.records]
        ).value_counts()
        rows.append(
            {
                "level": level.level.value,
                "status": level.status.value,
                **{status: int(count) for status, count in statuses.items()},
            }
        )
    table = pd.DataFrame(rows).set_index("level")
    counts = [column for column in table.columns if column != "status"]
    table[counts] = table[counts].fillna(0).astype(int)
    return table


def differing_fields(run: RiskRun) -> pd.DataFrame:
    """Per level, which fields differ between matched records, and how often.

    A record is ``matched_different`` as soon as any field differs, including
    fields that only one side populates. Only the fields named in the
    measurement policy are measured against materiality thresholds.
    """

    measured = {(level, field) for _, level, field, _ in MEASURED_FIELDS}
    rows = []
    for level in run.result.comparison.candidates[0].levels:
        counts: dict[str, int] = {}
        for record in level.records:
            for difference in record.differences or ():
                counts[difference.field] = counts.get(difference.field, 0) + 1
        for field, count in sorted(counts.items()):
            rows.append(
                {
                    "level": level.level.value,
                    "field": field,
                    "records": count,
                    "measured": (level.level, field) in measured,
                }
            )
    return pd.DataFrame(rows, columns=["level", "field", "records", "measured"])


def families_table(run: RiskRun) -> pd.DataFrame:
    """Per divergence family: status, largest threshold ratio, score share."""

    families = run.report["candidates"][0]["families"]
    return pd.DataFrame(
        [
            {
                "family": item["family"],
                "status": item["status"],
                "maximum threshold ratio": item.get("maximum_threshold_ratio"),
                "score contribution": item.get("score_contribution"),
            }
            for item in families
        ]
    ).set_index("family")


def findings_counts(run: RiskRun) -> pd.DataFrame:
    """How many findings of each kind and code."""

    frame = pd.DataFrame(
        [{"kind": item.kind.value, "code": item.code} for item in run.result.findings]
    )
    return frame.value_counts().rename("count").to_frame()


def report_excerpt(run: RiskRun) -> str:
    """The Markdown report from its title through the comparison-levels table.

    It stops before the divergence-family section, whose renderer places bullet
    lists between table rows (QUALITY.md); ``families_table`` shows that part
    from the JSON report instead.
    """

    lines = run.markdown.splitlines()
    stop = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith(("### Divergence families", "## Independent findings"))
        ),
        len(lines),
    )
    return "\n".join(lines[:stop]).rstrip()


def report_findings(run: RiskRun, rows: int = 5) -> str:
    """The report's "Independent findings" table: its header and first rows."""

    lines = run.markdown.splitlines()
    start = lines.index("## Independent findings")
    table = [line for line in lines[start + 1 :] if line.startswith("|")]
    total = len(table) - 2
    shown = table[: 2 + rows]
    return "\n".join(
        ["## Independent findings", "", *shown, f"... {total} findings in total"]
    )
