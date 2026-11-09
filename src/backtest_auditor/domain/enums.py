from enum import StrEnum


class ReturnConvention(StrEnum):
    SIMPLE = "simple"
    LOG = "log"


class ObservationCalendarStatus(StrEnum):
    VERIFIED = "verified"
    DECLARED_UNVERIFIED = "declared_unverified"
    MISMATCH = "mismatch"
    INTRADAY_UNSUPPORTED = "intraday_unsupported"


class ObservationCalendarSource(StrEnum):
    BUILT_IN_24_7 = "built_in_24_7"
    BUILT_IN_WEEKDAYS = "built_in_weekdays"
    SESSION_FILE = "session_file"
    DECLARATION_ONLY = "declaration_only"


class LeveragePolicy(StrEnum):
    UNLEVERED = "unlevered"
    FIXED = "fixed"
    DYNAMIC = "dynamic"


class PriceAdjustmentPolicy(StrEnum):
    ADJUSTED = "adjusted"
    UNADJUSTED = "unadjusted"
    NOT_APPLICABLE = "not_applicable"


class ReturnCostBasis(StrEnum):
    GROSS = "gross"
    NET_OF_TRANSACTION_COSTS = "net_of_transaction_costs"
    NET_OF_ALL_DECLARED_COSTS = "net_of_all_declared_costs"
    MIXED = "mixed"
    PARTIALLY_DECLARED = "partially_declared"
    UNDECLARED = "undeclared"


class SeriesRole(StrEnum):
    STRATEGY = "strategy"
    BENCHMARK = "benchmark"
    GROSS_STRATEGY = "gross_strategy"
    RISK_FREE = "risk_free"


class BenchmarkAlignmentStatus(StrEnum):
    ELIGIBLE = "eligible"
    TIMESTAMP_MISMATCH = "timestamp_mismatch"


class AdvancedRiskStatus(StrEnum):
    ELIGIBLE = "eligible"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    DOWNSIDE_DEVIATION_ZERO = "downside_deviation_zero"


class PairedSeriesStatus(StrEnum):
    ELIGIBLE = "eligible"
    TIMESTAMP_MISMATCH = "timestamp_mismatch"


class BenchmarkInferenceStatus(StrEnum):
    ELIGIBLE = "eligible"
    BENCHMARK_UNAVAILABLE = "benchmark_unavailable"
    TIMESTAMP_MISMATCH = "timestamp_mismatch"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    SINGULAR_DESIGN = "singular_design"
    NON_POSITIVE_VARIANCE = "non_positive_variance"


class DataSnoopingStatus(StrEnum):
    ELIGIBLE = "eligible"
    FAMILY_INELIGIBLE = "family_ineligible"
    BENCHMARK_UNAVAILABLE = "benchmark_unavailable"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    NO_VALID_TRIALS = "no_valid_trials"


class TrialOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class SelectionDirection(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    CUSTOM = "custom"


class SplitRole(StrEnum):
    IN_SAMPLE = "in_sample"
    OUT_OF_SAMPLE = "out_of_sample"


class ExperimentFamilyStatus(StrEnum):
    ELIGIBLE = "eligible"
    INCOMPLETE_SEARCH_HISTORY = "incomplete_search_history"
    INSUFFICIENT_ELIGIBLE_TRIALS = "insufficient_eligible_trials"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"


class DeflatedSharpeRatioMethod(StrEnum):
    CLASSIC_EXPECTED_MAXIMUM = "classic_expected_maximum"


class DSRTrialCountPolicy(StrEnum):
    SELECTION_ELIGIBLE = "selection_eligible"


class DSRTrialCountBasis(StrEnum):
    SELECTION_ELIGIBLE = "selection_eligible"
    DECLARED_ATTEMPTS = "declared_attempts"
    USER_SUPPLIED_EFFECTIVE = "user_supplied_effective"


class DeflatedSharpeRatioStatus(StrEnum):
    ELIGIBLE = "eligible"
    FAMILY_INELIGIBLE = "family_ineligible"
    PERIODS_PER_YEAR_UNAVAILABLE = "periods_per_year_unavailable"
    INCOMPLETE_TRIAL_SHARPE_DISTRIBUTION = "incomplete_trial_sharpe_distribution"
    SELECTED_TRIAL_NOT_MAXIMUM_SHARPE = "selected_trial_not_maximum_sharpe"
    SELECTED_RETURN_MOMENTS_UNAVAILABLE = "selected_return_moments_unavailable"
    NON_POSITIVE_SHARPE_VARIANCE_ADJUSTMENT = "non_positive_sharpe_variance_adjustment"
    INVALID_EFFECTIVE_TRIAL_COUNT = "invalid_effective_trial_count"


class CSCVMethod(StrEnum):
    COMBINATORIALLY_SYMMETRIC = "combinatorially_symmetric"


class CSCVPerformanceMetric(StrEnum):
    PERIOD_SHARPE_RATIO = "period_sharpe_ratio"


class CSCVRankTieMethod(StrEnum):
    AVERAGE = "average"


class CSCVWinnerTiePolicy(StrEnum):
    FIRST_BY_ATTEMPT_INDEX = "first_by_attempt_index"


class CSCVStatus(StrEnum):
    ELIGIBLE = "eligible"
    FAMILY_INELIGIBLE = "family_ineligible"
    SELECTION_RULE_INCOMPATIBLE = "selection_rule_incompatible"
    PERIODS_PER_YEAR_UNAVAILABLE = "periods_per_year_unavailable"
    OBSERVATIONS_NOT_DIVISIBLE_BY_PARTITIONS = (
        "observations_not_divisible_by_partitions"
    )
    INSUFFICIENT_HALF_SAMPLE_OBSERVATIONS = "insufficient_half_sample_observations"
    COMBINATION_LIMIT_EXCEEDED = "combination_limit_exceeded"
    INCOMPLETE_SPLIT_METRICS = "incomplete_split_metrics"


class CSCVSplitStatus(StrEnum):
    ELIGIBLE = "eligible"
    PERFORMANCE_METRIC_UNAVAILABLE = "performance_metric_unavailable"


class RobustnessPerformanceMetric(StrEnum):
    PERIOD_SHARPE_RATIO = "period_sharpe_ratio"


class ParameterDistanceMetric(StrEnum):
    STANDARDIZED_EUCLIDEAN = "standardized_euclidean"


class RobustnessRankTieMethod(StrEnum):
    AVERAGE = "average"


class RobustnessWinnerTiePolicy(StrEnum):
    FIRST_BY_ATTEMPT_INDEX = "first_by_attempt_index"


class ParameterRobustnessStatus(StrEnum):
    ELIGIBLE = "eligible"
    FAMILY_INELIGIBLE = "family_ineligible"
    SELECTION_RULE_INCOMPATIBLE = "selection_rule_incompatible"
    PERIODS_PER_YEAR_UNAVAILABLE = "periods_per_year_unavailable"
    PARAMETER_SCHEMA_INCOMPATIBLE = "parameter_schema_incompatible"
    SELECTED_SCORE_UNAVAILABLE = "selected_score_unavailable"
    INSUFFICIENT_NEIGHBORS = "insufficient_neighbors"
    INCOMPLETE_NEIGHBOR_METRICS = "incomplete_neighbor_metrics"


class TemporalRobustnessStatus(StrEnum):
    ELIGIBLE = "eligible"
    FAMILY_INELIGIBLE = "family_ineligible"
    SELECTION_RULE_INCOMPATIBLE = "selection_rule_incompatible"
    PERIODS_PER_YEAR_UNAVAILABLE = "periods_per_year_unavailable"
    OBSERVATIONS_NOT_DIVISIBLE_BY_WINDOWS = "observations_not_divisible_by_windows"
    INSUFFICIENT_WINDOW_OBSERVATIONS = "insufficient_window_observations"
    INCOMPLETE_WINDOW_METRICS = "incomplete_window_metrics"


class RobustnessSliceStatus(StrEnum):
    ELIGIBLE = "eligible"
    PERFORMANCE_METRIC_UNAVAILABLE = "performance_metric_unavailable"


class FrequencyStatus(StrEnum):
    DECLARED = "declared"
    INFERRED_REGULAR = "inferred_regular"
    CALENDAR_VERIFIED = "calendar_verified"
    IRREGULAR = "irregular"
    AMBIGUOUS = "ambiguous"
    DECLARED_CONFLICT = "declared_conflict"


class SerialDependenceStatus(StrEnum):
    ELIGIBLE = "eligible"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    ZERO_VARIANCE = "zero_variance"


class HACKernel(StrEnum):
    BARTLETT = "bartlett"


class SerialAdjustmentStatus(StrEnum):
    ELIGIBLE = "eligible"
    SHARPE_UNAVAILABLE = "sharpe_unavailable"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    NON_POSITIVE_RETURN_LONG_RUN_VARIANCE = "non_positive_return_long_run_variance"
    SHARPE_UNCERTAINTY_UNAVAILABLE = "sharpe_uncertainty_unavailable"
    ZERO_INFLUENCE_VARIANCE = "zero_influence_variance"
    NON_POSITIVE_SHARPE_LONG_RUN_VARIANCE = "non_positive_sharpe_long_run_variance"


class BootstrapMethod(StrEnum):
    MOVING_BLOCK = "moving_block"
    STATIONARY = "stationary"


class BootstrapIntervalMethod(StrEnum):
    PERCENTILE = "percentile"


class BootstrapStatus(StrEnum):
    ELIGIBLE = "eligible"
    SAMPLING_INELIGIBLE = "sampling_ineligible"
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    BLOCK_LENGTH_NOT_BELOW_OBSERVATION_COUNT = (
        "block_length_not_below_observation_count"
    )


class BootstrapMetric(StrEnum):
    PERIOD_MEAN_RETURN = "period_mean_return"
    PERIOD_SAMPLE_VOLATILITY = "period_sample_volatility"
    FIXED_HORIZON_CUMULATIVE_SIMPLE_RETURN = "fixed_horizon_cumulative_simple_return"
    ANNUALIZED_ARITHMETIC_MEAN_RETURN = "annualized_arithmetic_mean_return"
    IID_ANNUALIZED_SAMPLE_VOLATILITY = "iid_annualized_sample_volatility"
    PERIOD_SHARPE_RATIO = "period_sharpe_ratio"
    IID_ANNUALIZED_SHARPE_RATIO = "iid_annualized_sharpe_ratio"
    HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO = "hac_adjusted_annualized_sharpe_ratio"


class BootstrapMetricStatus(StrEnum):
    ELIGIBLE = "eligible"
    POINT_ESTIMATE_UNAVAILABLE = "point_estimate_unavailable"
    INSUFFICIENT_VALID_REPLICATIONS = "insufficient_valid_replications"


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
