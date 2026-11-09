import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.domain.assumptions import TemporalRobustnessSpec
from backtest_auditor.domain.enums import (
    ReturnConvention,
    RobustnessSliceStatus,
    SelectionDirection,
    TemporalRobustnessStatus,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (
    ExperimentFamily,
    ExperimentSplit,
    ExperimentTrial,
)
from backtest_auditor.domain.results import (
    ExternalSplitConsistencyResult,
    TemporalRobustnessResult,
    TemporalWindowResult,
)
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.family_metrics import (
    average_ranks,
    period_sharpe_scores,
    relative_rank_and_logit,
)
from backtest_auditor.statistics.return_basis import (
    annual_to_period_rate,
    to_simple_returns,
)


def calculate_temporal_robustness(
    family: ExperimentFamily,
    spec: TemporalRobustnessSpec,
) -> TemporalRobustnessResult:
    """Audit selected-trial stability across equal windows and declared splits."""

    eligible = _selection_eligible_trials(family)
    common: dict[str, Any] = {"selection_eligible_trial_count": len(eligible)}
    if not _family_is_eligible(family, eligible):
        return _unavailable_result(
            family,
            spec,
            status=TemporalRobustnessStatus.FAMILY_INELIGIBLE,
            **common,
        )
    if (
        family.manifest.selection_direction is not SelectionDirection.MAXIMIZE
        or family.manifest.selection_metric != spec.selection_metric_name
    ):
        return _unavailable_result(
            family,
            spec,
            status=TemporalRobustnessStatus.SELECTION_RULE_INCOMPATIBLE,
            **common,
        )
    periods_per_year = family.returns.sampling.periods_per_year
    if periods_per_year is None or periods_per_year <= 0:
        return _unavailable_result(
            family,
            spec,
            status=TemporalRobustnessStatus.PERIODS_PER_YEAR_UNAVAILABLE,
            **common,
        )
    period_rate = annual_to_period_rate(
        spec.annual_risk_free_rate,
        periods_per_year,
    )
    trial_ids = tuple(trial.trial_id for trial in eligible)
    matrix = np.column_stack(
        [
            to_simple_returns(family.returns.series_for(trial_id))
            for trial_id in trial_ids
        ]
    )
    selected_index = trial_ids.index(family.manifest.selected_trial_id)
    external_splits = _calculate_external_splits(
        family,
        matrix,
        trial_ids=trial_ids,
        period_rate=period_rate,
    )
    valid_external_count = sum(
        item.status is RobustnessSliceStatus.ELIGIBLE for item in external_splits
    )
    period_values: dict[str, Any] = {
        "periods_per_year": periods_per_year,
        "period_risk_free_rate_value": period_rate,
        "external_splits": external_splits,
        "valid_external_split_count": valid_external_count,
        "invalid_external_split_count": len(external_splits) - valid_external_count,
    }
    observation_count = len(family.returns.timestamps)
    if observation_count % spec.window_count != 0:
        return _unavailable_result(
            family,
            spec,
            status=(TemporalRobustnessStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_WINDOWS),
            **common,
            **period_values,
        )
    observations_per_window = observation_count // spec.window_count
    if observations_per_window < 2:
        return _unavailable_result(
            family,
            spec,
            status=TemporalRobustnessStatus.INSUFFICIENT_WINDOW_OBSERVATIONS,
            observations_per_window=observations_per_window,
            **common,
            **period_values,
        )

    windows = _calculate_windows(
        family,
        matrix,
        trial_ids=trial_ids,
        selected_index=selected_index,
        observations_per_window=observations_per_window,
        period_rate=period_rate,
    )
    valid_windows = tuple(
        item for item in windows if item.status is RobustnessSliceStatus.ELIGIBLE
    )
    window_values: dict[str, Any] = {
        "observations_per_window": observations_per_window,
        "windows": windows,
        "valid_window_count": len(valid_windows),
        "invalid_window_count": len(windows) - len(valid_windows),
    }
    if len(valid_windows) != len(windows):
        return _unavailable_result(
            family,
            spec,
            status=TemporalRobustnessStatus.INCOMPLETE_WINDOW_METRICS,
            **common,
            **period_values,
            **window_values,
        )

    scores = np.asarray(
        [item.selected_period_sharpe_ratio for item in valid_windows],
        dtype=float,
    )
    logits = np.asarray(
        [item.selected_rank_logit for item in valid_windows],
        dtype=float,
    )
    top_half_fraction = float(
        np.mean([item.selected_in_top_half for item in valid_windows])
    )
    tied_best_fraction = float(
        np.mean([item.selected_tied_for_best for item in valid_windows])
    )
    below_zero_fraction = float(
        np.mean([item.selected_score_below_zero for item in valid_windows])
    )
    winner_ids = {
        trial_id for window in valid_windows for trial_id in window.tied_best_trial_ids
    }
    return TemporalRobustnessResult(
        status=TemporalRobustnessStatus.ELIGIBLE,
        performance_metric=spec.performance_metric,
        declared_selection_metric=family.manifest.selection_metric,
        confirmed_selection_metric=spec.selection_metric_name,
        rank_tie_method=spec.rank_tie_method,
        winner_tie_policy=spec.winner_tie_policy,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_rate,
        observation_count=observation_count,
        window_count=spec.window_count,
        observations_per_window=observations_per_window,
        selected_trial_id=family.manifest.selected_trial_id,
        selection_eligible_trial_count=len(eligible),
        minimum_acceptable_top_half_fraction=(
            spec.minimum_acceptable_top_half_fraction
        ),
        maximum_acceptable_below_zero_fraction=(
            spec.maximum_acceptable_below_zero_fraction
        ),
        windows=windows,
        valid_window_count=len(valid_windows),
        invalid_window_count=0,
        selected_score_mean=float(np.mean(scores)),
        selected_score_sample_standard_deviation=(
            0.0 if has_zero_sample_variation(scores) else float(np.std(scores, ddof=1))
        ),
        selected_score_minimum=float(np.min(scores)),
        selected_score_maximum=float(np.max(scores)),
        selected_score_range=float(np.max(scores) - np.min(scores)),
        selected_top_half_fraction=top_half_fraction,
        top_half_fraction_requirement_met=(
            top_half_fraction >= spec.minimum_acceptable_top_half_fraction
        ),
        selected_tied_best_fraction=tied_best_fraction,
        selected_below_zero_fraction=below_zero_fraction,
        below_zero_fraction_requirement_met=(
            below_zero_fraction <= spec.maximum_acceptable_below_zero_fraction
        ),
        mean_rank_logit=float(np.mean(logits)),
        median_rank_logit=float(np.median(logits)),
        distinct_window_winner_trial_ids=tuple(
            trial_id for trial_id in trial_ids if trial_id in winner_ids
        ),
        external_splits=external_splits,
        valid_external_split_count=valid_external_count,
        invalid_external_split_count=len(external_splits) - valid_external_count,
    )


def _calculate_windows(
    family: ExperimentFamily,
    matrix: NDArray[np.float64],
    *,
    trial_ids: tuple[str, ...],
    selected_index: int,
    observations_per_window: int,
    period_rate: float,
) -> tuple[TemporalWindowResult, ...]:
    results = []
    for zero_index in range(matrix.shape[0] // observations_per_window):
        start = zero_index * observations_per_window
        stop = start + observations_per_window
        scores = period_sharpe_scores(
            matrix[start:stop, :],
            period_risk_free_rate_value=period_rate,
        )
        timestamps = family.returns.timestamps[start:stop]
        unavailable = tuple(
            trial_ids[index]
            for index, score in enumerate(scores)
            if not math.isfinite(score)
        )
        if unavailable:
            selected_score = float(scores[selected_index])
            results.append(
                TemporalWindowResult(
                    window_index=zero_index + 1,
                    status=RobustnessSliceStatus.PERFORMANCE_METRIC_UNAVAILABLE,
                    observation_count=observations_per_window,
                    start_timestamp=timestamps[0],
                    end_timestamp=timestamps[-1],
                    selected_trial_id=trial_ids[selected_index],
                    selected_period_sharpe_ratio=(
                        selected_score if math.isfinite(selected_score) else None
                    ),
                    selected_rank=None,
                    selected_relative_rank=None,
                    selected_rank_logit=None,
                    selected_in_top_half=None,
                    selected_tied_for_best=None,
                    selected_score_below_zero=None,
                    tied_best_trial_ids=(),
                    unavailable_trial_ids=unavailable,
                )
            )
            continue
        ranks = average_ranks(scores)
        selected_rank = float(ranks[selected_index])
        relative_rank, logit = relative_rank_and_logit(
            selected_rank,
            len(trial_ids),
        )
        best = float(np.max(scores))
        tied_best_ids = tuple(
            trial_ids[index] for index, score in enumerate(scores) if score == best
        )
        selected_score = float(scores[selected_index])
        results.append(
            TemporalWindowResult(
                window_index=zero_index + 1,
                status=RobustnessSliceStatus.ELIGIBLE,
                observation_count=observations_per_window,
                start_timestamp=timestamps[0],
                end_timestamp=timestamps[-1],
                selected_trial_id=trial_ids[selected_index],
                selected_period_sharpe_ratio=selected_score,
                selected_rank=selected_rank,
                selected_relative_rank=relative_rank,
                selected_rank_logit=logit,
                selected_in_top_half=logit > 0.0,
                selected_tied_for_best=(trial_ids[selected_index] in tied_best_ids),
                selected_score_below_zero=selected_score < 0.0,
                tied_best_trial_ids=tied_best_ids,
                unavailable_trial_ids=(),
            )
        )
    return tuple(results)


def _calculate_external_splits(
    family: ExperimentFamily,
    matrix: NDArray[np.float64],
    *,
    trial_ids: tuple[str, ...],
    period_rate: float,
) -> tuple[ExternalSplitConsistencyResult, ...]:
    return tuple(
        _calculate_external_split(
            family,
            split,
            matrix,
            trial_ids=trial_ids,
            period_rate=period_rate,
        )
        for split in family.splits
    )


def _calculate_external_split(
    family: ExperimentFamily,
    split: ExperimentSplit,
    matrix: NDArray[np.float64],
    *,
    trial_ids: tuple[str, ...],
    period_rate: float,
) -> ExternalSplitConsistencyResult:
    in_rows = family.returns.timestamps.get_indexer(split.in_sample_timestamps)
    out_rows = family.returns.timestamps.get_indexer(split.out_of_sample_timestamps)
    unavailable = list(trial_ids) if len(in_rows) < 2 or len(out_rows) < 2 else []
    in_scores = (
        np.full(len(trial_ids), np.nan)
        if unavailable
        else period_sharpe_scores(
            matrix[in_rows, :],
            period_risk_free_rate_value=period_rate,
        )
    )
    out_scores = (
        np.full(len(trial_ids), np.nan)
        if unavailable
        else period_sharpe_scores(
            matrix[out_rows, :],
            period_risk_free_rate_value=period_rate,
        )
    )
    if not unavailable:
        unavailable.extend(
            trial_ids[index]
            for index in range(len(trial_ids))
            if not math.isfinite(in_scores[index])
            or not math.isfinite(out_scores[index])
        )
    if unavailable:
        return ExternalSplitConsistencyResult(
            split_id=split.split_id,
            status=RobustnessSliceStatus.PERFORMANCE_METRIC_UNAVAILABLE,
            in_sample_observation_count=len(in_rows),
            out_of_sample_observation_count=len(out_rows),
            in_sample_winner_trial_id=None,
            tied_in_sample_winner_trial_ids=(),
            selected_in_sample_score=None,
            selected_out_of_sample_score=None,
            selected_out_of_sample_rank=None,
            selected_out_of_sample_relative_rank=None,
            selected_out_of_sample_rank_logit=None,
            selected_out_of_sample_in_top_half=None,
            selected_out_of_sample_score_below_zero=None,
            tied_out_of_sample_best_trial_ids=(),
            in_sample_winner_retained_out_of_sample=None,
            unavailable_trial_ids=tuple(unavailable),
        )

    best_in = float(np.max(in_scores))
    tied_in = tuple(index for index, score in enumerate(in_scores) if score == best_in)
    winner_index = tied_in[0]
    out_ranks = average_ranks(out_scores)
    out_rank = float(out_ranks[winner_index])
    relative_rank, logit = relative_rank_and_logit(out_rank, len(trial_ids))
    best_out = float(np.max(out_scores))
    tied_out = tuple(
        trial_ids[index] for index, score in enumerate(out_scores) if score == best_out
    )
    out_score = float(out_scores[winner_index])
    return ExternalSplitConsistencyResult(
        split_id=split.split_id,
        status=RobustnessSliceStatus.ELIGIBLE,
        in_sample_observation_count=len(in_rows),
        out_of_sample_observation_count=len(out_rows),
        in_sample_winner_trial_id=trial_ids[winner_index],
        tied_in_sample_winner_trial_ids=tuple(trial_ids[index] for index in tied_in),
        selected_in_sample_score=best_in,
        selected_out_of_sample_score=out_score,
        selected_out_of_sample_rank=out_rank,
        selected_out_of_sample_relative_rank=relative_rank,
        selected_out_of_sample_rank_logit=logit,
        selected_out_of_sample_in_top_half=logit > 0.0,
        selected_out_of_sample_score_below_zero=out_score < 0.0,
        tied_out_of_sample_best_trial_ids=tied_out,
        in_sample_winner_retained_out_of_sample=(trial_ids[winner_index] in tied_out),
        unavailable_trial_ids=(),
    )


def _selection_eligible_trials(
    family: ExperimentFamily,
) -> tuple[ExperimentTrial, ...]:
    return tuple(
        trial
        for trial in family.trials
        if trial.outcome is TrialOutcome.COMPLETED and trial.included_in_selection
    )


def _family_is_eligible(
    family: ExperimentFamily,
    eligible: tuple[ExperimentTrial, ...],
) -> bool:
    return (
        family.manifest.search_complete
        and len(family.trials) == family.manifest.declared_total_attempted_trials
        and len(eligible) >= 2
        and len(family.returns.timestamps) >= 4
    )


def _unavailable_result(
    family: ExperimentFamily,
    spec: TemporalRobustnessSpec,
    *,
    status: TemporalRobustnessStatus,
    periods_per_year: int | None = None,
    period_risk_free_rate_value: float | None = None,
    observations_per_window: int | None = None,
    selection_eligible_trial_count: int,
    windows: tuple[TemporalWindowResult, ...] = (),
    valid_window_count: int = 0,
    invalid_window_count: int = 0,
    external_splits: tuple[ExternalSplitConsistencyResult, ...] = (),
    valid_external_split_count: int = 0,
    invalid_external_split_count: int = 0,
) -> TemporalRobustnessResult:
    return TemporalRobustnessResult(
        status=status,
        performance_metric=spec.performance_metric,
        declared_selection_metric=family.manifest.selection_metric,
        confirmed_selection_metric=spec.selection_metric_name,
        rank_tie_method=spec.rank_tie_method,
        winner_tie_policy=spec.winner_tie_policy,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_risk_free_rate_value,
        observation_count=len(family.returns.timestamps),
        window_count=spec.window_count,
        observations_per_window=observations_per_window,
        selected_trial_id=family.manifest.selected_trial_id,
        selection_eligible_trial_count=selection_eligible_trial_count,
        minimum_acceptable_top_half_fraction=(
            spec.minimum_acceptable_top_half_fraction
        ),
        maximum_acceptable_below_zero_fraction=(
            spec.maximum_acceptable_below_zero_fraction
        ),
        windows=windows,
        valid_window_count=valid_window_count,
        invalid_window_count=invalid_window_count,
        selected_score_mean=None,
        selected_score_sample_standard_deviation=None,
        selected_score_minimum=None,
        selected_score_maximum=None,
        selected_score_range=None,
        selected_top_half_fraction=None,
        top_half_fraction_requirement_met=None,
        selected_tied_best_fraction=None,
        selected_below_zero_fraction=None,
        below_zero_fraction_requirement_met=None,
        mean_rank_logit=None,
        median_rank_logit=None,
        distinct_window_winner_trial_ids=(),
        external_splits=external_splits,
        valid_external_split_count=valid_external_split_count,
        invalid_external_split_count=invalid_external_split_count,
    )
