import math

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import (
    BootstrapSpec,
    SerialAdjustmentSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    BootstrapMetric,
    BootstrapMetricStatus,
    BootstrapStatus,
    HACKernel,
    ReturnConvention,
)
from backtest_auditor.domain.results import (
    BootstrapMetricResult,
    BootstrapResult,
)
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)
from backtest_auditor.statistics.annualized import (
    calculate_annualized_statistics,
)
from backtest_auditor.statistics.bootstrap import (
    calculate_bootstrap_confidence_intervals,
)
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.serial_adjustment import (
    calculate_serial_adjustment,
)


def _series(
    values: list[float] | np.ndarray,
    *,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
    periods_per_year: int | None = 12,
    timestamps: pd.DatetimeIndex | None = None,
) -> ReturnSeries:
    values_array = np.asarray(values, dtype=np.float64)
    return ReturnSeries(
        timestamps=(
            pd.date_range(
                "2026-01-01",
                periods=len(values_array),
                freq="D",
            )
            if timestamps is None
            else timestamps
        ),
        values=values_array,
        convention=convention,
        sampling=SamplingSpec(periods_per_year=periods_per_year),
    )


def _spec(
    *,
    replications: int = 40,
    confidence_level: float = 0.8,
    block_length: int = 2,
    random_seed: int = 123,
) -> BootstrapSpec:
    return BootstrapSpec(
        method=BootstrapMethod.MOVING_BLOCK,
        interval_method=BootstrapIntervalMethod.PERCENTILE,
        replications=replications,
        confidence_level=confidence_level,
        block_length=block_length,
        random_seed=random_seed,
    )


def _metric(
    result: BootstrapResult,
    metric: BootstrapMetric,
) -> BootstrapMetricResult:
    return next(item for item in result.metrics if item.metric is metric)


def _eligible_result(
    series: ReturnSeries,
    *,
    spec: BootstrapSpec,
    include_hac: bool = True,
) -> BootstrapResult:
    sampling = assess_sampling(series)
    annualized = calculate_annualized_statistics(
        series,
        sampling,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )
    serial_adjustment = (
        None
        if not include_hac
        else calculate_serial_adjustment(
            series,
            annualized,
            None,
            spec=SerialAdjustmentSpec(
                maximum_lag=1,
                kernel=HACKernel.BARTLETT,
            ),
        )
    )
    result = calculate_bootstrap_confidence_intervals(
        series,
        sampling,
        annualized,
        serial_adjustment,
        spec=spec,
    )
    assert result is not None
    return result


def test_moving_block_percentile_intervals_match_independent_reference() -> None:
    values = np.asarray([0.01, -0.02, 0.03, 0.005, 0.015, 0.02])
    spec = _spec()
    result = _eligible_result(_series(values), spec=spec)

    random_generator = np.random.default_rng(spec.random_seed)
    mean_distribution: list[float] = []
    hac_sharpe_distribution: list[float] = []
    blocks_per_replication = math.ceil(len(values) / spec.block_length)
    for _ in range(spec.replications):
        starts = random_generator.integers(
            0,
            len(values) - spec.block_length + 1,
            size=blocks_per_replication,
        )
        resample = np.concatenate(
            [values[start : start + spec.block_length] for start in starts]
        )[: len(values)]
        mean_return = float(np.mean(resample))
        volatility = float(np.std(resample, ddof=1))
        mean_distribution.append(mean_return)

        centered = resample - mean_return
        denominator = float(np.dot(centered, centered))
        lag_one_correlation = float(np.dot(centered[1:], centered[:-1]) / denominator)
        bartlett_ratio = 1.0 + lag_one_correlation
        hac_sharpe_distribution.append(
            (mean_return / volatility) * math.sqrt(12 / bartlett_ratio)
        )

    expected_mean_bounds = np.quantile(
        mean_distribution,
        [0.1, 0.9],
        method="linear",
    )
    expected_hac_bounds = np.quantile(
        hac_sharpe_distribution,
        [0.1, 0.9],
        method="linear",
    )

    mean_metric = _metric(
        result,
        BootstrapMetric.PERIOD_MEAN_RETURN,
    )
    hac_metric = _metric(
        result,
        BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO,
    )

    assert result.status is BootstrapStatus.ELIGIBLE
    assert result.overlapping_block_count == 5
    assert result.blocks_per_replication == 3
    assert mean_metric.lower_bound == pytest.approx(expected_mean_bounds[0])
    assert mean_metric.upper_bound == pytest.approx(expected_mean_bounds[1])
    assert mean_metric.bootstrap_standard_error == pytest.approx(
        np.std(mean_distribution, ddof=1)
    )
    assert hac_metric.lower_bound == pytest.approx(expected_hac_bounds[0])
    assert hac_metric.upper_bound == pytest.approx(expected_hac_bounds[1])
    assert hac_metric.successful_replications == spec.replications


def test_bootstrap_is_reproducible_for_same_seed_and_changes_for_new_seed() -> None:
    series = _series([0.01, -0.02, 0.03, 0.005, 0.015, 0.02])

    first = _eligible_result(series, spec=_spec(random_seed=7))
    second = _eligible_result(series, spec=_spec(random_seed=7))
    changed = _eligible_result(series, spec=_spec(random_seed=8))

    assert first == second
    assert (
        _metric(
            first,
            BootstrapMetric.PERIOD_MEAN_RETURN,
        ).lower_bound
        != _metric(
            changed,
            BootstrapMetric.PERIOD_MEAN_RETURN,
        ).lower_bound
    )


def test_stationary_bootstrap_is_reproducible_and_has_no_fixed_block_counts() -> None:
    series = _series([0.01, -0.02, 0.03, 0.005, 0.015, 0.02])
    spec = BootstrapSpec(
        method=BootstrapMethod.STATIONARY,
        interval_method=BootstrapIntervalMethod.PERCENTILE,
        replications=40,
        confidence_level=0.8,
        block_length=2,
        random_seed=123,
    )

    first = _eligible_result(series, spec=spec)
    second = _eligible_result(series, spec=spec)

    assert first == second
    assert first.status is BootstrapStatus.ELIGIBLE
    assert first.method is BootstrapMethod.STATIONARY
    assert first.overlapping_block_count is None
    assert first.blocks_per_replication is None
    assert _metric(first, BootstrapMetric.PERIOD_MEAN_RETURN).lower_bound is not None


def test_simple_and_log_inputs_produce_equivalent_bootstrap_evidence() -> None:
    simple_values = np.asarray([0.01, -0.02, 0.03, 0.005, 0.015, 0.02])
    simple = _eligible_result(
        _series(simple_values),
        spec=_spec(),
    )
    log = _eligible_result(
        _series(
            np.log1p(simple_values),
            convention=ReturnConvention.LOG,
        ),
        spec=_spec(),
    )

    assert log.return_basis is ReturnConvention.SIMPLE
    for simple_metric, log_metric in zip(
        simple.metrics,
        log.metrics,
        strict=True,
    ):
        assert simple_metric.metric is log_metric.metric
        assert log_metric.point_estimate == pytest.approx(simple_metric.point_estimate)
        assert log_metric.lower_bound == pytest.approx(simple_metric.lower_bound)
        assert log_metric.upper_bound == pytest.approx(simple_metric.upper_bound)


def test_regular_series_without_annualization_keeps_period_intervals() -> None:
    series = _series(
        [0.01, -0.02, 0.03, 0.005, 0.015],
        periods_per_year=None,
    )
    sampling = assess_sampling(series)
    result = calculate_bootstrap_confidence_intervals(
        series,
        sampling,
        None,
        None,
        spec=_spec(),
    )

    assert result is not None
    assert result.status is BootstrapStatus.ELIGIBLE
    assert (
        _metric(
            result,
            BootstrapMetric.PERIOD_MEAN_RETURN,
        ).status
        is BootstrapMetricStatus.ELIGIBLE
    )
    assert (
        _metric(
            result,
            BootstrapMetric.ANNUALIZED_ARITHMETIC_MEAN_RETURN,
        ).status
        is BootstrapMetricStatus.POINT_ESTIMATE_UNAVAILABLE
    )
    assert (
        _metric(
            result,
            BootstrapMetric.PERIOD_SHARPE_RATIO,
        ).status
        is BootstrapMetricStatus.POINT_ESTIMATE_UNAVAILABLE
    )


def test_zero_variance_keeps_non_sharpe_intervals_and_marks_sharpe_unavailable() -> (
    None
):
    result = _eligible_result(
        _series([0.01, 0.01, 0.01, 0.01]),
        spec=_spec(block_length=2),
        include_hac=False,
    )

    volatility = _metric(
        result,
        BootstrapMetric.PERIOD_SAMPLE_VOLATILITY,
    )
    sharpe = _metric(
        result,
        BootstrapMetric.PERIOD_SHARPE_RATIO,
    )

    assert volatility.status is BootstrapMetricStatus.ELIGIBLE
    assert volatility.point_estimate == 0.0
    assert volatility.lower_bound == 0.0
    assert volatility.upper_bound == 0.0
    assert sharpe.status is BootstrapMetricStatus.POINT_ESTIMATE_UNAVAILABLE
    assert sharpe.attempted_replications == 0


def test_irregular_sampling_preserves_configuration_without_resampling() -> None:
    timestamps = pd.DatetimeIndex(
        ["2026-01-01", "2026-01-02", "2026-01-04", "2026-01-07"]
    )
    series = _series(
        [0.01, -0.02, 0.03, 0.005],
        timestamps=timestamps,
    )
    sampling = assess_sampling(series)
    spec = _spec()

    result = calculate_bootstrap_confidence_intervals(
        series,
        sampling,
        None,
        None,
        spec=spec,
    )

    assert result is not None
    assert result.status is BootstrapStatus.SAMPLING_INELIGIBLE
    assert result.block_length == spec.block_length
    assert result.random_seed == spec.random_seed
    assert result.metrics == ()


def test_block_length_must_be_below_observation_count_at_runtime() -> None:
    series = _series([0.01, -0.02, 0.03, 0.005])
    sampling = assess_sampling(series)
    spec = _spec(block_length=4)

    result = calculate_bootstrap_confidence_intervals(
        series,
        sampling,
        None,
        None,
        spec=spec,
    )

    assert result is not None
    assert result.status is (BootstrapStatus.BLOCK_LENGTH_NOT_BELOW_OBSERVATION_COUNT)
    assert result.block_length == 4
    assert result.metrics == ()


def test_unconfigured_bootstrap_returns_none() -> None:
    series = _series([0.01, -0.02, 0.03])

    assert (
        calculate_bootstrap_confidence_intervals(
            series,
            assess_sampling(series),
            None,
            None,
        )
        is None
    )
