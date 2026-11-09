"""Generate or verify the deterministic V1.5F comparison evidence example."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from backtest_auditor.implementation_risk import (
    AlignmentMode,
    CanonicalArtifactFileBundleAdapter,
    LevelComparisonPolicy,
    ReconciliationComparisonPolicy,
    ReconciliationComparisonService,
    ReconciliationNormalizationService,
    comparison_policy_to_json,
)
from scripts.generate_v1_5e_normalization_example import build_example


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "v1_5f_comparison"


def generate_example(destination: Path) -> None:
    scope, (reference, candidate), plan = build_example()
    assert candidate.equity is not None
    candidate = replace(
        candidate,
        equity=(replace(candidate.equity[0], total_equity=Decimal("100497.50")),),
    )
    normalized = ReconciliationNormalizationService(
        CanonicalArtifactFileBundleAdapter()
    ).normalize(scope, (reference, candidate), plan)
    policy = ReconciliationComparisonPolicy(
        scope.reconciliation_id,
        tuple(
            LevelComparisonPolicy(
                level,
                AlignmentMode.SEMANTIC,
                "Reviewed cross-engine semantic identity for this example.",
            )
            for level in scope.requested_levels
        ),
    )
    comparison = ReconciliationComparisonService().compare(normalized, policy)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "comparison-policy.json").write_text(
        comparison_policy_to_json(policy) + "\n", encoding="utf-8"
    )
    summary = {
        "reconciliation_id": comparison.scope.reconciliation_id,
        "normalization_plan_sha256": comparison.normalization_plan_sha256,
        "comparison_policy_sha256": comparison.comparison_policy_sha256,
        "candidates": [
            {
                "run_id": candidate_result.candidate_run.run_id,
                "levels": [
                    {
                        "level": level.level.value,
                        "status": level.status.value,
                        "exact_match": level.exact_match,
                        "record_statuses": [
                            record.status.value for record in level.records
                        ],
                        "differences": [
                            {
                                "field": difference.field,
                                "decimal_delta": difference.decimal_delta,
                                "temporal_delta_microseconds": difference.temporal_delta_microseconds,
                            }
                            for record in level.records
                            for difference in record.differences
                        ],
                    }
                    for level in candidate_result.levels
                ],
            }
            for candidate_result in comparison.candidates
        ],
    }
    (destination / "comparison-summary.json").write_text(
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
            for name in ("comparison-policy.json", "comparison-summary.json"):
                if (generated / name).read_bytes() != (
                    EXAMPLE_ROOT / name
                ).read_bytes():
                    raise SystemExit(f"stale V1.5F example: {name}")
    else:
        generate_example(EXAMPLE_ROOT)


if __name__ == "__main__":
    main()
