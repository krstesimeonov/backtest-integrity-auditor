from datetime import datetime
from enum import Enum

from backtest_auditor.application.single_run_audit import (
    SingleRunAuditResult,
)
from backtest_auditor.application.experiment_family_audit import (
    ExperimentFamilyAuditResult,
)
from backtest_auditor.domain.enums import (
    BootstrapStatus,
    HACKernel,
    SerialAdjustmentStatus,
    SerialDependenceStatus,
)
from backtest_auditor.domain.results import (
    AdvancedRiskStatisticsResult,
    BenchmarkAlignmentResult,
    BenchmarkAlphaInferenceResult,
    BenchmarkComparisonResult,
    GrossNetCostDragResult,
    ObservationCalendarAssessmentResult,
    PairedSeriesAlignmentResult,
    PerformancePathResult,
    RegimeAnalysisResult,
    ReturnConstructionAssessmentResult,
    RiskFreeSeriesResult,
)
from backtest_auditor.reporting.serialization import (
    REPORT_SCHEMA_VERSION,
)
from backtest_auditor.reporting.family_markdown_report import (
    render_experiment_family_markdown_report,
)
from backtest_auditor.reporting.evidence_markdown import (
    append_evidence_profile_section,
    append_run_manifest_section,
)


def render_markdown_report(
    result: SingleRunAuditResult | ExperimentFamilyAuditResult,
) -> str:
    """Render a deterministic human-readable Markdown report."""

    if isinstance(result, ExperimentFamilyAuditResult):
        return render_experiment_family_markdown_report(result)

    statistics = result.descriptive_statistics
    performance_path = result.performance_path
    observation_calendar = result.observation_calendar
    return_construction = result.return_construction
    benchmark_calendar = result.benchmark_observation_calendar
    benchmark_construction = result.benchmark_return_construction
    benchmark_alignment = result.benchmark_alignment
    benchmark_comparison = result.benchmark_comparison
    distribution = result.distribution_statistics
    serial_dependence = result.serial_dependence
    sampling = result.sampling_assessment
    annualized = result.annualized_statistics
    uncertainty = result.sharpe_uncertainty
    track_record = result.track_record_length
    serial_adjustment = result.serial_adjustment
    bootstrap = result.bootstrap
    lines = [
        "# Backtest Integrity Audit",
        "",
        f"- Schema version: `{REPORT_SCHEMA_VERSION}`",
        "- Audit type: `single_run`",
        f"- Run ID: `{_escape(result.run_id)}`",
        "",
        "## Sampling assessment",
        "",
        "| Property | Value |",
        "|---|---:|",
        f"| Status | {sampling.status.value} |",
        (
            "| Declared frequency | "
            f"{_format_optional_text(sampling.declared_frequency)} |"
        ),
        (
            "| Inferred frequency | "
            f"{_format_optional_text(sampling.inferred_frequency)} |"
        ),
        (f"| Periods per year | {_format_number(sampling.periods_per_year)} |"),
        f"| Interval count | {sampling.interval_count} |",
        (
            "| Minimum interval (seconds) | "
            f"{_format_number(sampling.minimum_interval_seconds)} |"
        ),
        (
            "| Maximum interval (seconds) | "
            f"{_format_number(sampling.maximum_interval_seconds)} |"
        ),
        (
            "| Annualization eligible | "
            f"{str(sampling.annualization_eligible).lower()} |"
        ),
        "",
        "## Descriptive statistics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Observation count | {statistics.observation_count} |",
        (f"| Start timestamp | {_escape(statistics.start_timestamp.isoformat())} |"),
        (f"| End timestamp | {_escape(statistics.end_timestamp.isoformat())} |"),
        f"| Mean return | {_format_number(statistics.mean_return)} |",
        (f"| Sample volatility | {_format_number(statistics.sample_volatility)} |"),
        (f"| Minimum return | {_format_number(statistics.minimum_return)} |"),
        (f"| Maximum return | {_format_number(statistics.maximum_return)} |"),
        (
            "| Cumulative simple return | "
            f"{_format_number(statistics.cumulative_simple_return)} |"
        ),
        (f"| Input return convention | {statistics.return_convention.value} |"),
        "",
        "## Distribution statistics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        (f"| Return basis | {distribution.return_basis.value} |"),
        (f"| Sample skewness | {_format_number(distribution.sample_skewness)} |"),
        (
            "| Sample excess kurtosis | "
            f"{_format_number(distribution.sample_excess_kurtosis)} |"
        ),
        (
            "| Sample Pearson kurtosis | "
            f"{_format_number(distribution.sample_pearson_kurtosis)} |"
        ),
        "",
        (
            "Method note: skewness and kurtosis use finite-sample "
            "bias corrections. Pearson kurtosis equals 3 for a "
            "normal distribution; excess kurtosis equals 0."
        ),
    ]

    evidence_lines: list[str] = []
    append_evidence_profile_section(evidence_lines, result.evidence_profile)
    append_run_manifest_section(evidence_lines, result.run_manifest)
    lines[6:6] = evidence_lines + [""]

    lines.extend(
        _calendar_section(
            "Strategy observation calendar",
            observation_calendar,
        )
    )
    lines.extend(
        _return_construction_section(
            "Strategy return construction",
            return_construction,
        )
    )
    lines.extend(_performance_path_section(performance_path))
    lines.extend(_advanced_risk_section(result.advanced_risk_statistics))
    lines.extend(_risk_free_section(result.risk_free_series))
    lines.extend(_gross_net_section(result.gross_net_cost_drag))
    lines.extend(_regime_section(result.regime_analysis))
    lines.extend(
        _benchmark_section(
            benchmark_calendar,
            benchmark_construction,
            benchmark_alignment,
            benchmark_comparison,
        )
    )
    lines.extend(_benchmark_inference_section(result.benchmark_alpha_inference))

    lines.extend(["", "## Serial-dependence diagnostics", ""])

    if serial_dependence is None:
        lines.append(
            "Not configured; no maximum lag or significance level was supplied."
        )
    else:
        lines.extend(
            [
                "| Metric | Value |",
                "|---|---:|",
                f"| Status | {serial_dependence.status.value} |",
                (f"| Observation count | {serial_dependence.observation_count} |"),
                (f"| Return basis | {serial_dependence.return_basis.value} |"),
                (f"| Maximum lag | {serial_dependence.maximum_lag} |"),
                (
                    "| Significance level | "
                    f"{_format_number(serial_dependence.significance_level)} |"
                ),
            ]
        )

        if serial_dependence.status is not SerialDependenceStatus.ELIGIBLE:
            lines.extend(
                [
                    "",
                    (
                        "Not calculated because the selected lag was "
                        "not below the sample size or return variance "
                        "was zero. The configured choices are retained "
                        "above as audit evidence."
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    (
                        "| Strongest absolute autocorrelation lag | "
                        f"{serial_dependence.strongest_absolute_autocorrelation_lag} |"
                    ),
                    (
                        "| Strongest absolute autocorrelation | "
                        f"{_format_number(serial_dependence.strongest_absolute_autocorrelation)} |"
                    ),
                    (
                        "| Ljung-Box statistic | "
                        f"{_format_number(serial_dependence.ljung_box_statistic)} |"
                    ),
                    (
                        "| Degrees of freedom | "
                        f"{serial_dependence.degrees_of_freedom} |"
                    ),
                    (f"| p-value | {_format_number(serial_dependence.p_value)} |"),
                    (
                        "| Serial dependence detected | "
                        f"{str(serial_dependence.serial_dependence_detected).lower()} |"
                    ),
                    (
                        "| Approximate two-sided ACF confidence bound | "
                        f"{_format_number(serial_dependence.acf_confidence_bound)} |"
                    ),
                    (
                        "| Mean long-run variance ratio | "
                        f"{_format_number(serial_dependence.mean_long_run_variance_ratio)} |"
                    ),
                    (
                        "| Mean effective observation count | "
                        f"{_format_number(serial_dependence.mean_effective_observation_count)} |"
                    ),
                    (
                        "| Runs-test usable observations | "
                        f"{_format_number(serial_dependence.runs_observation_count)} |"
                    ),
                    (
                        "| Observed / expected runs | "
                        f"{_format_number(serial_dependence.runs_count)} / "
                        f"{_format_number(serial_dependence.runs_expected_count)} |"
                    ),
                    (
                        "| Runs z-statistic | "
                        f"{_format_number(serial_dependence.runs_z_statistic)} |"
                    ),
                    (
                        "| Runs p-value | "
                        f"{_format_number(serial_dependence.runs_p_value)} |"
                    ),
                    (
                        "| Runs dependence detected | "
                        f"{_format_boolean(serial_dependence.runs_dependence_detected)} |"
                    ),
                    "",
                    "| Lag | Sample autocorrelation | Partial autocorrelation |",
                    "|---:|---:|---:|",
                ]
            )
            partial = {
                estimate.lag: estimate.autocorrelation
                for estimate in serial_dependence.partial_autocorrelations
            }
            lines.extend(
                (
                    f"| {estimate.lag} "
                    f"| {_format_number(estimate.autocorrelation)} "
                    f"| {_format_number(partial.get(estimate.lag))} |"
                )
                for estimate in serial_dependence.autocorrelations
            )
            if serial_dependence.variance_ratios:
                lines.extend(
                    [
                        "",
                        (
                            "| Variance-ratio horizon | Variance ratio | Robust SE "
                            "| z-statistic | p-value | Dependence detected |"
                        ),
                        "|---:|---:|---:|---:|---:|---:|",
                    ]
                )
                lines.extend(
                    (
                        f"| {item.horizon} "
                        f"| {_format_number(item.variance_ratio)} "
                        f"| {_format_number(item.heteroskedastic_robust_standard_error)} "
                        f"| {_format_number(item.z_statistic)} "
                        f"| {_format_number(item.p_value)} "
                        f"| {_format_boolean(item.dependence_detected)} |"
                    )
                    for item in serial_dependence.variance_ratios
                )
            lines.extend(
                [
                    "",
                    (
                        "Method note: ACF/PACF are descriptive; the ACF bound is "
                        "the large-sample z_(1-alpha/2)/sqrt(n) reference. "
                        "Ljung-Box tests "
                        "joint zero autocorrelation, the median-sign runs test "
                        "checks ordering, and Lo-MacKinlay variance ratios use "
                        "heteroskedasticity-robust standard errors. All p-values "
                        "are asymptotic; non-rejection does not prove IID returns."
                    ),
                ]
            )

    lines.extend(["", "## Annualized statistics", ""])

    if annualized is None:
        lines.append(
            "Not calculated because the sampling assessment "
            "is not eligible for annualization."
        )
    else:
        lines.extend(
            [
                "| Metric | Value |",
                "|---|---:|",
                (f"| Periods per year | {annualized.periods_per_year} |"),
                (f"| Return basis | {annualized.return_basis.value} |"),
                (
                    "| Annualized arithmetic mean return | "
                    f"{_format_number(annualized.annualized_arithmetic_mean_return)} |"
                ),
                (
                    "| Annualized sample volatility | "
                    f"{_format_number(annualized.annualized_sample_volatility)} |"
                ),
                (
                    "| Annual risk-free rate | "
                    f"{_format_number(annualized.annual_risk_free_rate)} |"
                ),
                (
                    "| Equivalent period risk-free rate | "
                    f"{_format_number(annualized.period_risk_free_rate)} |"
                ),
                (
                    "| Annualized Sharpe ratio | "
                    f"{_format_number(annualized.annualized_sharpe_ratio)} |"
                ),
            ]
        )
        lines.extend(
            [
                "",
                (
                    "Method note: these are point estimates using "
                    "linear mean scaling and square-root-of-time "
                    "volatility scaling."
                ),
            ]
        )

    lines.extend(["", "## Sharpe uncertainty and PSR", ""])

    if uncertainty is None:
        lines.append(
            "Not calculated because annualized Sharpe or the "
            "required distribution-shape estimates are undefined."
        )
    else:
        lines.extend(
            [
                "| Metric | Value |",
                "|---|---:|",
                (f"| Observation count | {uncertainty.observation_count} |"),
                (
                    "| Period Sharpe ratio | "
                    f"{_format_number(uncertainty.period_sharpe_ratio)} |"
                ),
                (
                    "| Annualized Sharpe ratio | "
                    f"{_format_number(uncertainty.annualized_sharpe_ratio)} |"
                ),
                (
                    "| Sharpe variance adjustment | "
                    f"{_format_number(uncertainty.sharpe_variance_adjustment)} |"
                ),
                (
                    "| Period Sharpe standard error | "
                    f"{_format_number(uncertainty.period_sharpe_standard_error)} |"
                ),
                (
                    "| Annualized Sharpe standard error | "
                    f"{_format_number(uncertainty.annualized_sharpe_standard_error)} |"
                ),
                (
                    "| Benchmark period Sharpe ratio | "
                    f"{_format_number(uncertainty.benchmark_period_sharpe_ratio)} |"
                ),
                (
                    "| Benchmark annualized Sharpe ratio | "
                    f"{_format_number(uncertainty.benchmark_annualized_sharpe_ratio)} |"
                ),
                (
                    "| Probabilistic Sharpe Ratio | "
                    f"{_format_number(uncertainty.probabilistic_sharpe_ratio)} |"
                ),
                "",
                (
                    "Method note: the Sharpe standard error and PSR "
                    "use the higher-moment-adjusted asymptotic "
                    "formula at the observation frequency. Serial "
                    "dependence is diagnosed separately but is not "
                    "corrected in these values. Resampling uncertainty "
                    "and multiple-testing selection are also not "
                    "corrected in this increment."
                ),
            ]
        )

    lines.extend(["", "## Minimum track-record length", ""])

    if track_record is None:
        lines.append(
            "Not calculated because PSR or an explicit PSR "
            "confidence requirement is unavailable."
        )
    else:
        lines.extend(
            [
                "| Metric | Value |",
                "|---|---:|",
                (f"| Observation count | {track_record.observation_count} |"),
                (
                    "| Required PSR confidence level | "
                    f"{_format_number(track_record.required_psr_confidence_level)} |"
                ),
                (
                    "| Observed Probabilistic Sharpe Ratio | "
                    f"{_format_number(track_record.observed_probabilistic_sharpe_ratio)} "
                    "|"
                ),
                (
                    "| Confidence requirement met | "
                    f"{str(track_record.confidence_requirement_met).lower()} |"
                ),
                (
                    "| Normal critical value | "
                    f"{_format_number(track_record.normal_critical_value)} |"
                ),
                (
                    "| Observed period Sharpe difference | "
                    f"{_format_number(track_record.observed_period_sharpe_difference)} "
                    "|"
                ),
                (
                    "| Minimum track-record length (observations) | "
                    f"{_format_number(track_record.minimum_track_record_length_observations)} "
                    "|"
                ),
                (
                    "| Minimum required whole observations | "
                    f"{_format_number(track_record.minimum_required_observations)} |"
                ),
                (
                    "| Equivalent track-record length (years) | "
                    f"{_format_number(track_record.minimum_track_record_length_years)} "
                    "|"
                ),
                (
                    "| Additional observations required | "
                    f"{_format_number(track_record.additional_observations_required)} |"
                ),
                (
                    "| Observations above minimum | "
                    f"{_format_number(track_record.observations_above_minimum)} |"
                ),
                "",
                (
                    "Method note: MinTRL is a conditional asymptotic "
                    "estimate using the observed Sharpe, skewness, "
                    "kurtosis, benchmark, and periods-per-year scale. "
                    "The whole-observation requirement is rounded up "
                    "and never falls below the four observations needed "
                    "for this implementation's moment estimates. It is "
                    "not a guarantee that future returns will preserve "
                    "the observed distribution."
                ),
            ]
        )

    lines.extend(["", "## Serial-dependence adjustment", ""])

    if serial_adjustment is None:
        lines.append("Not configured; no HAC maximum lag and kernel were supplied.")
    else:
        lines.extend(
            [
                "| Configuration | Value |",
                "|---|---:|",
                f"| Status | {serial_adjustment.status.value} |",
                (f"| Observation count | {serial_adjustment.observation_count} |"),
                (f"| Return basis | {serial_adjustment.return_basis.value} |"),
                (f"| Maximum lag | {serial_adjustment.maximum_lag} |"),
                f"| Kernel | {serial_adjustment.kernel.value} |",
                (
                    "| Periods per year | "
                    f"{_format_number(serial_adjustment.periods_per_year)} |"
                ),
            ]
        )

        if serial_adjustment.iid_annualization_factor is not None:
            lines.extend(
                [
                    "",
                    "### HAC annualization comparison",
                    "",
                    "| Metric | Value |",
                    "|---|---:|",
                    (
                        "| Return long-run variance ratio | "
                        f"{_format_number(serial_adjustment.return_long_run_variance_ratio)} |"
                    ),
                    (
                        "| IID annualization factor | "
                        f"{_format_number(serial_adjustment.iid_annualization_factor)} |"
                    ),
                    (
                        "| HAC annualization factor | "
                        f"{_format_number(serial_adjustment.hac_annualization_factor)} |"
                    ),
                    (
                        "| Full Lo annual horizon | "
                        f"{_format_boolean(serial_adjustment.full_lo_annual_horizon)} |"
                    ),
                    (
                        "| IID annualized Sharpe ratio | "
                        f"{_format_number(serial_adjustment.iid_annualized_sharpe_ratio)} |"
                    ),
                    (
                        "| HAC-adjusted annualized Sharpe ratio | "
                        f"{_format_number(serial_adjustment.hac_adjusted_annualized_sharpe_ratio)} |"
                    ),
                ]
            )

        if serial_adjustment.return_autocorrelations:
            lines.extend(
                [
                    "",
                    "| Return lag | Autocorrelation | Bartlett weight "
                    "| Weighted contribution |",
                    "|---:|---:|---:|---:|",
                ]
            )
            lines.extend(
                (
                    f"| {estimate.lag} "
                    f"| {_format_number(estimate.autocorrelation)} "
                    f"| {_format_number(estimate.kernel_weight)} "
                    f"| {_format_number(estimate.weighted_contribution)} |"
                )
                for estimate in serial_adjustment.return_autocorrelations
            )

        if serial_adjustment.iid_sharpe_variance_adjustment is not None:
            lines.extend(
                [
                    "",
                    "### HAC Sharpe uncertainty comparison",
                    "",
                    "| Metric | Value |",
                    "|---|---:|",
                    (
                        "| Sharpe long-run variance ratio | "
                        f"{_format_number(serial_adjustment.sharpe_long_run_variance_ratio)} |"
                    ),
                    (
                        "| IID Sharpe variance adjustment | "
                        f"{_format_number(serial_adjustment.iid_sharpe_variance_adjustment)} |"
                    ),
                    (
                        "| HAC Sharpe variance adjustment | "
                        f"{_format_number(serial_adjustment.hac_sharpe_variance_adjustment)} |"
                    ),
                    (
                        "| IID period Sharpe standard error | "
                        f"{_format_number(serial_adjustment.iid_period_sharpe_standard_error)} |"
                    ),
                    (
                        "| HAC period Sharpe standard error | "
                        f"{_format_number(serial_adjustment.hac_period_sharpe_standard_error)} |"
                    ),
                    (
                        "| Effective observation count | "
                        f"{_format_number(serial_adjustment.effective_observation_count)} |"
                    ),
                    (
                        "| Benchmark period Sharpe ratio | "
                        f"{_format_number(serial_adjustment.benchmark_period_sharpe_ratio)} |"
                    ),
                    (
                        "| IID Probabilistic Sharpe Ratio | "
                        f"{_format_number(serial_adjustment.iid_probabilistic_sharpe_ratio)} |"
                    ),
                    (
                        "| HAC Probabilistic Sharpe Ratio | "
                        f"{_format_number(serial_adjustment.hac_probabilistic_sharpe_ratio)} |"
                    ),
                    (
                        "| Required PSR confidence level | "
                        f"{_format_number(serial_adjustment.required_psr_confidence_level)} |"
                    ),
                    (
                        "| HAC confidence requirement met | "
                        f"{_format_boolean(serial_adjustment.hac_confidence_requirement_met)} |"
                    ),
                    (
                        "| HAC MinTRL (observations) | "
                        f"{_format_number(serial_adjustment.hac_minimum_track_record_length_observations)} |"
                    ),
                    (
                        "| HAC minimum required observations | "
                        f"{_format_number(serial_adjustment.hac_minimum_required_observations)} |"
                    ),
                    (
                        "| HAC MinTRL (years) | "
                        f"{_format_number(serial_adjustment.hac_minimum_track_record_length_years)} |"
                    ),
                    (
                        "| HAC additional observations required | "
                        f"{_format_number(serial_adjustment.hac_additional_observations_required)} |"
                    ),
                    (
                        "| HAC observations above minimum | "
                        f"{_format_number(serial_adjustment.hac_observations_above_minimum)} |"
                    ),
                ]
            )

        if serial_adjustment.influence_autocorrelations:
            lines.extend(
                [
                    "",
                    "| Influence lag | Autocorrelation | Bartlett "
                    "weight | Weighted contribution |",
                    "|---:|---:|---:|---:|",
                ]
            )
            lines.extend(
                (
                    f"| {estimate.lag} "
                    f"| {_format_number(estimate.autocorrelation)} "
                    f"| {_format_number(estimate.kernel_weight)} "
                    f"| {_format_number(estimate.weighted_contribution)} |"
                )
                for estimate in serial_adjustment.influence_autocorrelations
            )

        if serial_adjustment.status is not SerialAdjustmentStatus.ELIGIBLE:
            lines.extend(
                [
                    "",
                    (
                        "The configured adjustment is not fully "
                        "eligible. Any calculable point-estimate "
                        "evidence is retained above; unavailable "
                        "fields remain undefined."
                    ),
                ]
            )

        lines.extend(
            [
                "",
                (
                    "Method note: return autocorrelations adjust the "
                    "annualization factor. Influence-series "
                    "autocorrelations adjust the higher-moment "
                    "Sharpe variance, PSR, and MinTRL. Bartlett "
                    "weights equal 1 - lag / (maximum lag + 1). "
                    "When maximum lag equals periods per year minus "
                    "one, the point-estimate factor spans Lo's full "
                    "annual horizon; otherwise it is a truncated HAC "
                    "approximation. These are asymptotic plug-in "
                    "estimates and can be unstable in short samples; "
                    "effective observations may exceed the raw count "
                    "under negative dependence. Bandwidth uncertainty "
                    "is not included."
                ),
            ]
        )

    lines.extend(["", "## Bootstrap confidence intervals", ""])

    if bootstrap is None:
        lines.append(
            "Not configured; the complete bootstrap specification was not supplied."
        )
    else:
        lines.extend(
            [
                "| Configuration | Value |",
                "|---|---:|",
                f"| Status | {bootstrap.status.value} |",
                (f"| Observation count | {bootstrap.observation_count} |"),
                f"| Return basis | {bootstrap.return_basis.value} |",
                f"| Method | {bootstrap.method.value} |",
                (f"| Interval method | {bootstrap.interval_method.value} |"),
                f"| Replications | {bootstrap.replications} |",
                (
                    "| Confidence level | "
                    f"{_format_number(bootstrap.confidence_level)} |"
                ),
                (
                    "| Lower / upper quantiles | "
                    f"{_format_number(bootstrap.lower_quantile)} / "
                    f"{_format_number(bootstrap.upper_quantile)} |"
                ),
                f"| Block length | {bootstrap.block_length} |",
                f"| Random seed | {bootstrap.random_seed} |",
                (
                    "| Overlapping source blocks | "
                    f"{_format_number(bootstrap.overlapping_block_count)} |"
                ),
                (
                    "| Blocks per replication | "
                    f"{_format_number(bootstrap.blocks_per_replication)} |"
                ),
                (
                    "| Periods per year | "
                    f"{_format_number(bootstrap.periods_per_year)} |"
                ),
                (f"| HAC maximum lag | {_format_number(bootstrap.hac_maximum_lag)} |"),
                (
                    "| HAC kernel | "
                    + _format_optional_text(_optional_enum_value(bootstrap.hac_kernel))
                    + " |"
                ),
            ]
        )

        if bootstrap.status is BootstrapStatus.ELIGIBLE:
            lines.extend(
                [
                    "",
                    (
                        "| Metric | Status | Point estimate | Lower "
                        "bound | Upper bound | Bootstrap SE | "
                        "Successful / attempted |"
                    ),
                    "|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            lines.extend(
                (
                    f"| {_escape(metric.metric.value)} "
                    f"| {metric.status.value} "
                    f"| {_format_number(metric.point_estimate)} "
                    f"| {_format_number(metric.lower_bound)} "
                    f"| {_format_number(metric.upper_bound)} "
                    f"| {_format_number(metric.bootstrap_standard_error)} "
                    f"| {metric.successful_replications} / "
                    f"{metric.attempted_replications} |"
                )
                for metric in bootstrap.metrics
            )
        else:
            lines.extend(
                [
                    "",
                    (
                        "No interval was calculated. The complete "
                        "configuration is retained above as audit "
                        "evidence."
                    ),
                ]
            )

        lines.extend(
            [
                "",
                (
                    "Method note: moving-block resampling draws fixed-length "
                    "overlapping blocks; stationary resampling draws circular "
                    "blocks with geometrically distributed lengths and the "
                    "configured mean. Both preserve local dependence. "
                    "Two-sided percentile bounds are the "
                    "configured lower and upper quantiles of each "
                    "bootstrap distribution. The fixed-horizon "
                    "cumulative-return interval always uses the original "
                    "observation count. IID-labeled annualized metrics "
                    "retain square-root-of-time scaling; the HAC-adjusted "
                    "Sharpe interval instead re-estimates the selected "
                    "Bartlett ratio in every replication. The result is "
                    "conditional on stationarity, block length, finite "
                    "replications, and the selected interval method."
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## Input issues",
            "",
        ]
    )

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


def _advanced_risk_section(result: AdvancedRiskStatisticsResult | None) -> list[str]:
    lines = ["", "## Downside, tail, and drawdown risk", ""]
    if result is None:
        lines.append(
            "Not configured; no target return and tail confidence were supplied."
        )
        return lines
    lines.extend(
        [
            "| Metric | Value |",
            "|---|---:|",
            f"| Status | {result.status.value} |",
            f"| Observation count | {result.observation_count} |",
            f"| Return basis | {result.return_basis.value} |",
            (
                "| Minimum acceptable period return | "
                f"{_format_number(result.minimum_acceptable_period_return)} |"
            ),
            (
                "| Tail confidence level | "
                f"{_format_number(result.tail_confidence_level)} |"
            ),
            f"| Downside observations | {result.downside_observation_count} |",
            f"| Downside deviation | {_format_number(result.downside_deviation)} |",
            (
                "| Period Sortino ratio | "
                f"{_format_number(result.period_sortino_ratio)} |"
            ),
            (
                "| Annualized Sortino ratio | "
                f"{_format_number(result.annualized_sortino_ratio)} |"
            ),
            f"| Omega ratio | {_format_number(result.omega_ratio)} |",
            (
                "| Historical loss VaR | "
                f"{_format_number(result.historical_value_at_risk)} |"
            ),
            (
                "| Historical expected shortfall | "
                f"{_format_number(result.historical_expected_shortfall)} |"
            ),
            f"| Calmar ratio | {_format_number(result.calmar_ratio)} |",
            f"| Ulcer Index | {_format_number(result.ulcer_index)} |",
            "",
            (
                "Method note: historical VaR/expected shortfall are empirical loss "
                "statistics, Sortino and Omega use the declared period target, and "
                "Calmar/Ulcer use the supplied wealth path. No distribution is fitted."
            ),
        ]
    )
    return lines


def _alignment_rows(alignment: PairedSeriesAlignmentResult) -> list[str]:
    return [
        f"| Alignment status | {alignment.status.value} |",
        f"| Paired role | {alignment.role.value} |",
        (
            "| Strategy / paired observations | "
            f"{alignment.strategy_observation_count} / "
            f"{alignment.paired_observation_count} |"
        ),
        f"| Exactly aligned observations | {alignment.aligned_observation_count} |",
        (
            "| Strategy-only timestamps | "
            f"{_format_sequence(alignment.strategy_only_timestamps)} |"
        ),
        (
            "| Paired-only timestamps | "
            f"{_format_sequence(alignment.paired_only_timestamps)} |"
        ),
    ]


def _risk_free_section(result: RiskFreeSeriesResult | None) -> list[str]:
    lines = ["", "## Time-varying risk-free evidence", ""]
    if result is None:
        lines.append("No period risk-free return series was supplied.")
        return lines
    lines.extend(["| Metric | Value |", "|---|---:|"])
    lines.extend(_alignment_rows(result.alignment))
    lines.extend(
        [
            (
                "| Mean period risk-free return | "
                f"{_format_number(result.mean_period_risk_free_return)} |"
            ),
            (
                "| Cumulative risk-free return | "
                f"{_format_number(result.cumulative_risk_free_return)} |"
            ),
            (
                "| Mean period excess return | "
                f"{_format_number(result.mean_period_excess_return)} |"
            ),
            (
                "| Excess-return sample volatility | "
                f"{_format_number(result.excess_return_sample_volatility)} |"
            ),
            (
                "| Period excess Sharpe ratio | "
                f"{_format_number(result.period_excess_sharpe_ratio)} |"
            ),
            (
                "| Annualized excess Sharpe ratio | "
                f"{_format_number(result.annualized_excess_sharpe_ratio)} |"
            ),
            "",
            (
                "Boundary: this additive series calculation does not silently "
                "replace the explicitly configured scalar risk-free assumption "
                "used by the legacy Sharpe/PSR/HAC methods."
            ),
        ]
    )
    return lines


def _gross_net_section(result: GrossNetCostDragResult | None) -> list[str]:
    lines = ["", "## Gross-to-net cost drag", ""]
    if result is None:
        lines.append("No gross strategy return series was supplied.")
        return lines
    lines.extend(["| Metric | Value |", "|---|---:|"])
    lines.extend(_alignment_rows(result.alignment))
    lines.extend(
        [
            (
                "| Mean period cost drag | "
                f"{_format_number(result.mean_period_cost_drag)} |"
            ),
            (
                "| Cumulative gross return | "
                f"{_format_number(result.cumulative_gross_return)} |"
            ),
            (
                "| Cumulative net return | "
                f"{_format_number(result.cumulative_net_return)} |"
            ),
            (
                "| Cumulative cost drag | "
                f"{_format_number(result.cumulative_cost_drag)} |"
            ),
            (
                "| Annualized arithmetic cost drag | "
                f"{_format_number(result.annualized_arithmetic_cost_drag)} |"
            ),
            (
                "| Positive / negative drag periods | "
                f"{_format_number(result.periods_with_positive_cost_drag)} / "
                f"{_format_number(result.periods_with_negative_cost_drag)} |"
            ),
        ]
    )
    return lines


def _regime_section(result: RegimeAnalysisResult | None) -> list[str]:
    lines = ["", "## Declared-regime slices", ""]
    if result is None:
        lines.append("No externally declared regime series was supplied.")
        return lines
    lines.extend(
        [
            "| Property | Value |",
            "|---|---:|",
            f"| Status | {result.status.value} |",
            f"| Aligned observations | {result.observation_count} |",
            f"| Distinct regimes | {result.regime_count} |",
            (
                "| Strategy-only timestamps | "
                f"{_format_sequence(result.strategy_only_timestamps)} |"
            ),
            (
                "| Regime-only timestamps | "
                f"{_format_sequence(result.regime_only_timestamps)} |"
            ),
        ]
    )
    if result.slices:
        lines.extend(
            [
                "",
                (
                    "| Regime | Observations | Mean return | Sample volatility "
                    "| Cumulative return | Period Sharpe |"
                ),
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        lines.extend(
            (
                f"| {_escape(item.regime)} | {item.observation_count} "
                f"| {_format_number(item.mean_period_return)} "
                f"| {_format_number(item.sample_volatility)} "
                f"| {_format_number(item.cumulative_simple_return)} "
                f"| {_format_number(item.period_sharpe_ratio)} |"
            )
            for item in result.slices
        )
    lines.extend(
        [
            "",
            (
                "Boundary: regimes are supplied labels, not inferred market states; "
                "these slices are descriptive and do not correct selection bias."
            ),
        ]
    )
    return lines


def _benchmark_inference_section(
    result: BenchmarkAlphaInferenceResult | None,
) -> list[str]:
    lines = ["", "## Benchmark alpha inference", ""]
    if result is None:
        lines.append(
            "Not configured; no HAC alpha-inference specification was supplied."
        )
        return lines
    lines.extend(
        [
            "| Metric | Value |",
            "|---|---:|",
            f"| Status | {result.status.value} |",
            f"| Observation count | {result.observation_count} |",
            f"| Bartlett-HAC maximum lag | {result.maximum_lag} |",
            f"| Confidence level | {_format_number(result.confidence_level)} |",
            f"| Period alpha | {_format_number(result.period_alpha)} |",
            f"| Beta | {_format_number(result.beta)} |",
            f"| HAC standard error | {_format_number(result.hac_standard_error)} |",
            f"| Test statistic | {_format_number(result.test_statistic)} |",
            (f"| Two-sided p-value | {_format_number(result.two_sided_p_value)} |"),
            (
                "| Confidence interval | "
                f"[{_format_number(result.confidence_interval_lower)}, "
                f"{_format_number(result.confidence_interval_upper)}] |"
            ),
            (
                "| Statistically different from zero | "
                f"{_format_boolean(result.statistically_different_from_zero)} |"
            ),
            "",
            (
                "Method note: OLS estimates period alpha and beta; a Bartlett-HAC "
                "sandwich covariance supplies the two-sided normal approximation."
            ),
        ]
    )
    return lines


def _calendar_section(
    heading: str,
    assessment: ObservationCalendarAssessmentResult | None,
) -> list[str]:
    lines = ["", f"## {heading}", ""]
    if assessment is None:
        lines.append("Not declared.")
        return lines

    lines.extend(
        [
            "| Property | Value |",
            "|---|---:|",
            f"| Status | {assessment.status.value} |",
            f"| Calendar name | {_escape(assessment.calendar_name)} |",
            f"| Verification source | {assessment.source.value} |",
            (f"| Calendar timezone | {_escape(assessment.calendar_timezone)} |"),
            (
                "| Timestamp timezone | "
                f"{_format_optional_text(assessment.timestamp_timezone)} |"
            ),
            f"| Observation count | {assessment.observation_count} |",
            (f"| Observed session count | {assessment.observed_session_count} |"),
            (
                "| Expected session count | "
                f"{_format_number(assessment.expected_session_count)} |"
            ),
            (
                "| Missing session dates | "
                f"{_format_sequence(assessment.missing_session_dates)} |"
            ),
            (
                "| Unexpected session dates | "
                f"{_format_sequence(assessment.unexpected_session_dates)} |"
            ),
            "",
            (
                "Method note: built-in `24/7` and `WEEKDAYS` policies "
                "generate daily sessions. A named exchange declaration is "
                "not treated as verified unless authoritative session dates "
                "are supplied. The weekday policy is not an exchange-holiday "
                "calendar."
            ),
        ]
    )
    return lines


def _return_construction_section(
    heading: str,
    assessment: ReturnConstructionAssessmentResult,
) -> list[str]:
    return [
        "",
        f"## {heading}",
        "",
        "| Property | Value |",
        "|---|---:|",
        f"| Metadata supplied | {_format_boolean(assessment.supplied)} |",
        (
            "| Declared / required fields | "
            f"{assessment.declared_field_count} / "
            f"{assessment.required_field_count} |"
        ),
        (f"| Completeness ratio | {_format_number(assessment.completeness_ratio)} |"),
        f"| Cost basis | {assessment.cost_basis.value} |",
        (
            "| Transaction costs included | "
            f"{_format_boolean(assessment.transaction_costs_included)} |"
        ),
        f"| Fees included | {_format_boolean(assessment.fees_included)} |",
        (f"| Leverage policy | {_format_optional_enum(assessment.leverage_policy)} |"),
        f"| Currency | {_format_optional_text(assessment.currency)} |",
        (
            "| Price adjustment policy | "
            f"{_format_optional_enum(assessment.price_adjustment_policy)} |"
        ),
        (f"| Data source | {_format_optional_text(assessment.data_source)} |"),
        (f"| Data vintage | {_format_optional_text(assessment.data_vintage)} |"),
        (
            "| Stale-price policy | "
            f"{_format_optional_text(assessment.stale_price_policy)} |"
        ),
        (
            "| Delisting-return policy | "
            f"{_format_optional_text(assessment.delisting_return_policy)} |"
        ),
        (
            "| Survivorship bias controlled | "
            f"{_format_boolean(assessment.survivorship_bias_controlled)} |"
        ),
        (
            "| Look-ahead bias controlled | "
            f"{_format_boolean(assessment.lookahead_bias_controlled)} |"
        ),
        (f"| Signal timing | {_format_optional_text(assessment.signal_timing)} |"),
        (
            "| Execution timing | "
            f"{_format_optional_text(assessment.execution_timing)} |"
        ),
    ]


def _performance_path_section(result: PerformancePathResult) -> list[str]:
    return [
        "",
        "## Performance path evidence",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Return basis | {result.return_basis.value} |",
        f"| Starting wealth | {_format_number(result.starting_wealth)} |",
        f"| Ending wealth | {_format_number(result.ending_wealth)} |",
        (
            "| Cumulative simple return | "
            f"{_format_number(result.cumulative_simple_return)} |"
        ),
        f"| CAGR | {_format_number(result.cagr)} |",
        (f"| CAGR periods per year | {_format_number(result.periods_per_year)} |"),
        (f"| Maximum drawdown | {_format_number(result.maximum_drawdown)} |"),
        (
            "| Maximum-drawdown peak | "
            f"{_format_timestamp(result.maximum_drawdown_peak_timestamp)} |"
        ),
        (
            "| Maximum-drawdown trough | "
            f"{_format_timestamp(result.maximum_drawdown_trough_timestamp)} |"
        ),
        (
            "| Maximum-drawdown recovery | "
            f"{_format_timestamp(result.maximum_drawdown_recovery_timestamp)} |"
        ),
        (
            "| Maximum drawdown recovered | "
            f"{_format_boolean(result.maximum_drawdown_recovered)} |"
        ),
        (
            "| Maximum-drawdown duration (observations) | "
            f"{result.maximum_drawdown_duration_observations} |"
        ),
        (
            "| Longest time underwater (observations) | "
            f"{result.longest_time_underwater_observations} |"
        ),
        (
            "| Longest-underwater start | "
            f"{_format_timestamp(result.longest_time_underwater_start_timestamp)} |"
        ),
        (
            "| Longest-underwater end | "
            f"{_format_timestamp(result.longest_time_underwater_end_timestamp)} |"
        ),
        "",
        (
            "Method note: wealth starts at 1.0 and all path calculations "
            "use period simple returns. CAGR uses the explicit eligible "
            "periods-per-year scale and observation count; it is not inferred "
            "from wall-clock time. Drawdown running peaks include initial "
            "wealth, so the peak timestamp is undefined when the path falls "
            "below 1.0 immediately."
        ),
    ]


def _benchmark_section(
    calendar: ObservationCalendarAssessmentResult | None,
    construction: ReturnConstructionAssessmentResult | None,
    alignment: BenchmarkAlignmentResult | None,
    comparison: BenchmarkComparisonResult | None,
) -> list[str]:
    lines = ["", "## Benchmark-relative evidence", ""]
    if alignment is None:
        lines.append("No benchmark return series was supplied.")
        return lines

    lines.extend(
        [
            "| Alignment property | Value |",
            "|---|---:|",
            f"| Status | {alignment.status.value} |",
            (f"| Strategy observations | {alignment.strategy_observation_count} |"),
            (f"| Benchmark observations | {alignment.benchmark_observation_count} |"),
            (f"| Aligned observations | {alignment.aligned_observation_count} |"),
            (
                "| Strategy-only timestamps | "
                f"{_format_sequence(alignment.strategy_only_timestamps)} |"
            ),
            (
                "| Benchmark-only timestamps | "
                f"{_format_sequence(alignment.benchmark_only_timestamps)} |"
            ),
        ]
    )
    if comparison is None:
        lines.extend(
            [
                "",
                (
                    "Relative statistics were withheld because exact "
                    "timestamp alignment was not satisfied."
                ),
            ]
        )
    else:
        lines.extend(
            [
                "",
                "| Relative metric | Value |",
                "|---|---:|",
                f"| Benchmark ID | {_escape(comparison.benchmark_id)} |",
                f"| Return basis | {comparison.return_basis.value} |",
                (
                    "| Strategy cumulative return | "
                    f"{_format_number(comparison.strategy_cumulative_simple_return)} |"
                ),
                (
                    "| Benchmark cumulative return | "
                    f"{_format_number(comparison.benchmark_cumulative_simple_return)} |"
                ),
                (
                    "| Relative wealth return | "
                    f"{_format_number(comparison.relative_wealth_return)} |"
                ),
                (
                    "| Mean period active return | "
                    f"{_format_number(comparison.mean_period_active_return)} |"
                ),
                (
                    "| Period tracking error | "
                    f"{_format_number(comparison.period_tracking_error)} |"
                ),
                (
                    "| Annualized tracking error | "
                    f"{_format_number(comparison.annualized_tracking_error)} |"
                ),
                (
                    "| Period information ratio | "
                    f"{_format_number(comparison.period_information_ratio)} |"
                ),
                (
                    "| Annualized information ratio | "
                    f"{_format_number(comparison.annualized_information_ratio)} |"
                ),
                (
                    "| Return correlation | "
                    f"{_format_number(comparison.return_correlation)} |"
                ),
                f"| Beta | {_format_number(comparison.beta)} |",
                (
                    "| Period arithmetic alpha | "
                    f"{_format_number(comparison.period_arithmetic_alpha)} |"
                ),
                (
                    "| Annualized arithmetic alpha | "
                    f"{_format_number(comparison.annualized_arithmetic_alpha)} |"
                ),
                "",
                (
                    "Method note: active return is strategy simple return "
                    "minus benchmark simple return. Information ratio uses "
                    "sample tracking error. Beta and alpha are sample OLS "
                    "moment estimates with an intercept. Annualized fields use "
                    "the same explicit scale as the strategy audit and are "
                    "withheld when that scale is ineligible. These relative "
                    "annualizations are IID-style point estimates; Part H does "
                    "not automatically adjust active-return statistics."
                ),
            ]
        )

    if calendar is not None:
        lines.extend(_calendar_section("Benchmark observation calendar", calendar))
    if construction is not None:
        lines.extend(
            _return_construction_section(
                "Benchmark return construction",
                construction,
            )
        )
    return lines


def _format_number(value: float | int | None) -> str:
    if value is None:
        return "undefined"
    return format(value, ".12g")


def _format_optional_text(value: str | None) -> str:
    return "not supplied" if value is None else _escape(value)


def _format_boolean(value: bool | None) -> str:
    return "undefined" if value is None else str(value).lower()


def _format_optional_enum(value: Enum | None) -> str:
    return "not supplied" if value is None else value.value


def _format_timestamp(value: datetime | None) -> str:
    return "undefined" if value is None else _escape(value.isoformat())


def _format_sequence(values: tuple[str, ...]) -> str:
    if not values:
        return "none"
    return _escape(", ".join(values))


def _optional_enum_value(value: HACKernel | None) -> str | None:
    return None if value is None else value.value


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("\r", " ")
        .replace("\n", " ")
    )
