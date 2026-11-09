import math
from dataclasses import dataclass

from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    CSCVMethod,
    CSCVPerformanceMetric,
    CSCVRankTieMethod,
    CSCVWinnerTiePolicy,
    DeflatedSharpeRatioMethod,
    DSRTrialCountPolicy,
    HACKernel,
    ParameterDistanceMetric,
    RobustnessPerformanceMetric,
    RobustnessRankTieMethod,
    RobustnessWinnerTiePolicy,
)


#: Upper bound on CSCV partitions. The published total_combinations is
#: C(S, S/2), and CPython refuses to render an integer wider than 4300 digits,
#: so an unbounded S turned a typed ineligibility into an uncaught ValueError
#: during report serialisation. C(1024, 512) already has 306 digits and
#: astronomically exceeds any usable maximum_combinations, so the bound
#: rejects only inputs that could never produce a report.
MAXIMUM_CSCV_PARTITION_COUNT = 1024


@dataclass(frozen=True, slots=True)
class SharpeRatioSpec:
    """Explicit assumptions required for a basic Sharpe ratio."""

    annual_risk_free_rate: float

    def __post_init__(self) -> None:
        annual_risk_free_rate = float(self.annual_risk_free_rate)

        if not math.isfinite(annual_risk_free_rate):
            raise ValueError("annual_risk_free_rate must be finite.")

        if annual_risk_free_rate <= -1.0:
            raise ValueError("annual_risk_free_rate must be greater than -1.0.")

        object.__setattr__(
            self,
            "annual_risk_free_rate",
            annual_risk_free_rate,
        )


@dataclass(frozen=True, slots=True)
class ProbabilisticSharpeRatioSpec:
    """Explicit benchmark and optional evidence requirement for PSR."""

    benchmark_annualized_sharpe_ratio: float
    required_psr_confidence_level: float | None = None

    def __post_init__(self) -> None:
        benchmark = float(self.benchmark_annualized_sharpe_ratio)

        if not math.isfinite(benchmark):
            raise ValueError("benchmark_annualized_sharpe_ratio must be finite.")

        object.__setattr__(
            self,
            "benchmark_annualized_sharpe_ratio",
            benchmark,
        )

        confidence_level = self.required_psr_confidence_level
        if confidence_level is None:
            return

        confidence_level = float(confidence_level)
        if (
            not math.isfinite(confidence_level)
            or confidence_level <= 0.5
            or confidence_level >= 1.0
        ):
            raise ValueError(
                "required_psr_confidence_level must be finite and "
                "strictly between 0.5 and 1.0."
            )

        object.__setattr__(
            self,
            "required_psr_confidence_level",
            confidence_level,
        )


@dataclass(frozen=True, slots=True)
class SerialDependenceSpec:
    """Explicit choices for the serial-dependence diagnostic."""

    maximum_lag: int
    significance_level: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_lag, bool)
            or not isinstance(self.maximum_lag, int)
            or self.maximum_lag <= 0
        ):
            raise ValueError("maximum_lag must be a positive integer.")

        significance_level = float(self.significance_level)
        if (
            not math.isfinite(significance_level)
            or significance_level <= 0.0
            or significance_level >= 1.0
        ):
            raise ValueError(
                "significance_level must be finite and strictly between 0.0 and 1.0."
            )

        object.__setattr__(
            self,
            "significance_level",
            significance_level,
        )


@dataclass(frozen=True, slots=True)
class AdvancedRiskSpec:
    """Explicit target and tail probability for downside/tail statistics."""

    minimum_acceptable_period_return: float
    tail_confidence_level: float

    def __post_init__(self) -> None:
        target = float(self.minimum_acceptable_period_return)
        confidence = float(self.tail_confidence_level)
        if not math.isfinite(target):
            raise ValueError("minimum_acceptable_period_return must be finite.")
        if not math.isfinite(confidence) or confidence <= 0.5 or confidence >= 1.0:
            raise ValueError(
                "tail_confidence_level must be finite and strictly between 0.5 and 1.0."
            )
        object.__setattr__(self, "minimum_acceptable_period_return", target)
        object.__setattr__(self, "tail_confidence_level", confidence)


@dataclass(frozen=True, slots=True)
class BenchmarkInferenceSpec:
    """Explicit Bartlett-HAC bandwidth and confidence for CAPM alpha inference."""

    maximum_lag: int
    confidence_level: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_lag, bool)
            or not isinstance(self.maximum_lag, int)
            or self.maximum_lag < 0
        ):
            raise ValueError("maximum_lag must be a non-negative integer.")
        confidence = float(self.confidence_level)
        if not math.isfinite(confidence) or confidence <= 0.5 or confidence >= 1.0:
            raise ValueError(
                "confidence_level must be finite and strictly between 0.5 and 1.0."
            )
        object.__setattr__(self, "confidence_level", confidence)


@dataclass(frozen=True, slots=True)
class DataSnoopingSpec:
    """Stationary-bootstrap configuration for White RC and Hansen SPA."""

    replications: int
    mean_block_length: int
    random_seed: int
    significance_level: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.replications, bool)
            or not isinstance(self.replications, int)
            or self.replications < 2
        ):
            raise ValueError("replications must be an integer of at least 2.")
        if (
            isinstance(self.mean_block_length, bool)
            or not isinstance(self.mean_block_length, int)
            or self.mean_block_length <= 0
        ):
            raise ValueError("mean_block_length must be a positive integer.")
        if (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or self.random_seed < 0
        ):
            raise ValueError("random_seed must be a non-negative integer.")
        significance = float(self.significance_level)
        if (
            not math.isfinite(significance)
            or significance <= 0.0
            or significance >= 0.5
        ):
            raise ValueError(
                "significance_level must be finite and strictly between 0.0 and 0.5."
            )
        object.__setattr__(self, "significance_level", significance)


@dataclass(frozen=True, slots=True)
class SerialAdjustmentSpec:
    """Explicit bandwidth and kernel for the HAC adjustment."""

    maximum_lag: int
    kernel: HACKernel

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_lag, bool)
            or not isinstance(self.maximum_lag, int)
            or self.maximum_lag <= 0
        ):
            raise ValueError("maximum_lag must be a positive integer.")

        try:
            kernel = HACKernel(self.kernel)
        except ValueError as error:
            supported = ", ".join(item.value for item in HACKernel)
            raise ValueError(f"kernel must be one of: {supported}.") from error

        object.__setattr__(self, "kernel", kernel)


@dataclass(frozen=True, slots=True)
class BootstrapSpec:
    """Explicit resampling and interval choices for bootstrap evidence."""

    method: BootstrapMethod
    interval_method: BootstrapIntervalMethod
    replications: int
    confidence_level: float
    block_length: int
    random_seed: int

    def __post_init__(self) -> None:
        try:
            method = BootstrapMethod(self.method)
        except ValueError as error:
            supported = ", ".join(item.value for item in BootstrapMethod)
            raise ValueError(f"method must be one of: {supported}.") from error

        try:
            interval_method = BootstrapIntervalMethod(self.interval_method)
        except ValueError as error:
            supported = ", ".join(item.value for item in BootstrapIntervalMethod)
            raise ValueError(f"interval_method must be one of: {supported}.") from error

        if (
            isinstance(self.replications, bool)
            or not isinstance(self.replications, int)
            or self.replications < 2
        ):
            raise ValueError(
                "replications must be an integer greater than or equal to 2."
            )

        confidence_level = float(self.confidence_level)
        if (
            not math.isfinite(confidence_level)
            or confidence_level <= 0.5
            or confidence_level >= 1.0
        ):
            raise ValueError(
                "confidence_level must be finite and strictly between 0.5 and 1.0."
            )

        if (
            isinstance(self.block_length, bool)
            or not isinstance(self.block_length, int)
            or self.block_length <= 0
        ):
            raise ValueError("block_length must be a positive integer.")

        if (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or self.random_seed < 0
        ):
            raise ValueError("random_seed must be a non-negative integer.")

        object.__setattr__(self, "method", method)
        object.__setattr__(
            self,
            "interval_method",
            interval_method,
        )
        object.__setattr__(
            self,
            "confidence_level",
            confidence_level,
        )


@dataclass(frozen=True, slots=True)
class DeflatedSharpeRatioSpec:
    """Explicit choices for classical family-level DSR evidence."""

    method: DeflatedSharpeRatioMethod
    trial_count_policy: DSRTrialCountPolicy
    annual_risk_free_rate: float
    required_confidence_level: float
    effective_independent_trial_count: int | None = None
    effective_trial_count_methodology: str | None = None

    def __post_init__(self) -> None:
        try:
            method = DeflatedSharpeRatioMethod(self.method)
        except ValueError as error:
            supported = ", ".join(item.value for item in DeflatedSharpeRatioMethod)
            raise ValueError(f"method must be one of: {supported}.") from error
        try:
            trial_count_policy = DSRTrialCountPolicy(self.trial_count_policy)
        except ValueError as error:
            supported = ", ".join(item.value for item in DSRTrialCountPolicy)
            raise ValueError(
                f"trial_count_policy must be one of: {supported}."
            ) from error

        annual_risk_free_rate = float(self.annual_risk_free_rate)
        if not math.isfinite(annual_risk_free_rate):
            raise ValueError("annual_risk_free_rate must be finite.")
        if annual_risk_free_rate <= -1.0:
            raise ValueError("annual_risk_free_rate must be greater than -1.0.")

        confidence_level = float(self.required_confidence_level)
        if (
            not math.isfinite(confidence_level)
            or confidence_level <= 0.5
            or confidence_level >= 1.0
        ):
            raise ValueError(
                "required_confidence_level must be finite and strictly "
                "between 0.5 and 1.0."
            )

        effective_count = self.effective_independent_trial_count
        methodology = self.effective_trial_count_methodology
        if (effective_count is None) != (methodology is None):
            raise ValueError(
                "effective_independent_trial_count and "
                "effective_trial_count_methodology must be supplied "
                "together."
            )
        if effective_count is not None:
            if (
                isinstance(effective_count, bool)
                or not isinstance(effective_count, int)
                or effective_count <= 0
            ):
                raise ValueError(
                    "effective_independent_trial_count must be a positive integer."
                )
            assert methodology is not None
            methodology = methodology.strip()
            if not methodology:
                raise ValueError("effective_trial_count_methodology must not be empty.")

        object.__setattr__(self, "method", method)
        object.__setattr__(
            self,
            "trial_count_policy",
            trial_count_policy,
        )
        object.__setattr__(
            self,
            "annual_risk_free_rate",
            annual_risk_free_rate,
        )
        object.__setattr__(
            self,
            "required_confidence_level",
            confidence_level,
        )
        object.__setattr__(
            self,
            "effective_trial_count_methodology",
            methodology,
        )


@dataclass(frozen=True, slots=True)
class CSCVSpec:
    """Explicit choices for CSCV and Probability of Backtest Overfitting."""

    method: CSCVMethod
    performance_metric: CSCVPerformanceMetric
    selection_metric_name: str
    partition_count: int
    annual_risk_free_rate: float
    maximum_combinations: int
    rank_tie_method: CSCVRankTieMethod
    winner_tie_policy: CSCVWinnerTiePolicy
    maximum_acceptable_pbo: float

    def __post_init__(self) -> None:
        try:
            method = CSCVMethod(self.method)
        except ValueError as error:
            supported = ", ".join(item.value for item in CSCVMethod)
            raise ValueError(f"method must be one of: {supported}.") from error
        try:
            performance_metric = CSCVPerformanceMetric(self.performance_metric)
        except ValueError as error:
            supported = ", ".join(item.value for item in CSCVPerformanceMetric)
            raise ValueError(
                f"performance_metric must be one of: {supported}."
            ) from error
        try:
            rank_tie_method = CSCVRankTieMethod(self.rank_tie_method)
        except ValueError as error:
            supported = ", ".join(item.value for item in CSCVRankTieMethod)
            raise ValueError(f"rank_tie_method must be one of: {supported}.") from error
        try:
            winner_tie_policy = CSCVWinnerTiePolicy(self.winner_tie_policy)
        except ValueError as error:
            supported = ", ".join(item.value for item in CSCVWinnerTiePolicy)
            raise ValueError(
                f"winner_tie_policy must be one of: {supported}."
            ) from error

        if not isinstance(self.selection_metric_name, str):
            raise ValueError("selection_metric_name must be a string.")
        selection_metric_name = self.selection_metric_name.strip()
        if not selection_metric_name:
            raise ValueError("selection_metric_name must not be empty.")

        if (
            isinstance(self.partition_count, bool)
            or not isinstance(self.partition_count, int)
            or self.partition_count < 2
            or self.partition_count % 2 != 0
            or self.partition_count > MAXIMUM_CSCV_PARTITION_COUNT
        ):
            raise ValueError(
                "partition_count must be an even integer between 2 and "
                f"{MAXIMUM_CSCV_PARTITION_COUNT}."
            )

        annual_risk_free_rate = float(self.annual_risk_free_rate)
        if not math.isfinite(annual_risk_free_rate):
            raise ValueError("annual_risk_free_rate must be finite.")
        if annual_risk_free_rate <= -1.0:
            raise ValueError("annual_risk_free_rate must be greater than -1.0.")

        if (
            isinstance(self.maximum_combinations, bool)
            or not isinstance(self.maximum_combinations, int)
            or self.maximum_combinations <= 0
        ):
            raise ValueError("maximum_combinations must be a positive integer.")

        maximum_acceptable_pbo = float(self.maximum_acceptable_pbo)
        if (
            not math.isfinite(maximum_acceptable_pbo)
            or maximum_acceptable_pbo <= 0.0
            or maximum_acceptable_pbo >= 1.0
        ):
            raise ValueError(
                "maximum_acceptable_pbo must be finite and strictly between "
                "0.0 and 1.0."
            )

        object.__setattr__(self, "method", method)
        object.__setattr__(self, "performance_metric", performance_metric)
        object.__setattr__(self, "selection_metric_name", selection_metric_name)
        object.__setattr__(
            self,
            "annual_risk_free_rate",
            annual_risk_free_rate,
        )
        object.__setattr__(self, "rank_tie_method", rank_tie_method)
        object.__setattr__(self, "winner_tie_policy", winner_tie_policy)
        object.__setattr__(
            self,
            "maximum_acceptable_pbo",
            maximum_acceptable_pbo,
        )


@dataclass(frozen=True, slots=True)
class ParameterScale:
    """One explicit unit scale used by the local parameter distance."""

    name: str
    scale: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ValueError("parameter scale name must be a string.")
        name = self.name.strip()
        if not name:
            raise ValueError("parameter scale name must not be empty.")
        scale = float(self.scale)
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError("parameter scale must be finite and greater than 0.0.")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "scale", scale)


@dataclass(frozen=True, slots=True)
class ParameterRobustnessSpec:
    """Explicit definition of a selected trial's local parameter neighborhood."""

    performance_metric: RobustnessPerformanceMetric
    selection_metric_name: str
    annual_risk_free_rate: float
    distance_metric: ParameterDistanceMetric
    parameter_scales: tuple[ParameterScale, ...]
    maximum_distance: float
    minimum_neighbor_count: int
    maximum_acceptable_score_difference: float
    minimum_acceptable_neighbor_fraction: float

    def __post_init__(self) -> None:
        try:
            performance_metric = RobustnessPerformanceMetric(self.performance_metric)
        except ValueError as error:
            supported = ", ".join(item.value for item in RobustnessPerformanceMetric)
            raise ValueError(
                f"performance_metric must be one of: {supported}."
            ) from error
        try:
            distance_metric = ParameterDistanceMetric(self.distance_metric)
        except ValueError as error:
            supported = ", ".join(item.value for item in ParameterDistanceMetric)
            raise ValueError(f"distance_metric must be one of: {supported}.") from error
        selection_metric_name = _required_text(
            self.selection_metric_name,
            "selection_metric_name",
        )
        annual_risk_free_rate = _annual_risk_free_rate(self.annual_risk_free_rate)
        parameter_scales = tuple(self.parameter_scales)
        if not parameter_scales:
            raise ValueError("parameter_scales must not be empty.")
        names = tuple(item.name for item in parameter_scales)
        if len(set(names)) != len(names):
            raise ValueError("parameter scale names must be unique.")
        if tuple(sorted(names)) != names:
            raise ValueError("parameter scales must be ordered by parameter name.")
        maximum_distance = _positive_finite(
            self.maximum_distance,
            "maximum_distance",
        )
        if (
            isinstance(self.minimum_neighbor_count, bool)
            or not isinstance(self.minimum_neighbor_count, int)
            or self.minimum_neighbor_count <= 0
        ):
            raise ValueError("minimum_neighbor_count must be a positive integer.")
        maximum_difference = float(self.maximum_acceptable_score_difference)
        if not math.isfinite(maximum_difference) or maximum_difference < 0.0:
            raise ValueError(
                "maximum_acceptable_score_difference must be finite and "
                "greater than or equal to 0.0."
            )
        minimum_fraction = _unit_interval(
            self.minimum_acceptable_neighbor_fraction,
            "minimum_acceptable_neighbor_fraction",
        )
        object.__setattr__(self, "performance_metric", performance_metric)
        object.__setattr__(self, "selection_metric_name", selection_metric_name)
        object.__setattr__(self, "annual_risk_free_rate", annual_risk_free_rate)
        object.__setattr__(self, "distance_metric", distance_metric)
        object.__setattr__(self, "parameter_scales", parameter_scales)
        object.__setattr__(self, "maximum_distance", maximum_distance)
        object.__setattr__(
            self,
            "maximum_acceptable_score_difference",
            maximum_difference,
        )
        object.__setattr__(
            self,
            "minimum_acceptable_neighbor_fraction",
            minimum_fraction,
        )


@dataclass(frozen=True, slots=True)
class TemporalRobustnessSpec:
    """Explicit equal-window and declared-split consistency choices."""

    performance_metric: RobustnessPerformanceMetric
    selection_metric_name: str
    annual_risk_free_rate: float
    window_count: int
    rank_tie_method: RobustnessRankTieMethod
    winner_tie_policy: RobustnessWinnerTiePolicy
    minimum_acceptable_top_half_fraction: float
    maximum_acceptable_below_zero_fraction: float

    def __post_init__(self) -> None:
        try:
            performance_metric = RobustnessPerformanceMetric(self.performance_metric)
        except ValueError as error:
            supported = ", ".join(item.value for item in RobustnessPerformanceMetric)
            raise ValueError(
                f"performance_metric must be one of: {supported}."
            ) from error
        try:
            rank_tie_method = RobustnessRankTieMethod(self.rank_tie_method)
        except ValueError as error:
            supported = ", ".join(item.value for item in RobustnessRankTieMethod)
            raise ValueError(f"rank_tie_method must be one of: {supported}.") from error
        try:
            winner_tie_policy = RobustnessWinnerTiePolicy(self.winner_tie_policy)
        except ValueError as error:
            supported = ", ".join(item.value for item in RobustnessWinnerTiePolicy)
            raise ValueError(
                f"winner_tie_policy must be one of: {supported}."
            ) from error
        selection_metric_name = _required_text(
            self.selection_metric_name,
            "selection_metric_name",
        )
        annual_risk_free_rate = _annual_risk_free_rate(self.annual_risk_free_rate)
        if (
            isinstance(self.window_count, bool)
            or not isinstance(self.window_count, int)
            or self.window_count < 2
        ):
            raise ValueError("window_count must be an integer of at least 2.")
        minimum_top_half = _unit_interval(
            self.minimum_acceptable_top_half_fraction,
            "minimum_acceptable_top_half_fraction",
        )
        maximum_below_zero = _unit_interval(
            self.maximum_acceptable_below_zero_fraction,
            "maximum_acceptable_below_zero_fraction",
        )
        object.__setattr__(self, "performance_metric", performance_metric)
        object.__setattr__(self, "selection_metric_name", selection_metric_name)
        object.__setattr__(self, "annual_risk_free_rate", annual_risk_free_rate)
        object.__setattr__(self, "rank_tie_method", rank_tie_method)
        object.__setattr__(self, "winner_tie_policy", winner_tie_policy)
        object.__setattr__(
            self,
            "minimum_acceptable_top_half_fraction",
            minimum_top_half,
        )
        object.__setattr__(
            self,
            "maximum_acceptable_below_zero_fraction",
            maximum_below_zero,
        )


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _annual_risk_free_rate(value: float) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= -1.0:
        raise ValueError("annual_risk_free_rate must be finite and greater than -1.0.")
    return parsed


def _positive_finite(value: float, field_name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{field_name} must be finite and greater than 0.0.")
    return parsed


def _unit_interval(value: float, field_name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{field_name} must be finite and between 0.0 and 1.0.")
    return parsed
