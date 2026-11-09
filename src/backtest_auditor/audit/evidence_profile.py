from backtest_auditor.domain.enums import (
    AdvancedRiskStatus,
    BenchmarkAlignmentStatus,
    BenchmarkInferenceStatus,
    BootstrapMetric,
    BootstrapMetricStatus,
    BootstrapStatus,
    CSCVStatus,
    DeflatedSharpeRatioStatus,
    DSRTrialCountBasis,
    DataSnoopingStatus,
    ParameterRobustnessStatus,
    PairedSeriesStatus,
    ReturnCostBasis,
    SerialAdjustmentStatus,
    SerialDependenceStatus,
    TemporalRobustnessStatus,
)
from backtest_auditor.domain.evidence import (
    EVIDENCE_PROFILE_BOUNDARY,
    EVIDENCE_PROFILE_METHOD,
    EvidenceDimensionName,
    EvidenceDimensionResult,
    EvidenceProfileResult,
    EvidenceStatus,
)
from backtest_auditor.domain.results import (
    AdvancedRiskStatisticsResult,
    AnnualizedStatisticsResult,
    BenchmarkAlignmentResult,
    BenchmarkAlphaInferenceResult,
    BootstrapResult,
    CSCVResult,
    DeflatedSharpeRatioResult,
    DataSnoopingResult,
    ExperimentFamilyAssessmentResult,
    GrossNetCostDragResult,
    ParameterRobustnessResult,
    ReturnConstructionAssessmentResult,
    RiskFreeSeriesResult,
    SamplingAssessmentResult,
    SerialAdjustmentResult,
    SerialDependenceResult,
    SharpeUncertaintyResult,
    TemporalRobustnessResult,
    TrackRecordLengthResult,
    RegimeAnalysisResult,
)


def build_single_run_evidence_profile(
    *,
    return_construction: ReturnConstructionAssessmentResult,
    sampling: SamplingAssessmentResult,
    annualized_statistics: AnnualizedStatisticsResult | None,
    sharpe_uncertainty: SharpeUncertaintyResult | None,
    track_record_length: TrackRecordLengthResult | None,
    serial_dependence: SerialDependenceResult | None,
    serial_adjustment: SerialAdjustmentResult | None,
    bootstrap: BootstrapResult | None,
    benchmark_alignment: BenchmarkAlignmentResult | None,
    advanced_risk: AdvancedRiskStatisticsResult | None = None,
    risk_free_series: RiskFreeSeriesResult | None = None,
    gross_net_cost_drag: GrossNetCostDragResult | None = None,
    regime_analysis: RegimeAnalysisResult | None = None,
    benchmark_inference: BenchmarkAlphaInferenceResult | None = None,
    input_issue_codes: tuple[str, ...],
    run_manifest_configured: bool,
) -> EvidenceProfileResult:
    return EvidenceProfileResult(
        method=EVIDENCE_PROFILE_METHOD,
        audit_type="single_run",
        dimensions=(
            _input_integrity_dimension(input_issue_codes),
            _return_methodology_dimension(return_construction, gross_net_cost_drag),
            _sampling_dimension(sampling),
            _single_statistical_dimension(
                annualized_statistics,
                sharpe_uncertainty,
                track_record_length,
                advanced_risk,
                risk_free_series,
            ),
            _serial_dimension(serial_dependence, serial_adjustment),
            _resampling_dimension(bootstrap),
            _benchmark_dimension(benchmark_alignment, benchmark_inference),
            _single_regime_dimension(regime_analysis),
            _reproducibility_dimension(run_manifest_configured),
        ),
        interpretation_boundary=EVIDENCE_PROFILE_BOUNDARY,
    )


def build_experiment_family_evidence_profile(
    *,
    assessment: ExperimentFamilyAssessmentResult,
    dsr: DeflatedSharpeRatioResult | None,
    cscv: CSCVResult | None,
    parameter_robustness: ParameterRobustnessResult | None,
    temporal_robustness: TemporalRobustnessResult | None,
    data_snooping: DataSnoopingResult | None = None,
    input_issue_codes: tuple[str, ...],
    run_manifest_configured: bool,
) -> EvidenceProfileResult:
    return EvidenceProfileResult(
        method=EVIDENCE_PROFILE_METHOD,
        audit_type="experiment_family",
        dimensions=(
            _input_integrity_dimension(input_issue_codes),
            _experiment_completeness_dimension(assessment),
            _multiple_testing_dimension(dsr, cscv, data_snooping),
            _parameter_dimension(parameter_robustness),
            _temporal_dimension(temporal_robustness),
            _reproducibility_dimension(run_manifest_configured),
        ),
        interpretation_boundary=EVIDENCE_PROFILE_BOUNDARY,
    )


def _input_integrity_dimension(
    input_issue_codes: tuple[str, ...],
) -> EvidenceDimensionResult:
    supporting = (
        ("CANONICAL_INPUT_ACCEPTED",)
        if not input_issue_codes
        else ("CANONICAL_INPUT_ACCEPTED_AFTER_NORMALIZATION",)
    )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.INPUT_INTEGRITY,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary=(
            "The input passed the canonical blocking validation contract."
            if not input_issue_codes
            else "The input passed blocking validation with preserved normalization issues."
        ),
        supporting_evidence_codes=supporting,
        adverse_evidence_codes=input_issue_codes,
        assumption_codes=("BLOCKING_INPUT_ERRORS_REJECTED_BEFORE_AUDIT",),
    )


def _return_methodology_dimension(
    result: ReturnConstructionAssessmentResult,
    cost_drag: GrossNetCostDragResult | None = None,
) -> EvidenceDimensionResult:
    if not result.supplied:
        # UNDECLARED is in the adverse set below, so a run with no methodology
        # flags at all was published as FRAGILE with the summary "Declared
        # return-construction evidence contains material risk flags" -- for a
        # run where the producer declared nothing. That is the default
        # single-run invocation, so it was the common case.
        if (
            cost_drag is not None
            and cost_drag.alignment.status is PairedSeriesStatus.TIMESTAMP_MISMATCH
        ):
            # A misaligned gross/net pair (1.4.0) is an observed fact, not a
            # declaration, so it stays adverse when nothing was declared.
            return EvidenceDimensionResult(
                dimension=EvidenceDimensionName.RETURN_METHODOLOGY,
                status=EvidenceStatus.FRAGILE,
                summary=(
                    "The gross and net return series are misaligned, and no "
                    "return-construction evidence was declared."
                ),
                adverse_evidence_codes=("GROSS_NET_TIMESTAMP_MISMATCH",),
                unavailable_evidence_codes=("RETURN_CONSTRUCTION_NOT_SUPPLIED",),
                assumption_codes=("UNDECLARED_FIELDS_ARE_NOT_INFERRED",),
                next_evidence_required=(
                    "Supply gross and net returns on identical timestamps, and "
                    "declare cost treatment, leverage, currency, price "
                    "adjustment, provenance, and bias controls.",
                ),
            )
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.RETURN_METHODOLOGY,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="No return-construction evidence was declared.",
            unavailable_evidence_codes=("RETURN_CONSTRUCTION_NOT_SUPPLIED",),
            assumption_codes=("UNDECLARED_FIELDS_ARE_NOT_INFERRED",),
            next_evidence_required=(
                "Declare cost treatment, leverage, currency, price adjustment, "
                "provenance, and bias controls for the return series.",
            ),
        )

    adverse = []
    if result.lookahead_bias_controlled is False:
        adverse.append("LOOKAHEAD_BIAS_NOT_CONTROLLED")
    if result.survivorship_bias_controlled is False:
        adverse.append("SURVIVORSHIP_BIAS_NOT_CONTROLLED")
    if result.cost_basis in {
        ReturnCostBasis.GROSS,
        ReturnCostBasis.MIXED,
        ReturnCostBasis.PARTIALLY_DECLARED,
        ReturnCostBasis.UNDECLARED,
    }:
        adverse.append(f"RETURN_COST_BASIS_{result.cost_basis.value.upper()}")
    if (
        cost_drag is not None
        and cost_drag.alignment.status is PairedSeriesStatus.TIMESTAMP_MISMATCH
    ):
        adverse.append("GROSS_NET_TIMESTAMP_MISMATCH")
    if adverse:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.RETURN_METHODOLOGY,
            status=EvidenceStatus.FRAGILE,
            summary="Declared return-construction evidence contains material risk flags.",
            adverse_evidence_codes=tuple(adverse),
            assumption_codes=("RETURN_CONSTRUCTION_FIELDS_ARE_PRODUCER_DECLARATIONS",),
            next_evidence_required=(
                "Supply net, bias-controlled returns with complete timing and provenance declarations.",
            ),
        )
    if result.completeness_ratio < 1.0:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.RETURN_METHODOLOGY,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Return-construction and leakage declarations are incomplete.",
            unavailable_evidence_codes=("RETURN_CONSTRUCTION_FIELDS_INCOMPLETE",),
            assumption_codes=("UNDECLARED_FIELDS_ARE_NOT_INFERRED",),
            next_evidence_required=(
                "Supply every return-construction, timing, cost, and bias-control field.",
            ),
        )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.RETURN_METHODOLOGY,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="The return-construction declaration is complete without an explicit adverse flag.",
        supporting_evidence_codes=("RETURN_CONSTRUCTION_DECLARATION_COMPLETE",),
        assumption_codes=("RETURN_CONSTRUCTION_FIELDS_ARE_PRODUCER_DECLARATIONS",),
    )


def _sampling_dimension(
    result: SamplingAssessmentResult,
) -> EvidenceDimensionResult:
    if not result.annualization_eligible:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.SAMPLING_ELIGIBILITY,
            status=EvidenceStatus.INELIGIBLE,
            summary="Sampling evidence is not eligible for annualized inference.",
            unavailable_evidence_codes=(
                f"SAMPLING_STATUS_{result.status.value.upper()}",
                "ANNUALIZATION_INELIGIBLE",
            ),
            next_evidence_required=(
                "Supply regular or calendar-verified sampling and an explicit periods-per-year value.",
            ),
        )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.SAMPLING_ELIGIBILITY,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="Sampling supports annualization under the explicit frequency scale.",
        supporting_evidence_codes=(
            f"SAMPLING_STATUS_{result.status.value.upper()}",
            "ANNUALIZATION_ELIGIBLE",
        ),
        assumption_codes=("PERIODS_PER_YEAR_EXPLICIT_OR_VERIFIED",),
    )


def _single_statistical_dimension(
    annualized: AnnualizedStatisticsResult | None,
    uncertainty: SharpeUncertaintyResult | None,
    track_record: TrackRecordLengthResult | None,
    advanced_risk: AdvancedRiskStatisticsResult | None = None,
    risk_free_series: RiskFreeSeriesResult | None = None,
) -> EvidenceDimensionResult:
    if annualized is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.STATISTICAL_EVIDENCE,
            status=EvidenceStatus.INELIGIBLE,
            summary="Annualized statistical evidence is unavailable.",
            unavailable_evidence_codes=("ANNUALIZED_STATISTICS_UNAVAILABLE",),
            next_evidence_required=("Resolve sampling eligibility first.",),
        )
    if uncertainty is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.STATISTICAL_EVIDENCE,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="A point estimate exists, but PSR-style Sharpe uncertainty is unavailable.",
            supporting_evidence_codes=("ANNUALIZED_POINT_ESTIMATES_AVAILABLE",),
            unavailable_evidence_codes=("SHARPE_UNCERTAINTY_UNAVAILABLE",),
            next_evidence_required=(
                "Supply an explicit Sharpe benchmark and enough varying observations for higher moments.",
            ),
        )
    if uncertainty.probabilistic_sharpe_ratio is None:
        # calculate_sharpe_uncertainty returns a populated result object with
        # probabilistic_sharpe_ratio=None when no Sharpe benchmark was given
        # or the higher-moment variance adjustment is non-positive. Testing
        # `uncertainty is None` therefore published
        # PROBABILISTIC_SHARPE_RATIO_AVAILABLE for a report whose PSR field is
        # null and which simultaneously carried
        # NON_POSITIVE_SHARPE_VARIANCE_ESTIMATE in its findings.
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.STATISTICAL_EVIDENCE,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="A point estimate exists, but the PSR value is undefined.",
            supporting_evidence_codes=("ANNUALIZED_POINT_ESTIMATES_AVAILABLE",),
            unavailable_evidence_codes=("PROBABILISTIC_SHARPE_RATIO_UNAVAILABLE",),
            next_evidence_required=(
                "Supply an explicit Sharpe benchmark, and enough varying "
                "observations for a positive higher-moment variance estimate.",
            ),
        )
    if track_record is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.STATISTICAL_EVIDENCE,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="PSR is available, but no explicit confidence requirement was configured.",
            supporting_evidence_codes=("PROBABILISTIC_SHARPE_RATIO_AVAILABLE",),
            unavailable_evidence_codes=("PSR_CONFIDENCE_REQUIREMENT_NOT_CONFIGURED",),
            assumption_codes=("ASYMPTOTIC_HIGHER_MOMENT_SHARPE_INFERENCE",),
            next_evidence_required=(
                "Supply an explicit required PSR confidence level.",
            ),
        )
    if not track_record.confidence_requirement_met:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.STATISTICAL_EVIDENCE,
            status=EvidenceStatus.FRAGILE,
            summary="The configured PSR confidence requirement is not met.",
            supporting_evidence_codes=("PROBABILISTIC_SHARPE_RATIO_AVAILABLE",),
            adverse_evidence_codes=("PSR_CONFIDENCE_REQUIREMENT_NOT_MET",),
            assumption_codes=("ASYMPTOTIC_HIGHER_MOMENT_SHARPE_INFERENCE",),
            next_evidence_required=(
                "Treat the evidence as insufficient; collect genuinely new observations rather than retuning the threshold.",
            ),
        )
    supporting = [
        "PROBABILISTIC_SHARPE_RATIO_AVAILABLE",
        "PSR_CONFIDENCE_REQUIREMENT_MET",
    ]
    # As for PSR above: the result object exists in its ineligible states too
    # (e.g. downside_deviation_zero, where Sortino and Omega are null), so the
    # availability code follows the status, not the object.
    if (
        advanced_risk is not None
        and advanced_risk.status is AdvancedRiskStatus.ELIGIBLE
    ):
        supporting.append("ADVANCED_DOWNSIDE_TAIL_STATISTICS_AVAILABLE")
    if (
        risk_free_series is not None
        and risk_free_series.alignment.status is PairedSeriesStatus.ELIGIBLE
    ):
        supporting.append("TIME_VARYING_RISK_FREE_SERIES_ALIGNED")
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.STATISTICAL_EVIDENCE,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="The configured PSR confidence requirement is met.",
        supporting_evidence_codes=tuple(supporting),
        assumption_codes=("ASYMPTOTIC_HIGHER_MOMENT_SHARPE_INFERENCE",),
    )


def _serial_dimension(
    dependence: SerialDependenceResult | None,
    adjustment: SerialAdjustmentResult | None,
) -> EvidenceDimensionResult:
    if dependence is None and adjustment is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.SERIAL_ROBUSTNESS,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Serial-dependence evidence was not configured.",
            unavailable_evidence_codes=("SERIAL_DIAGNOSTIC_NOT_CONFIGURED",),
            next_evidence_required=(
                "Configure both a serial diagnostic and HAC adjustment.",
            ),
        )
    if adjustment is None:
        if dependence is not None and dependence.status is not (
            SerialDependenceStatus.ELIGIBLE
        ):
            # calculate_serial_dependence returns a fully populated result with
            # every estimate None when the status is INSUFFICIENT_OBSERVATIONS
            # or ZERO_VARIANCE. Claiming SERIAL_DIAGNOSTIC_AVAILABLE there
            # contradicted the findings list of the same report.
            return EvidenceDimensionResult(
                dimension=EvidenceDimensionName.SERIAL_ROBUSTNESS,
                status=EvidenceStatus.INELIGIBLE,
                summary=(
                    "The configured serial diagnostic is unavailable for this series."
                ),
                unavailable_evidence_codes=(
                    f"SERIAL_DEPENDENCE_STATUS_{dependence.status.value.upper()}",
                ),
                next_evidence_required=(
                    "Resolve the reported serial-diagnostic eligibility failure.",
                ),
            )
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.SERIAL_ROBUSTNESS,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Serial dependence may be diagnosed, but adjusted inference is absent.",
            supporting_evidence_codes=("SERIAL_DIAGNOSTIC_AVAILABLE",),
            unavailable_evidence_codes=("HAC_ADJUSTMENT_NOT_CONFIGURED",),
            next_evidence_required=("Configure an explicit HAC lag and kernel.",),
        )
    if adjustment.status is not SerialAdjustmentStatus.ELIGIBLE:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.SERIAL_ROBUSTNESS,
            status=EvidenceStatus.INELIGIBLE,
            summary="The configured serial adjustment is unavailable for this series.",
            unavailable_evidence_codes=(
                f"SERIAL_ADJUSTMENT_STATUS_{adjustment.status.value.upper()}",
            ),
            next_evidence_required=("Resolve the reported HAC eligibility failure.",),
        )
    supporting = ["HAC_ADJUSTMENT_ELIGIBLE"]
    adverse = []
    if dependence is not None and dependence.serial_dependence_detected is True:
        adverse.append("SERIAL_DEPENDENCE_DETECTED")
    if dependence is not None and dependence.runs_dependence_detected is True:
        adverse.append("RUNS_DEPENDENCE_DETECTED")
    if dependence is not None and any(
        item.dependence_detected is True for item in dependence.variance_ratios
    ):
        adverse.append("VARIANCE_RATIO_DEPENDENCE_DETECTED")
    if dependence is not None and dependence.partial_autocorrelations:
        supporting.append("PARTIAL_AUTOCORRELATIONS_AVAILABLE")
    if adjustment.hac_confidence_requirement_met is False:
        adverse.append("HAC_PSR_CONFIDENCE_REQUIREMENT_NOT_MET")
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.SERIAL_ROBUSTNESS,
            status=EvidenceStatus.FRAGILE,
            summary="HAC-adjusted Sharpe evidence fails the configured confidence requirement.",
            supporting_evidence_codes=tuple(supporting),
            adverse_evidence_codes=tuple(adverse),
            assumption_codes=("BARTLETT_HAC_WITH_EXPLICIT_BANDWIDTH",),
            next_evidence_required=(
                "Treat the serially adjusted evidence as fragile.",
            ),
        )
    if adjustment.hac_confidence_requirement_met is True:
        supporting.append("HAC_PSR_CONFIDENCE_REQUIREMENT_MET")
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.SERIAL_ROBUSTNESS,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="The configured HAC adjustment is available without a failed requirement.",
        supporting_evidence_codes=tuple(supporting),
        adverse_evidence_codes=tuple(adverse),
        assumption_codes=("BARTLETT_HAC_WITH_EXPLICIT_BANDWIDTH",),
    )


def _resampling_dimension(
    result: BootstrapResult | None,
) -> EvidenceDimensionResult:
    if result is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.RESAMPLING_ROBUSTNESS,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Time-series bootstrap evidence was not configured.",
            unavailable_evidence_codes=("BOOTSTRAP_NOT_CONFIGURED",),
            next_evidence_required=(
                "Configure the bootstrap method, interval, block length, replications, and seed.",
            ),
        )
    if result.status is not BootstrapStatus.ELIGIBLE:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.RESAMPLING_ROBUSTNESS,
            status=EvidenceStatus.INELIGIBLE,
            summary="The configured bootstrap is unavailable for this series.",
            unavailable_evidence_codes=(
                f"BOOTSTRAP_STATUS_{result.status.value.upper()}",
            ),
            next_evidence_required=(
                "Resolve the reported bootstrap eligibility failure.",
            ),
        )
    sharpe_metric = next(
        (
            item
            for item in result.metrics
            if item.metric is BootstrapMetric.PERIOD_SHARPE_RATIO
        ),
        None,
    )
    if (
        sharpe_metric is None
        or sharpe_metric.status is not BootstrapMetricStatus.ELIGIBLE
        or sharpe_metric.lower_bound is None
        or sharpe_metric.upper_bound is None
    ):
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.RESAMPLING_ROBUSTNESS,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Bootstrap intervals exist, but the period-Sharpe interval is unavailable.",
            supporting_evidence_codes=("BOOTSTRAP_EXECUTION_ELIGIBLE",),
            unavailable_evidence_codes=(
                "BOOTSTRAP_PERIOD_SHARPE_INTERVAL_UNAVAILABLE",
            ),
            assumption_codes=("MOVING_BLOCK_LENGTH_USER_SUPPLIED",),
            next_evidence_required=(
                "Supply the explicit Sharpe inputs required by the bootstrap metric.",
            ),
        )
    if sharpe_metric.lower_bound <= 0.0:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.RESAMPLING_ROBUSTNESS,
            status=EvidenceStatus.FRAGILE,
            summary="The bootstrap period-Sharpe interval is not strictly above zero.",
            supporting_evidence_codes=("BOOTSTRAP_PERIOD_SHARPE_INTERVAL_AVAILABLE",),
            adverse_evidence_codes=(
                "BOOTSTRAP_PERIOD_SHARPE_LOWER_BOUND_NOT_POSITIVE",
            ),
            assumption_codes=(
                "MOVING_BLOCK_LENGTH_USER_SUPPLIED",
                "ZERO_PERIOD_SHARPE_REFERENCE",
            ),
            next_evidence_required=(
                "Treat resampling support as fragile under the configured interval.",
            ),
        )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.RESAMPLING_ROBUSTNESS,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="The bootstrap period-Sharpe interval is strictly above zero.",
        supporting_evidence_codes=(
            "BOOTSTRAP_PERIOD_SHARPE_INTERVAL_AVAILABLE",
            "BOOTSTRAP_PERIOD_SHARPE_LOWER_BOUND_POSITIVE",
        ),
        assumption_codes=(
            "MOVING_BLOCK_LENGTH_USER_SUPPLIED",
            "ZERO_PERIOD_SHARPE_REFERENCE",
        ),
    )


def _benchmark_dimension(
    alignment: BenchmarkAlignmentResult | None,
    inference: BenchmarkAlphaInferenceResult | None = None,
) -> EvidenceDimensionResult:
    if alignment is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.BENCHMARK_EVIDENCE,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="No benchmark-relative evidence was supplied.",
            unavailable_evidence_codes=("BENCHMARK_NOT_SUPPLIED",),
            next_evidence_required=(
                "Supply a timestamp-aligned benchmark when relative claims are required.",
            ),
        )
    if alignment.status is not BenchmarkAlignmentStatus.ELIGIBLE:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.BENCHMARK_EVIDENCE,
            status=EvidenceStatus.INELIGIBLE,
            summary="Benchmark-relative statistics are withheld because timestamps do not align.",
            unavailable_evidence_codes=("BENCHMARK_TIMESTAMP_MISMATCH",),
            next_evidence_required=(
                "Supply exactly aligned benchmark observations without inner-joining.",
            ),
        )
    supporting = ["BENCHMARK_EXACT_TIMESTAMP_ALIGNMENT"]
    adverse = []
    if inference is not None:
        if inference.status is BenchmarkInferenceStatus.ELIGIBLE:
            supporting.append("BENCHMARK_ALPHA_HAC_INFERENCE_AVAILABLE")
            if inference.statistically_different_from_zero is False:
                adverse.append("BENCHMARK_ALPHA_NOT_DIFFERENT_FROM_ZERO")
        else:
            adverse.append(
                f"BENCHMARK_INFERENCE_STATUS_{inference.status.value.upper()}"
            )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.BENCHMARK_EVIDENCE,
        status=(
            EvidenceStatus.FRAGILE
            if adverse
            else EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS
        ),
        summary="Benchmark-relative evidence is available on exact timestamps.",
        supporting_evidence_codes=tuple(supporting),
        adverse_evidence_codes=tuple(adverse),
        assumption_codes=("BENCHMARK_COMPARABILITY_DECLARATIONS_APPLY",),
    )


def _experiment_completeness_dimension(
    result: ExperimentFamilyAssessmentResult,
) -> EvidenceDimensionResult:
    if not result.selection_bias_methods_structurally_eligible:
        unavailable = []
        if not result.complete_search_history:
            unavailable.append("COMPLETE_SEARCH_HISTORY_UNAVAILABLE")
        if result.eligible_trial_count < 2:
            unavailable.append("INSUFFICIENT_SELECTION_ELIGIBLE_TRIALS")
        if result.observation_count < 4:
            unavailable.append("INSUFFICIENT_ALIGNED_OBSERVATIONS")
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.EXPERIMENT_COMPLETENESS,
            status=EvidenceStatus.INELIGIBLE,
            summary="The experiment family is structurally incomplete for selection-bias methods.",
            unavailable_evidence_codes=tuple(unavailable),
            next_evidence_required=(
                "Supply the complete attempted search and aligned eligible trial matrix.",
            ),
        )
    adverse = (
        ("COMPLETED_TRIALS_EXCLUDED_FROM_SELECTION",)
        if result.excluded_completed_trial_count
        else ()
    )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.EXPERIMENT_COMPLETENESS,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="The complete declared experiment family supports family-level methods.",
        supporting_evidence_codes=(
            "COMPLETE_SEARCH_HISTORY",
            "ALIGNED_SELECTION_ELIGIBLE_TRIAL_MATRIX",
        ),
        adverse_evidence_codes=adverse,
        assumption_codes=("SEARCH_COMPLETE_DECLARATION_IS_ACCURATE",),
    )


def _multiple_testing_dimension(
    dsr: DeflatedSharpeRatioResult | None,
    cscv: CSCVResult | None,
    data_snooping: DataSnoopingResult | None = None,
) -> EvidenceDimensionResult:
    if dsr is None and cscv is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.MULTIPLE_TESTING_EVIDENCE,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Neither DSR nor CSCV/PBO was configured.",
            unavailable_evidence_codes=(
                "DSR_NOT_CONFIGURED",
                "CSCV_PBO_NOT_CONFIGURED",
            ),
            next_evidence_required=(
                "Configure both complementary selection-bias methods.",
            ),
        )
    unavailable = []
    if dsr is None:
        unavailable.append("DSR_NOT_CONFIGURED")
    elif dsr.status is not DeflatedSharpeRatioStatus.ELIGIBLE:
        unavailable.append(f"DSR_STATUS_{dsr.status.value.upper()}")
    if cscv is None:
        unavailable.append("CSCV_PBO_NOT_CONFIGURED")
    elif cscv.status is not CSCVStatus.ELIGIBLE:
        unavailable.append(f"CSCV_STATUS_{cscv.status.value.upper()}")
    if unavailable:
        status = (
            EvidenceStatus.INELIGIBLE
            if any("STATUS_" in item for item in unavailable)
            else EvidenceStatus.INSUFFICIENT_EVIDENCE
        )
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.MULTIPLE_TESTING_EVIDENCE,
            status=status,
            summary="The complementary DSR and CSCV/PBO evidence set is incomplete.",
            unavailable_evidence_codes=tuple(unavailable),
            next_evidence_required=(
                "Resolve eligibility and configure both DSR and CSCV/PBO.",
            ),
        )
    assert dsr is not None and cscv is not None
    primary_dsr = next(
        scenario
        for scenario in dsr.scenarios
        if scenario.trial_count_basis is DSRTrialCountBasis.SELECTION_ELIGIBLE
    )
    adverse = []
    supporting = []
    if primary_dsr.confidence_requirement_met:
        supporting.append("DSR_CONFIDENCE_REQUIREMENT_MET")
    else:
        adverse.append("DSR_CONFIDENCE_REQUIREMENT_NOT_MET")
    if cscv.pbo_requirement_met:
        supporting.append("PBO_REQUIREMENT_MET")
    else:
        adverse.append("PBO_REQUIREMENT_NOT_MET")
    if data_snooping is not None:
        if data_snooping.status is not DataSnoopingStatus.ELIGIBLE:
            adverse.append(f"DATA_SNOOPING_STATUS_{data_snooping.status.value.upper()}")
        else:
            supporting.append("WHITE_REALITY_CHECK_AVAILABLE")
            supporting.append("HANSEN_SPA_AVAILABLE")
            if data_snooping.white_reality_check_rejects_null is False:
                adverse.append("WHITE_REALITY_CHECK_NULL_NOT_REJECTED")
            if data_snooping.hansen_spa_rejects_null is False:
                adverse.append("HANSEN_SPA_NULL_NOT_REJECTED")
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.MULTIPLE_TESTING_EVIDENCE,
        status=(
            EvidenceStatus.FRAGILE
            if adverse
            else EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS
        ),
        summary=(
            "At least one configured selection-bias requirement fails."
            if adverse
            else "Both configured DSR and PBO requirements are met."
        ),
        supporting_evidence_codes=tuple(supporting),
        adverse_evidence_codes=tuple(adverse),
        assumption_codes=(
            "DSR_CLASSICAL_INDEPENDENT_TRIAL_APPROXIMATION",
            "CSCV_EQUAL_SYMMETRIC_PARTITIONS",
        ),
        next_evidence_required=(
            (
                "Treat the selection process as fragile; do not optimize "
                "against these diagnostics.",
            )
            if adverse
            else ()
        ),
    )


def _parameter_dimension(
    result: ParameterRobustnessResult | None,
) -> EvidenceDimensionResult:
    if result is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.PARAMETER_ROBUSTNESS,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Parameter-neighborhood robustness was not configured.",
            unavailable_evidence_codes=("PARAMETER_ROBUSTNESS_NOT_CONFIGURED",),
            next_evidence_required=(
                "Supply explicit parameter scales, radius, density, and tolerance requirements.",
            ),
        )
    if result.status is not ParameterRobustnessStatus.ELIGIBLE:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.PARAMETER_ROBUSTNESS,
            status=EvidenceStatus.INELIGIBLE,
            summary="The configured parameter neighborhood is unavailable.",
            unavailable_evidence_codes=(
                f"PARAMETER_ROBUSTNESS_STATUS_{result.status.value.upper()}",
            ),
            next_evidence_required=(
                "Resolve the reported neighborhood eligibility failure without widening it for a preferred result.",
            ),
        )
    adverse = []
    supporting = []
    if result.neighbor_fraction_requirement_met:
        supporting.append("PARAMETER_NEIGHBOR_FRACTION_REQUIREMENT_MET")
    else:
        adverse.append("PARAMETER_NEIGHBOR_FRACTION_REQUIREMENT_NOT_MET")
    if result.selected_is_local_maximum:
        supporting.append("SELECTED_TRIAL_IS_LOCAL_MAXIMUM")
    else:
        adverse.append("SELECTED_TRIAL_NOT_LOCAL_MAXIMUM")
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.PARAMETER_ROBUSTNESS,
        status=(
            EvidenceStatus.FRAGILE
            if adverse
            else EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS
        ),
        summary=(
            "The selected configuration is fragile within the declared neighborhood."
            if adverse
            else "The selected configuration meets the declared local robustness requirements."
        ),
        supporting_evidence_codes=tuple(supporting),
        adverse_evidence_codes=tuple(adverse),
        assumption_codes=("USER_DECLARED_PARAMETER_GEOMETRY",),
        next_evidence_required=(
            (
                "Treat the local result as fragile under the frozen "
                "neighborhood definition.",
            )
            if adverse
            else ()
        ),
    )


def _temporal_dimension(
    result: TemporalRobustnessResult | None,
) -> EvidenceDimensionResult:
    if result is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.TEMPORAL_ROBUSTNESS,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="Temporal robustness was not configured.",
            unavailable_evidence_codes=("TEMPORAL_ROBUSTNESS_NOT_CONFIGURED",),
            next_evidence_required=(
                "Supply equal-window requirements and explicit tie policies.",
            ),
        )
    if result.status is not TemporalRobustnessStatus.ELIGIBLE:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.TEMPORAL_ROBUSTNESS,
            status=EvidenceStatus.INELIGIBLE,
            summary="The configured equal-window temporal analysis is unavailable.",
            unavailable_evidence_codes=(
                f"TEMPORAL_ROBUSTNESS_STATUS_{result.status.value.upper()}",
            ),
            next_evidence_required=(
                "Resolve the reported temporal eligibility failure without trimming history.",
            ),
        )
    adverse = []
    supporting = []
    if result.top_half_fraction_requirement_met:
        supporting.append("TEMPORAL_TOP_HALF_REQUIREMENT_MET")
    else:
        adverse.append("TEMPORAL_TOP_HALF_REQUIREMENT_NOT_MET")
    if result.below_zero_fraction_requirement_met:
        supporting.append("TEMPORAL_BELOW_ZERO_REQUIREMENT_MET")
    else:
        adverse.append("TEMPORAL_BELOW_ZERO_REQUIREMENT_NOT_MET")
    failed_retention = sum(
        item.in_sample_winner_retained_out_of_sample is False
        for item in result.external_splits
    )
    if failed_retention:
        adverse.append("EXTERNAL_SPLIT_WINNER_NOT_RETAINED")
    elif result.external_splits:
        supporting.append("EXTERNAL_SPLIT_WINNERS_RETAINED")
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.TEMPORAL_ROBUSTNESS,
        status=(
            EvidenceStatus.FRAGILE
            if adverse
            else EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS
        ),
        summary=(
            "At least one temporal or declared-fold consistency condition fails."
            if adverse
            else "The configured temporal requirements are met."
        ),
        supporting_evidence_codes=tuple(supporting),
        adverse_evidence_codes=tuple(adverse),
        assumption_codes=(
            "EQUAL_CONTIGUOUS_WINDOWS_ARE_DESCRIPTIVE",
            "SUBPERIOD_SHARPES_NOT_HAC_ADJUSTED",
        ),
        next_evidence_required=(
            (
                "Treat temporal evidence as fragile and inspect every "
                "preserved window and fold.",
            )
            if adverse
            else ()
        ),
    )


def _single_regime_dimension(
    result: RegimeAnalysisResult | None,
) -> EvidenceDimensionResult:
    if result is None:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.TEMPORAL_ROBUSTNESS,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="No externally declared regime labels were supplied.",
            unavailable_evidence_codes=("DECLARED_REGIME_LABELS_NOT_SUPPLIED",),
            next_evidence_required=(
                "Supply timestamp-aligned external regime labels when conditional claims are required.",
            ),
        )
    if result.status is not PairedSeriesStatus.ELIGIBLE:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.TEMPORAL_ROBUSTNESS,
            status=EvidenceStatus.INELIGIBLE,
            summary="Declared regimes are unavailable because timestamps do not align.",
            unavailable_evidence_codes=("REGIME_TIMESTAMP_MISMATCH",),
            next_evidence_required=(
                "Supply one regime label for every return timestamp.",
            ),
        )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.TEMPORAL_ROBUSTNESS,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="Conditional statistics are available for externally declared regimes.",
        supporting_evidence_codes=("DECLARED_REGIME_ANALYSIS_AVAILABLE",),
        assumption_codes=(
            "REGIME_LABELS_ARE_EXTERNAL_PRODUCER_DECLARATIONS",
            "REGIMES_ARE_NOT_INFERRED_OR_OPTIMIZED",
        ),
    )


def _reproducibility_dimension(
    configured: bool,
) -> EvidenceDimensionResult:
    if not configured:
        return EvidenceDimensionResult(
            dimension=EvidenceDimensionName.REPRODUCIBILITY,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            summary="A deterministic audit-run manifest was not configured.",
            unavailable_evidence_codes=("AUDIT_RUN_MANIFEST_NOT_CONFIGURED",),
            next_evidence_required=(
                "Supply an audit ID, timezone-aware audit timestamp, and Git revision together.",
            ),
        )
    return EvidenceDimensionResult(
        dimension=EvidenceDimensionName.REPRODUCIBILITY,
        status=EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS,
        summary="The report includes a content-hashed deterministic audit-run manifest.",
        supporting_evidence_codes=(
            "RAW_INPUT_HASHES_RECORDED",
            "NORMALIZED_DATA_HASH_RECORDED",
            "CONFIGURATION_HASH_RECORDED",
            "METHOD_AND_DEPENDENCY_VERSIONS_RECORDED",
        ),
        assumption_codes=("SUPPLIED_GIT_REVISION_IDENTIFIES_THE_EXECUTED_SOURCE",),
    )
