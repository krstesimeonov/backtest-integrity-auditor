from dataclasses import replace

import numpy as np

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.domain.assumptions import DataSnoopingSpec
from backtest_auditor.domain.enums import DataSnoopingStatus, ExperimentFamilyStatus
from backtest_auditor.ingestion.experiment_family import read_experiment_family_files
from backtest_auditor.statistics.data_snooping import calculate_data_snooping_tests


def _family(*, benchmark: bool = True):
    return read_experiment_family_files(
        (
            "examples/cscv_family_manifest_v1_4.json"
            if benchmark
            else "examples/cscv_family_manifest.json"
        ),
        "examples/cscv_family_trials.csv",
        "examples/cscv_family_returns.csv",
        benchmark_path=("examples/cscv_family_benchmark.csv" if benchmark else None),
    ).family


def test_white_reality_check_and_spa_are_seeded_and_family_wide() -> None:
    family = _family()
    assessment = audit_experiment_family(family).assessment
    spec = DataSnoopingSpec(199, 2, 42, 0.05)

    first = calculate_data_snooping_tests(family, assessment, spec=spec)
    second = calculate_data_snooping_tests(family, assessment, spec=spec)

    assert first == second
    assert first is not None
    assert first.status is DataSnoopingStatus.ELIGIBLE
    assert first.selection_eligible_trial_count == 4
    assert first.selected_trial_id == "trial-001"
    assert first.observed_maximum_trial_ids == ("trial-001",)
    assert 0.0 < first.white_reality_check_p_value <= 1.0
    assert 0.0 < first.hansen_spa_p_value <= 1.0


def test_data_snooping_reports_structural_ineligibility_before_resampling() -> None:
    family = _family()
    assessment = audit_experiment_family(family).assessment
    spec = DataSnoopingSpec(20, 2, 7, 0.05)

    ineligible = calculate_data_snooping_tests(
        family,
        replace(
            assessment,
            status=ExperimentFamilyStatus.INCOMPLETE_SEARCH_HISTORY,
        ),
        spec=spec,
    )
    no_benchmark_family = _family(benchmark=False)
    unavailable = calculate_data_snooping_tests(
        no_benchmark_family,
        audit_experiment_family(no_benchmark_family).assessment,
        spec=spec,
    )
    insufficient = calculate_data_snooping_tests(
        family,
        assessment,
        spec=replace(spec, mean_block_length=assessment.observation_count),
    )

    assert ineligible.status is DataSnoopingStatus.FAMILY_INELIGIBLE
    assert unavailable.status is DataSnoopingStatus.BENCHMARK_UNAVAILABLE
    assert insufficient.status is DataSnoopingStatus.INSUFFICIENT_OBSERVATIONS
    assert unavailable.white_reality_check_p_value is None


def test_data_snooping_with_constant_differentials_has_no_valid_trials() -> None:
    family = _family()
    benchmark = family.benchmark_returns
    assert benchmark is not None
    values = np.repeat(benchmark.values[:, None], 4, axis=1)
    constant_family = replace(
        family,
        returns=replace(family.returns, values=values),
    )
    assessment = audit_experiment_family(constant_family).assessment

    result = calculate_data_snooping_tests(
        constant_family,
        assessment,
        spec=DataSnoopingSpec(20, 2, 3, 0.05),
    )

    assert result.status is DataSnoopingStatus.NO_VALID_TRIALS
    assert result.hansen_spa_p_value is None


def test_data_snooping_is_opt_in() -> None:
    family = _family()
    assert (
        calculate_data_snooping_tests(
            family,
            audit_experiment_family(family).assessment,
        )
        is None
    )
