import json

from backtest_auditor.application.experiment_family_audit import (
    ExperimentFamilyAuditResult,
    ExperimentTrialAssessmentResult,
)
from backtest_auditor.reporting.serialization import REPORT_SCHEMA_VERSION
from backtest_auditor.reporting.evidence_markdown import (
    append_evidence_profile_section,
    append_run_manifest_section,
)


def render_experiment_family_markdown_report(
    result: ExperimentFamilyAuditResult,
) -> str:
    """Render an experiment-family result as a deterministic Markdown report."""

    assessment = result.assessment
    lines = [
        "# Backtest Integrity Audit",
        "",
        f"- Schema version: `{REPORT_SCHEMA_VERSION}`",
        "- Audit type: `experiment_family`",
        f"- Family ID: `{_escape(result.family_id)}`",
        "",
        "## Experiment-family completeness",
        "",
        "| Property | Value |",
        "|---|---:|",
        f"| Status | {assessment.status.value} |",
        (
            "| Declared attempted trials | "
            f"{assessment.declared_total_attempted_trials} |"
        ),
        f"| Documented trials | {assessment.documented_trial_count} |",
        f"| Completed trials | {assessment.completed_trial_count} |",
        f"| Failed trials | {assessment.failed_trial_count} |",
        f"| Selection-eligible trials | {assessment.eligible_trial_count} |",
        (
            "| Completed trials excluded from selection | "
            f"{assessment.excluded_completed_trial_count} |"
        ),
        (f"| Supplied return series | {assessment.supplied_return_series_count} |"),
        (
            "| Search complete declared | "
            f"{str(assessment.search_complete_declared).lower()} |"
        ),
        (
            "| Complete search history | "
            f"{str(assessment.complete_search_history).lower()} |"
        ),
        (
            "| Undocumented attempt indices | "
            f"{_format_indices(assessment.undocumented_attempt_indices)} |"
        ),
        (f"| Winner-only evidence | {str(assessment.winner_only_evidence).lower()} |"),
        (
            "| Later selection-bias methods structurally eligible | "
            f"{str(assessment.selection_bias_methods_structurally_eligible).lower()} |"
        ),
        "",
        (
            "Structural eligibility means only that the family contract is "
            "complete enough for family-level methods. It does not mean that "
            "DSR, CSCV, or PBO supports the strategy."
        ),
        "",
        "## Selection record",
        "",
        "| Property | Value |",
        "|---|---:|",
        (f"| Selected trial ID | {_escape(assessment.selected_trial_id)} |"),
        (f"| Selected attempt index | {assessment.selected_trial_attempt_index} |"),
        f"| Rule | {_escape(assessment.selection_rule)} |",
        f"| Metric | {_escape(assessment.selection_metric)} |",
        f"| Direction | {assessment.selection_direction.value} |",
    ]

    evidence_lines: list[str] = []
    append_evidence_profile_section(evidence_lines, result.evidence_profile)
    append_run_manifest_section(evidence_lines, result.run_manifest)
    lines[6:6] = evidence_lines + [""]

    _append_dsr_section(lines, result)
    _append_cscv_section(lines, result)
    _append_parameter_robustness_section(lines, result)
    _append_temporal_robustness_section(lines, result)
    _append_data_snooping_section(lines, result)

    lines.extend(
        [
            "",
            "## Canonical return matrix",
            "",
            "| Property | Value |",
            "|---|---:|",
            f"| Return basis | {assessment.return_basis.value} |",
            f"| Observation count | {assessment.observation_count} |",
            (
                "| Start timestamp | "
                f"{_escape(assessment.start_timestamp.isoformat())} |"
            ),
            (f"| End timestamp | {_escape(assessment.end_timestamp.isoformat())} |"),
            (
                "| Exact timestamp alignment | "
                f"{str(assessment.exact_timestamp_alignment).lower()} |"
            ),
            (
                "| Declared frequency | "
                f"{_optional_text(assessment.declared_frequency)} |"
            ),
            (f"| Periods per year | {_optional_number(assessment.periods_per_year)} |"),
            f"| Timezone | {_optional_text(assessment.timezone)} |",
            (f"| Parameter schema | {_format_texts(assessment.parameter_names)} |"),
        ]
    )

    lines.extend(["", "## Trial evidence", ""])
    lines.extend(
        [
            (
                "| Attempt | Trial ID | Outcome | In selection | Selected "
                "| Selection score | Returns | Parameters | Source | Reason |"
            ),
            "|---:|---|---|---:|---:|---:|---:|---|---|---|",
        ]
    )
    lines.extend(
        (
            f"| {trial.attempt_index} "
            f"| {_escape(trial.trial_id)} "
            f"| {trial.outcome.value} "
            f"| {str(trial.included_in_selection).lower()} "
            f"| {str(trial.selected).lower()} "
            f"| {_optional_float(trial.selection_score)} "
            f"| {str(trial.return_series_supplied).lower()} "
            f"| {_escape(_parameter_json(trial))} "
            f"| {_optional_text(trial.source)} "
            f"| {_optional_text(trial.reason)} |"
        )
        for trial in result.trials
    )

    lines.extend(["", "## Declared splits", ""])
    if result.splits:
        lines.extend(
            [
                (
                    "| Split ID | In-sample observations | Out-of-sample "
                    "observations | In-sample range | Out-of-sample range |"
                ),
                "|---|---:|---:|---|---|",
            ]
        )
        lines.extend(
            (
                f"| {_escape(split.split_id)} "
                f"| {split.in_sample_observation_count} "
                f"| {split.out_of_sample_observation_count} "
                f"| {_escape(split.in_sample_start_timestamp.isoformat())} to "
                f"{_escape(split.in_sample_end_timestamp.isoformat())} "
                f"| {_escape(split.out_of_sample_start_timestamp.isoformat())} to "
                f"{_escape(split.out_of_sample_end_timestamp.isoformat())} |"
            )
            for split in result.splits
        )
    else:
        lines.append("No train/test or fold membership was supplied.")

    lines.extend(["", "## Shared benchmark", ""])
    if assessment.benchmark_id is None:
        lines.append("No shared benchmark return series was supplied.")
    else:
        lines.extend(
            [
                "| Property | Value |",
                "|---|---:|",
                f"| Benchmark ID | {_escape(assessment.benchmark_id)} |",
                (f"| Return basis | {assessment.benchmark_return_basis.value} |"),  # type: ignore[union-attr]  # QUALITY.md
                (f"| Observation count | {assessment.benchmark_observation_count} |"),
                "| Exact timestamp alignment | true |",
            ]
        )

    lines.extend(["", "## Input issues", ""])
    if result.input_issues:
        lines.extend(
            [
                "| Code | Severity | Blocking | Location | Message |",
                "|---|---|---:|---|---|",
            ]
        )
        lines.extend(
            (
                f"| {_escape(issue.code)} "
                f"| {issue.severity.value} "
                f"| {str(issue.blocking).lower()} "
                f"| {_escape(issue.location or '')} "
                f"| {_escape(issue.message)} |"
            )
            for issue in result.input_issues
        )
    else:
        lines.append("No input issues were recorded.")

    lines.extend(["", "## Findings", ""])
    if result.findings:
        lines.extend(
            [
                ("| Code | Category | Claim | Implication | Remediation |"),
                "|---|---|---|---|---|",
            ]
        )
        lines.extend(
            (
                f"| {_escape(finding.code)} "
                f"| {finding.category.value} "
                f"| {_escape(finding.claim)} "
                f"| {_escape(finding.implication)} "
                f"| {_escape(finding.remediation or '')} |"
            )
            for finding in result.findings
        )
    else:
        lines.append("No audit findings were generated.")
    return "\n".join(lines) + "\n"


def _append_dsr_section(
    lines: list[str],
    result: ExperimentFamilyAuditResult,
) -> None:
    lines.extend(["", "## Deflated Sharpe Ratio", ""])
    dsr = result.deflated_sharpe_ratio
    if dsr is None:
        lines.append("DSR was not configured.")
        return

    lines.extend(
        [
            "| Property | Value |",
            "|---|---:|",
            f"| Status | {dsr.status.value} |",
            f"| Method | {dsr.method.value} |",
            f"| Trial-count policy | {dsr.trial_count_policy.value} |",
            f"| Return basis | {dsr.return_basis.value} |",
            (f"| Annual risk-free rate | {_format_float(dsr.annual_risk_free_rate)} |"),
            (
                "| Period risk-free rate | "
                f"{_optional_float(dsr.period_risk_free_rate)} |"
            ),
            (
                "| Required confidence | "
                f"{_format_float(dsr.required_confidence_level)} |"
            ),
            (f"| Declared attempts | {dsr.declared_attempted_trial_count} |"),
            (f"| Selection-eligible trials | {dsr.selection_eligible_trial_count} |"),
            (
                "| Valid selection-trial Sharpes | "
                f"{dsr.valid_selection_trial_sharpe_count} |"
            ),
            (
                "| Selected period Sharpe | "
                f"{_optional_float(dsr.selected_period_sharpe_ratio)} |"
            ),
            (
                "| Selected IID-scaled annualized Sharpe | "
                f"{_optional_float(dsr.selected_iid_annualized_sharpe_ratio)} |"
            ),
            (
                "| Selected is observed maximum | "
                f"{_optional_boolean(dsr.selected_is_observed_maximum)} |"
            ),
            (
                "| Cross-trial Sharpe standard deviation | "
                f"{_optional_float(dsr.cross_trial_sample_standard_deviation)} |"
            ),
            (
                "| User-supplied effective trial count | "
                f"{_optional_number(dsr.effective_independent_trial_count)} |"
            ),
            (
                "| Effective-count methodology | "
                f"{_optional_text(dsr.effective_trial_count_methodology)} |"
            ),
            (
                "| Effective count verified by auditor | "
                f"{_optional_boolean(dsr.effective_trial_count_verified)} |"
            ),
        ]
    )

    lines.extend(["", "### DSR trial-count scenarios", ""])
    if not dsr.scenarios:
        lines.append("No DSR scenario was eligible for calculation.")
    else:
        lines.extend(
            [
                (
                    "| Count basis | Trials | Expected maximum period Sharpe "
                    "| DSR | Requirement met |"
                ),
                "|---|---:|---:|---:|---:|",
            ]
        )
        lines.extend(
            (
                f"| {scenario.trial_count_basis.value} "
                f"| {scenario.trial_count} "
                f"| {_format_float(scenario.expected_maximum_period_sharpe_ratio)} "
                f"| {_format_float(scenario.deflated_sharpe_ratio)} "
                f"| {str(scenario.confidence_requirement_met).lower()} |"
            )
            for scenario in dsr.scenarios
        )

    correlation = dsr.correlation_summary
    lines.extend(["", "### Trial-dependence evidence", ""])
    if correlation is None:
        lines.append("Pairwise return-correlation evidence is unavailable.")
    else:
        lines.extend(
            [
                "| Property | Value |",
                "|---|---:|",
                f"| Trial pairs | {correlation.pair_count} |",
                f"| Minimum correlation | {_optional_float(correlation.minimum_correlation)} |",
                f"| Maximum correlation | {_optional_float(correlation.maximum_correlation)} |",
                f"| Mean correlation | {_optional_float(correlation.mean_correlation)} |",
                f"| Median correlation | {_optional_float(correlation.median_correlation)} |",
                (
                    "| Strongest absolute correlation | "
                    f"{_optional_float(correlation.strongest_absolute_correlation)} |"
                ),
            ]
        )

    lines.extend(
        [
            "",
            (
                "The classical DSR scenarios use an expected-maximum, "
                "location-only adjustment. Correlation statistics do not "
                "automatically become an effective number of independent "
                "trials, and DSR is not CSCV or PBO."
            ),
        ]
    )


def _append_cscv_section(
    lines: list[str],
    result: ExperimentFamilyAuditResult,
) -> None:
    lines.extend(["", "## CSCV and Probability of Backtest Overfitting", ""])
    cscv = result.cscv
    if cscv is None:
        lines.append("CSCV/PBO was not configured.")
        return

    lines.extend(
        [
            "| Property | Value |",
            "|---|---:|",
            f"| Status | {cscv.status.value} |",
            f"| Method | {cscv.method.value} |",
            f"| Performance metric | {cscv.performance_metric.value} |",
            (
                "| Confirmed selection metric | "
                f"{_escape(cscv.confirmed_selection_metric)} |"
            ),
            f"| Rank tie method | {cscv.rank_tie_method.value} |",
            f"| Winner tie policy | {cscv.winner_tie_policy.value} |",
            f"| Partitions | {cscv.partition_count} |",
            (
                "| Observations per partition | "
                f"{_optional_number(cscv.observations_per_partition)} |"
            ),
            f"| Exact symmetric combinations | {cscv.total_combinations} |",
            f"| Configured combination limit | {cscv.maximum_combinations} |",
            f"| Valid splits | {cscv.valid_split_count} |",
            f"| Invalid splits | {cscv.invalid_split_count} |",
            (
                "| Probability of Backtest Overfitting | "
                f"{_optional_float(cscv.probability_of_backtest_overfitting)} |"
            ),
            (
                "| Maximum acceptable PBO | "
                f"{_format_float(cscv.maximum_acceptable_pbo)} |"
            ),
            (
                "| PBO requirement met | "
                f"{_optional_boolean(cscv.pbo_requirement_met)} |"
            ),
            (
                "| Probability selected OOS score is below zero | "
                f"{_optional_float(cscv.probability_selected_oos_score_below_zero)} |"
            ),
            f"| Mean rank logit | {_optional_float(cscv.mean_rank_logit)} |",
            f"| Median rank logit | {_optional_float(cscv.median_rank_logit)} |",
            (
                "| Performance-degradation slope | "
                f"{_optional_float(cscv.performance_degradation_slope)} |"
            ),
            (
                "| Performance-degradation R-squared | "
                f"{_optional_float(cscv.performance_degradation_r_squared)} |"
            ),
        ]
    )

    lines.extend(["", "### CSCV partitions", ""])
    if not cscv.partitions:
        lines.append("No CSCV partitions were constructed.")
    else:
        lines.extend(
            [
                "| Partition | Observations | Time range |",
                "|---:|---:|---|",
            ]
        )
        lines.extend(
            (
                f"| {item.partition_index} | {item.observation_count} | "
                f"{_escape(item.start_timestamp.isoformat())} to "
                f"{_escape(item.end_timestamp.isoformat())} |"
            )
            for item in cscv.partitions
        )

    lines.extend(["", "### CSCV split evidence", ""])
    if not cscv.splits:
        lines.append("No CSCV split evidence was calculated.")
    else:
        lines.extend(
            [
                (
                    "| Combination | Status | IS partitions | OOS partitions "
                    "| IS winner | IS score | OOS score | OOS rank | Logit | Overfit |"
                ),
                "|---:|---|---|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        lines.extend(
            (
                f"| {item.combination_index} | {item.status.value} | "
                f"{_format_indices(item.in_sample_partition_indices)} | "
                f"{_format_indices(item.out_of_sample_partition_indices)} | "
                f"{_optional_text(item.selected_trial_id)} | "
                f"{_optional_float(item.selected_in_sample_score)} | "
                f"{_optional_float(item.selected_out_of_sample_score)} | "
                f"{_optional_float(item.out_of_sample_rank)} | "
                f"{_optional_float(item.rank_logit)} | "
                f"{_optional_boolean(item.overfit_event)} |"
            )
            for item in cscv.splits
        )

    lines.extend(
        [
            "",
            (
                "CSCV exhaustively reuses each equal-sized half-sample in "
                "both IS and OOS roles. It audits selection-rank degradation; "
                "it is distinct from PSR and full-sample DSR."
            ),
        ]
    )


def _append_parameter_robustness_section(
    lines: list[str],
    result: ExperimentFamilyAuditResult,
) -> None:
    lines.extend(["", "## Parameter-neighborhood robustness", ""])
    parameter = result.parameter_robustness
    if parameter is None:
        lines.append("Parameter-neighborhood robustness was not configured.")
        return
    lines.extend(
        [
            "| Property | Value |",
            "|---|---:|",
            f"| Status | {parameter.status.value} |",
            f"| Performance metric | {parameter.performance_metric.value} |",
            f"| Distance metric | {parameter.distance_metric.value} |",
            (
                "| Confirmed selection metric | "
                f"{_escape(parameter.confirmed_selection_metric)} |"
            ),
            f"| Parameter scales | {_parameter_scales(parameter.parameter_scales)} |",
            f"| Maximum distance | {_format_float(parameter.maximum_distance)} |",
            f"| Required neighbors | {parameter.minimum_neighbor_count} |",
            f"| In-radius neighbors | {parameter.neighbor_count} |",
            (
                "| Duplicate selected configurations | "
                f"{_format_texts(parameter.duplicate_configuration_trial_ids)} |"
            ),
            (
                "| Maximum acceptable absolute Sharpe difference | "
                f"{_format_float(parameter.maximum_acceptable_score_difference)} |"
            ),
            (
                "| Required acceptable-neighbor fraction | "
                f"{_format_float(parameter.minimum_acceptable_neighbor_fraction)} |"
            ),
            (
                "| Observed acceptable-neighbor fraction | "
                f"{_optional_float(parameter.acceptable_neighbor_fraction)} |"
            ),
            (
                "| Neighbor-fraction requirement met | "
                f"{_optional_boolean(parameter.neighbor_fraction_requirement_met)} |"
            ),
            (
                "| Selected is local maximum | "
                f"{_optional_boolean(parameter.selected_is_local_maximum)} |"
            ),
            (
                "| Maximum degradation | "
                f"{_optional_float(parameter.maximum_degradation)} |"
            ),
            (
                "| Maximum improvement | "
                f"{_optional_float(parameter.maximum_improvement)} |"
            ),
            (
                "| Steepest absolute change per distance | "
                f"{_optional_float(parameter.steepest_absolute_score_change_per_distance)} |"
            ),
        ]
    )
    lines.extend(["", "### Local neighbors", ""])
    if not parameter.neighbors:
        lines.append("No tested configurations fall inside the defined neighborhood.")
    else:
        lines.extend(
            [
                (
                    "| Attempt | Trial ID | Distance | Changed parameters | "
                    "Period Sharpe | Difference | Within tolerance |"
                ),
                "|---:|---|---:|---|---:|---:|---:|",
            ]
        )
        lines.extend(
            (
                f"| {item.attempt_index} | {_escape(item.trial_id)} | "
                f"{_format_float(item.standardized_distance)} | "
                f"{_format_texts(item.changed_parameter_names)} | "
                f"{_optional_float(item.period_sharpe_ratio)} | "
                f"{_optional_float(item.score_difference_from_selected)} | "
                f"{_optional_boolean(item.within_acceptable_score_difference)} |"
            )
            for item in parameter.neighbors
        )
    lines.extend(["", "### One-axis sensitivities", ""])
    if not parameter.axis_sensitivities:
        lines.append("One-axis sensitivity summaries are unavailable.")
    else:
        lines.extend(
            [
                (
                    "| Parameter | One-axis neighbors | Closest lower | Lower difference "
                    "| Closest upper | Upper difference | Maximum slope |"
                ),
                "|---|---:|---|---:|---|---:|---:|",
            ]
        )
        lines.extend(
            (
                f"| {_escape(item.parameter_name)} | {item.one_axis_neighbor_count} | "
                f"{_optional_text(item.closest_lower_trial_id)} | "
                f"{_optional_float(item.closest_lower_score_difference)} | "
                f"{_optional_text(item.closest_upper_trial_id)} | "
                f"{_optional_float(item.closest_upper_score_difference)} | "
                f"{_optional_float(item.maximum_absolute_score_change_per_scaled_unit)} |"
            )
            for item in parameter.axis_sensitivities
        )
    lines.extend(
        [
            "",
            (
                "The neighborhood holds every unscaled parameter exactly fixed. "
                "Zero-distance duplicates are preserved separately and do not count "
                "as robustness neighbors."
            ),
        ]
    )


def _append_temporal_robustness_section(
    lines: list[str],
    result: ExperimentFamilyAuditResult,
) -> None:
    lines.extend(["", "## Temporal and declared-split robustness", ""])
    temporal = result.temporal_robustness
    if temporal is None:
        lines.append("Temporal robustness was not configured.")
        return
    lines.extend(
        [
            "| Property | Value |",
            "|---|---:|",
            f"| Status | {temporal.status.value} |",
            f"| Performance metric | {temporal.performance_metric.value} |",
            f"| Rank tie method | {temporal.rank_tie_method.value} |",
            f"| Winner tie policy | {temporal.winner_tie_policy.value} |",
            f"| Equal windows | {temporal.window_count} |",
            (
                "| Observations per window | "
                f"{_optional_number(temporal.observations_per_window)} |"
            ),
            f"| Valid windows | {temporal.valid_window_count} |",
            f"| Invalid windows | {temporal.invalid_window_count} |",
            (
                "| Selected top-half fraction | "
                f"{_optional_float(temporal.selected_top_half_fraction)} |"
            ),
            (
                "| Minimum acceptable top-half fraction | "
                f"{_format_float(temporal.minimum_acceptable_top_half_fraction)} |"
            ),
            (
                "| Top-half requirement met | "
                f"{_optional_boolean(temporal.top_half_fraction_requirement_met)} |"
            ),
            (
                "| Selected below-zero fraction | "
                f"{_optional_float(temporal.selected_below_zero_fraction)} |"
            ),
            (
                "| Maximum acceptable below-zero fraction | "
                f"{_format_float(temporal.maximum_acceptable_below_zero_fraction)} |"
            ),
            (
                "| Below-zero requirement met | "
                f"{_optional_boolean(temporal.below_zero_fraction_requirement_met)} |"
            ),
            f"| Selected score range | {_optional_float(temporal.selected_score_range)} |",
            f"| Mean rank logit | {_optional_float(temporal.mean_rank_logit)} |",
            f"| Median rank logit | {_optional_float(temporal.median_rank_logit)} |",
            (
                "| Distinct window winners | "
                f"{_format_texts(temporal.distinct_window_winner_trial_ids)} |"
            ),
        ]
    )
    lines.extend(["", "### Equal contiguous windows", ""])
    if not temporal.windows:
        lines.append("No temporal windows were constructed.")
    else:
        lines.extend(
            [
                (
                    "| Window | Status | Time range | Selected Sharpe | Rank | Logit "
                    "| Top half | Tied best | Below zero | Best trial IDs |"
                ),
                "|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        lines.extend(
            (
                f"| {item.window_index} | {item.status.value} | "
                f"{_escape(item.start_timestamp.isoformat())} to "
                f"{_escape(item.end_timestamp.isoformat())} | "
                f"{_optional_float(item.selected_period_sharpe_ratio)} | "
                f"{_optional_float(item.selected_rank)} | "
                f"{_optional_float(item.selected_rank_logit)} | "
                f"{_optional_boolean(item.selected_in_top_half)} | "
                f"{_optional_boolean(item.selected_tied_for_best)} | "
                f"{_optional_boolean(item.selected_score_below_zero)} | "
                f"{_format_texts(item.tied_best_trial_ids)} |"
            )
            for item in temporal.windows
        )
    lines.extend(["", "### Declared train/test or fold consistency", ""])
    if not temporal.external_splits:
        lines.append("No declared split was supplied for consistency analysis.")
    else:
        lines.extend(
            [
                (
                    "| Split | Status | IS winner | IS score | OOS score | OOS rank "
                    "| OOS logit | OOS top half | Winner retained |"
                ),
                "|---|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        lines.extend(
            (
                f"| {_escape(item.split_id)} | {item.status.value} | "
                f"{_optional_text(item.in_sample_winner_trial_id)} | "
                f"{_optional_float(item.selected_in_sample_score)} | "
                f"{_optional_float(item.selected_out_of_sample_score)} | "
                f"{_optional_float(item.selected_out_of_sample_rank)} | "
                f"{_optional_float(item.selected_out_of_sample_rank_logit)} | "
                f"{_optional_boolean(item.selected_out_of_sample_in_top_half)} | "
                f"{_optional_boolean(item.in_sample_winner_retained_out_of_sample)} |"
            )
            for item in temporal.external_splits
        )
    lines.extend(
        [
            "",
            (
                "Equal windows describe subperiod rank and sign. Declared splits "
                "independently replay each supplied IS winner into its OOS set. "
                "Neither is CSCV/PBO or a formal structural-break test."
            ),
        ]
    )


def _append_data_snooping_section(
    lines: list[str],
    result: ExperimentFamilyAuditResult,
) -> None:
    lines.extend(["", "## Data-snooping controls", ""])
    data_snooping = result.data_snooping
    if data_snooping is None:
        lines.append("White Reality Check and Hansen SPA were not configured.")
        return
    lines.extend(
        [
            "| Property | Value |",
            "|---|---:|",
            f"| Status | {data_snooping.status.value} |",
            f"| Observation count | {data_snooping.observation_count} |",
            (
                "| Selection-eligible trials | "
                f"{data_snooping.selection_eligible_trial_count} |"
            ),
            f"| Benchmark ID | {_optional_text(data_snooping.benchmark_id)} |",
            f"| Replications | {data_snooping.replications} |",
            f"| Mean block length | {data_snooping.mean_block_length} |",
            f"| Random seed | {data_snooping.random_seed} |",
            (
                "| Significance level | "
                f"{_format_float(data_snooping.significance_level)} |"
            ),
            (f"| Selected trial ID | {_escape(data_snooping.selected_trial_id)} |"),
            (
                "| Selected mean active return | "
                f"{_optional_float(data_snooping.selected_mean_active_return)} |"
            ),
            (
                "| Observed maximum mean active return | "
                f"{_optional_float(data_snooping.observed_maximum_mean_active_return)} |"
            ),
            (
                "| Trials tied at observed maximum | "
                f"{_format_texts(data_snooping.observed_maximum_trial_ids)} |"
            ),
            (
                "| White Reality Check p-value | "
                f"{_optional_float(data_snooping.white_reality_check_p_value)} |"
            ),
            (
                "| White Reality Check rejects null | "
                f"{_optional_boolean(data_snooping.white_reality_check_rejects_null)} |"
            ),
            (
                "| Hansen SPA p-value | "
                f"{_optional_float(data_snooping.hansen_spa_p_value)} |"
            ),
            (
                "| Hansen SPA rejects null | "
                f"{_optional_boolean(data_snooping.hansen_spa_rejects_null)} |"
            ),
            "",
            (
                "Method note: both tests compare the complete selection-eligible "
                "family with the shared benchmark using deterministic stationary "
                "bootstrap resamples. White centers all candidate differentials; "
                "SPA applies Hansen's consistency-based studentized recentering. "
                "Neither is calculated from winner-only evidence."
            ),
        ]
    )


def _parameter_json(trial: ExperimentTrialAssessmentResult) -> str:
    return json.dumps(
        {parameter.name: parameter.value for parameter in trial.parameters},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _format_indices(values: tuple[int, ...]) -> str:
    return "none" if not values else ", ".join(str(item) for item in values)


def _format_texts(values: tuple[str, ...]) -> str:
    return "none" if not values else _escape(", ".join(values))


def _parameter_scales(values: tuple[tuple[str, float], ...]) -> str:
    if not values:
        return "none"
    return _escape(
        ", ".join(f"{name}={format(scale, '.12g')}" for name, scale in values)
    )


def _optional_text(value: str | None) -> str:
    return "not supplied" if value is None else _escape(value)


def _optional_number(value: int | None) -> str:
    return "not supplied" if value is None else str(value)


def _optional_float(value: float | None) -> str:
    return "not supplied" if value is None else format(value, ".12g")


def _format_float(value: float) -> str:
    return format(value, ".12g")


def _optional_boolean(value: bool | None) -> str:
    return "not supplied" if value is None else str(value).lower()


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("\r", " ")
        .replace("\n", " ")
    )
