from backtest_auditor.domain.enums import (
    CSCVStatus,
    DeflatedSharpeRatioStatus,
    DSRTrialCountBasis,
    ParameterRobustnessStatus,
    RobustnessSliceStatus,
    TemporalRobustnessStatus,
)
from backtest_auditor.domain.findings import (
    AuditFinding,
    FindingCategory,
)
from backtest_auditor.domain.results import (
    CSCVResult,
    DeflatedSharpeRatioResult,
    ExperimentFamilyAssessmentResult,
    ParameterRobustnessResult,
    TemporalRobustnessResult,
)


def generate_experiment_family_findings(
    result: ExperimentFamilyAssessmentResult,
    dsr: DeflatedSharpeRatioResult | None,
    cscv: CSCVResult | None,
    parameter_robustness: ParameterRobustnessResult | None,
    temporal_robustness: TemporalRobustnessResult | None,
    *,
    external_splits_supplied: bool,
) -> tuple[AuditFinding, ...]:
    findings: list[AuditFinding] = []
    if not result.complete_search_history:
        findings.append(
            AuditFinding(
                code="EXPERIMENT_SEARCH_HISTORY_INCOMPLETE",
                category=FindingCategory.SELECTION_BIAS,
                claim=(
                    "The supplied evidence is not declared to be the complete "
                    "experiment search history."
                ),
                implication=(
                    "The observed winner cannot be placed reliably within all "
                    "attempted alternatives, so DSR and PBO inputs are "
                    "structurally incomplete."
                ),
                remediation=(
                    "Supply every attempted trial, including failed attempts, "
                    "and set search_complete only when the declaration is true."
                ),
            )
        )
    if result.undocumented_attempt_indices:
        findings.append(
            AuditFinding(
                code="UNDOCUMENTED_ATTEMPTED_TRIALS",
                category=FindingCategory.SELECTION_BIAS,
                claim=(
                    f"{len(result.undocumented_attempt_indices)} declared "
                    "attempt(s) have no trial metadata."
                ),
                implication=(
                    "Missing attempts can hide failed or unfavorable strategy "
                    "variants and understate multiple testing."
                ),
                remediation=(
                    "Add metadata for the missing attempt indices, preserving "
                    "failures and exclusions with explicit reasons."
                ),
            )
        )
    if result.winner_only_evidence:
        findings.append(
            AuditFinding(
                code="WINNER_ONLY_EXPERIMENT_EVIDENCE",
                category=FindingCategory.SELECTION_BIAS,
                claim="Only the selected trial has a supplied return series.",
                implication=(
                    "A survivor-only input cannot quantify how exceptional the "
                    "winner is relative to the search that produced it."
                ),
                remediation=(
                    "Supply return series for every completed trial, not only "
                    "the reported winner."
                ),
            )
        )
    if result.eligible_trial_count < 2:
        findings.append(
            AuditFinding(
                code="INSUFFICIENT_ELIGIBLE_TRIALS_FOR_FAMILY_ANALYSIS",
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "Fewer than two completed trials are included in the selection set."
                ),
                implication=(
                    "There is no multi-trial comparison on which to base "
                    "selection-bias evidence."
                ),
                remediation=(
                    "Supply a genuine experiment family with at least two "
                    "selection-eligible completed trials."
                ),
            )
        )
    if result.observation_count < 4:
        findings.append(
            AuditFinding(
                code="INSUFFICIENT_OBSERVATIONS_FOR_FAMILY_METHODS",
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "The aligned family matrix contains fewer than four "
                    "observations per completed trial."
                ),
                implication=(
                    "Higher-moment DSR inference and symmetric half-sample "
                    "CSCV evidence are not structurally available."
                ),
                remediation="Supply at least four aligned observations.",
            )
        )
    if result.excluded_completed_trial_count > 0:
        findings.append(
            AuditFinding(
                code="COMPLETED_TRIALS_EXCLUDED_FROM_SELECTION",
                category=FindingCategory.SELECTION_BIAS,
                claim=(
                    f"{result.excluded_completed_trial_count} completed "
                    "trial(s) were excluded from the declared selection set."
                ),
                implication=(
                    "Exclusion rules can materially change the apparent rank "
                    "of the winner and must be evaluated before family-level "
                    "statistics are interpreted."
                ),
                remediation=(
                    "Confirm that every exclusion reason was specified before "
                    "observing performance and retain the excluded curves."
                ),
            )
        )
    if result.failed_trial_count > 0:
        findings.append(
            AuditFinding(
                code="FAILED_EXPERIMENT_TRIALS_DOCUMENTED",
                category=FindingCategory.DATA_QUALITY,
                claim=(
                    f"{result.failed_trial_count} attempted trial(s) failed "
                    "and have explicit metadata rather than fabricated returns."
                ),
                implication=(
                    "Later multiple-testing logic must retain their attempt "
                    "count while excluding nonexistent performance series."
                ),
                remediation=None,
            )
        )
    if not result.split_metadata_supplied:
        findings.append(
            AuditFinding(
                code="EXPERIMENT_SPLIT_METADATA_NOT_SUPPLIED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="No declared train/test or fold membership was supplied.",
                implication=(
                    "The family remains usable for DSR and internally "
                    "constructed CSCV, but it cannot preserve an external "
                    "train/test design."
                ),
                remediation=(
                    "Supply the optional split-membership CSV when the research "
                    "process used named train/test folds."
                ),
            )
        )
    _append_dsr_findings(findings, dsr)
    _append_cscv_findings(
        findings,
        cscv,
        external_splits_supplied=external_splits_supplied,
    )
    _append_parameter_robustness_findings(findings, parameter_robustness)
    _append_temporal_robustness_findings(
        findings,
        temporal_robustness,
        external_splits_supplied=external_splits_supplied,
    )
    return tuple(findings)


def _append_dsr_findings(
    findings: list[AuditFinding],
    dsr: DeflatedSharpeRatioResult | None,
) -> None:
    if dsr is None:
        findings.append(
            AuditFinding(
                code="DEFLATED_SHARPE_RATIO_NOT_CONFIGURED",
                category=FindingCategory.SELECTION_BIAS,
                claim="Deflated Sharpe Ratio evidence was not configured.",
                implication=(
                    "The report preserves the experiment family but does not "
                    "quantify whether the selected Sharpe survives the "
                    "declared strategy search."
                ),
                remediation=(
                    "Supply the complete explicit DSR configuration when "
                    "family-level multiple-testing evidence is required."
                ),
            )
        )
        return

    if dsr.status is not DeflatedSharpeRatioStatus.ELIGIBLE:
        messages = {
            DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE: (
                "The experiment family is structurally ineligible for DSR.",
                (
                    "Complete search history, at least two selection-eligible "
                    "trials, and at least four aligned observations are "
                    "required."
                ),
            ),
            DeflatedSharpeRatioStatus.PERIODS_PER_YEAR_UNAVAILABLE: (
                "DSR cannot derive a period risk-free rate.",
                (
                    "A positive periods_per_year declaration is required "
                    "because the configured risk-free rate is annual."
                ),
            ),
            (DeflatedSharpeRatioStatus.INCOMPLETE_TRIAL_SHARPE_DISTRIBUTION): (
                "At least one selection-eligible trial has undefined Sharpe.",
                (
                    "The complete cross-trial Sharpe distribution is required; "
                    "zero-volatility or otherwise undefined trials cannot be "
                    "silently removed."
                ),
            ),
            (DeflatedSharpeRatioStatus.SELECTED_TRIAL_NOT_MAXIMUM_SHARPE): (
                (
                    "The selected trial is not the maximum observed Sharpe "
                    "among selection-eligible trials."
                ),
                (
                    "Classical winner DSR assumes the reported strategy is the "
                    "observed maximum whose selection inflation is being "
                    "tested."
                ),
            ),
            (DeflatedSharpeRatioStatus.SELECTED_RETURN_MOMENTS_UNAVAILABLE): (
                "Selected-trial skewness or kurtosis is unavailable.",
                (
                    "Classical DSR requires both moments to correct Sharpe "
                    "uncertainty for non-normal returns."
                ),
            ),
            (DeflatedSharpeRatioStatus.NON_POSITIVE_SHARPE_VARIANCE_ADJUSTMENT): (
                "The selected Sharpe variance adjustment is non-positive.",
                (
                    "The asymptotic DSR standard error is not defined under "
                    "the observed plug-in moments."
                ),
            ),
            DeflatedSharpeRatioStatus.INVALID_EFFECTIVE_TRIAL_COUNT: (
                (
                    "The supplied effective independent-trial count exceeds "
                    "the selection-eligible trial count."
                ),
                (
                    "An effective count cannot introduce more independent "
                    "trials than the documented selection set contains."
                ),
            ),
        }
        claim, implication = messages[dsr.status]
        findings.append(
            AuditFinding(
                code="DEFLATED_SHARPE_RATIO_UNAVAILABLE",
                category=FindingCategory.SELECTION_BIAS,
                claim=claim,
                implication=implication,
                remediation=(
                    "Correct the reported evidence or configuration; do not "
                    "replace missing family evidence with a default."
                ),
            )
        )
        return

    primary = next(
        scenario
        for scenario in dsr.scenarios
        if scenario.trial_count_basis is DSRTrialCountBasis.SELECTION_ELIGIBLE
    )
    if not primary.confidence_requirement_met:
        findings.append(
            AuditFinding(
                code="DSR_CONFIDENCE_REQUIREMENT_NOT_MET",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    "The selection-eligible-count DSR does not meet the "
                    "configured confidence requirement."
                ),
                implication=(
                    "The selected Sharpe is not sufficiently exceptional "
                    "under the classical independent-trials search "
                    "adjustment and stated assumptions."
                ),
                remediation=(
                    "Treat the result as insufficient evidence; do not add "
                    "data or trials solely to chase the threshold."
                ),
            )
        )

    findings.append(
        AuditFinding(
            code="DSR_INDEPENDENT_TRIALS_APPROXIMATION",
            category=FindingCategory.METHODOLOGICAL_RISK,
            claim=(
                "The primary classical DSR scenario treats every "
                "selection-eligible trial as independent."
            ),
            implication=(
                "Correlated strategy variants can make the literal trial "
                "count differ from the number of effectively independent "
                "tests; the reported correlation summary is evidence, not an "
                "automatic effective-count estimator."
            ),
            remediation=(
                "Interpret the declared-attempt sensitivity and, when an "
                "independence analysis exists, supply its effective count "
                "with a methodology statement."
            ),
        )
    )
    findings.append(
        AuditFinding(
            code="DSR_ASYMPTOTIC_PLUGIN_INFERENCE",
            category=FindingCategory.METHODOLOGICAL_RISK,
            claim=(
                "Classical DSR is an asymptotic plug-in estimate using the "
                "observed cross-trial dispersion and selected-trial moments."
            ),
            implication=(
                "Short histories, few trials, and unstable skewness or "
                "kurtosis estimates can materially change the reported "
                "probability."
            ),
            remediation=(
                "Interpret DSR with the observation and trial counts shown in "
                "the report and retain independent robustness evidence."
            ),
        )
    )
    findings.append(
        AuditFinding(
            code="DSR_SERIAL_DEPENDENCE_NOT_ADJUSTED",
            category=FindingCategory.METHODOLOGICAL_RISK,
            claim=(
                "The classical DSR standard error does not apply a HAC or "
                "other serial-dependence correction."
            ),
            implication=(
                "Serially dependent returns can make the IID-style DSR "
                "uncertainty estimate unreliable."
            ),
            remediation=(
                "Interpret DSR alongside serial-dependence evidence; do not "
                "treat it as a replacement for the Part H adjustment."
            ),
        )
    )
    selected_sharpe = dsr.selected_period_sharpe_ratio
    excluded_better = tuple(
        estimate.trial_id
        for estimate in dsr.trial_sharpe_estimates
        if not estimate.included_in_selection
        and estimate.period_sharpe_ratio is not None
        and selected_sharpe is not None
        and estimate.period_sharpe_ratio > selected_sharpe
    )
    if excluded_better:
        findings.append(
            AuditFinding(
                code="EXCLUDED_TRIALS_EXCEED_SELECTED_SHARPE",
                category=FindingCategory.SELECTION_BIAS,
                claim=(
                    f"{len(excluded_better)} excluded completed trial(s) "
                    "have a higher observed Sharpe than the selected trial."
                ),
                implication=(
                    "The winner is the maximum only within the declared "
                    "selection-eligible set, so exclusion timing and rules are "
                    "material to the DSR interpretation."
                ),
                remediation=(
                    "Verify that the exclusion constraints were fixed before "
                    "performance was observed."
                ),
            )
        )
    if dsr.effective_independent_trial_count is not None:
        findings.append(
            AuditFinding(
                code="USER_SUPPLIED_EFFECTIVE_TRIAL_COUNT_UNVERIFIED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "The effective independent-trial count is user-supplied "
                    "and not verified by the auditor."
                ),
                implication=(
                    "The corresponding DSR scenario is conditional on the "
                    "declared external methodology."
                ),
                remediation=(
                    "Retain reproducible clustering or independence evidence "
                    "alongside the manifest."
                ),
            )
        )


def _append_cscv_findings(
    findings: list[AuditFinding],
    cscv: CSCVResult | None,
    *,
    external_splits_supplied: bool,
) -> None:
    if cscv is None:
        findings.append(
            AuditFinding(
                code="CSCV_PBO_NOT_CONFIGURED",
                category=FindingCategory.SELECTION_BIAS,
                claim="CSCV and Probability of Backtest Overfitting were not configured.",
                implication=(
                    "The report does not measure how often an in-sample "
                    "winner ranks at or below the out-of-sample median across "
                    "symmetric partitions."
                ),
                remediation=(
                    "Supply the complete explicit CSCV configuration when "
                    "out-of-sample rank-degradation evidence is required."
                ),
            )
        )
        return

    if cscv.status is not CSCVStatus.ELIGIBLE:
        messages = {
            CSCVStatus.FAMILY_INELIGIBLE: (
                "The experiment family is structurally ineligible for CSCV/PBO.",
                "Complete search history, two eligible trials, and four observations are required.",
            ),
            CSCVStatus.SELECTION_RULE_INCOMPATIBLE: (
                "The configured CSCV metric does not match the declared selection rule.",
                "PBO requires the same metric and direction as the audited selection process.",
            ),
            CSCVStatus.PERIODS_PER_YEAR_UNAVAILABLE: (
                "CSCV cannot derive the configured period risk-free rate.",
                "A positive periods_per_year declaration is required for an annual rate.",
            ),
            CSCVStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_PARTITIONS: (
                "The observation count is not divisible by the CSCV partition count.",
                "Equal disjoint partitions are required; no remainder was dropped.",
            ),
            CSCVStatus.INSUFFICIENT_HALF_SAMPLE_OBSERVATIONS: (
                "The CSCV half-samples are too short for sample Sharpe ratios.",
                "Every IS and OOS score requires at least two observations.",
            ),
            CSCVStatus.COMBINATION_LIMIT_EXCEEDED: (
                "The exact CSCV combination count exceeds the configured safety limit.",
                "No combinations were sampled because that would change CSCV.",
            ),
            CSCVStatus.INCOMPLETE_SPLIT_METRICS: (
                "At least one CSCV split has an undefined trial Sharpe ratio.",
                "The complete logit distribution is required; no split was dropped.",
            ),
        }
        claim, implication = messages[cscv.status]
        findings.append(
            AuditFinding(
                code="CSCV_PBO_UNAVAILABLE",
                category=FindingCategory.SELECTION_BIAS,
                claim=claim,
                implication=implication,
                remediation=(
                    "Correct the family evidence or explicit CSCV "
                    "configuration; do not substitute a partial calculation."
                ),
            )
        )
        return

    if not cscv.pbo_requirement_met:
        findings.append(
            AuditFinding(
                code="PBO_REQUIREMENT_NOT_MET",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    "The estimated PBO exceeds the configured maximum acceptable value."
                ),
                implication=(
                    "In-sample winners rank at or below the OOS median too "
                    "frequently for the stated requirement."
                ),
                remediation=(
                    "Treat this as adverse selection-process evidence; do not "
                    "optimize strategy parameters against PBO."
                ),
            )
        )
    if cscv.selection_eligible_trial_count <= 10:
        findings.append(
            AuditFinding(
                code="PBO_RANK_GRANULARITY_LIMITED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="The CSCV universe contains ten or fewer eligible trials.",
                implication="The relative ranks and logits have limited resolution.",
                remediation="Interpret the split-level rank distribution shown.",
            )
        )
    if cscv.total_combinations < 100:
        findings.append(
            AuditFinding(
                code="PBO_COMBINATION_RESOLUTION_LIMITED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="The partition count produces fewer than 100 logits.",
                implication="The empirical PBO frequency is coarse.",
                remediation=(
                    "Choose partitions from history and time structure, not "
                    "to obtain a preferred PBO."
                ),
            )
        )

    tied_count = sum(
        len(split.tied_in_sample_winner_trial_ids) > 1 for split in cscv.splits
    )
    if tied_count:
        findings.append(
            AuditFinding(
                code="CSCV_IN_SAMPLE_WINNER_TIES_RESOLVED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=f"{tied_count} CSCV split(s) had tied IS winners.",
                implication=(
                    "The first-by-attempt-index policy determines which tied "
                    "strategy contributes the OOS rank."
                ),
                remediation="Inspect the preserved tied trial IDs.",
            )
        )
    if external_splits_supplied:
        findings.append(
            AuditFinding(
                code="DECLARED_SPLITS_NOT_USED_BY_CSCV",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="Declared external splits are preserved but not reused by CSCV.",
                implication=(
                    "CSCV constructs exhaustive equal-sized symmetric "
                    "half-samples; external validation remains separate."
                ),
                remediation=None,
            )
        )
    findings.extend(
        [
            AuditFinding(
                code="CSCV_TIME_DEPENDENCE_LIMITATION",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "CSCV recombines contiguous partitions and does not remove "
                    "serial dependence or structural breaks."
                ),
                implication="Partition size and regime coverage can affect logits.",
                remediation="Interpret PBO with temporal robustness evidence.",
            ),
            AuditFinding(
                code="CSCV_NOT_A_SELECTION_OBJECTIVE",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="PBO is an audit diagnostic, not an optimization objective.",
                implication="Optimizing against PBO would overfit the diagnostic.",
                remediation="Freeze the search and CSCV configuration in advance.",
            ),
        ]
    )


def _append_parameter_robustness_findings(
    findings: list[AuditFinding],
    result: ParameterRobustnessResult | None,
) -> None:
    if result is None:
        findings.append(
            AuditFinding(
                code="PARAMETER_ROBUSTNESS_NOT_CONFIGURED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="Local parameter-neighborhood robustness was not configured.",
                implication=(
                    "The report does not show whether nearby tested configurations "
                    "form a plateau or a performance cliff."
                ),
                remediation=(
                    "Supply explicit parameter scales, a distance radius, and "
                    "acceptance requirements when neighborhood evidence is required."
                ),
            )
        )
        return
    if result.status is not ParameterRobustnessStatus.ELIGIBLE:
        messages = {
            ParameterRobustnessStatus.FAMILY_INELIGIBLE: (
                "The family is structurally ineligible for parameter robustness.",
                "Complete search history, two eligible trials, and four observations are required.",
            ),
            ParameterRobustnessStatus.SELECTION_RULE_INCOMPATIBLE: (
                "The configured parameter metric does not match the declared maximize rule.",
                "Neighborhood evidence must recalculate the criterion used for selection.",
            ),
            ParameterRobustnessStatus.PERIODS_PER_YEAR_UNAVAILABLE: (
                "Parameter robustness cannot derive the period risk-free rate.",
                "A positive periods_per_year declaration is required for the annual rate.",
            ),
            ParameterRobustnessStatus.PARAMETER_SCHEMA_INCOMPATIBLE: (
                "At least one scaled parameter is absent or non-numeric.",
                "Every scaled dimension must be numeric for every selection-eligible trial.",
            ),
            ParameterRobustnessStatus.SELECTED_SCORE_UNAVAILABLE: (
                "The selected trial has an undefined full-sample Sharpe ratio.",
                "A zero-volatility selected curve cannot anchor a Sharpe neighborhood.",
            ),
            ParameterRobustnessStatus.INSUFFICIENT_NEIGHBORS: (
                "Fewer tested neighbors fall inside the configured radius than required.",
                "The supplied search does not support the requested local robustness claim.",
            ),
            ParameterRobustnessStatus.INCOMPLETE_NEIGHBOR_METRICS: (
                "At least one in-radius neighbor has an undefined Sharpe ratio.",
                "No neighbor was silently removed, so aggregate plateau evidence is unavailable.",
            ),
        }
        claim, implication = messages[result.status]
        findings.append(
            AuditFinding(
                code="PARAMETER_ROBUSTNESS_UNAVAILABLE",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=claim,
                implication=implication,
                remediation=(
                    "Correct the family evidence or explicit neighborhood definition; "
                    "do not widen the radius solely to obtain a favorable result."
                ),
            )
        )
        return
    if not result.neighbor_fraction_requirement_met:
        findings.append(
            AuditFinding(
                code="PARAMETER_NEIGHBORHOOD_FRAGILE",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    "Too few local neighbors remain within the configured absolute "
                    "Sharpe difference."
                ),
                implication=(
                    "The selected result is sensitive to nearby tested parameter changes."
                ),
                remediation="Treat the selected configuration as locally fragile.",
            )
        )
    if result.selected_is_local_maximum is False:
        findings.append(
            AuditFinding(
                code="SELECTED_TRIAL_NOT_LOCAL_SHARPE_MAXIMUM",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="At least one configured neighbor has a higher recalculated Sharpe.",
                implication=(
                    "The declared selection score and the confirmed robustness metric "
                    "do not identify the same local winner."
                ),
                remediation="Inspect the preserved neighbor scores and metric definition.",
            )
        )
    if result.duplicate_configuration_trial_ids:
        findings.append(
            AuditFinding(
                code="DUPLICATE_PARAMETER_CONFIGURATIONS_PRESERVED",
                category=FindingCategory.DATA_QUALITY,
                claim=(
                    f"{len(result.duplicate_configuration_trial_ids)} eligible trial(s) "
                    "duplicate the selected parameter configuration."
                ),
                implication=(
                    "Zero-distance repeats are not independent neighbors and were listed "
                    "separately rather than counted in the plateau fraction."
                ),
                remediation="Inspect why identical configurations were attempted repeatedly.",
            )
        )
    findings.extend(
        [
            AuditFinding(
                code="PARAMETER_NEIGHBORHOOD_DEFINITION_CONDITIONAL",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "The neighborhood is conditional on user-declared scales, radius, "
                    "and fixed values for every unscaled parameter."
                ),
                implication=(
                    "Different predeclared geometry can produce different plateau and cliff evidence."
                ),
                remediation="Record the geometry before interpreting the selected result.",
            ),
            AuditFinding(
                code="PARAMETER_ROBUSTNESS_NOT_A_SELECTION_OBJECTIVE",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="Local robustness is an audit diagnostic, not a tuning objective.",
                implication="Tuning against the diagnostic would reuse the same evidence.",
                remediation="Freeze the search and neighborhood contract in advance.",
            ),
        ]
    )


def _append_temporal_robustness_findings(
    findings: list[AuditFinding],
    result: TemporalRobustnessResult | None,
    *,
    external_splits_supplied: bool,
) -> None:
    if result is None:
        findings.append(
            AuditFinding(
                code="TEMPORAL_ROBUSTNESS_NOT_CONFIGURED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="Equal-window temporal robustness was not configured.",
                implication=(
                    "The report does not show whether selected-trial rank and sign "
                    "are consistent through the audited history."
                ),
                remediation="Supply the complete explicit temporal configuration.",
            )
        )
        return
    if result.status is not TemporalRobustnessStatus.ELIGIBLE:
        messages = {
            TemporalRobustnessStatus.FAMILY_INELIGIBLE: (
                "The family is structurally ineligible for temporal robustness.",
                "Complete search history, two eligible trials, and four observations are required.",
            ),
            TemporalRobustnessStatus.SELECTION_RULE_INCOMPATIBLE: (
                "The temporal metric does not match the declared maximize rule.",
                "Window ranks must use the criterion that produced the selection.",
            ),
            TemporalRobustnessStatus.PERIODS_PER_YEAR_UNAVAILABLE: (
                "Temporal robustness cannot derive the period risk-free rate.",
                "A positive periods_per_year declaration is required for the annual rate.",
            ),
            TemporalRobustnessStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_WINDOWS: (
                "The observation count is not divisible by the configured window count.",
                "No remainder was trimmed from the temporal history.",
            ),
            TemporalRobustnessStatus.INSUFFICIENT_WINDOW_OBSERVATIONS: (
                "At least one equal temporal window would contain fewer than two observations.",
                "Sample Sharpe is undefined for such a window.",
            ),
            TemporalRobustnessStatus.INCOMPLETE_WINDOW_METRICS: (
                "At least one window has an undefined eligible-trial Sharpe ratio.",
                "No trial or window was dropped from aggregate consistency evidence.",
            ),
        }
        claim, implication = messages[result.status]
        findings.append(
            AuditFinding(
                code="TEMPORAL_ROBUSTNESS_UNAVAILABLE",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=claim,
                implication=implication,
                remediation="Correct the evidence or explicit window configuration.",
            )
        )
    else:
        if not result.top_half_fraction_requirement_met:
            findings.append(
                AuditFinding(
                    code="TEMPORAL_TOP_HALF_REQUIREMENT_NOT_MET",
                    category=FindingCategory.STATISTICAL_EVIDENCE,
                    claim=(
                        "The selected trial is in the top half of too few temporal windows."
                    ),
                    implication="Its cross-trial rank is not stable through time.",
                    remediation="Treat the selected performance as temporally fragile.",
                )
            )
        if not result.below_zero_fraction_requirement_met:
            findings.append(
                AuditFinding(
                    code="TEMPORAL_BELOW_ZERO_REQUIREMENT_NOT_MET",
                    category=FindingCategory.STATISTICAL_EVIDENCE,
                    claim=(
                        "The selected Sharpe is below zero in more windows than allowed."
                    ),
                    implication="Positive full-history performance is not persistent by window.",
                    remediation="Inspect regime timing and avoid averaging away adverse subperiods.",
                )
            )
    invalid_external = sum(
        item.status is not RobustnessSliceStatus.ELIGIBLE
        for item in result.external_splits
    )
    failed_retention = sum(
        item.in_sample_winner_retained_out_of_sample is False
        for item in result.external_splits
    )
    if external_splits_supplied and invalid_external:
        findings.append(
            AuditFinding(
                code="EXTERNAL_SPLIT_CONSISTENCY_INCOMPLETE",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=f"{invalid_external} declared split(s) have undefined Sharpe evidence.",
                implication="The affected train/test design remains preserved but unevaluable.",
                remediation="Inspect split size and zero-volatility trial IDs.",
            )
        )
    if failed_retention:
        findings.append(
            AuditFinding(
                code="EXTERNAL_SPLIT_WINNER_NOT_RETAINED",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    f"The in-sample winner was not tied for best out-of-sample in "
                    f"{failed_retention} declared split(s)."
                ),
                implication="The supplied research design shows winner instability.",
                remediation="Treat declared-fold performance as separate adverse evidence.",
            )
        )
    findings.extend(
        [
            AuditFinding(
                code="TEMPORAL_WINDOWS_BOUNDARY_SENSITIVE",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "Equal contiguous windows are descriptive and sensitive to the "
                    "configured count and boundaries."
                ),
                implication=(
                    "They provide a limited stability view, not a formal structural-break test."
                ),
                remediation="Interpret the complete window table without optimizing boundaries.",
            ),
            AuditFinding(
                code="TEMPORAL_ROBUSTNESS_SERIAL_DEPENDENCE_UNADJUSTED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="Window and fold Sharpes are not HAC-adjusted.",
                implication="Serial dependence can affect subperiod score interpretation.",
                remediation="Interpret this evidence alongside the serial diagnostics.",
            ),
        ]
    )
