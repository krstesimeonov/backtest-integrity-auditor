"""Generate or verify deterministic V1.5G divergence evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from backtest_auditor.implementation_risk import (
    AlignmentMode,
    CandidateComparison,
    ComparisonLevel,
    DivergenceFamily,
    DivergenceFieldRule,
    DivergenceMeasurementPolicy,
    DivergenceMeasurementService,
    EngineRunReference,
    FieldDifference,
    LevelComparison,
    LevelComparisonStatus,
    ReconciliationComparison,
    ReconciliationScope,
    RecordComparison,
    RecordComparisonStatus,
    divergence_policy_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "v1_5g_divergence"


def _changed(
    key: str, field: str, reference: str, candidate: str, delta: str
) -> RecordComparison:
    return RecordComparison(
        key,
        RecordComparisonStatus.MATCHED_DIFFERENT,
        ("reference-record",),
        ("candidate-record",),
        (FieldDifference(field, reference, candidate, delta),),
    )


def generate_example(destination: Path) -> None:
    reference = EngineRunReference("engine-a-run", "Engine A", "1", "a" * 64)
    candidate = EngineRunReference("engine-b-run", "Engine B", "2", "b" * 64)
    levels = (
        ComparisonLevel.ORDER,
        ComparisonLevel.COST,
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    scope = ReconciliationScope("v1-5g-example", reference, (candidate,), levels)
    level_results = (
        LevelComparison(
            ComparisonLevel.ORDER,
            LevelComparisonStatus.COMPARED,
            AlignmentMode.SEMANTIC,
            (
                _changed(
                    "order-1",
                    "quantity",
                    '{"type":"decimal","value":"10"}',
                    '{"type":"decimal","value":"12"}',
                    "2",
                ),
            ),
        ),
        LevelComparison(
            ComparisonLevel.COST,
            LevelComparisonStatus.COMPARED,
            AlignmentMode.SEMANTIC,
            (
                _changed(
                    "cost-1",
                    "amount",
                    '{"type":"decimal","value":"1.25"}',
                    '{"type":"decimal","value":"1.50"}',
                    "0.25",
                ),
            ),
        ),
        LevelComparison(
            ComparisonLevel.EQUITY,
            LevelComparisonStatus.COMPARED,
            AlignmentMode.SEMANTIC,
            (
                _changed(
                    "equity-1",
                    "total_equity",
                    '{"type":"decimal","value":"100500"}',
                    '{"type":"decimal","value":"100497.50"}',
                    "-2.50",
                ),
            ),
        ),
        LevelComparison(
            ComparisonLevel.RETURN,
            LevelComparisonStatus.COMPARED,
            AlignmentMode.SEMANTIC,
            (
                _changed(
                    "return-1",
                    "value",
                    '{"type":"decimal","value":"0.005"}',
                    '{"type":"decimal","value":"0.004975"}',
                    "-0.000025",
                ),
            ),
        ),
    )
    comparison = ReconciliationComparison(
        scope, "c" * 64, "d" * 64, (CandidateComparison(candidate, level_results),)
    )
    policy = DivergenceMeasurementPolicy(
        scope.reconciliation_id,
        (
            DivergenceFieldRule(
                DivergenceFamily.TRANSACTION_COST,
                ComparisonLevel.COST,
                "amount",
                "Canonical transaction-cost amount.",
            ),
            DivergenceFieldRule(
                DivergenceFamily.SIZING,
                ComparisonLevel.ORDER,
                "quantity",
                "Canonical submitted quantity.",
            ),
            DivergenceFieldRule(
                DivergenceFamily.ACCOUNTING,
                ComparisonLevel.EQUITY,
                "total_equity",
                "Canonical account equity.",
            ),
            DivergenceFieldRule(
                DivergenceFamily.RETURN,
                ComparisonLevel.RETURN,
                "value",
                "Canonical period return.",
            ),
        ),
    )
    result = DivergenceMeasurementService().measure(comparison, policy)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "measurement-policy.json").write_text(
        divergence_policy_to_json(policy) + "\n", encoding="utf-8"
    )
    summary = {
        "reconciliation_id": result.scope.reconciliation_id,
        "normalization_plan_sha256": result.normalization_plan_sha256,
        "comparison_policy_sha256": result.comparison_policy_sha256,
        "measurement_policy_sha256": result.measurement_policy_sha256,
        "families": [
            {
                "family": family.family.value,
                "status": family.status.value,
                "observations": [
                    {
                        "level": item.level.value,
                        "field": item.field,
                        "decimal_delta": item.decimal_delta,
                    }
                    for item in family.observations
                ],
            }
            for family in result.candidates[0].families
        ],
    }
    (destination / "divergence-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary)
            generate_example(generated)
            for name in ("measurement-policy.json", "divergence-summary.json"):
                if (generated / name).read_bytes() != (
                    EXAMPLE_ROOT / name
                ).read_bytes():
                    raise SystemExit(f"stale V1.5G example: {name}")
    else:
        generate_example(EXAMPLE_ROOT)


if __name__ == "__main__":
    main()
