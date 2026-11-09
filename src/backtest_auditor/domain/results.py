from dataclasses import dataclass

import pandas as pd

from backtest_auditor.domain.enums import (
    AdvancedRiskStatus,
    BenchmarkAlignmentStatus,
    BenchmarkInferenceStatus,
    BootstrapIntervalMethod,
    BootstrapMethod,
    BootstrapMetric,
    BootstrapMetricStatus,
    BootstrapStatus,
    CSCVMethod,
    CSCVPerformanceMetric,
    CSCVRankTieMethod,
    CSCVSplitStatus,
    CSCVStatus,
    CSCVWinnerTiePolicy,
    DeflatedSharpeRatioMethod,
    DeflatedSharpeRatioStatus,
    DataSnoopingStatus,
    DSRTrialCountBasis,
    DSRTrialCountPolicy,
    ExperimentFamilyStatus,
    FrequencyStatus,
    HACKernel,
    LeveragePolicy,
    ObservationCalendarSource,
    ObservationCalendarStatus,
    ParameterDistanceMetric,
    ParameterRobustnessStatus,
    PairedSeriesStatus,
    PriceAdjustmentPolicy,
    ReturnConvention,
    ReturnCostBasis,
    SelectionDirection,
    RobustnessPerformanceMetric,
    RobustnessRankTieMethod,
    RobustnessSliceStatus,
    RobustnessWinnerTiePolicy,
    SerialAdjustmentStatus,
    SerialDependenceStatus,
    SeriesRole,
    TrialOutcome,
    TemporalRobustnessStatus,
)
from backtest_auditor.domain.experiment import TrialParameter


@dataclass(frozen=True, slots=True)
class ObservationCalendarAssessmentResult:
    status: ObservationCalendarStatus
    calendar_name: str
    source: ObservationCalendarSource
    calendar_timezone: str
    timestamp_timezone: str | None
    observation_count: int
    observed_session_count: int
    expected_session_count: int | None
    missing_session_dates: tuple[str, ...]
    unexpected_session_dates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReturnConstructionAssessmentResult:
    role: SeriesRole
    supplied: bool
    declared_field_count: int
    required_field_count: int
    completeness_ratio: float
    cost_basis: ReturnCostBasis
    transaction_costs_included: bool | None
    fees_included: bool | None
    leverage_policy: LeveragePolicy | None
    currency: str | None
    price_adjustment_policy: PriceAdjustmentPolicy | None
    data_source: str | None
    data_vintage: str | None
    stale_price_policy: str | None
    delisting_return_policy: str | None
    survivorship_bias_controlled: bool | None
    lookahead_bias_controlled: bool | None
    signal_timing: str | None
    execution_timing: str | None


@dataclass(frozen=True, slots=True)
class PerformancePathResult:
    observation_count: int
    return_basis: ReturnConvention
    periods_per_year: int | None
    starting_wealth: float
    ending_wealth: float | None
    cumulative_simple_return: float | None
    cagr: float | None
    maximum_drawdown: float | None
    maximum_drawdown_peak_timestamp: pd.Timestamp | None
    maximum_drawdown_trough_timestamp: pd.Timestamp | None
    maximum_drawdown_recovery_timestamp: pd.Timestamp | None
    maximum_drawdown_recovered: bool | None
    maximum_drawdown_duration_observations: int | None
    longest_time_underwater_observations: int | None
    longest_time_underwater_start_timestamp: pd.Timestamp | None
    longest_time_underwater_end_timestamp: pd.Timestamp | None


@dataclass(frozen=True, slots=True)
class BenchmarkAlignmentResult:
    status: BenchmarkAlignmentStatus
    strategy_observation_count: int
    benchmark_observation_count: int
    aligned_observation_count: int
    strategy_only_timestamps: tuple[str, ...]
    benchmark_only_timestamps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkComparisonResult:
    benchmark_id: str
    observation_count: int
    return_basis: ReturnConvention
    periods_per_year: int | None
    strategy_cumulative_simple_return: float
    benchmark_cumulative_simple_return: float
    relative_wealth_return: float | None
    mean_period_active_return: float
    period_tracking_error: float | None
    annualized_tracking_error: float | None
    period_information_ratio: float | None
    annualized_information_ratio: float | None
    return_correlation: float | None
    beta: float | None
    period_arithmetic_alpha: float | None
    annualized_arithmetic_alpha: float | None


@dataclass(frozen=True, slots=True)
class BenchmarkAlphaInferenceResult:
    status: BenchmarkInferenceStatus
    observation_count: int
    maximum_lag: int
    confidence_level: float
    period_alpha: float | None
    beta: float | None
    hac_standard_error: float | None
    test_statistic: float | None
    two_sided_p_value: float | None
    confidence_interval_lower: float | None
    confidence_interval_upper: float | None
    statistically_different_from_zero: bool | None


@dataclass(frozen=True, slots=True)
class PairedSeriesAlignmentResult:
    role: SeriesRole
    status: PairedSeriesStatus
    strategy_observation_count: int
    paired_observation_count: int
    aligned_observation_count: int
    strategy_only_timestamps: tuple[str, ...]
    paired_only_timestamps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RiskFreeSeriesResult:
    alignment: PairedSeriesAlignmentResult
    mean_period_risk_free_return: float | None
    cumulative_risk_free_return: float | None
    mean_period_excess_return: float | None
    excess_return_sample_volatility: float | None
    period_excess_sharpe_ratio: float | None
    annualized_excess_sharpe_ratio: float | None


@dataclass(frozen=True, slots=True)
class GrossNetCostDragResult:
    alignment: PairedSeriesAlignmentResult
    mean_period_cost_drag: float | None
    cumulative_gross_return: float | None
    cumulative_net_return: float | None
    cumulative_cost_drag: float | None
    annualized_arithmetic_cost_drag: float | None
    periods_with_positive_cost_drag: int | None
    periods_with_negative_cost_drag: int | None


@dataclass(frozen=True, slots=True)
class RegimeSliceResult:
    regime: str
    observation_count: int
    mean_period_return: float
    sample_volatility: float | None
    cumulative_simple_return: float
    period_sharpe_ratio: float | None


@dataclass(frozen=True, slots=True)
class RegimeAnalysisResult:
    status: PairedSeriesStatus
    observation_count: int
    regime_count: int
    slices: tuple[RegimeSliceResult, ...]
    strategy_only_timestamps: tuple[str, ...]
    regime_only_timestamps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdvancedRiskStatisticsResult:
    status: AdvancedRiskStatus
    observation_count: int
    return_basis: ReturnConvention
    minimum_acceptable_period_return: float
    tail_confidence_level: float
    downside_observation_count: int
    downside_deviation: float
    period_sortino_ratio: float | None
    annualized_sortino_ratio: float | None
    omega_ratio: float | None
    historical_value_at_risk: float | None
    historical_expected_shortfall: float | None
    calmar_ratio: float | None
    ulcer_index: float | None


@dataclass(frozen=True, slots=True)
class ExperimentTrialAssessmentResult:
    trial_id: str
    attempt_index: int
    outcome: TrialOutcome
    included_in_selection: bool
    selected: bool
    selection_score: float | None
    return_series_supplied: bool
    observation_count: int | None
    parameters: tuple[TrialParameter, ...]
    source: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class ExperimentSplitAssessmentResult:
    split_id: str
    in_sample_observation_count: int
    out_of_sample_observation_count: int
    in_sample_timestamps: tuple[pd.Timestamp, ...]
    out_of_sample_timestamps: tuple[pd.Timestamp, ...]
    in_sample_start_timestamp: pd.Timestamp
    in_sample_end_timestamp: pd.Timestamp
    out_of_sample_start_timestamp: pd.Timestamp
    out_of_sample_end_timestamp: pd.Timestamp


@dataclass(frozen=True, slots=True)
class ExperimentFamilyAssessmentResult:
    status: ExperimentFamilyStatus
    input_schema_version: str
    family_id: str
    source: str | None

    declared_total_attempted_trials: int
    documented_trial_count: int
    documented_attempt_indices: tuple[int, ...]
    undocumented_attempt_indices: tuple[int, ...]
    completed_trial_count: int
    failed_trial_count: int
    eligible_trial_count: int
    excluded_completed_trial_count: int
    supplied_return_series_count: int

    search_complete_declared: bool
    complete_search_history: bool
    winner_only_evidence: bool
    selection_bias_methods_structurally_eligible: bool

    selected_trial_id: str
    selected_trial_attempt_index: int
    selection_rule: str
    selection_metric: str
    selection_direction: SelectionDirection

    return_basis: ReturnConvention
    observation_count: int
    start_timestamp: pd.Timestamp
    end_timestamp: pd.Timestamp
    exact_timestamp_alignment: bool
    declared_frequency: str | None
    periods_per_year: int | None
    timezone: str | None

    parameter_names: tuple[str, ...]
    parameter_count: int
    split_metadata_supplied: bool
    split_count: int

    benchmark_id: str | None
    benchmark_return_basis: ReturnConvention | None
    benchmark_observation_count: int | None


@dataclass(frozen=True, slots=True)
class TrialSharpeEstimate:
    trial_id: str
    included_in_selection: bool
    selected: bool
    observation_count: int
    period_mean_excess_return: float
    period_sample_volatility: float
    period_sharpe_ratio: float | None
    iid_annualized_sharpe_ratio: float | None


@dataclass(frozen=True, slots=True)
class TrialCorrelationSummaryResult:
    trial_count: int
    pair_count: int
    minimum_correlation: float | None
    maximum_correlation: float | None
    mean_correlation: float | None
    median_correlation: float | None
    strongest_absolute_correlation: float | None
    strongest_absolute_correlation_trial_ids: tuple[str, str] | None


@dataclass(frozen=True, slots=True)
class DeflatedSharpeScenarioResult:
    trial_count_basis: DSRTrialCountBasis
    trial_count: int
    expected_maximum_standard_normal: float
    expected_maximum_period_sharpe_ratio: float
    expected_maximum_iid_annualized_sharpe_ratio: float
    test_statistic: float
    deflated_sharpe_ratio: float
    confidence_requirement_met: bool


@dataclass(frozen=True, slots=True)
class DeflatedSharpeRatioResult:
    status: DeflatedSharpeRatioStatus
    method: DeflatedSharpeRatioMethod
    trial_count_policy: DSRTrialCountPolicy
    return_basis: ReturnConvention
    annual_risk_free_rate: float
    required_confidence_level: float
    periods_per_year: int | None
    period_risk_free_rate: float | None
    observation_count: int
    declared_attempted_trial_count: int
    completed_trial_count: int
    selection_eligible_trial_count: int
    valid_selection_trial_sharpe_count: int
    selected_trial_id: str
    trial_sharpe_estimates: tuple[TrialSharpeEstimate, ...]
    selected_period_sharpe_ratio: float | None
    selected_iid_annualized_sharpe_ratio: float | None
    observed_maximum_period_sharpe_ratio: float | None
    observed_maximum_trial_ids: tuple[str, ...]
    selected_is_observed_maximum: bool | None
    cross_trial_mean_period_sharpe_ratio: float | None
    cross_trial_sample_standard_deviation: float | None
    selected_sample_skewness: float | None
    selected_sample_pearson_kurtosis: float | None
    selected_sharpe_variance_adjustment: float | None
    selected_period_sharpe_standard_error: float | None
    correlation_summary: TrialCorrelationSummaryResult | None
    effective_independent_trial_count: int | None
    effective_trial_count_methodology: str | None
    effective_trial_count_verified: bool | None
    scenarios: tuple[DeflatedSharpeScenarioResult, ...]


@dataclass(frozen=True, slots=True)
class CSCVPartitionResult:
    partition_index: int
    observation_count: int
    start_timestamp: pd.Timestamp
    end_timestamp: pd.Timestamp


@dataclass(frozen=True, slots=True)
class CSCVSplitResult:
    combination_index: int
    status: CSCVSplitStatus
    in_sample_partition_indices: tuple[int, ...]
    out_of_sample_partition_indices: tuple[int, ...]
    selected_trial_id: str | None
    tied_in_sample_winner_trial_ids: tuple[str, ...]
    selected_in_sample_score: float | None
    selected_out_of_sample_score: float | None
    out_of_sample_rank: float | None
    relative_out_of_sample_rank: float | None
    rank_logit: float | None
    overfit_event: bool | None
    selected_out_of_sample_score_below_zero: bool | None
    unavailable_trial_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CSCVResult:
    status: CSCVStatus
    method: CSCVMethod
    performance_metric: CSCVPerformanceMetric
    declared_selection_metric: str
    confirmed_selection_metric: str
    rank_tie_method: CSCVRankTieMethod
    winner_tie_policy: CSCVWinnerTiePolicy
    return_basis: ReturnConvention
    annual_risk_free_rate: float
    periods_per_year: int | None
    period_risk_free_rate: float | None
    observation_count: int
    partition_count: int
    observations_per_partition: int | None
    total_combinations: int
    maximum_combinations: int
    declared_attempted_trial_count: int
    completed_trial_count: int
    selection_eligible_trial_count: int
    maximum_acceptable_pbo: float
    partitions: tuple[CSCVPartitionResult, ...]
    splits: tuple[CSCVSplitResult, ...]
    valid_split_count: int
    invalid_split_count: int
    probability_of_backtest_overfitting: float | None
    pbo_requirement_met: bool | None
    probability_selected_oos_score_below_zero: float | None
    mean_rank_logit: float | None
    median_rank_logit: float | None
    performance_degradation_intercept: float | None
    performance_degradation_slope: float | None
    performance_degradation_r_squared: float | None


@dataclass(frozen=True, slots=True)
class ParameterNeighborResult:
    trial_id: str
    attempt_index: int
    standardized_distance: float
    changed_parameter_names: tuple[str, ...]
    period_sharpe_ratio: float | None
    score_difference_from_selected: float | None
    within_acceptable_score_difference: bool | None


@dataclass(frozen=True, slots=True)
class ParameterAxisSensitivityResult:
    parameter_name: str
    one_axis_neighbor_count: int
    closest_lower_trial_id: str | None
    closest_lower_score_difference: float | None
    closest_upper_trial_id: str | None
    closest_upper_score_difference: float | None
    maximum_absolute_score_change_per_scaled_unit: float | None


@dataclass(frozen=True, slots=True)
class ParameterRobustnessResult:
    status: ParameterRobustnessStatus
    performance_metric: RobustnessPerformanceMetric
    declared_selection_metric: str
    confirmed_selection_metric: str
    distance_metric: ParameterDistanceMetric
    return_basis: ReturnConvention
    annual_risk_free_rate: float
    periods_per_year: int | None
    period_risk_free_rate: float | None
    selected_trial_id: str
    selected_period_sharpe_ratio: float | None
    parameter_scales: tuple[tuple[str, float], ...]
    maximum_distance: float
    minimum_neighbor_count: int
    maximum_acceptable_score_difference: float
    minimum_acceptable_neighbor_fraction: float
    selection_eligible_trial_count: int
    candidate_trial_count: int
    neighbor_count: int
    duplicate_configuration_trial_ids: tuple[str, ...]
    neighbors: tuple[ParameterNeighborResult, ...]
    unavailable_neighbor_trial_ids: tuple[str, ...]
    acceptable_neighbor_count: int | None
    acceptable_neighbor_fraction: float | None
    neighbor_fraction_requirement_met: bool | None
    selected_is_local_maximum: bool | None
    minimum_neighbor_score: float | None
    maximum_neighbor_score: float | None
    mean_neighbor_score: float | None
    maximum_degradation: float | None
    maximum_improvement: float | None
    steepest_absolute_score_change_per_distance: float | None
    axis_sensitivities: tuple[ParameterAxisSensitivityResult, ...]


@dataclass(frozen=True, slots=True)
class TemporalWindowResult:
    window_index: int
    status: RobustnessSliceStatus
    observation_count: int
    start_timestamp: pd.Timestamp
    end_timestamp: pd.Timestamp
    selected_trial_id: str
    selected_period_sharpe_ratio: float | None
    selected_rank: float | None
    selected_relative_rank: float | None
    selected_rank_logit: float | None
    selected_in_top_half: bool | None
    selected_tied_for_best: bool | None
    selected_score_below_zero: bool | None
    tied_best_trial_ids: tuple[str, ...]
    unavailable_trial_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExternalSplitConsistencyResult:
    split_id: str
    status: RobustnessSliceStatus
    in_sample_observation_count: int
    out_of_sample_observation_count: int
    in_sample_winner_trial_id: str | None
    tied_in_sample_winner_trial_ids: tuple[str, ...]
    selected_in_sample_score: float | None
    selected_out_of_sample_score: float | None
    selected_out_of_sample_rank: float | None
    selected_out_of_sample_relative_rank: float | None
    selected_out_of_sample_rank_logit: float | None
    selected_out_of_sample_in_top_half: bool | None
    selected_out_of_sample_score_below_zero: bool | None
    tied_out_of_sample_best_trial_ids: tuple[str, ...]
    in_sample_winner_retained_out_of_sample: bool | None
    unavailable_trial_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemporalRobustnessResult:
    status: TemporalRobustnessStatus
    performance_metric: RobustnessPerformanceMetric
    declared_selection_metric: str
    confirmed_selection_metric: str
    rank_tie_method: RobustnessRankTieMethod
    winner_tie_policy: RobustnessWinnerTiePolicy
    return_basis: ReturnConvention
    annual_risk_free_rate: float
    periods_per_year: int | None
    period_risk_free_rate: float | None
    observation_count: int
    window_count: int
    observations_per_window: int | None
    selected_trial_id: str
    selection_eligible_trial_count: int
    minimum_acceptable_top_half_fraction: float
    maximum_acceptable_below_zero_fraction: float
    windows: tuple[TemporalWindowResult, ...]
    valid_window_count: int
    invalid_window_count: int
    selected_score_mean: float | None
    selected_score_sample_standard_deviation: float | None
    selected_score_minimum: float | None
    selected_score_maximum: float | None
    selected_score_range: float | None
    selected_top_half_fraction: float | None
    top_half_fraction_requirement_met: bool | None
    selected_tied_best_fraction: float | None
    selected_below_zero_fraction: float | None
    below_zero_fraction_requirement_met: bool | None
    mean_rank_logit: float | None
    median_rank_logit: float | None
    distinct_window_winner_trial_ids: tuple[str, ...]
    external_splits: tuple[ExternalSplitConsistencyResult, ...]
    valid_external_split_count: int
    invalid_external_split_count: int


@dataclass(frozen=True, slots=True)
class DataSnoopingResult:
    status: DataSnoopingStatus
    observation_count: int
    selection_eligible_trial_count: int
    benchmark_id: str | None
    replications: int
    mean_block_length: int
    random_seed: int
    significance_level: float
    selected_trial_id: str
    selected_mean_active_return: float | None
    observed_maximum_mean_active_return: float | None
    observed_maximum_trial_ids: tuple[str, ...]
    white_reality_check_p_value: float | None
    white_reality_check_rejects_null: bool | None
    hansen_spa_p_value: float | None
    hansen_spa_rejects_null: bool | None


@dataclass(frozen=True, slots=True)
class SamplingAssessmentResult:
    status: FrequencyStatus
    observation_count: int
    interval_count: int

    declared_frequency: str | None
    inferred_frequency: str | None
    periods_per_year: int | None

    minimum_interval_seconds: float | None
    maximum_interval_seconds: float | None
    annualization_eligible: bool


@dataclass(frozen=True, slots=True)
class AnnualizedStatisticsResult:
    periods_per_year: int
    return_basis: ReturnConvention

    annualized_arithmetic_mean_return: float
    annualized_sample_volatility: float

    annual_risk_free_rate: float | None
    period_risk_free_rate: float | None
    annualized_sharpe_ratio: float | None


@dataclass(frozen=True, slots=True)
class DistributionStatisticsResult:
    observation_count: int
    return_basis: ReturnConvention

    sample_skewness: float | None
    sample_excess_kurtosis: float | None
    sample_pearson_kurtosis: float | None


@dataclass(frozen=True, slots=True)
class SharpeUncertaintyResult:
    observation_count: int
    periods_per_year: int

    period_sharpe_ratio: float
    annualized_sharpe_ratio: float
    sharpe_variance_adjustment: float

    period_sharpe_standard_error: float | None
    annualized_sharpe_standard_error: float | None

    benchmark_period_sharpe_ratio: float | None
    benchmark_annualized_sharpe_ratio: float | None
    probabilistic_sharpe_ratio: float | None


@dataclass(frozen=True, slots=True)
class TrackRecordLengthResult:
    observation_count: int
    periods_per_year: int

    required_psr_confidence_level: float
    observed_probabilistic_sharpe_ratio: float
    confidence_requirement_met: bool

    normal_critical_value: float
    observed_period_sharpe_difference: float

    minimum_track_record_length_observations: float | None
    minimum_required_observations: int | None
    minimum_track_record_length_years: float | None

    additional_observations_required: int | None
    observations_above_minimum: int | None


@dataclass(frozen=True, slots=True)
class AutocorrelationEstimate:
    lag: int
    autocorrelation: float


@dataclass(frozen=True, slots=True)
class SerialDependenceResult:
    status: SerialDependenceStatus
    observation_count: int
    return_basis: ReturnConvention
    maximum_lag: int
    significance_level: float
    autocorrelations: tuple[AutocorrelationEstimate, ...]

    strongest_absolute_autocorrelation_lag: int | None
    strongest_absolute_autocorrelation: float | None

    ljung_box_statistic: float | None
    degrees_of_freedom: int | None
    p_value: float | None
    serial_dependence_detected: bool | None

    partial_autocorrelations: tuple[AutocorrelationEstimate, ...]
    acf_confidence_bound: float | None
    mean_long_run_variance_ratio: float | None
    mean_effective_observation_count: float | None
    runs_observation_count: int | None
    runs_count: int | None
    runs_expected_count: float | None
    runs_z_statistic: float | None
    runs_p_value: float | None
    runs_dependence_detected: bool | None
    variance_ratios: tuple["VarianceRatioResult", ...]


@dataclass(frozen=True, slots=True)
class VarianceRatioResult:
    horizon: int
    variance_ratio: float
    heteroskedastic_robust_standard_error: float | None
    z_statistic: float | None
    p_value: float | None
    dependence_detected: bool | None


@dataclass(frozen=True, slots=True)
class HACAutocorrelationEstimate:
    lag: int
    autocorrelation: float
    kernel_weight: float
    weighted_contribution: float


@dataclass(frozen=True, slots=True)
class SerialAdjustmentResult:
    status: SerialAdjustmentStatus
    observation_count: int
    return_basis: ReturnConvention
    maximum_lag: int
    kernel: HACKernel
    periods_per_year: int | None

    return_autocorrelations: tuple[HACAutocorrelationEstimate, ...]
    return_long_run_variance_ratio: float | None
    iid_annualization_factor: float | None
    hac_annualization_factor: float | None
    full_lo_annual_horizon: bool | None
    iid_annualized_sharpe_ratio: float | None
    hac_adjusted_annualized_sharpe_ratio: float | None

    influence_autocorrelations: tuple[HACAutocorrelationEstimate, ...]
    sharpe_long_run_variance_ratio: float | None
    iid_sharpe_variance_adjustment: float | None
    hac_sharpe_variance_adjustment: float | None
    iid_period_sharpe_standard_error: float | None
    hac_period_sharpe_standard_error: float | None
    effective_observation_count: float | None

    benchmark_period_sharpe_ratio: float | None
    iid_probabilistic_sharpe_ratio: float | None
    hac_probabilistic_sharpe_ratio: float | None
    required_psr_confidence_level: float | None
    hac_confidence_requirement_met: bool | None

    hac_minimum_track_record_length_observations: float | None
    hac_minimum_required_observations: int | None
    hac_minimum_track_record_length_years: float | None
    hac_additional_observations_required: int | None
    hac_observations_above_minimum: int | None


@dataclass(frozen=True, slots=True)
class BootstrapMetricResult:
    metric: BootstrapMetric
    status: BootstrapMetricStatus
    point_estimate: float | None
    lower_bound: float | None
    upper_bound: float | None
    bootstrap_standard_error: float | None
    attempted_replications: int
    successful_replications: int


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    status: BootstrapStatus
    observation_count: int
    return_basis: ReturnConvention
    method: BootstrapMethod
    interval_method: BootstrapIntervalMethod
    replications: int
    confidence_level: float
    lower_quantile: float
    upper_quantile: float
    block_length: int
    random_seed: int
    overlapping_block_count: int | None
    blocks_per_replication: int | None
    periods_per_year: int | None
    hac_maximum_lag: int | None
    hac_kernel: HACKernel | None
    metrics: tuple[BootstrapMetricResult, ...]


@dataclass(frozen=True, slots=True)
class DescriptiveStatisticsResult:
    observation_count: int
    start_timestamp: pd.Timestamp
    end_timestamp: pd.Timestamp

    mean_return: float | None
    sample_volatility: float | None

    minimum_return: float
    maximum_return: float

    cumulative_simple_return: float | None

    return_convention: ReturnConvention
