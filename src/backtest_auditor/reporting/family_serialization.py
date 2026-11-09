from typing import Any

from backtest_auditor.application.experiment_family_audit import (
    ExperimentFamilyAuditResult,
)
from backtest_auditor.domain.findings import AuditFinding
from backtest_auditor.domain.results import (
    CSCVResult,
    DeflatedSharpeRatioResult,
    DataSnoopingResult,
    ExperimentSplitAssessmentResult,
    ExperimentTrialAssessmentResult,
    ParameterRobustnessResult,
    TemporalRobustnessResult,
)
from backtest_auditor.reporting.serialization import (
    REPORT_SCHEMA_VERSION,
    evidence_profile_to_dict,
    run_manifest_to_dict,
    validation_issue_to_dict,
)


def experiment_family_audit_to_dict(
    result: ExperimentFamilyAuditResult,
) -> dict[str, Any]:
    """Serialize an experiment-family result as report schema 2.5 data."""

    assessment = result.assessment
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "audit_type": "experiment_family",
        "family_id": result.family_id,
        "evidence_profile": evidence_profile_to_dict(result.evidence_profile),
        "run_manifest": run_manifest_to_dict(result.run_manifest),
        "input_schema_version": assessment.input_schema_version,
        "status": assessment.status.value,
        "structurally_eligible": (
            assessment.selection_bias_methods_structurally_eligible
        ),
        "source": assessment.source,
        "completeness": {
            "declared_total_attempted_trials": (
                assessment.declared_total_attempted_trials
            ),
            "documented_trial_count": assessment.documented_trial_count,
            "documented_attempt_indices": list(assessment.documented_attempt_indices),
            "undocumented_attempt_indices": list(
                assessment.undocumented_attempt_indices
            ),
            "completed_trial_count": assessment.completed_trial_count,
            "failed_trial_count": assessment.failed_trial_count,
            "eligible_trial_count": assessment.eligible_trial_count,
            "excluded_completed_trial_count": (
                assessment.excluded_completed_trial_count
            ),
            "supplied_return_series_count": (assessment.supplied_return_series_count),
            "search_complete_declared": (assessment.search_complete_declared),
            "complete_search_history": (assessment.complete_search_history),
            "winner_only_evidence": assessment.winner_only_evidence,
            "selection_bias_methods_structurally_eligible": (
                assessment.selection_bias_methods_structurally_eligible
            ),
        },
        "selection": {
            "selected_trial_id": assessment.selected_trial_id,
            "selected_trial_attempt_index": (assessment.selected_trial_attempt_index),
            "rule": assessment.selection_rule,
            "metric": assessment.selection_metric,
            "direction": assessment.selection_direction.value,
        },
        "deflated_sharpe_ratio": _dsr_to_dict(result.deflated_sharpe_ratio),
        "cscv_probability_of_backtest_overfitting": _cscv_to_dict(result.cscv),
        "parameter_robustness": _parameter_robustness_to_dict(
            result.parameter_robustness
        ),
        "temporal_robustness": _temporal_robustness_to_dict(result.temporal_robustness),
        "data_snooping": _data_snooping_to_dict(result.data_snooping),
        "return_matrix": {
            "return_basis": assessment.return_basis.value,
            "observation_count": assessment.observation_count,
            "start_timestamp": assessment.start_timestamp.isoformat(),
            "end_timestamp": assessment.end_timestamp.isoformat(),
            "exact_timestamp_alignment": (assessment.exact_timestamp_alignment),
            "declared_frequency": assessment.declared_frequency,
            "periods_per_year": assessment.periods_per_year,
            "timezone": assessment.timezone,
        },
        "parameter_schema": {
            "parameter_count": assessment.parameter_count,
            "parameter_names": list(assessment.parameter_names),
        },
        "benchmark": (
            None
            if assessment.benchmark_id is None
            else {
                "benchmark_id": assessment.benchmark_id,
                "return_basis": (
                    None
                    if assessment.benchmark_return_basis is None
                    else assessment.benchmark_return_basis.value
                ),
                "observation_count": (assessment.benchmark_observation_count),
                "exact_timestamp_alignment": True,
            }
        ),
        "trials": [_trial_to_dict(trial) for trial in result.trials],
        "splits": [_split_to_dict(split_result) for split_result in result.splits],
        "split_metadata": {
            "supplied": assessment.split_metadata_supplied,
            "split_count": assessment.split_count,
        },
        "input_issues": [
            validation_issue_to_dict(issue) for issue in result.input_issues
        ],
        "findings": [_finding_to_dict(finding) for finding in result.findings],
    }


def _dsr_to_dict(
    result: DeflatedSharpeRatioResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    correlation = result.correlation_summary
    return {
        "status": result.status.value,
        "method": result.method.value,
        "trial_count_policy": result.trial_count_policy.value,
        "return_basis": result.return_basis.value,
        "annual_risk_free_rate": result.annual_risk_free_rate,
        "periods_per_year": result.periods_per_year,
        "period_risk_free_rate": result.period_risk_free_rate,
        "required_confidence_level": result.required_confidence_level,
        "observation_count": result.observation_count,
        "trial_counts": {
            "declared_attempted": result.declared_attempted_trial_count,
            "completed": result.completed_trial_count,
            "selection_eligible": result.selection_eligible_trial_count,
            "valid_selection_sharpes": (result.valid_selection_trial_sharpe_count),
            "effective_independent_user_supplied": (
                result.effective_independent_trial_count
            ),
            "effective_count_methodology": (result.effective_trial_count_methodology),
            "effective_count_verified": (result.effective_trial_count_verified),
        },
        "selected_trial": {
            "trial_id": result.selected_trial_id,
            "period_sharpe_ratio": (result.selected_period_sharpe_ratio),
            "iid_annualized_sharpe_ratio": (
                result.selected_iid_annualized_sharpe_ratio
            ),
            "observed_maximum_period_sharpe_ratio": (
                result.observed_maximum_period_sharpe_ratio
            ),
            "observed_maximum_trial_ids": list(result.observed_maximum_trial_ids),
            "is_observed_maximum": (result.selected_is_observed_maximum),
            "sample_skewness": result.selected_sample_skewness,
            "sample_pearson_kurtosis": (result.selected_sample_pearson_kurtosis),
            "sharpe_variance_adjustment": (result.selected_sharpe_variance_adjustment),
            "period_sharpe_standard_error": (
                result.selected_period_sharpe_standard_error
            ),
        },
        "cross_trial_sharpe_distribution": {
            "mean_period_sharpe_ratio": (result.cross_trial_mean_period_sharpe_ratio),
            "sample_standard_deviation": (result.cross_trial_sample_standard_deviation),
        },
        "correlation_summary": (
            None
            if correlation is None
            else {
                "trial_count": correlation.trial_count,
                "pair_count": correlation.pair_count,
                "minimum": correlation.minimum_correlation,
                "maximum": correlation.maximum_correlation,
                "mean": correlation.mean_correlation,
                "median": correlation.median_correlation,
                "strongest_absolute": (correlation.strongest_absolute_correlation),
                "strongest_absolute_trial_ids": (
                    None
                    if correlation.strongest_absolute_correlation_trial_ids is None
                    else list(correlation.strongest_absolute_correlation_trial_ids)
                ),
            }
        ),
        "trial_sharpe_estimates": [
            {
                "trial_id": item.trial_id,
                "included_in_selection": item.included_in_selection,
                "selected": item.selected,
                "observation_count": item.observation_count,
                "period_mean_excess_return": (item.period_mean_excess_return),
                "period_sample_volatility": (item.period_sample_volatility),
                "period_sharpe_ratio": item.period_sharpe_ratio,
                "iid_annualized_sharpe_ratio": (item.iid_annualized_sharpe_ratio),
            }
            for item in result.trial_sharpe_estimates
        ],
        "scenarios": [
            {
                "trial_count_basis": scenario.trial_count_basis.value,
                "trial_count": scenario.trial_count,
                "expected_maximum_standard_normal": (
                    scenario.expected_maximum_standard_normal
                ),
                "expected_maximum_period_sharpe_ratio": (
                    scenario.expected_maximum_period_sharpe_ratio
                ),
                "expected_maximum_iid_annualized_sharpe_ratio": (
                    scenario.expected_maximum_iid_annualized_sharpe_ratio
                ),
                "test_statistic": scenario.test_statistic,
                "deflated_sharpe_ratio": (scenario.deflated_sharpe_ratio),
                "confidence_requirement_met": (scenario.confidence_requirement_met),
            }
            for scenario in result.scenarios
        ],
    }


def _data_snooping_to_dict(
    result: DataSnoopingResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "observation_count": result.observation_count,
        "selection_eligible_trial_count": result.selection_eligible_trial_count,
        "benchmark_id": result.benchmark_id,
        "replications": result.replications,
        "mean_block_length": result.mean_block_length,
        "random_seed": result.random_seed,
        "significance_level": result.significance_level,
        "selected_trial_id": result.selected_trial_id,
        "selected_mean_active_return": result.selected_mean_active_return,
        "observed_maximum_mean_active_return": (
            result.observed_maximum_mean_active_return
        ),
        "observed_maximum_trial_ids": list(result.observed_maximum_trial_ids),
        "white_reality_check_p_value": result.white_reality_check_p_value,
        "white_reality_check_rejects_null": (result.white_reality_check_rejects_null),
        "hansen_spa_p_value": result.hansen_spa_p_value,
        "hansen_spa_rejects_null": result.hansen_spa_rejects_null,
    }


def _cscv_to_dict(result: CSCVResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "method": result.method.value,
        "performance_metric": result.performance_metric.value,
        "declared_selection_metric": result.declared_selection_metric,
        "confirmed_selection_metric": result.confirmed_selection_metric,
        "rank_tie_method": result.rank_tie_method.value,
        "winner_tie_policy": result.winner_tie_policy.value,
        "return_basis": result.return_basis.value,
        "annual_risk_free_rate": result.annual_risk_free_rate,
        "periods_per_year": result.periods_per_year,
        "period_risk_free_rate": result.period_risk_free_rate,
        "observation_count": result.observation_count,
        "partition_count": result.partition_count,
        "observations_per_partition": result.observations_per_partition,
        "total_combinations": result.total_combinations,
        "maximum_combinations": result.maximum_combinations,
        "trial_counts": {
            "declared_attempted": result.declared_attempted_trial_count,
            "completed": result.completed_trial_count,
            "selection_eligible": result.selection_eligible_trial_count,
        },
        "maximum_acceptable_pbo": result.maximum_acceptable_pbo,
        "probability_of_backtest_overfitting": (
            result.probability_of_backtest_overfitting
        ),
        "pbo_requirement_met": result.pbo_requirement_met,
        "probability_selected_oos_score_below_zero": (
            result.probability_selected_oos_score_below_zero
        ),
        "mean_rank_logit": result.mean_rank_logit,
        "median_rank_logit": result.median_rank_logit,
        "performance_degradation": {
            "intercept": result.performance_degradation_intercept,
            "slope": result.performance_degradation_slope,
            "r_squared": result.performance_degradation_r_squared,
        },
        "valid_split_count": result.valid_split_count,
        "invalid_split_count": result.invalid_split_count,
        "partitions": [
            {
                "partition_index": item.partition_index,
                "observation_count": item.observation_count,
                "start_timestamp": item.start_timestamp.isoformat(),
                "end_timestamp": item.end_timestamp.isoformat(),
            }
            for item in result.partitions
        ],
        "splits": [
            {
                "combination_index": item.combination_index,
                "status": item.status.value,
                "in_sample_partition_indices": list(item.in_sample_partition_indices),
                "out_of_sample_partition_indices": list(
                    item.out_of_sample_partition_indices
                ),
                "selected_trial_id": item.selected_trial_id,
                "tied_in_sample_winner_trial_ids": list(
                    item.tied_in_sample_winner_trial_ids
                ),
                "selected_in_sample_score": item.selected_in_sample_score,
                "selected_out_of_sample_score": item.selected_out_of_sample_score,
                "out_of_sample_rank": item.out_of_sample_rank,
                "relative_out_of_sample_rank": (item.relative_out_of_sample_rank),
                "rank_logit": item.rank_logit,
                "overfit_event": item.overfit_event,
                "selected_out_of_sample_score_below_zero": (
                    item.selected_out_of_sample_score_below_zero
                ),
                "unavailable_trial_ids": list(item.unavailable_trial_ids),
            }
            for item in result.splits
        ],
    }


def _parameter_robustness_to_dict(
    result: ParameterRobustnessResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "performance_metric": result.performance_metric.value,
        "declared_selection_metric": result.declared_selection_metric,
        "confirmed_selection_metric": result.confirmed_selection_metric,
        "distance_metric": result.distance_metric.value,
        "return_basis": result.return_basis.value,
        "annual_risk_free_rate": result.annual_risk_free_rate,
        "periods_per_year": result.periods_per_year,
        "period_risk_free_rate": result.period_risk_free_rate,
        "selected_trial_id": result.selected_trial_id,
        "selected_period_sharpe_ratio": result.selected_period_sharpe_ratio,
        "parameter_scales": {name: scale for name, scale in result.parameter_scales},
        "maximum_distance": result.maximum_distance,
        "minimum_neighbor_count": result.minimum_neighbor_count,
        "maximum_acceptable_score_difference": (
            result.maximum_acceptable_score_difference
        ),
        "minimum_acceptable_neighbor_fraction": (
            result.minimum_acceptable_neighbor_fraction
        ),
        "trial_counts": {
            "selection_eligible": result.selection_eligible_trial_count,
            "candidates": result.candidate_trial_count,
            "neighbors": result.neighbor_count,
        },
        "duplicate_configuration_trial_ids": list(
            result.duplicate_configuration_trial_ids
        ),
        "unavailable_neighbor_trial_ids": list(result.unavailable_neighbor_trial_ids),
        "acceptable_neighbor_count": result.acceptable_neighbor_count,
        "acceptable_neighbor_fraction": result.acceptable_neighbor_fraction,
        "neighbor_fraction_requirement_met": (result.neighbor_fraction_requirement_met),
        "selected_is_local_maximum": result.selected_is_local_maximum,
        "neighbor_score_summary": {
            "minimum": result.minimum_neighbor_score,
            "maximum": result.maximum_neighbor_score,
            "mean": result.mean_neighbor_score,
            "maximum_degradation": result.maximum_degradation,
            "maximum_improvement": result.maximum_improvement,
            "steepest_absolute_change_per_distance": (
                result.steepest_absolute_score_change_per_distance
            ),
        },
        "neighbors": [
            {
                "trial_id": item.trial_id,
                "attempt_index": item.attempt_index,
                "standardized_distance": item.standardized_distance,
                "changed_parameter_names": list(item.changed_parameter_names),
                "period_sharpe_ratio": item.period_sharpe_ratio,
                "score_difference_from_selected": (item.score_difference_from_selected),
                "within_acceptable_score_difference": (
                    item.within_acceptable_score_difference
                ),
            }
            for item in result.neighbors
        ],
        "axis_sensitivities": [
            {
                "parameter_name": item.parameter_name,
                "one_axis_neighbor_count": item.one_axis_neighbor_count,
                "closest_lower_trial_id": item.closest_lower_trial_id,
                "closest_lower_score_difference": (item.closest_lower_score_difference),
                "closest_upper_trial_id": item.closest_upper_trial_id,
                "closest_upper_score_difference": (item.closest_upper_score_difference),
                "maximum_absolute_score_change_per_scaled_unit": (
                    item.maximum_absolute_score_change_per_scaled_unit
                ),
            }
            for item in result.axis_sensitivities
        ],
    }


def _temporal_robustness_to_dict(
    result: TemporalRobustnessResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "performance_metric": result.performance_metric.value,
        "declared_selection_metric": result.declared_selection_metric,
        "confirmed_selection_metric": result.confirmed_selection_metric,
        "rank_tie_method": result.rank_tie_method.value,
        "winner_tie_policy": result.winner_tie_policy.value,
        "return_basis": result.return_basis.value,
        "annual_risk_free_rate": result.annual_risk_free_rate,
        "periods_per_year": result.periods_per_year,
        "period_risk_free_rate": result.period_risk_free_rate,
        "observation_count": result.observation_count,
        "window_count": result.window_count,
        "observations_per_window": result.observations_per_window,
        "selected_trial_id": result.selected_trial_id,
        "selection_eligible_trial_count": result.selection_eligible_trial_count,
        "minimum_acceptable_top_half_fraction": (
            result.minimum_acceptable_top_half_fraction
        ),
        "maximum_acceptable_below_zero_fraction": (
            result.maximum_acceptable_below_zero_fraction
        ),
        "valid_window_count": result.valid_window_count,
        "invalid_window_count": result.invalid_window_count,
        "selected_score_summary": {
            "mean": result.selected_score_mean,
            "sample_standard_deviation": (
                result.selected_score_sample_standard_deviation
            ),
            "minimum": result.selected_score_minimum,
            "maximum": result.selected_score_maximum,
            "range": result.selected_score_range,
        },
        "selected_top_half_fraction": result.selected_top_half_fraction,
        "top_half_fraction_requirement_met": (result.top_half_fraction_requirement_met),
        "selected_tied_best_fraction": result.selected_tied_best_fraction,
        "selected_below_zero_fraction": result.selected_below_zero_fraction,
        "below_zero_fraction_requirement_met": (
            result.below_zero_fraction_requirement_met
        ),
        "mean_rank_logit": result.mean_rank_logit,
        "median_rank_logit": result.median_rank_logit,
        "distinct_window_winner_trial_ids": list(
            result.distinct_window_winner_trial_ids
        ),
        "windows": [
            {
                "window_index": item.window_index,
                "status": item.status.value,
                "observation_count": item.observation_count,
                "start_timestamp": item.start_timestamp.isoformat(),
                "end_timestamp": item.end_timestamp.isoformat(),
                "selected_trial_id": item.selected_trial_id,
                "selected_period_sharpe_ratio": (item.selected_period_sharpe_ratio),
                "selected_rank": item.selected_rank,
                "selected_relative_rank": item.selected_relative_rank,
                "selected_rank_logit": item.selected_rank_logit,
                "selected_in_top_half": item.selected_in_top_half,
                "selected_tied_for_best": item.selected_tied_for_best,
                "selected_score_below_zero": item.selected_score_below_zero,
                "tied_best_trial_ids": list(item.tied_best_trial_ids),
                "unavailable_trial_ids": list(item.unavailable_trial_ids),
            }
            for item in result.windows
        ],
        "external_split_consistency": {
            "valid_split_count": result.valid_external_split_count,
            "invalid_split_count": result.invalid_external_split_count,
            "splits": [
                {
                    "split_id": item.split_id,
                    "status": item.status.value,
                    "in_sample_observation_count": (item.in_sample_observation_count),
                    "out_of_sample_observation_count": (
                        item.out_of_sample_observation_count
                    ),
                    "in_sample_winner_trial_id": item.in_sample_winner_trial_id,
                    "tied_in_sample_winner_trial_ids": list(
                        item.tied_in_sample_winner_trial_ids
                    ),
                    "selected_in_sample_score": item.selected_in_sample_score,
                    "selected_out_of_sample_score": (item.selected_out_of_sample_score),
                    "selected_out_of_sample_rank": (item.selected_out_of_sample_rank),
                    "selected_out_of_sample_relative_rank": (
                        item.selected_out_of_sample_relative_rank
                    ),
                    "selected_out_of_sample_rank_logit": (
                        item.selected_out_of_sample_rank_logit
                    ),
                    "selected_out_of_sample_in_top_half": (
                        item.selected_out_of_sample_in_top_half
                    ),
                    "selected_out_of_sample_score_below_zero": (
                        item.selected_out_of_sample_score_below_zero
                    ),
                    "tied_out_of_sample_best_trial_ids": list(
                        item.tied_out_of_sample_best_trial_ids
                    ),
                    "in_sample_winner_retained_out_of_sample": (
                        item.in_sample_winner_retained_out_of_sample
                    ),
                    "unavailable_trial_ids": list(item.unavailable_trial_ids),
                }
                for item in result.external_splits
            ],
        },
    }


def _trial_to_dict(
    result: ExperimentTrialAssessmentResult,
) -> dict[str, Any]:
    return {
        "trial_id": result.trial_id,
        "attempt_index": result.attempt_index,
        "outcome": result.outcome.value,
        "included_in_selection": result.included_in_selection,
        "selected": result.selected,
        "selection_score": result.selection_score,
        "return_series_supplied": result.return_series_supplied,
        "observation_count": result.observation_count,
        "parameters": {
            parameter.name: parameter.value for parameter in result.parameters
        },
        "source": result.source,
        "reason": result.reason,
    }


def _split_to_dict(
    result: ExperimentSplitAssessmentResult,
) -> dict[str, Any]:
    return {
        "split_id": result.split_id,
        "in_sample_observation_count": (result.in_sample_observation_count),
        "out_of_sample_observation_count": (result.out_of_sample_observation_count),
        "in_sample_timestamps": [
            timestamp.isoformat() for timestamp in result.in_sample_timestamps
        ],
        "out_of_sample_timestamps": [
            timestamp.isoformat() for timestamp in result.out_of_sample_timestamps
        ],
        "in_sample_start_timestamp": (result.in_sample_start_timestamp.isoformat()),
        "in_sample_end_timestamp": (result.in_sample_end_timestamp.isoformat()),
        "out_of_sample_start_timestamp": (
            result.out_of_sample_start_timestamp.isoformat()
        ),
        "out_of_sample_end_timestamp": (result.out_of_sample_end_timestamp.isoformat()),
    }


def _finding_to_dict(finding: AuditFinding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "category": finding.category.value,
        "claim": finding.claim,
        "implication": finding.implication,
        "remediation": finding.remediation,
    }
