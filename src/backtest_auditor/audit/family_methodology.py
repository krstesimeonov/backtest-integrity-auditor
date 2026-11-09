from backtest_auditor.domain.enums import (
    ExperimentFamilyStatus,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import ExperimentFamily
from backtest_auditor.domain.results import (
    ExperimentFamilyAssessmentResult,
    ExperimentSplitAssessmentResult,
    ExperimentTrialAssessmentResult,
)


def assess_experiment_family(
    family: ExperimentFamily,
) -> tuple[
    ExperimentFamilyAssessmentResult,
    tuple[ExperimentTrialAssessmentResult, ...],
    tuple[ExperimentSplitAssessmentResult, ...],
]:
    manifest = family.manifest
    documented_indices = tuple(trial.attempt_index for trial in family.trials)
    undocumented_indices = tuple(
        index
        for index in range(
            1,
            manifest.declared_total_attempted_trials + 1,
        )
        if index not in documented_indices
    )
    completed = tuple(
        trial for trial in family.trials if trial.outcome is TrialOutcome.COMPLETED
    )
    failed = tuple(
        trial for trial in family.trials if trial.outcome is TrialOutcome.FAILED
    )
    eligible = tuple(trial for trial in completed if trial.included_in_selection)
    excluded = tuple(trial for trial in completed if not trial.included_in_selection)
    complete_search_history = (
        manifest.search_complete
        and len(family.trials) == manifest.declared_total_attempted_trials
        and not undocumented_indices
    )
    structurally_eligible = (
        complete_search_history
        and len(eligible) >= 2
        and len(family.returns.timestamps) >= 4
    )
    if not complete_search_history:
        status = ExperimentFamilyStatus.INCOMPLETE_SEARCH_HISTORY
    elif len(eligible) < 2:
        status = ExperimentFamilyStatus.INSUFFICIENT_ELIGIBLE_TRIALS
    elif len(family.returns.timestamps) < 4:
        status = ExperimentFamilyStatus.INSUFFICIENT_OBSERVATIONS
    else:
        status = ExperimentFamilyStatus.ELIGIBLE

    selected_trial = next(trial for trial in family.trials if trial.selected)
    benchmark = family.benchmark_returns
    assessment = ExperimentFamilyAssessmentResult(
        status=status,
        input_schema_version=manifest.schema_version,
        family_id=manifest.family_id,
        source=manifest.source,
        declared_total_attempted_trials=(manifest.declared_total_attempted_trials),
        documented_trial_count=len(family.trials),
        documented_attempt_indices=documented_indices,
        undocumented_attempt_indices=undocumented_indices,
        completed_trial_count=len(completed),
        failed_trial_count=len(failed),
        eligible_trial_count=len(eligible),
        excluded_completed_trial_count=len(excluded),
        supplied_return_series_count=len(family.returns.trial_ids),
        search_complete_declared=manifest.search_complete,
        complete_search_history=complete_search_history,
        winner_only_evidence=(
            len(family.returns.trial_ids) == 1
            and family.returns.trial_ids[0] == manifest.selected_trial_id
        ),
        selection_bias_methods_structurally_eligible=(structurally_eligible),
        selected_trial_id=manifest.selected_trial_id,
        selected_trial_attempt_index=selected_trial.attempt_index,
        selection_rule=manifest.selection_rule,
        selection_metric=manifest.selection_metric,
        selection_direction=manifest.selection_direction,
        return_basis=family.returns.convention,
        observation_count=len(family.returns.timestamps),
        start_timestamp=family.returns.timestamps[0],
        end_timestamp=family.returns.timestamps[-1],
        exact_timestamp_alignment=True,
        declared_frequency=family.returns.sampling.declared_frequency,
        periods_per_year=family.returns.sampling.periods_per_year,
        timezone=family.returns.sampling.timezone,
        parameter_names=manifest.parameter_names,
        parameter_count=len(manifest.parameter_names),
        split_metadata_supplied=bool(family.splits),
        split_count=len(family.splits),
        benchmark_id=manifest.benchmark_id,
        benchmark_return_basis=(None if benchmark is None else benchmark.convention),
        benchmark_observation_count=(
            None if benchmark is None else len(benchmark.timestamps)
        ),
    )

    supplied_ids = set(family.returns.trial_ids)
    trial_results = tuple(
        ExperimentTrialAssessmentResult(
            trial_id=trial.trial_id,
            attempt_index=trial.attempt_index,
            outcome=trial.outcome,
            included_in_selection=trial.included_in_selection,
            selected=trial.selected,
            selection_score=trial.selection_score,
            return_series_supplied=trial.trial_id in supplied_ids,
            observation_count=(
                len(family.returns.timestamps)
                if trial.trial_id in supplied_ids
                else None
            ),
            parameters=trial.parameters,
            source=trial.source,
            reason=trial.reason,
        )
        for trial in family.trials
    )
    split_results = tuple(
        ExperimentSplitAssessmentResult(
            split_id=split.split_id,
            in_sample_observation_count=len(split.in_sample_timestamps),
            out_of_sample_observation_count=len(split.out_of_sample_timestamps),
            in_sample_timestamps=tuple(split.in_sample_timestamps),
            out_of_sample_timestamps=tuple(split.out_of_sample_timestamps),
            in_sample_start_timestamp=split.in_sample_timestamps[0],
            in_sample_end_timestamp=split.in_sample_timestamps[-1],
            out_of_sample_start_timestamp=(split.out_of_sample_timestamps[0]),
            out_of_sample_end_timestamp=(split.out_of_sample_timestamps[-1]),
        )
        for split in family.splits
    )
    return assessment, trial_results, split_results
