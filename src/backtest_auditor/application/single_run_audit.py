from dataclasses import dataclass

from backtest_auditor import REPORT_SCHEMA_VERSION

from backtest_auditor.audit.checks import (
    generate_annualized_statistical_findings,
    generate_basic_statistical_findings,
    generate_bootstrap_findings,
    generate_periods_per_year_findings,
    generate_sampling_findings,
    generate_serial_adjustment_findings,
    generate_serial_dependence_findings,
    generate_sharpe_uncertainty_findings,
    generate_track_record_findings,
)
from backtest_auditor.audit.advanced_checks import (
    generate_advanced_single_run_findings,
)
from backtest_auditor.audit.context_checks import (
    generate_benchmark_comparability_findings,
    generate_benchmark_findings,
    generate_calendar_findings,
    generate_performance_path_findings,
    generate_return_construction_findings,
    generate_return_magnitude_findings,
)
from backtest_auditor.audit.methodology import (
    assess_return_construction,
)
from backtest_auditor.audit.evidence_profile import (
    build_single_run_evidence_profile,
)
from backtest_auditor.application.run_manifest import (
    build_single_run_manifest,
    canonical_configuration,
)
from backtest_auditor.domain.assumptions import (
    AdvancedRiskSpec,
    BenchmarkInferenceSpec,
    BootstrapSpec,
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.findings import AuditFinding
from backtest_auditor.domain.evidence import EvidenceProfileResult
from backtest_auditor.domain.enums import SeriesRole
from backtest_auditor.domain.issues import ValidationIssue
from backtest_auditor.domain.results import (
    AdvancedRiskStatisticsResult,
    AnnualizedStatisticsResult,
    BenchmarkAlignmentResult,
    BenchmarkComparisonResult,
    BenchmarkAlphaInferenceResult,
    BootstrapResult,
    DescriptiveStatisticsResult,
    DistributionStatisticsResult,
    GrossNetCostDragResult,
    ObservationCalendarAssessmentResult,
    PerformancePathResult,
    RegimeAnalysisResult,
    ReturnConstructionAssessmentResult,
    RiskFreeSeriesResult,
    SamplingAssessmentResult,
    SerialAdjustmentResult,
    SerialDependenceResult,
    SharpeUncertaintyResult,
    TrackRecordLengthResult,
)
from backtest_auditor.domain.runs import StrategyRun
from backtest_auditor.domain.reproducibility import (
    AuditRunManifestResult,
    AuditRunSpec,
    InputArtifactHash,
)
from backtest_auditor.statistics.annualized import (
    calculate_annualized_statistics,
)
from backtest_auditor.statistics.additive_domain import (
    calculate_gross_net_cost_drag,
    calculate_regime_analysis,
    calculate_risk_free_series_evidence,
)
from backtest_auditor.statistics.advanced_risk import (
    calculate_advanced_risk_statistics,
)
from backtest_auditor.statistics.benchmark import (
    assess_benchmark_alignment,
    calculate_benchmark_comparison,
)
from backtest_auditor.statistics.benchmark_inference import (
    calculate_benchmark_alpha_inference,
)
from backtest_auditor.statistics.bootstrap import (
    calculate_bootstrap_confidence_intervals,
)
from backtest_auditor.statistics.descriptive import (
    calculate_descriptive_statistics,
)
from backtest_auditor.statistics.calendar import (
    assess_observation_calendar,
)
from backtest_auditor.statistics.performance_path import (
    calculate_performance_path,
)
from backtest_auditor.statistics.distribution import (
    calculate_distribution_statistics,
)
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.serial_adjustment import (
    calculate_serial_adjustment,
)
from backtest_auditor.statistics.serial_dependence import (
    calculate_serial_dependence,
)
from backtest_auditor.statistics.sharpe_uncertainty import (
    calculate_sharpe_uncertainty,
)
from backtest_auditor.statistics.track_record import (
    calculate_track_record_length,
)


@dataclass(frozen=True, slots=True)
class SingleRunAuditResult:
    run_id: str
    observation_calendar: ObservationCalendarAssessmentResult | None
    return_construction: ReturnConstructionAssessmentResult
    sampling_assessment: SamplingAssessmentResult
    descriptive_statistics: DescriptiveStatisticsResult
    performance_path: PerformancePathResult
    advanced_risk_statistics: AdvancedRiskStatisticsResult | None
    risk_free_series: RiskFreeSeriesResult | None
    gross_net_cost_drag: GrossNetCostDragResult | None
    regime_analysis: RegimeAnalysisResult | None
    benchmark_observation_calendar: ObservationCalendarAssessmentResult | None
    benchmark_return_construction: ReturnConstructionAssessmentResult | None
    benchmark_alignment: BenchmarkAlignmentResult | None
    benchmark_comparison: BenchmarkComparisonResult | None
    benchmark_alpha_inference: BenchmarkAlphaInferenceResult | None
    distribution_statistics: DistributionStatisticsResult
    serial_dependence: SerialDependenceResult | None
    serial_adjustment: SerialAdjustmentResult | None
    bootstrap: BootstrapResult | None
    annualized_statistics: AnnualizedStatisticsResult | None
    sharpe_uncertainty: SharpeUncertaintyResult | None
    track_record_length: TrackRecordLengthResult | None
    evidence_profile: EvidenceProfileResult
    run_manifest: AuditRunManifestResult | None
    findings: tuple[AuditFinding, ...]
    input_issues: tuple[ValidationIssue, ...] = ()


def audit_single_run(
    run: StrategyRun,
    *,
    input_issues: tuple[ValidationIssue, ...] = (),
    sharpe_spec: SharpeRatioSpec | None = None,
    psr_spec: ProbabilisticSharpeRatioSpec | None = None,
    serial_dependence_spec: SerialDependenceSpec | None = None,
    serial_adjustment_spec: SerialAdjustmentSpec | None = None,
    bootstrap_spec: BootstrapSpec | None = None,
    advanced_risk_spec: AdvancedRiskSpec | None = None,
    benchmark_inference_spec: BenchmarkInferenceSpec | None = None,
    run_manifest_spec: AuditRunSpec | None = None,
    input_artifacts: tuple[InputArtifactHash, ...] = (),
) -> SingleRunAuditResult:
    """Audit one timestamped return series.

    Methods that need a choice (Sharpe and PSR, serial diagnostics, HAC,
    bootstrap, downside risk, alpha inference) run only when their
    specification is supplied, and evidence from auxiliary series only when
    the series is attached to ``run``; nothing is assumed in place of a
    missing choice. The result carries the dimensioned evidence profile, the
    findings, and, when ``run_manifest_spec`` is given, a content-hashed
    audit-run manifest.

    Args:
        run: The normalized strategy return series with its declarations
            (sampling, calendar, return construction) and optional benchmark,
            risk-free, gross-return and regime series.
        input_issues: Non-blocking validation issues found while reading the
            input, carried into the report.
        sharpe_spec: Annual risk-free rate for the annualized Sharpe ratio.
        psr_spec: Benchmark Sharpe ratio and confidence level for the
            Probabilistic Sharpe Ratio and minimum track-record length.
        serial_dependence_spec: Maximum lag and significance level for the
            serial-dependence diagnostics.
        serial_adjustment_spec: HAC lag and kernel for the adjusted Sharpe.
        bootstrap_spec: Complete, seeded bootstrap configuration.
        advanced_risk_spec: Target return and tail confidence for downside,
            tail and drawdown risk.
        benchmark_inference_spec: HAC configuration for benchmark alpha.
        run_manifest_spec: Explicit audit identity; without it no manifest is
            produced and nothing is inferred.
        input_artifacts: SHA-256 identities of the raw input files.

    Returns:
        The complete single-run audit result, ready for the JSON and Markdown
        renderers.
    """

    observation_calendar = assess_observation_calendar(
        run.returns,
        run.observation_calendar,
    )
    return_construction = assess_return_construction(
        run.return_construction,
        role=SeriesRole.STRATEGY,
    )
    sampling_assessment = assess_sampling(
        run.returns,
        observation_calendar,
    )

    statistics = calculate_descriptive_statistics(run.returns)
    performance_path = calculate_performance_path(
        run.returns,
        sampling_assessment,
    )
    advanced_risk_statistics = calculate_advanced_risk_statistics(
        run.returns,
        sampling_assessment,
        performance_path,
        spec=advanced_risk_spec,
    )
    risk_free_series = calculate_risk_free_series_evidence(
        run.returns,
        run.risk_free_returns,
        sampling_assessment,
    )
    gross_net_cost_drag = calculate_gross_net_cost_drag(
        run.returns,
        run.gross_returns,
        sampling_assessment,
    )
    regime_analysis = calculate_regime_analysis(
        run.returns,
        run.regimes,
        risk_free=run.risk_free_returns,
    )
    distribution_statistics = calculate_distribution_statistics(run.returns)
    serial_dependence = calculate_serial_dependence(
        run.returns,
        spec=serial_dependence_spec,
    )
    annualized_statistics = calculate_annualized_statistics(
        run.returns,
        sampling_assessment,
        sharpe_spec=sharpe_spec,
    )
    sharpe_uncertainty = calculate_sharpe_uncertainty(
        annualized_statistics,
        distribution_statistics,
        psr_spec=psr_spec,
    )
    track_record_length = calculate_track_record_length(
        sharpe_uncertainty,
        psr_spec=psr_spec,
    )
    serial_adjustment = calculate_serial_adjustment(
        run.returns,
        annualized_statistics,
        sharpe_uncertainty,
        spec=serial_adjustment_spec,
        psr_spec=psr_spec,
    )
    bootstrap = calculate_bootstrap_confidence_intervals(
        run.returns,
        sampling_assessment,
        annualized_statistics,
        serial_adjustment,
        spec=bootstrap_spec,
    )

    benchmark_observation_calendar = None
    benchmark_return_construction = None
    benchmark_alignment = None
    benchmark_comparison = None
    benchmark_alpha_inference = None
    if run.benchmark is not None:
        benchmark_observation_calendar = assess_observation_calendar(
            run.benchmark.returns,
            run.benchmark.observation_calendar,
        )
        benchmark_return_construction = assess_return_construction(
            run.benchmark.return_construction,
            role=SeriesRole.BENCHMARK,
        )
        benchmark_alignment = assess_benchmark_alignment(
            run.returns,
            run.benchmark.returns,
        )
        benchmark_comparison = calculate_benchmark_comparison(
            run.returns,
            run.benchmark.returns,
            benchmark_alignment,
            sampling_assessment,
            benchmark_id=run.benchmark.benchmark_id,
        )
    benchmark_alpha_inference = calculate_benchmark_alpha_inference(
        run.returns,
        None if run.benchmark is None else run.benchmark.returns,
        benchmark_alignment,
        spec=benchmark_inference_spec,
    )

    findings = (
        generate_calendar_findings(
            observation_calendar,
            role=SeriesRole.STRATEGY,
        )
        + generate_return_construction_findings(return_construction)
        + generate_sampling_findings(sampling_assessment)
        + generate_periods_per_year_findings(run.returns, sampling_assessment)
        + generate_basic_statistical_findings(statistics)
        + generate_return_magnitude_findings(run.returns)
        + generate_performance_path_findings(performance_path)
        + (
            ()
            if run.benchmark is None
            else generate_calendar_findings(
                benchmark_observation_calendar,
                role=SeriesRole.BENCHMARK,
            )
        )
        + (
            ()
            if benchmark_return_construction is None
            else generate_return_construction_findings(benchmark_return_construction)
        )
        + generate_benchmark_comparability_findings(
            return_construction,
            benchmark_return_construction,
        )
        + generate_benchmark_findings(
            benchmark_alignment,
            benchmark_comparison,
        )
        + generate_serial_dependence_findings(
            annualized_statistics,
            serial_dependence,
            spec=serial_dependence_spec,
        )
        + generate_annualized_statistical_findings(annualized_statistics)
        + generate_sharpe_uncertainty_findings(
            annualized_statistics,
            distribution_statistics,
            sharpe_uncertainty,
            psr_spec=psr_spec,
        )
        + generate_track_record_findings(
            sharpe_uncertainty,
            track_record_length,
            psr_spec=psr_spec,
        )
        + generate_serial_adjustment_findings(
            serial_dependence,
            serial_adjustment,
            spec=serial_adjustment_spec,
        )
        + generate_bootstrap_findings(
            sampling_assessment,
            bootstrap,
            spec=bootstrap_spec,
        )
        + generate_advanced_single_run_findings(
            advanced_risk_statistics,
            risk_free_series,
            gross_net_cost_drag,
            regime_analysis,
            benchmark_alpha_inference,
        )
    )

    evidence_profile = build_single_run_evidence_profile(
        return_construction=return_construction,
        sampling=sampling_assessment,
        annualized_statistics=annualized_statistics,
        sharpe_uncertainty=sharpe_uncertainty,
        track_record_length=track_record_length,
        serial_dependence=serial_dependence,
        serial_adjustment=serial_adjustment,
        bootstrap=bootstrap,
        benchmark_alignment=benchmark_alignment,
        advanced_risk=advanced_risk_statistics,
        risk_free_series=risk_free_series,
        gross_net_cost_drag=gross_net_cost_drag,
        regime_analysis=regime_analysis,
        benchmark_inference=benchmark_alpha_inference,
        input_issue_codes=tuple(issue.code for issue in input_issues),
        run_manifest_configured=run_manifest_spec is not None,
    )
    run_manifest = None
    if run_manifest_spec is not None:
        configured_methods = [
            "annualized_statistics",
            "audit_run_manifest",
            "descriptive_statistics",
            "distribution_statistics",
            "evidence_profile",
            "observation_calendar_assessment",
            "performance_path",
            "return_construction_assessment",
            "sampling_assessment",
        ]
        if run.benchmark is not None:
            configured_methods.append("benchmark_comparison")
        if benchmark_inference_spec is not None:
            configured_methods.append("benchmark_alpha_hac_inference")
        if advanced_risk_spec is not None:
            configured_methods.append("advanced_downside_tail_statistics")
        if run.risk_free_returns is not None:
            configured_methods.append("time_varying_risk_free_evidence")
        if run.gross_returns is not None:
            configured_methods.append("gross_net_cost_drag")
        if run.regimes is not None:
            configured_methods.append("declared_regime_analysis")
        if psr_spec is not None:
            configured_methods.append("probabilistic_sharpe_ratio")
            if psr_spec.required_psr_confidence_level is not None:
                configured_methods.append("minimum_track_record_length")
        if serial_dependence_spec is not None:
            configured_methods.append("serial_dependence_diagnostic")
        if serial_adjustment_spec is not None:
            configured_methods.append("hac_serial_adjustment")
        if bootstrap_spec is not None:
            configured_methods.append(
                "bootstrap_stationary_percentile"
                if bootstrap_spec.method.value == "stationary"
                else "bootstrap_moving_block_percentile"
            )
        run_manifest = build_single_run_manifest(
            spec=run_manifest_spec,
            input_artifacts=input_artifacts,
            run=run,
            report_schema_version=REPORT_SCHEMA_VERSION,
            audit_configuration=canonical_configuration(
                {
                    "strategy_declarations": {
                        "sampling": run.returns.sampling,
                        "observation_calendar": run.observation_calendar,
                        "return_construction": run.return_construction,
                    },
                    "benchmark_declarations": (
                        None
                        if run.benchmark is None
                        else {
                            "benchmark_id": run.benchmark.benchmark_id,
                            "sampling": run.benchmark.returns.sampling,
                            "observation_calendar": (
                                run.benchmark.observation_calendar
                            ),
                            "return_construction": (run.benchmark.return_construction),
                        }
                    ),
                    "audit_specs": {
                        "sharpe": sharpe_spec,
                        "probabilistic_sharpe": psr_spec,
                        "serial_dependence": serial_dependence_spec,
                        "serial_adjustment": serial_adjustment_spec,
                        "bootstrap": bootstrap_spec,
                        "advanced_risk": advanced_risk_spec,
                        "benchmark_inference": benchmark_inference_spec,
                    },
                }
            ),
            configured_method_names=tuple(configured_methods),
            random_seeds=(
                ()
                if bootstrap_spec is None
                else (("bootstrap", bootstrap_spec.random_seed),)
            ),
            findings=findings,
            input_issues=tuple(input_issues),
        )

    return SingleRunAuditResult(
        run_id=run.run_id,
        observation_calendar=observation_calendar,
        return_construction=return_construction,
        sampling_assessment=sampling_assessment,
        descriptive_statistics=statistics,
        performance_path=performance_path,
        advanced_risk_statistics=advanced_risk_statistics,
        risk_free_series=risk_free_series,
        gross_net_cost_drag=gross_net_cost_drag,
        regime_analysis=regime_analysis,
        benchmark_observation_calendar=(benchmark_observation_calendar),
        benchmark_return_construction=(benchmark_return_construction),
        benchmark_alignment=benchmark_alignment,
        benchmark_comparison=benchmark_comparison,
        benchmark_alpha_inference=benchmark_alpha_inference,
        distribution_statistics=distribution_statistics,
        serial_dependence=serial_dependence,
        serial_adjustment=serial_adjustment,
        bootstrap=bootstrap,
        annualized_statistics=annualized_statistics,
        sharpe_uncertainty=sharpe_uncertainty,
        track_record_length=track_record_length,
        evidence_profile=evidence_profile,
        run_manifest=run_manifest,
        findings=findings,
        input_issues=tuple(input_issues),
    )
