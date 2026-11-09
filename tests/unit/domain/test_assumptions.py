import math

import pytest

from backtest_auditor.domain.assumptions import (
    AdvancedRiskSpec,
    BenchmarkInferenceSpec,
    BootstrapSpec,
    CSCVSpec,
    DataSnoopingSpec,
    DeflatedSharpeRatioSpec,
    ParameterRobustnessSpec,
    ParameterScale,
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
    SharpeRatioSpec,
    TemporalRobustnessSpec,
)
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


def _dsr_spec(**overrides: object) -> DeflatedSharpeRatioSpec:
    values = {
        "method": DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        "trial_count_policy": DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        "annual_risk_free_rate": 0.0,
        "required_confidence_level": 0.95,
    }
    values.update(overrides)
    return DeflatedSharpeRatioSpec(**values)


def _cscv_spec(**overrides: object) -> CSCVSpec:
    values = {
        "method": CSCVMethod.COMBINATORIALLY_SYMMETRIC,
        "performance_metric": CSCVPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "partition_count": 4,
        "annual_risk_free_rate": 0.0,
        "maximum_combinations": 100,
        "rank_tie_method": CSCVRankTieMethod.AVERAGE,
        "winner_tie_policy": CSCVWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        "maximum_acceptable_pbo": 0.5,
    }
    values.update(overrides)
    return CSCVSpec(**values)


def _parameter_spec(**overrides: object) -> ParameterRobustnessSpec:
    values = {
        "performance_metric": RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "annual_risk_free_rate": 0.0,
        "distance_metric": ParameterDistanceMetric.STANDARDIZED_EUCLIDEAN,
        "parameter_scales": (ParameterScale("lookback", 5.0),),
        "maximum_distance": 1.0,
        "minimum_neighbor_count": 2,
        "maximum_acceptable_score_difference": 0.1,
        "minimum_acceptable_neighbor_fraction": 0.5,
    }
    values.update(overrides)
    return ParameterRobustnessSpec(**values)


def _temporal_spec(**overrides: object) -> TemporalRobustnessSpec:
    values = {
        "performance_metric": RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "annual_risk_free_rate": 0.0,
        "window_count": 2,
        "rank_tie_method": RobustnessRankTieMethod.AVERAGE,
        "winner_tie_policy": RobustnessWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        "minimum_acceptable_top_half_fraction": 0.5,
        "maximum_acceptable_below_zero_fraction": 0.5,
    }
    values.update(overrides)
    return TemporalRobustnessSpec(**values)


def test_sharpe_spec_normalizes_rate_to_float() -> None:
    spec = SharpeRatioSpec(annual_risk_free_rate=0)

    assert spec.annual_risk_free_rate == 0.0
    assert isinstance(spec.annual_risk_free_rate, float)


@pytest.mark.parametrize(
    "invalid_rate",
    [-1.0, -2.0, math.inf, -math.inf, math.nan],
)
def test_sharpe_spec_rejects_invalid_annual_rate(
    invalid_rate: float,
) -> None:
    with pytest.raises(ValueError):
        SharpeRatioSpec(annual_risk_free_rate=invalid_rate)


@pytest.mark.parametrize(
    "invalid_benchmark",
    [math.inf, -math.inf, math.nan],
)
def test_psr_spec_rejects_non_finite_benchmark(
    invalid_benchmark: float,
) -> None:
    with pytest.raises(ValueError):
        ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=(invalid_benchmark)
        )


def test_psr_spec_normalizes_explicit_confidence_level() -> None:
    spec = ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=0.0,
        required_psr_confidence_level="0.95",  # type: ignore[arg-type]
    )

    assert spec.required_psr_confidence_level == 0.95
    assert isinstance(spec.required_psr_confidence_level, float)


@pytest.mark.parametrize(
    "invalid_confidence",
    [0.0, 0.5, 1.0, 1.1, math.inf, -math.inf, math.nan],
)
def test_psr_spec_rejects_invalid_confidence_level(
    invalid_confidence: float,
) -> None:
    with pytest.raises(ValueError):
        ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=0.0,
            required_psr_confidence_level=invalid_confidence,
        )


def test_psr_spec_does_not_assume_a_confidence_level() -> None:
    spec = ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0)

    assert spec.required_psr_confidence_level is None


def test_serial_dependence_spec_preserves_explicit_choices() -> None:
    spec = SerialDependenceSpec(
        maximum_lag=5,
        significance_level=0.01,
    )

    assert spec.maximum_lag == 5
    assert spec.significance_level == 0.01


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_serial_dependence_spec_rejects_invalid_lag(value) -> None:
    with pytest.raises(ValueError):
        SerialDependenceSpec(
            maximum_lag=value,
            significance_level=0.05,
        )


@pytest.mark.parametrize(
    "value",
    [0.0, 1.0, -0.1, 1.1, math.nan, math.inf],
)
def test_serial_dependence_spec_rejects_invalid_significance_level(
    value: float,
) -> None:
    with pytest.raises(ValueError):
        SerialDependenceSpec(
            maximum_lag=1,
            significance_level=value,
        )


def test_serial_adjustment_spec_preserves_explicit_choices() -> None:
    spec = SerialAdjustmentSpec(
        maximum_lag=5,
        kernel=HACKernel.BARTLETT,
    )

    assert spec.maximum_lag == 5
    assert spec.kernel is HACKernel.BARTLETT


def test_serial_adjustment_spec_normalizes_kernel_string() -> None:
    spec = SerialAdjustmentSpec(
        maximum_lag=1,
        kernel="bartlett",  # type: ignore[arg-type]
    )

    assert spec.kernel is HACKernel.BARTLETT


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_serial_adjustment_spec_rejects_invalid_lag(value) -> None:
    with pytest.raises(ValueError):
        SerialAdjustmentSpec(
            maximum_lag=value,
            kernel=HACKernel.BARTLETT,
        )


def test_serial_adjustment_spec_rejects_unknown_kernel() -> None:
    with pytest.raises(ValueError):
        SerialAdjustmentSpec(
            maximum_lag=1,
            kernel="uniform",  # type: ignore[arg-type]
        )


def test_bootstrap_spec_preserves_and_normalizes_explicit_choices() -> None:
    spec = BootstrapSpec(
        method="moving_block",  # type: ignore[arg-type]
        interval_method="percentile",  # type: ignore[arg-type]
        replications=2_000,
        confidence_level="0.95",  # type: ignore[arg-type]
        block_length=5,
        random_seed=42,
    )

    assert spec.method is BootstrapMethod.MOVING_BLOCK
    assert spec.interval_method is BootstrapIntervalMethod.PERCENTILE
    assert spec.replications == 2_000
    assert spec.confidence_level == 0.95
    assert spec.block_length == 5
    assert spec.random_seed == 42


@pytest.mark.parametrize("value", [1, 0, -1, 1.5, True])
def test_bootstrap_spec_rejects_invalid_replications(value) -> None:
    with pytest.raises(ValueError):
        BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=value,
            confidence_level=0.95,
            block_length=2,
            random_seed=42,
        )


@pytest.mark.parametrize(
    "value",
    [0.5, 1.0, 0.0, math.nan, math.inf],
)
def test_bootstrap_spec_rejects_invalid_confidence(value: float) -> None:
    with pytest.raises(ValueError):
        BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=100,
            confidence_level=value,
            block_length=2,
            random_seed=42,
        )


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_bootstrap_spec_rejects_invalid_block_length(value) -> None:
    with pytest.raises(ValueError):
        BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=100,
            confidence_level=0.95,
            block_length=value,
            random_seed=42,
        )


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_bootstrap_spec_rejects_invalid_seed(value) -> None:
    with pytest.raises(ValueError):
        BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=100,
            confidence_level=0.95,
            block_length=2,
            random_seed=value,
        )


def test_bootstrap_spec_rejects_unknown_methods() -> None:
    with pytest.raises(ValueError):
        BootstrapSpec(
            method="unknown",  # type: ignore[arg-type]
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=100,
            confidence_level=0.95,
            block_length=2,
            random_seed=42,
        )

    with pytest.raises(ValueError):
        BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method="bca",  # type: ignore[arg-type]
            replications=100,
            confidence_level=0.95,
            block_length=2,
            random_seed=42,
        )


def test_parameter_robustness_spec_requires_sorted_unique_scales() -> None:
    with pytest.raises(ValueError, match="ordered"):
        ParameterRobustnessSpec(
            performance_metric=RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
            selection_metric_name="period_sharpe_ratio",
            annual_risk_free_rate=0.0,
            distance_metric=ParameterDistanceMetric.STANDARDIZED_EUCLIDEAN,
            parameter_scales=(
                ParameterScale("threshold", 0.1),
                ParameterScale("lookback", 5),
            ),
            maximum_distance=1.0,
            minimum_neighbor_count=2,
            maximum_acceptable_score_difference=0.1,
            minimum_acceptable_neighbor_fraction=0.5,
        )


@pytest.mark.parametrize("scale", [0.0, -1.0, math.nan, math.inf])
def test_parameter_scale_must_be_positive_and_finite(scale: float) -> None:
    with pytest.raises(ValueError):
        ParameterScale("lookback", scale)


@pytest.mark.parametrize("window_count", [0, 1, 2.5, True])
def test_temporal_robustness_spec_rejects_invalid_window_count(
    window_count: object,
) -> None:
    with pytest.raises(ValueError):
        TemporalRobustnessSpec(
            performance_metric=RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
            selection_metric_name="period_sharpe_ratio",
            annual_risk_free_rate=0.0,
            window_count=window_count,  # type: ignore[arg-type]
            rank_tie_method=RobustnessRankTieMethod.AVERAGE,
            winner_tie_policy=RobustnessWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
            minimum_acceptable_top_half_fraction=0.5,
            maximum_acceptable_below_zero_fraction=0.5,
        )


@pytest.mark.parametrize("fraction", [-0.1, 1.1, math.nan, math.inf])
def test_temporal_robustness_spec_rejects_invalid_fractions(
    fraction: float,
) -> None:
    with pytest.raises(ValueError):
        TemporalRobustnessSpec(
            performance_metric=RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
            selection_metric_name="period_sharpe_ratio",
            annual_risk_free_rate=0.0,
            window_count=2,
            rank_tie_method=RobustnessRankTieMethod.AVERAGE,
            winner_tie_policy=RobustnessWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
            minimum_acceptable_top_half_fraction=fraction,
            maximum_acceptable_below_zero_fraction=0.5,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"method": "invented"}, "method must be one of"),
        ({"trial_count_policy": "invented"}, "trial_count_policy must be one of"),
        ({"annual_risk_free_rate": math.inf}, "must be finite"),
        ({"annual_risk_free_rate": -1.0}, "greater than -1.0"),
        ({"required_confidence_level": 0.5}, "strictly between"),
        (
            {"effective_independent_trial_count": 2},
            "must be supplied together",
        ),
        (
            {
                "effective_independent_trial_count": True,
                "effective_trial_count_methodology": "cluster estimate",
            },
            "positive integer",
        ),
        (
            {
                "effective_independent_trial_count": 2,
                "effective_trial_count_methodology": "   ",
            },
            "must not be empty",
        ),
    ],
)
def test_dsr_spec_rejects_invalid_or_incomplete_methodology(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _dsr_spec(**overrides)


def test_dsr_spec_normalizes_explicit_effective_count_methodology() -> None:
    result = _dsr_spec(
        effective_independent_trial_count=2,
        effective_trial_count_methodology="  cluster estimate  ",
    )

    assert result.effective_trial_count_methodology == "cluster estimate"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"method": "invented"}, "method must be one of"),
        ({"performance_metric": "invented"}, "performance_metric must be one of"),
        ({"rank_tie_method": "invented"}, "rank_tie_method must be one of"),
        ({"winner_tie_policy": "invented"}, "winner_tie_policy must be one of"),
        ({"selection_metric_name": 1}, "must be a string"),
        ({"selection_metric_name": "  "}, "must not be empty"),
        ({"partition_count": 3}, "even integer"),
        ({"annual_risk_free_rate": math.inf}, "must be finite"),
        ({"annual_risk_free_rate": -1.0}, "greater than -1.0"),
        ({"maximum_combinations": True}, "positive integer"),
        ({"maximum_acceptable_pbo": 1.0}, "strictly between"),
    ],
)
def test_cscv_spec_rejects_invalid_contract_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _cscv_spec(**overrides)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        (1, "must be a string"),
        ("  ", "must not be empty"),
    ],
)
def test_parameter_scale_rejects_invalid_names(name: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ParameterScale(name, 1.0)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"performance_metric": "invented"}, "performance_metric must be one of"),
        ({"distance_metric": "invented"}, "distance_metric must be one of"),
        ({"selection_metric_name": 1}, "must be a string"),
        ({"selection_metric_name": "  "}, "must not be empty"),
        ({"annual_risk_free_rate": -1.0}, "greater than -1.0"),
        ({"parameter_scales": ()}, "must not be empty"),
        (
            {
                "parameter_scales": (
                    ParameterScale("lookback", 5.0),
                    ParameterScale("lookback", 10.0),
                )
            },
            "must be unique",
        ),
        ({"maximum_distance": 0.0}, "greater than 0.0"),
        ({"minimum_neighbor_count": True}, "positive integer"),
        ({"maximum_acceptable_score_difference": -0.1}, "greater than or equal"),
        ({"minimum_acceptable_neighbor_fraction": 1.1}, "between 0.0 and 1.0"),
    ],
)
def test_parameter_robustness_spec_rejects_invalid_contract_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _parameter_spec(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"performance_metric": "invented"}, "performance_metric must be one of"),
        ({"rank_tie_method": "invented"}, "rank_tie_method must be one of"),
        ({"winner_tie_policy": "invented"}, "winner_tie_policy must be one of"),
        ({"selection_metric_name": 1}, "must be a string"),
        ({"selection_metric_name": "  "}, "must not be empty"),
        ({"annual_risk_free_rate": math.inf}, "greater than -1.0"),
    ],
)
def test_temporal_robustness_spec_rejects_invalid_contract_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _temporal_spec(**overrides)


@pytest.mark.parametrize(
    ("constructor", "arguments", "message"),
    [
        (AdvancedRiskSpec, (math.inf, 0.95), "period_return"),
        (AdvancedRiskSpec, (0.0, 0.5), "tail_confidence_level"),
        (BenchmarkInferenceSpec, (-1, 0.95), "maximum_lag"),
        (BenchmarkInferenceSpec, (1, 1.0), "confidence_level"),
        (DataSnoopingSpec, (1, 2, 42, 0.05), "replications"),
        (DataSnoopingSpec, (10, 0, 42, 0.05), "mean_block_length"),
        (DataSnoopingSpec, (10, 2, -1, 0.05), "random_seed"),
        (DataSnoopingSpec, (10, 2, 42, 0.5), "significance_level"),
    ],
)
def test_v1_4_specs_reject_invalid_contract_values(
    constructor: object,
    arguments: tuple[object, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        constructor(*arguments)
