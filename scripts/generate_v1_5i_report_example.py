"""Generate or verify the deterministic V1.5I end-to-end report example."""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from backtest_auditor.domain.reproducibility import AuditRunSpec
from backtest_auditor.implementation_risk import (
    AlignmentMode,
    ArtifactReturnConvention,
    AssetClass,
    AttributionRule,
    CanonicalArtifactFileBundleAdapter,
    CanonicalFrequency,
    CanonicalRunArtifacts,
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
    FrequencyKind,
    FrequencyNormalizationRule,
    ImplementationRiskAuditService,
    InstrumentIdentityRule,
    InstrumentReference,
    LevelComparisonPolicy,
    MaterialityRule,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    ReconciliationComparisonPolicy,
    ReconciliationNormalizationPlan,
    ReturnPoint,
    RiskAssessmentPolicy,
    RunNormalizationPolicy,
    TimeInForce,
    comparison_policy_to_json,
    divergence_policy_to_json,
    normalization_plan_to_json,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "v1_5i_implementation_risk"
RECONCILIATION_ID = "v1-5i-example"


def _bundle(*, candidate: bool) -> CanonicalRunArtifacts:
    timestamp = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    run = EngineRunReference(
        "candidate-run" if candidate else "reference-run",
        "Engine B" if candidate else "Engine A",
        "2.0" if candidate else "1.0",
        ("b" if candidate else "a") * 64,
    )
    return CanonicalRunArtifacts(
        run=run,
        orders=(
            OrderRecord(
                "order-b" if candidate else "order-a",
                timestamp,
                "AAPL",
                OrderSide.BUY,
                Decimal(12 if candidate else 10),
                OrderType.MARKET,
                TimeInForce.DAY,
                OrderStatus.SUBMITTED,
                submitted_at=timestamp,
            ),
        ),
        costs=(
            CostRecord(
                "cost-b" if candidate else "cost-a",
                timestamp,
                CostType.COMMISSION,
                Decimal("-1.25" if candidate else "-1"),
                "USD",
            ),
        ),
        equity=(
            EquityPoint(
                timestamp,
                "USD",
                Decimal("99997.5" if candidate else "100000"),
            ),
        ),
        returns=(
            ReturnPoint(
                datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc),
                timestamp,
                Decimal("0.009975" if candidate else "0.01"),
                ArtifactReturnConvention.SIMPLE,
            ),
        ),
    )


def build_policies(
    reference: CanonicalRunArtifacts,
    candidate: CanonicalRunArtifacts,
) -> tuple[
    ReconciliationNormalizationPlan,
    ReconciliationComparisonPolicy,
    DivergenceMeasurementPolicy,
    RiskAssessmentPolicy,
]:
    levels = (
        ComparisonLevel.ORDER,
        ComparisonLevel.COST,
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    canonical_instrument = InstrumentReference("AAPL", AssetClass.EQUITY, "AAPL", "USD")
    normalization = ReconciliationNormalizationPlan(
        RECONCILIATION_ID,
        tuple(
            RunNormalizationPolicy(
                bundle.run,
                instruments=(
                    InstrumentIdentityRule(
                        "AAPL",
                        canonical_instrument,
                        "Explicit identity mapping for the example instrument.",
                    ),
                ),
                currencies=(
                    CurrencyNormalizationRule(
                        "USD",
                        "USD",
                        "No FX conversion; denomination identifiers are identical.",
                    ),
                ),
                frequency=FrequencyNormalizationRule(
                    CanonicalFrequency("P1D", FrequencyKind.FIXED, 86_400_000_000),
                    "Explicit 24-hour return interval for the example.",
                ),
            )
            for bundle in (reference, candidate)
        ),
    )
    comparison = ReconciliationComparisonPolicy(
        RECONCILIATION_ID,
        tuple(
            LevelComparisonPolicy(
                level,
                AlignmentMode.SEMANTIC,
                "Reviewed semantic key for the deterministic V1.5I example.",
            )
            for level in levels
        ),
    )
    measurement_rules = (
        (
            DivergenceFamily.TRANSACTION_COST,
            ComparisonLevel.COST,
            "pnl_impact",
        ),
        (DivergenceFamily.SIZING, ComparisonLevel.ORDER, "quantity"),
        (DivergenceFamily.ACCOUNTING, ComparisonLevel.EQUITY, "total_equity"),
        (DivergenceFamily.RETURN, ComparisonLevel.RETURN, "value"),
    )
    measurement = DivergenceMeasurementPolicy(
        RECONCILIATION_ID,
        tuple(
            DivergenceFieldRule(family, level, field, "Reviewed canonical field.")
            for family, level, field in measurement_rules
        ),
    )
    thresholds = (
        (*measurement_rules[0], Decimal("0.1"), Decimal(2)),
        (*measurement_rules[1], Decimal(1), Decimal(3)),
        (*measurement_rules[2], Decimal(5), Decimal(2)),
        (*measurement_rules[3], Decimal("0.00001"), Decimal(2)),
    )
    assessment = RiskAssessmentPolicy(
        RECONCILIATION_ID,
        tuple(
            MaterialityRule(
                family,
                level,
                field,
                threshold,
                extreme,
                "Reviewed field-specific materiality threshold.",
            )
            for family, level, field, threshold, extreme in thresholds
        ),
        tuple(FamilyWeight(family, Decimal(25)) for family in DivergenceFamily),
        (
            AttributionRule(
                "cost_may_explain_return",
                DivergenceFamily.TRANSACTION_COST,
                DivergenceFamily.RETURN,
                "Co-occurrence supports investigation, not causal proof.",
            ),
        ),
    )
    return normalization, comparison, measurement, assessment


def generate_example(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    adapter = CanonicalArtifactFileBundleAdapter()
    reference = _bundle(candidate=False)
    candidate = _bundle(candidate=True)
    adapter.write(reference, destination / "reference-bundle.zip", overwrite=True)
    adapter.write(candidate, destination / "candidate-bundle.zip", overwrite=True)
    normalization, comparison, measurement, assessment = build_policies(
        reference, candidate
    )
    documents = {
        "normalization-plan.json": normalization_plan_to_json(normalization) + "\n",
        "comparison-policy.json": comparison_policy_to_json(comparison) + "\n",
        "measurement-policy.json": divergence_policy_to_json(measurement) + "\n",
        "assessment-policy.json": risk_policy_to_json(assessment) + "\n",
    }
    result = ImplementationRiskAuditService(adapter).audit(
        (reference, candidate),
        normalization,
        comparison,
        measurement,
        assessment,
        run_manifest_spec=AuditRunSpec(
            "v1-5i-example-audit",
            datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
            "v1.5.0-example",
        ),
    )
    documents["implementation-risk-report.json"] = render_implementation_risk_json(
        result
    )
    documents["implementation-risk-report.md"] = render_implementation_risk_markdown(
        result
    )
    for name, text in documents.items():
        (destination / name).write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if not arguments.check:
        generate_example(EXAMPLE_ROOT)
        return
    with tempfile.TemporaryDirectory() as temporary:
        generated = Path(temporary)
        generate_example(generated)
        expected = {
            item.relative_to(EXAMPLE_ROOT)
            for item in EXAMPLE_ROOT.rglob("*")
            if item.is_file()
        }
        actual = {
            item.relative_to(generated)
            for item in generated.rglob("*")
            if item.is_file()
        }
        if expected != actual:
            raise SystemExit("stale V1.5I example file set")
        for relative in sorted(expected):
            if (generated / relative).read_bytes() != (
                EXAMPLE_ROOT / relative
            ).read_bytes():
                raise SystemExit(f"stale V1.5I example: {relative}")


if __name__ == "__main__":
    main()
