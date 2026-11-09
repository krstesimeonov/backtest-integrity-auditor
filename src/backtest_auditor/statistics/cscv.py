import itertools
import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.domain.assumptions import CSCVSpec
from backtest_auditor.domain.enums import (
    CSCVSplitStatus,
    CSCVStatus,
    ReturnConvention,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import ExperimentFamily
from backtest_auditor.domain.results import (
    CSCVPartitionResult,
    CSCVResult,
    CSCVSplitResult,
)
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.return_basis import (
    annual_to_period_rate,
    to_simple_returns,
)
from backtest_auditor.statistics.family_metrics import (
    average_ranks,
    period_sharpe_scores,
)


def calculate_cscv(
    family: ExperimentFamily,
    spec: CSCVSpec,
) -> CSCVResult:
    """Calculate deterministic CSCV ranks and Probability of Backtest Overfitting."""

    manifest = family.manifest
    completed = tuple(
        trial for trial in family.trials if trial.outcome is TrialOutcome.COMPLETED
    )
    selection_eligible = tuple(
        trial for trial in completed if trial.included_in_selection
    )
    observation_count = len(family.returns.timestamps)
    total_combinations = math.comb(spec.partition_count, spec.partition_count // 2)
    complete_search_history = (
        manifest.search_complete
        and len(family.trials) == manifest.declared_total_attempted_trials
    )
    common: dict[str, Any] = {
        "completed_trial_count": len(completed),
        "selection_eligible_trial_count": len(selection_eligible),
        "total_combinations": total_combinations,
    }

    if (
        not complete_search_history
        or len(selection_eligible) < 2
        or observation_count < 4
    ):
        return _unavailable_result(
            family,
            spec,
            status=CSCVStatus.FAMILY_INELIGIBLE,
            **common,
        )

    if (
        manifest.selection_direction is not SelectionDirection.MAXIMIZE
        or manifest.selection_metric != spec.selection_metric_name
    ):
        return _unavailable_result(
            family,
            spec,
            status=CSCVStatus.SELECTION_RULE_INCOMPATIBLE,
            **common,
        )

    periods_per_year = family.returns.sampling.periods_per_year
    if periods_per_year is None or periods_per_year <= 0:
        return _unavailable_result(
            family,
            spec,
            status=CSCVStatus.PERIODS_PER_YEAR_UNAVAILABLE,
            **common,
        )

    period_risk_free_rate_value = annual_to_period_rate(
        spec.annual_risk_free_rate,
        periods_per_year,
    )
    period_values: dict[str, Any] = {
        "periods_per_year": periods_per_year,
        "period_risk_free_rate": period_risk_free_rate_value,
    }
    if observation_count % spec.partition_count != 0:
        return _unavailable_result(
            family,
            spec,
            status=CSCVStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_PARTITIONS,
            **common,
            **period_values,
        )

    observations_per_partition = observation_count // spec.partition_count
    half_sample_observations = observation_count // 2
    if observations_per_partition < 1 or half_sample_observations < 2:
        return _unavailable_result(
            family,
            spec,
            status=CSCVStatus.INSUFFICIENT_HALF_SAMPLE_OBSERVATIONS,
            observations_per_partition=observations_per_partition,
            **common,
            **period_values,
        )

    partitions = _build_partitions(
        family,
        observations_per_partition=observations_per_partition,
    )
    partition_values: dict[str, Any] = {
        "observations_per_partition": observations_per_partition,
        "partitions": partitions,
    }
    if total_combinations > spec.maximum_combinations:
        return _unavailable_result(
            family,
            spec,
            status=CSCVStatus.COMBINATION_LIMIT_EXCEEDED,
            **common,
            **period_values,
            **partition_values,
        )

    matrix = np.column_stack(
        [
            to_simple_returns(family.returns.series_for(trial.trial_id))
            for trial in selection_eligible
        ]
    )
    trial_ids = tuple(trial.trial_id for trial in selection_eligible)
    splits = _calculate_splits(
        matrix,
        trial_ids=trial_ids,
        partition_count=spec.partition_count,
        observations_per_partition=observations_per_partition,
        period_risk_free_rate=period_risk_free_rate_value,
    )
    valid_splits = tuple(
        split for split in splits if split.status is CSCVSplitStatus.ELIGIBLE
    )
    invalid_count = len(splits) - len(valid_splits)
    split_values: dict[str, Any] = {
        "splits": splits,
        "valid_split_count": len(valid_splits),
        "invalid_split_count": invalid_count,
    }
    if invalid_count:
        return _unavailable_result(
            family,
            spec,
            status=CSCVStatus.INCOMPLETE_SPLIT_METRICS,
            **common,
            **period_values,
            **partition_values,
            **split_values,
        )

    logits = np.asarray([split.rank_logit for split in valid_splits], dtype=float)
    selected_is_scores = np.asarray(
        [split.selected_in_sample_score for split in valid_splits],
        dtype=float,
    )
    selected_oos_scores = np.asarray(
        [split.selected_out_of_sample_score for split in valid_splits],
        dtype=float,
    )
    pbo = float(np.mean(logits <= 0.0))
    probability_below_zero = float(np.mean(selected_oos_scores < 0.0))
    intercept, slope, r_squared = _linear_degradation(
        selected_is_scores,
        selected_oos_scores,
    )

    return CSCVResult(
        status=CSCVStatus.ELIGIBLE,
        method=spec.method,
        performance_metric=spec.performance_metric,
        declared_selection_metric=manifest.selection_metric,
        confirmed_selection_metric=spec.selection_metric_name,
        rank_tie_method=spec.rank_tie_method,
        winner_tie_policy=spec.winner_tie_policy,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_risk_free_rate_value,
        observation_count=observation_count,
        partition_count=spec.partition_count,
        observations_per_partition=observations_per_partition,
        total_combinations=total_combinations,
        maximum_combinations=spec.maximum_combinations,
        declared_attempted_trial_count=(manifest.declared_total_attempted_trials),
        completed_trial_count=len(completed),
        selection_eligible_trial_count=len(selection_eligible),
        maximum_acceptable_pbo=spec.maximum_acceptable_pbo,
        partitions=partitions,
        splits=splits,
        valid_split_count=len(valid_splits),
        invalid_split_count=0,
        probability_of_backtest_overfitting=pbo,
        pbo_requirement_met=pbo <= spec.maximum_acceptable_pbo,
        probability_selected_oos_score_below_zero=probability_below_zero,
        mean_rank_logit=float(np.mean(logits)),
        median_rank_logit=float(np.median(logits)),
        performance_degradation_intercept=intercept,
        performance_degradation_slope=slope,
        performance_degradation_r_squared=r_squared,
    )


def _build_partitions(
    family: ExperimentFamily,
    *,
    observations_per_partition: int,
) -> tuple[CSCVPartitionResult, ...]:
    partitions = []
    for zero_index in range(
        family.returns.values.shape[0] // observations_per_partition
    ):
        start = zero_index * observations_per_partition
        stop = start + observations_per_partition
        timestamps = family.returns.timestamps[start:stop]
        partitions.append(
            CSCVPartitionResult(
                partition_index=zero_index + 1,
                observation_count=observations_per_partition,
                start_timestamp=timestamps[0],
                end_timestamp=timestamps[-1],
            )
        )
    return tuple(partitions)


def _calculate_splits(
    matrix: NDArray[np.float64],
    *,
    trial_ids: tuple[str, ...],
    partition_count: int,
    observations_per_partition: int,
    period_risk_free_rate: float,
) -> tuple[CSCVSplitResult, ...]:
    partition_indices = tuple(range(partition_count))
    half = partition_count // 2
    results = []
    for combination_index, in_sample_partitions in enumerate(
        itertools.combinations(partition_indices, half),
        start=1,
    ):
        in_sample_set = frozenset(in_sample_partitions)
        out_of_sample_partitions = tuple(
            index for index in partition_indices if index not in in_sample_set
        )
        in_sample_rows = _rows_for_partitions(
            in_sample_partitions,
            observations_per_partition=observations_per_partition,
        )
        out_of_sample_rows = _rows_for_partitions(
            out_of_sample_partitions,
            observations_per_partition=observations_per_partition,
        )
        in_sample_scores = period_sharpe_scores(
            matrix[in_sample_rows, :],
            period_risk_free_rate_value=period_risk_free_rate,
        )
        out_of_sample_scores = period_sharpe_scores(
            matrix[out_of_sample_rows, :],
            period_risk_free_rate_value=period_risk_free_rate,
        )
        unavailable = tuple(
            trial_ids[index]
            for index in range(len(trial_ids))
            if not math.isfinite(in_sample_scores[index])
            or not math.isfinite(out_of_sample_scores[index])
        )
        public_in_sample = tuple(index + 1 for index in in_sample_partitions)
        public_out_of_sample = tuple(index + 1 for index in out_of_sample_partitions)
        if unavailable:
            results.append(
                CSCVSplitResult(
                    combination_index=combination_index,
                    status=CSCVSplitStatus.PERFORMANCE_METRIC_UNAVAILABLE,
                    in_sample_partition_indices=public_in_sample,
                    out_of_sample_partition_indices=public_out_of_sample,
                    selected_trial_id=None,
                    tied_in_sample_winner_trial_ids=(),
                    selected_in_sample_score=None,
                    selected_out_of_sample_score=None,
                    out_of_sample_rank=None,
                    relative_out_of_sample_rank=None,
                    rank_logit=None,
                    overfit_event=None,
                    selected_out_of_sample_score_below_zero=None,
                    unavailable_trial_ids=unavailable,
                )
            )
            continue

        maximum_score = float(np.max(in_sample_scores))
        tied_winner_indices = tuple(
            index
            for index, score in enumerate(in_sample_scores)
            if score == maximum_score
        )
        selected_index = tied_winner_indices[0]
        out_of_sample_ranks = average_ranks(out_of_sample_scores)
        out_of_sample_rank = float(out_of_sample_ranks[selected_index])
        relative_rank = out_of_sample_rank / (len(trial_ids) + 1.0)
        rank_logit = math.log(relative_rank / (1.0 - relative_rank))
        selected_oos_score = float(out_of_sample_scores[selected_index])
        results.append(
            CSCVSplitResult(
                combination_index=combination_index,
                status=CSCVSplitStatus.ELIGIBLE,
                in_sample_partition_indices=public_in_sample,
                out_of_sample_partition_indices=public_out_of_sample,
                selected_trial_id=trial_ids[selected_index],
                tied_in_sample_winner_trial_ids=tuple(
                    trial_ids[index] for index in tied_winner_indices
                ),
                selected_in_sample_score=maximum_score,
                selected_out_of_sample_score=selected_oos_score,
                out_of_sample_rank=out_of_sample_rank,
                relative_out_of_sample_rank=relative_rank,
                rank_logit=rank_logit,
                overfit_event=rank_logit <= 0.0,
                selected_out_of_sample_score_below_zero=(selected_oos_score < 0.0),
                unavailable_trial_ids=(),
            )
        )
    return tuple(results)


def _rows_for_partitions(
    partition_indices: tuple[int, ...],
    *,
    observations_per_partition: int,
) -> NDArray[np.int64]:
    return np.concatenate(
        [
            np.arange(
                index * observations_per_partition,
                (index + 1) * observations_per_partition,
                dtype=np.int64,
            )
            for index in partition_indices
        ]
    )


def _linear_degradation(
    in_sample: NDArray[np.float64],
    out_of_sample: NDArray[np.float64],
) -> tuple[float | None, float | None, float | None]:
    centered_in_sample = in_sample - np.mean(in_sample)
    centered_out_of_sample = out_of_sample - np.mean(out_of_sample)
    sum_squares_in_sample = float(np.dot(centered_in_sample, centered_in_sample))
    # Centring identical scores need not give exact zeros, so the slope's
    # denominator can be a residue; the regression is unidentified either way.
    if has_zero_sample_variation(in_sample) or sum_squares_in_sample == 0.0:
        return None, None, None
    covariance_sum = float(np.dot(centered_in_sample, centered_out_of_sample))
    slope = covariance_sum / sum_squares_in_sample
    intercept = float(np.mean(out_of_sample) - slope * np.mean(in_sample))
    sum_squares_out_of_sample = float(
        np.dot(centered_out_of_sample, centered_out_of_sample)
    )
    r_squared = (
        0.0
        if has_zero_sample_variation(out_of_sample) or sum_squares_out_of_sample == 0.0
        else covariance_sum**2 / (sum_squares_in_sample * sum_squares_out_of_sample)
    )
    return intercept, slope, r_squared


def _unavailable_result(
    family: ExperimentFamily,
    spec: CSCVSpec,
    *,
    status: CSCVStatus,
    periods_per_year: int | None = None,
    period_risk_free_rate: float | None = None,
    observations_per_partition: int | None = None,
    total_combinations: int,
    completed_trial_count: int,
    selection_eligible_trial_count: int,
    partitions: tuple[CSCVPartitionResult, ...] = (),
    splits: tuple[CSCVSplitResult, ...] = (),
    valid_split_count: int = 0,
    invalid_split_count: int = 0,
) -> CSCVResult:
    return CSCVResult(
        status=status,
        method=spec.method,
        performance_metric=spec.performance_metric,
        declared_selection_metric=family.manifest.selection_metric,
        confirmed_selection_metric=spec.selection_metric_name,
        rank_tie_method=spec.rank_tie_method,
        winner_tie_policy=spec.winner_tie_policy,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_risk_free_rate,
        observation_count=len(family.returns.timestamps),
        partition_count=spec.partition_count,
        observations_per_partition=observations_per_partition,
        total_combinations=total_combinations,
        maximum_combinations=spec.maximum_combinations,
        declared_attempted_trial_count=(
            family.manifest.declared_total_attempted_trials
        ),
        completed_trial_count=completed_trial_count,
        selection_eligible_trial_count=selection_eligible_trial_count,
        maximum_acceptable_pbo=spec.maximum_acceptable_pbo,
        partitions=partitions,
        splits=splits,
        valid_split_count=valid_split_count,
        invalid_split_count=invalid_split_count,
        probability_of_backtest_overfitting=None,
        pbo_requirement_met=None,
        probability_selected_oos_score_below_zero=None,
        mean_rank_logit=None,
        median_rank_logit=None,
        performance_degradation_intercept=None,
        performance_degradation_slope=None,
        performance_degradation_r_squared=None,
    )
