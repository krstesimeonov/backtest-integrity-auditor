from __future__ import annotations

from benchmarks.benchmark_implementation_risk import (
    benchmark_implementation_risk,
    build_synthetic_reconciliation,
)
from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditService,
)
from scripts.generate_v1_5i_report_example import build_policies


def test_moderate_complete_reconciliation_preserves_linear_result_shape() -> None:
    reference, candidate = build_synthetic_reconciliation(record_count=64)
    result = ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
        (reference, candidate),
        *build_policies(reference, candidate),
    )

    assert result.assessment.candidates[0].implementation_risk_score == "87.5"
    assert (
        sum(
            len(family.observations)
            for family in result.divergence.candidates[0].families
        )
        == 4 * 64
    )
    assert len(result.findings) == 4 * 64 + 1


def test_complete_pipeline_stays_inside_smoke_time_and_memory_budgets() -> None:
    measured = benchmark_implementation_risk(
        record_count=128,
        repeats=2,
        time_budget_seconds=5.0,
        memory_budget_mib=128.0,
    )

    assert measured["budget_met"] is True
    assert measured["candidate_count"] == 1
    assert measured["finding_count"] == 4 * 128 + 1
