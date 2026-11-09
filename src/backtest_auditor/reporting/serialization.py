import json
from typing import Any

from backtest_auditor import REPORT_SCHEMA_VERSION

from backtest_auditor.application.single_run_audit import (
    SingleRunAuditResult,
)
from backtest_auditor.domain.enums import (
    BenchmarkAlignmentStatus,
    BootstrapMetricStatus,
    BootstrapStatus,
    ObservationCalendarStatus,
    SerialAdjustmentStatus,
    SerialDependenceStatus,
)
from backtest_auditor.domain.findings import AuditFinding
from backtest_auditor.domain.evidence import EvidenceProfileResult
from backtest_auditor.domain.issues import ValidationIssue
from backtest_auditor.domain.reproducibility import AuditRunManifestResult
from backtest_auditor.domain.results import (
    AdvancedRiskStatisticsResult,
    AnnualizedStatisticsResult,
    BenchmarkAlignmentResult,
    BenchmarkComparisonResult,
    BenchmarkAlphaInferenceResult,
    BootstrapMetricResult,
    BootstrapResult,
    DescriptiveStatisticsResult,
    DistributionStatisticsResult,
    GrossNetCostDragResult,
    HACAutocorrelationEstimate,
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


def single_run_audit_to_dict(
    result: SingleRunAuditResult,
) -> dict[str, Any]:
    """Convert an audit result into JSON-safe public report data."""

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "audit_type": "single_run",
        "run_id": result.run_id,
        "evidence_profile": evidence_profile_to_dict(result.evidence_profile),
        "run_manifest": run_manifest_to_dict(result.run_manifest),
        "observation_calendar": (
            None
            if result.observation_calendar is None
            else _observation_calendar_to_dict(result.observation_calendar)
        ),
        "return_construction": _return_construction_to_dict(result.return_construction),
        "sampling_assessment": _sampling_assessment_to_dict(result.sampling_assessment),
        "input_issues": [
            validation_issue_to_dict(issue) for issue in result.input_issues
        ],
        "descriptive_statistics": _statistics_to_dict(result.descriptive_statistics),
        "performance_path": _performance_path_to_dict(result.performance_path),
        "advanced_risk_statistics": _advanced_risk_to_dict(
            result.advanced_risk_statistics
        ),
        "risk_free_series": _risk_free_series_to_dict(result.risk_free_series),
        "gross_net_cost_drag": _gross_net_to_dict(result.gross_net_cost_drag),
        "regime_analysis": _regime_analysis_to_dict(result.regime_analysis),
        "benchmark_alpha_inference": _benchmark_inference_to_dict(
            result.benchmark_alpha_inference
        ),
        "benchmark": (
            None
            if result.benchmark_alignment is None
            else {
                "observation_calendar": (
                    None
                    if result.benchmark_observation_calendar is None
                    else _observation_calendar_to_dict(
                        result.benchmark_observation_calendar
                    )
                ),
                "return_construction": (
                    None
                    if result.benchmark_return_construction is None
                    else _return_construction_to_dict(
                        result.benchmark_return_construction
                    )
                ),
                "alignment": _benchmark_alignment_to_dict(result.benchmark_alignment),
                "comparison": (
                    None
                    if result.benchmark_comparison is None
                    else _benchmark_comparison_to_dict(result.benchmark_comparison)
                ),
            }
        ),
        "distribution_statistics": _distribution_statistics_to_dict(
            result.distribution_statistics
        ),
        "serial_dependence": (
            None
            if result.serial_dependence is None
            else _serial_dependence_to_dict(result.serial_dependence)
        ),
        "serial_adjustment": (
            None
            if result.serial_adjustment is None
            else _serial_adjustment_to_dict(result.serial_adjustment)
        ),
        "bootstrap": (
            None if result.bootstrap is None else _bootstrap_to_dict(result.bootstrap)
        ),
        "annualized_statistics": (
            None
            if result.annualized_statistics is None
            else _annualized_statistics_to_dict(result.annualized_statistics)
        ),
        "sharpe_uncertainty": (
            None
            if result.sharpe_uncertainty is None
            else _sharpe_uncertainty_to_dict(result.sharpe_uncertainty)
        ),
        "track_record_length": (
            None
            if result.track_record_length is None
            else _track_record_length_to_dict(result.track_record_length)
        ),
        "findings": [_finding_to_dict(finding) for finding in result.findings],
    }


def evidence_profile_to_dict(result: EvidenceProfileResult) -> dict[str, Any]:
    return {
        "method": result.method,
        "audit_type": result.audit_type,
        "interpretation_boundary": result.interpretation_boundary,
        "overall_status": None,
        "dimensions": [
            {
                "dimension": item.dimension.value,
                "status": item.status.value,
                "summary": item.summary,
                "supporting_evidence_codes": list(item.supporting_evidence_codes),
                "adverse_evidence_codes": list(item.adverse_evidence_codes),
                "unavailable_evidence_codes": list(item.unavailable_evidence_codes),
                "assumption_codes": list(item.assumption_codes),
                "next_evidence_required": list(item.next_evidence_required),
            }
            for item in result.dimensions
        ],
    }


def run_manifest_to_dict(
    result: AuditRunManifestResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "manifest_schema_version": result.manifest_schema_version,
        "audit_id": result.audit_id,
        "audit_timestamp_utc": result.audit_timestamp_utc,
        "audit_type": result.audit_type,
        "subject_id": result.subject_id,
        "package_version": result.package_version,
        "report_schema_version": result.report_schema_version,
        "git_commit": result.git_commit,
        "input_artifacts": [
            {
                "role": item.role,
                "file_name": item.file_name,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in result.input_artifacts
        ],
        "normalized_data_encoding": result.normalized_data_encoding,
        "normalized_data_sha256": result.normalized_data_sha256,
        "configuration": json.loads(result.configuration_json),
        "configuration_sha256": result.configuration_sha256,
        "random_seeds": {name: seed for name, seed in result.random_seeds},
        "method_versions": [
            {"name": item.name, "version": item.version}
            for item in result.method_versions
        ],
        "warnings": [
            {"source": item.source, "code": item.code} for item in result.warnings
        ],
        "environment": {
            "python_implementation": result.python_implementation,
            "python_version": result.python_version,
            "platform_system": result.platform_system,
            "platform_machine": result.platform_machine,
            "dependencies": [
                {"name": item.name, "version": item.version}
                for item in result.dependencies
            ],
        },
        "manifest_sha256": result.manifest_sha256,
    }


def _observation_calendar_to_dict(
    assessment: ObservationCalendarAssessmentResult,
) -> dict[str, Any]:
    return {
        "status": assessment.status.value,
        "verified": (assessment.status is ObservationCalendarStatus.VERIFIED),
        "calendar_name": assessment.calendar_name,
        "source": assessment.source.value,
        "calendar_timezone": assessment.calendar_timezone,
        "timestamp_timezone": assessment.timestamp_timezone,
        "observation_count": assessment.observation_count,
        "observed_session_count": assessment.observed_session_count,
        "expected_session_count": assessment.expected_session_count,
        "missing_session_dates": list(assessment.missing_session_dates),
        "unexpected_session_dates": list(assessment.unexpected_session_dates),
    }


def _return_construction_to_dict(
    assessment: ReturnConstructionAssessmentResult,
) -> dict[str, Any]:
    return {
        "role": assessment.role.value,
        "supplied": assessment.supplied,
        "declared_field_count": assessment.declared_field_count,
        "required_field_count": assessment.required_field_count,
        "completeness_ratio": assessment.completeness_ratio,
        "cost_basis": assessment.cost_basis.value,
        "transaction_costs_included": (assessment.transaction_costs_included),
        "fees_included": assessment.fees_included,
        "leverage_policy": (
            None
            if assessment.leverage_policy is None
            else assessment.leverage_policy.value
        ),
        "currency": assessment.currency,
        "price_adjustment_policy": (
            None
            if assessment.price_adjustment_policy is None
            else assessment.price_adjustment_policy.value
        ),
        "data_source": assessment.data_source,
        "data_vintage": assessment.data_vintage,
        "stale_price_policy": assessment.stale_price_policy,
        "delisting_return_policy": (assessment.delisting_return_policy),
        "survivorship_bias_controlled": (assessment.survivorship_bias_controlled),
        "lookahead_bias_controlled": (assessment.lookahead_bias_controlled),
        "signal_timing": assessment.signal_timing,
        "execution_timing": assessment.execution_timing,
    }


def _performance_path_to_dict(
    result: PerformancePathResult,
) -> dict[str, Any]:
    return {
        "observation_count": result.observation_count,
        "return_basis": result.return_basis.value,
        "periods_per_year": result.periods_per_year,
        "starting_wealth": result.starting_wealth,
        "ending_wealth": result.ending_wealth,
        "cumulative_simple_return": result.cumulative_simple_return,
        "cagr": result.cagr,
        "maximum_drawdown": result.maximum_drawdown,
        "maximum_drawdown_peak_timestamp": _timestamp_or_none(
            result.maximum_drawdown_peak_timestamp
        ),
        "maximum_drawdown_trough_timestamp": _timestamp_or_none(
            result.maximum_drawdown_trough_timestamp
        ),
        "maximum_drawdown_recovery_timestamp": _timestamp_or_none(
            result.maximum_drawdown_recovery_timestamp
        ),
        "maximum_drawdown_recovered": (result.maximum_drawdown_recovered),
        "maximum_drawdown_duration_observations": (
            result.maximum_drawdown_duration_observations
        ),
        "longest_time_underwater_observations": (
            result.longest_time_underwater_observations
        ),
        "longest_time_underwater_start_timestamp": _timestamp_or_none(
            result.longest_time_underwater_start_timestamp
        ),
        "longest_time_underwater_end_timestamp": _timestamp_or_none(
            result.longest_time_underwater_end_timestamp
        ),
    }


def _benchmark_alignment_to_dict(
    result: BenchmarkAlignmentResult,
) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "eligible": result.status is BenchmarkAlignmentStatus.ELIGIBLE,
        "strategy_observation_count": result.strategy_observation_count,
        "benchmark_observation_count": result.benchmark_observation_count,
        "aligned_observation_count": result.aligned_observation_count,
        "strategy_only_timestamps": list(result.strategy_only_timestamps),
        "benchmark_only_timestamps": list(result.benchmark_only_timestamps),
    }


def _benchmark_comparison_to_dict(
    result: BenchmarkComparisonResult,
) -> dict[str, Any]:
    return {
        "benchmark_id": result.benchmark_id,
        "observation_count": result.observation_count,
        "return_basis": result.return_basis.value,
        "periods_per_year": result.periods_per_year,
        "strategy_cumulative_simple_return": (result.strategy_cumulative_simple_return),
        "benchmark_cumulative_simple_return": (
            result.benchmark_cumulative_simple_return
        ),
        "relative_wealth_return": result.relative_wealth_return,
        "mean_period_active_return": result.mean_period_active_return,
        "period_tracking_error": result.period_tracking_error,
        "annualized_tracking_error": result.annualized_tracking_error,
        "period_information_ratio": result.period_information_ratio,
        "annualized_information_ratio": (result.annualized_information_ratio),
        "return_correlation": result.return_correlation,
        "beta": result.beta,
        "period_arithmetic_alpha": result.period_arithmetic_alpha,
        "annualized_arithmetic_alpha": (result.annualized_arithmetic_alpha),
    }


def _benchmark_inference_to_dict(
    result: BenchmarkAlphaInferenceResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "observation_count": result.observation_count,
        "maximum_lag": result.maximum_lag,
        "confidence_level": result.confidence_level,
        "period_alpha": result.period_alpha,
        "beta": result.beta,
        "hac_standard_error": result.hac_standard_error,
        "test_statistic": result.test_statistic,
        "two_sided_p_value": result.two_sided_p_value,
        "confidence_interval_lower": result.confidence_interval_lower,
        "confidence_interval_upper": result.confidence_interval_upper,
        "statistically_different_from_zero": (result.statistically_different_from_zero),
    }


def _alignment_to_dict(alignment: Any) -> dict[str, Any]:
    return {
        "role": alignment.role.value,
        "status": alignment.status.value,
        "strategy_observation_count": alignment.strategy_observation_count,
        "paired_observation_count": alignment.paired_observation_count,
        "aligned_observation_count": alignment.aligned_observation_count,
        "strategy_only_timestamps": list(alignment.strategy_only_timestamps),
        "paired_only_timestamps": list(alignment.paired_only_timestamps),
    }


def _risk_free_series_to_dict(
    result: RiskFreeSeriesResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "alignment": _alignment_to_dict(result.alignment),
        "mean_period_risk_free_return": result.mean_period_risk_free_return,
        "cumulative_risk_free_return": result.cumulative_risk_free_return,
        "mean_period_excess_return": result.mean_period_excess_return,
        "excess_return_sample_volatility": result.excess_return_sample_volatility,
        "period_excess_sharpe_ratio": result.period_excess_sharpe_ratio,
        "annualized_excess_sharpe_ratio": result.annualized_excess_sharpe_ratio,
    }


def _gross_net_to_dict(
    result: GrossNetCostDragResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "alignment": _alignment_to_dict(result.alignment),
        "mean_period_cost_drag": result.mean_period_cost_drag,
        "cumulative_gross_return": result.cumulative_gross_return,
        "cumulative_net_return": result.cumulative_net_return,
        "cumulative_cost_drag": result.cumulative_cost_drag,
        "annualized_arithmetic_cost_drag": result.annualized_arithmetic_cost_drag,
        "periods_with_positive_cost_drag": result.periods_with_positive_cost_drag,
        "periods_with_negative_cost_drag": result.periods_with_negative_cost_drag,
    }


def _regime_analysis_to_dict(
    result: RegimeAnalysisResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "observation_count": result.observation_count,
        "regime_count": result.regime_count,
        "strategy_only_timestamps": list(result.strategy_only_timestamps),
        "regime_only_timestamps": list(result.regime_only_timestamps),
        "slices": [
            {
                "regime": item.regime,
                "observation_count": item.observation_count,
                "mean_period_return": item.mean_period_return,
                "sample_volatility": item.sample_volatility,
                "cumulative_simple_return": item.cumulative_simple_return,
                "period_sharpe_ratio": item.period_sharpe_ratio,
            }
            for item in result.slices
        ],
    }


def _advanced_risk_to_dict(
    result: AdvancedRiskStatisticsResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status.value,
        "observation_count": result.observation_count,
        "return_basis": result.return_basis.value,
        "minimum_acceptable_period_return": (result.minimum_acceptable_period_return),
        "tail_confidence_level": result.tail_confidence_level,
        "downside_observation_count": result.downside_observation_count,
        "downside_deviation": result.downside_deviation,
        "period_sortino_ratio": result.period_sortino_ratio,
        "annualized_sortino_ratio": result.annualized_sortino_ratio,
        "omega_ratio": result.omega_ratio,
        "historical_value_at_risk": result.historical_value_at_risk,
        "historical_expected_shortfall": result.historical_expected_shortfall,
        "calmar_ratio": result.calmar_ratio,
        "ulcer_index": result.ulcer_index,
    }


def _timestamp_or_none(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _sampling_assessment_to_dict(
    assessment: SamplingAssessmentResult,
) -> dict[str, Any]:
    return {
        "status": assessment.status.value,
        "observation_count": assessment.observation_count,
        "interval_count": assessment.interval_count,
        "declared_frequency": assessment.declared_frequency,
        "inferred_frequency": assessment.inferred_frequency,
        "periods_per_year": assessment.periods_per_year,
        "minimum_interval_seconds": (assessment.minimum_interval_seconds),
        "maximum_interval_seconds": (assessment.maximum_interval_seconds),
        "annualization_eligible": (assessment.annualization_eligible),
    }


def validation_issue_to_dict(
    issue: ValidationIssue,
) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity.value,
        "blocking": issue.blocking,
        "location": issue.location,
    }


def _statistics_to_dict(
    statistics: DescriptiveStatisticsResult,
) -> dict[str, Any]:
    return {
        "observation_count": statistics.observation_count,
        "start_timestamp": statistics.start_timestamp.isoformat(),
        "end_timestamp": statistics.end_timestamp.isoformat(),
        "mean_return": statistics.mean_return,
        "sample_volatility": statistics.sample_volatility,
        "minimum_return": statistics.minimum_return,
        "maximum_return": statistics.maximum_return,
        "cumulative_simple_return": (statistics.cumulative_simple_return),
        "return_convention": statistics.return_convention.value,
    }


def _annualized_statistics_to_dict(
    statistics: AnnualizedStatisticsResult,
) -> dict[str, Any]:
    return {
        "periods_per_year": statistics.periods_per_year,
        "return_basis": statistics.return_basis.value,
        "annualized_arithmetic_mean_return": (
            statistics.annualized_arithmetic_mean_return
        ),
        "annualized_sample_volatility": (statistics.annualized_sample_volatility),
        "annual_risk_free_rate": (statistics.annual_risk_free_rate),
        "period_risk_free_rate": (statistics.period_risk_free_rate),
        "annualized_sharpe_ratio": (statistics.annualized_sharpe_ratio),
    }


def _distribution_statistics_to_dict(
    statistics: DistributionStatisticsResult,
) -> dict[str, Any]:
    return {
        "observation_count": statistics.observation_count,
        "return_basis": statistics.return_basis.value,
        "sample_skewness": statistics.sample_skewness,
        "sample_excess_kurtosis": (statistics.sample_excess_kurtosis),
        "sample_pearson_kurtosis": (statistics.sample_pearson_kurtosis),
    }


def _sharpe_uncertainty_to_dict(
    result: SharpeUncertaintyResult,
) -> dict[str, Any]:
    return {
        "observation_count": result.observation_count,
        "periods_per_year": result.periods_per_year,
        "period_sharpe_ratio": result.period_sharpe_ratio,
        "annualized_sharpe_ratio": (result.annualized_sharpe_ratio),
        "sharpe_variance_adjustment": (result.sharpe_variance_adjustment),
        "period_sharpe_standard_error": (result.period_sharpe_standard_error),
        "annualized_sharpe_standard_error": (result.annualized_sharpe_standard_error),
        "benchmark_period_sharpe_ratio": (result.benchmark_period_sharpe_ratio),
        "benchmark_annualized_sharpe_ratio": (result.benchmark_annualized_sharpe_ratio),
        "probabilistic_sharpe_ratio": (result.probabilistic_sharpe_ratio),
    }


def _serial_dependence_to_dict(
    result: SerialDependenceResult,
) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "eligible": (result.status is SerialDependenceStatus.ELIGIBLE),
        "observation_count": result.observation_count,
        "return_basis": result.return_basis.value,
        "maximum_lag": result.maximum_lag,
        "autocorrelations": [
            {
                "lag": estimate.lag,
                "autocorrelation": estimate.autocorrelation,
            }
            for estimate in result.autocorrelations
        ],
        "strongest_absolute_autocorrelation_lag": (
            result.strongest_absolute_autocorrelation_lag
        ),
        "strongest_absolute_autocorrelation": (
            result.strongest_absolute_autocorrelation
        ),
        "ljung_box_statistic": result.ljung_box_statistic,
        "degrees_of_freedom": result.degrees_of_freedom,
        "p_value": result.p_value,
        "significance_level": result.significance_level,
        "serial_dependence_detected": (result.serial_dependence_detected),
        "partial_autocorrelations": [
            {"lag": item.lag, "partial_autocorrelation": item.autocorrelation}
            for item in result.partial_autocorrelations
        ],
        "acf_confidence_bound": result.acf_confidence_bound,
        "mean_long_run_variance_ratio": result.mean_long_run_variance_ratio,
        "mean_effective_observation_count": (result.mean_effective_observation_count),
        "runs_test": {
            "observation_count": result.runs_observation_count,
            "runs_count": result.runs_count,
            "expected_count": result.runs_expected_count,
            "z_statistic": result.runs_z_statistic,
            "p_value": result.runs_p_value,
            "dependence_detected": result.runs_dependence_detected,
        },
        "variance_ratios": [
            {
                "horizon": item.horizon,
                "variance_ratio": item.variance_ratio,
                "heteroskedastic_robust_standard_error": (
                    item.heteroskedastic_robust_standard_error
                ),
                "z_statistic": item.z_statistic,
                "p_value": item.p_value,
                "dependence_detected": item.dependence_detected,
            }
            for item in result.variance_ratios
        ],
    }


def _serial_adjustment_to_dict(
    result: SerialAdjustmentResult,
) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "eligible": result.status is SerialAdjustmentStatus.ELIGIBLE,
        "observation_count": result.observation_count,
        "return_basis": result.return_basis.value,
        "maximum_lag": result.maximum_lag,
        "kernel": result.kernel.value,
        "periods_per_year": result.periods_per_year,
        "return_autocorrelations": [
            _hac_autocorrelation_to_dict(estimate)
            for estimate in result.return_autocorrelations
        ],
        "return_long_run_variance_ratio": (result.return_long_run_variance_ratio),
        "iid_annualization_factor": (result.iid_annualization_factor),
        "hac_annualization_factor": (result.hac_annualization_factor),
        "full_lo_annual_horizon": (result.full_lo_annual_horizon),
        "iid_annualized_sharpe_ratio": (result.iid_annualized_sharpe_ratio),
        "hac_adjusted_annualized_sharpe_ratio": (
            result.hac_adjusted_annualized_sharpe_ratio
        ),
        "influence_autocorrelations": [
            _hac_autocorrelation_to_dict(estimate)
            for estimate in result.influence_autocorrelations
        ],
        "sharpe_long_run_variance_ratio": (result.sharpe_long_run_variance_ratio),
        "iid_sharpe_variance_adjustment": (result.iid_sharpe_variance_adjustment),
        "hac_sharpe_variance_adjustment": (result.hac_sharpe_variance_adjustment),
        "iid_period_sharpe_standard_error": (result.iid_period_sharpe_standard_error),
        "hac_period_sharpe_standard_error": (result.hac_period_sharpe_standard_error),
        "effective_observation_count": (result.effective_observation_count),
        "benchmark_period_sharpe_ratio": (result.benchmark_period_sharpe_ratio),
        "iid_probabilistic_sharpe_ratio": (result.iid_probabilistic_sharpe_ratio),
        "hac_probabilistic_sharpe_ratio": (result.hac_probabilistic_sharpe_ratio),
        "required_psr_confidence_level": (result.required_psr_confidence_level),
        "hac_confidence_requirement_met": (result.hac_confidence_requirement_met),
        "hac_minimum_track_record_length_observations": (
            result.hac_minimum_track_record_length_observations
        ),
        "hac_minimum_required_observations": (result.hac_minimum_required_observations),
        "hac_minimum_track_record_length_years": (
            result.hac_minimum_track_record_length_years
        ),
        "hac_additional_observations_required": (
            result.hac_additional_observations_required
        ),
        "hac_observations_above_minimum": (result.hac_observations_above_minimum),
    }


def _hac_autocorrelation_to_dict(
    result: HACAutocorrelationEstimate,
) -> dict[str, Any]:
    return {
        "lag": result.lag,
        "autocorrelation": result.autocorrelation,
        "kernel_weight": result.kernel_weight,
        "weighted_contribution": result.weighted_contribution,
    }


def _bootstrap_to_dict(result: BootstrapResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "eligible": result.status is BootstrapStatus.ELIGIBLE,
        "observation_count": result.observation_count,
        "return_basis": result.return_basis.value,
        "method": result.method.value,
        "interval_method": result.interval_method.value,
        "replications": result.replications,
        "confidence_level": result.confidence_level,
        "lower_quantile": result.lower_quantile,
        "upper_quantile": result.upper_quantile,
        "block_length": result.block_length,
        "random_seed": result.random_seed,
        "overlapping_block_count": result.overlapping_block_count,
        "blocks_per_replication": result.blocks_per_replication,
        "periods_per_year": result.periods_per_year,
        "hac_maximum_lag": result.hac_maximum_lag,
        "hac_kernel": (None if result.hac_kernel is None else result.hac_kernel.value),
        "metrics": [_bootstrap_metric_to_dict(metric) for metric in result.metrics],
    }


def _bootstrap_metric_to_dict(
    result: BootstrapMetricResult,
) -> dict[str, Any]:
    return {
        "metric": result.metric.value,
        "status": result.status.value,
        "interval_available": (result.status is BootstrapMetricStatus.ELIGIBLE),
        "point_estimate": result.point_estimate,
        "lower_bound": result.lower_bound,
        "upper_bound": result.upper_bound,
        "bootstrap_standard_error": (result.bootstrap_standard_error),
        "attempted_replications": result.attempted_replications,
        "successful_replications": result.successful_replications,
        "failed_replications": (
            result.attempted_replications - result.successful_replications
        ),
    }


def _track_record_length_to_dict(
    result: TrackRecordLengthResult,
) -> dict[str, Any]:
    return {
        "observation_count": result.observation_count,
        "periods_per_year": result.periods_per_year,
        "required_psr_confidence_level": (result.required_psr_confidence_level),
        "observed_probabilistic_sharpe_ratio": (
            result.observed_probabilistic_sharpe_ratio
        ),
        "confidence_requirement_met": (result.confidence_requirement_met),
        "normal_critical_value": result.normal_critical_value,
        "observed_period_sharpe_difference": (result.observed_period_sharpe_difference),
        "minimum_track_record_length_observations": (
            result.minimum_track_record_length_observations
        ),
        "minimum_required_observations": (result.minimum_required_observations),
        "minimum_track_record_length_years": (result.minimum_track_record_length_years),
        "additional_observations_required": (result.additional_observations_required),
        "observations_above_minimum": (result.observations_above_minimum),
    }


def _finding_to_dict(
    finding: AuditFinding,
) -> dict[str, Any]:
    return {
        "code": finding.code,
        "category": finding.category.value,
        "claim": finding.claim,
        "implication": finding.implication,
        "remediation": finding.remediation,
    }
