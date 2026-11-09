"""Generate or verify deterministic V1.5H risk-assessment evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
from decimal import Decimal
from pathlib import Path

from backtest_auditor.implementation_risk import (
    AttributionRule,
    CandidateDivergence,
    ComparisonLevel,
    DivergenceFamily,
    DivergenceObservation,
    DivergenceStatus,
    EngineRunReference,
    FamilyDivergence,
    FamilyWeight,
    ImplementationRiskAssessmentService,
    MaterialityRule,
    ReconciliationDivergence,
    ReconciliationScope,
    RiskAssessmentPolicy,
    risk_policy_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "v1_5h_risk_assessment"


def _family(
    family: DivergenceFamily, level: ComparisonLevel, field: str, delta: str
) -> FamilyDivergence:
    observation = DivergenceObservation(
        family, level, f"{family.value}-key", field, "reference", "candidate", delta
    )
    return FamilyDivergence(
        family, DivergenceStatus.MEASURED, (observation,), 0, 0, 0, 0, 0
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
    scope = ReconciliationScope("v1-5h-example", reference, (candidate,), levels)
    divergence = ReconciliationDivergence(
        scope,
        "c" * 64,
        "d" * 64,
        "e" * 64,
        (
            CandidateDivergence(
                candidate,
                (
                    _family(
                        DivergenceFamily.TRANSACTION_COST,
                        ComparisonLevel.COST,
                        "amount",
                        "0.25",
                    ),
                    _family(
                        DivergenceFamily.SIZING, ComparisonLevel.ORDER, "quantity", "2"
                    ),
                    _family(
                        DivergenceFamily.ACCOUNTING,
                        ComparisonLevel.EQUITY,
                        "total_equity",
                        "-2.5",
                    ),
                    _family(
                        DivergenceFamily.RETURN,
                        ComparisonLevel.RETURN,
                        "value",
                        "-0.000025",
                    ),
                ),
            ),
        ),
    )
    policy = RiskAssessmentPolicy(
        scope.reconciliation_id,
        (
            MaterialityRule(
                DivergenceFamily.TRANSACTION_COST,
                ComparisonLevel.COST,
                "amount",
                Decimal("0.1"),
                Decimal(2),
                "Reviewed cost threshold.",
            ),
            MaterialityRule(
                DivergenceFamily.SIZING,
                ComparisonLevel.ORDER,
                "quantity",
                Decimal(1),
                Decimal(3),
                "Reviewed quantity threshold.",
            ),
            MaterialityRule(
                DivergenceFamily.ACCOUNTING,
                ComparisonLevel.EQUITY,
                "total_equity",
                Decimal(5),
                Decimal(2),
                "Reviewed equity threshold.",
            ),
            MaterialityRule(
                DivergenceFamily.RETURN,
                ComparisonLevel.RETURN,
                "value",
                Decimal("0.00001"),
                Decimal(2),
                "Reviewed return threshold.",
            ),
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
    result = ImplementationRiskAssessmentService().assess(divergence, policy)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "risk-policy.json").write_text(
        risk_policy_to_json(policy) + "\n", encoding="utf-8"
    )
    candidate_result = result.candidates[0]
    summary = {
        "reconciliation_id": result.scope.reconciliation_id,
        "assessment_policy_sha256": result.assessment_policy_sha256,
        "implementation_risk_score": candidate_result.implementation_risk_score,
        "uncertainty": candidate_result.uncertainty.value,
        "families": [
            {
                "family": family.family.value,
                "maximum_threshold_ratio": family.maximum_threshold_ratio,
                "score_contribution": family.score_contribution,
                "materiality": [item.materiality.value for item in family.assessments],
            }
            for family in candidate_result.families
        ],
        "attributions": [
            {"hypothesis_code": item.hypothesis_code, "status": item.status.value}
            for item in candidate_result.attributions
        ],
    }
    (destination / "risk-summary.json").write_text(
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
            for name in ("risk-policy.json", "risk-summary.json"):
                if (generated / name).read_bytes() != (
                    EXAMPLE_ROOT / name
                ).read_bytes():
                    raise SystemExit(f"stale V1.5H example: {name}")
    else:
        generate_example(EXAMPLE_ROOT)


if __name__ == "__main__":
    main()
