from benchmarks.benchmark_family_audit import build_synthetic_family
from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.domain.enums import ExperimentFamilyStatus


def test_moderate_aligned_family_is_assessed_without_special_case_paths() -> None:
    family = build_synthetic_family(
        trial_count=32,
        observation_count=128,
        seed=20260812,
    )

    result = audit_experiment_family(family)

    assert result.assessment.status is ExperimentFamilyStatus.ELIGIBLE
    assert result.assessment.documented_trial_count == 32
    assert result.assessment.observation_count == 128
    assert result.assessment.exact_timestamp_alignment is True
