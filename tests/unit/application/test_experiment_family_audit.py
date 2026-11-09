import numpy as np
import pandas as pd

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.domain.enums import (
    ExperimentFamilyStatus,
    ReturnConvention,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (
    ExperimentFamily,
    ExperimentFamilyManifest,
    ExperimentTrial,
    TrialParameter,
    TrialReturnMatrix,
)
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)


def _example_family() -> ExperimentFamily:
    return read_experiment_family_files(
        "examples/experiment_family_manifest.json",
        "examples/experiment_family_trials.csv",
        "examples/experiment_family_returns.csv",
        splits_path="examples/experiment_family_splits.csv",
        benchmark_path="examples/sample_benchmark.csv",
    ).family


def _trial(
    trial_id: str,
    index: int,
    *,
    selected: bool = False,
) -> ExperimentTrial:
    return ExperimentTrial(
        trial_id=trial_id,
        attempt_index=index,
        outcome=TrialOutcome.COMPLETED,
        included_in_selection=True,
        selected=selected,
        selection_score=float(index),
        parameters=(TrialParameter("lookback", index),),
    )


def _family(
    *,
    total: int,
    search_complete: bool,
    trials: tuple[ExperimentTrial, ...],
    observation_count: int = 4,
) -> ExperimentFamily:
    timestamps = pd.date_range(
        "2026-01-01",
        periods=observation_count,
        freq="D",
    )
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="assessment-family",
            declared_total_attempted_trials=total,
            search_complete=search_complete,
            selected_trial_id=next(
                trial.trial_id for trial in trials if trial.selected
            ),
            selection_rule="maximize validation Sharpe",
            selection_metric="validation_sharpe",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(
                declared_frequency="D",
                periods_per_year=365,
            ),
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=timestamps,
            trial_ids=tuple(trial.trial_id for trial in trials),
            values=np.arange(
                observation_count * len(trials),
                dtype=np.float64,
            ).reshape(observation_count, len(trials))
            / 1000.0,
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=365),
        ),
    )


def test_complete_family_assessment_preserves_all_trial_states() -> None:
    result = audit_experiment_family(_example_family())
    assessment = result.assessment

    assert assessment.status is ExperimentFamilyStatus.ELIGIBLE
    assert assessment.complete_search_history is True
    assert assessment.declared_total_attempted_trials == 4
    assert assessment.documented_trial_count == 4
    assert assessment.completed_trial_count == 3
    assert assessment.failed_trial_count == 1
    assert assessment.eligible_trial_count == 2
    assert assessment.excluded_completed_trial_count == 1
    assert assessment.supplied_return_series_count == 3
    assert assessment.selection_bias_methods_structurally_eligible is True
    assert assessment.split_count == 2
    assert assessment.benchmark_id == "market"
    assert {finding.code for finding in result.findings} == {
        "COMPLETED_TRIALS_EXCLUDED_FROM_SELECTION",
        "CSCV_PBO_NOT_CONFIGURED",
        "DEFLATED_SHARPE_RATIO_NOT_CONFIGURED",
        "FAILED_EXPERIMENT_TRIALS_DOCUMENTED",
        "PARAMETER_ROBUSTNESS_NOT_CONFIGURED",
        "TEMPORAL_ROBUSTNESS_NOT_CONFIGURED",
    }


def test_incomplete_winner_only_family_is_explicitly_ineligible() -> None:
    result = audit_experiment_family(
        _family(
            total=3,
            search_complete=False,
            trials=(_trial("winner", 1, selected=True),),
        )
    )
    assessment = result.assessment

    assert assessment.status is (ExperimentFamilyStatus.INCOMPLETE_SEARCH_HISTORY)
    assert assessment.undocumented_attempt_indices == (2, 3)
    assert assessment.winner_only_evidence is True
    assert assessment.selection_bias_methods_structurally_eligible is False
    assert {
        "EXPERIMENT_SEARCH_HISTORY_INCOMPLETE",
        "UNDOCUMENTED_ATTEMPTED_TRIALS",
        "WINNER_ONLY_EXPERIMENT_EVIDENCE",
        "INSUFFICIENT_ELIGIBLE_TRIALS_FOR_FAMILY_ANALYSIS",
        "EXPERIMENT_SPLIT_METADATA_NOT_SUPPLIED",
    }.issubset({finding.code for finding in result.findings})


def test_complete_short_family_has_observation_specific_status() -> None:
    result = audit_experiment_family(
        _family(
            total=2,
            search_complete=True,
            trials=(
                _trial("trial-1", 1),
                _trial("trial-2", 2, selected=True),
            ),
            observation_count=3,
        )
    )

    assert result.assessment.status is (
        ExperimentFamilyStatus.INSUFFICIENT_OBSERVATIONS
    )
    assert result.assessment.selection_bias_methods_structurally_eligible is False
    assert "INSUFFICIENT_OBSERVATIONS_FOR_FAMILY_METHODS" in {
        finding.code for finding in result.findings
    }
