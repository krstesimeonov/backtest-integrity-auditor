import math

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import (
    BenchmarkAlignmentStatus,
    ReturnConvention,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.benchmark import (
    assess_benchmark_alignment,
    calculate_benchmark_comparison,
)
from backtest_auditor.statistics.sampling import assess_sampling


def _series(
    values: np.ndarray,
    *,
    timestamps: pd.DatetimeIndex | None = None,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
) -> ReturnSeries:
    return ReturnSeries(
        timestamps=(
            pd.date_range("2026-01-01", periods=len(values), freq="D")
            if timestamps is None
            else timestamps
        ),
        values=values,
        convention=convention,
        sampling=SamplingSpec(periods_per_year=4),
    )


def test_benchmark_statistics_match_independent_numpy_calculation() -> None:
    strategy_values = np.asarray([0.02, 0.01, -0.01, 0.03])
    benchmark_values = np.asarray([0.01, 0.00, -0.005, 0.02])
    strategy = _series(strategy_values)
    benchmark = _series(benchmark_values)
    alignment = assess_benchmark_alignment(strategy, benchmark)

    result = calculate_benchmark_comparison(
        strategy,
        benchmark,
        alignment,
        assess_sampling(strategy),
        benchmark_id="market",
    )

    active = strategy_values - benchmark_values
    expected_te = float(np.std(active, ddof=1))
    expected_beta = float(
        np.cov(strategy_values, benchmark_values, ddof=1)[0, 1]
        / np.var(benchmark_values, ddof=1)
    )
    assert result is not None
    assert alignment.status is BenchmarkAlignmentStatus.ELIGIBLE
    assert result.mean_period_active_return == pytest.approx(np.mean(active))
    assert result.period_tracking_error == pytest.approx(expected_te)
    assert result.annualized_tracking_error == pytest.approx(expected_te * 2)
    assert result.period_information_ratio == pytest.approx(
        np.mean(active) / expected_te
    )
    assert result.annualized_information_ratio == pytest.approx(
        np.mean(active) / expected_te * 2
    )
    assert result.beta == pytest.approx(expected_beta)
    assert result.period_arithmetic_alpha == pytest.approx(
        np.mean(strategy_values) - expected_beta * np.mean(benchmark_values)
    )
    assert result.relative_wealth_return == pytest.approx(
        np.prod(1 + strategy_values) / np.prod(1 + benchmark_values) - 1
    )


def test_timestamp_mismatch_withholds_relative_statistics() -> None:
    strategy = _series(np.asarray([0.01, 0.02, 0.03]))
    benchmark = _series(
        np.asarray([0.01, 0.02, 0.03]),
        timestamps=pd.date_range("2026-01-02", periods=3, freq="D"),
    )
    alignment = assess_benchmark_alignment(strategy, benchmark)

    result = calculate_benchmark_comparison(
        strategy,
        benchmark,
        alignment,
        assess_sampling(strategy),
        benchmark_id="market",
    )

    assert alignment.status is BenchmarkAlignmentStatus.TIMESTAMP_MISMATCH
    assert alignment.strategy_only_timestamps == ("2026-01-01T00:00:00",)
    assert alignment.benchmark_only_timestamps == ("2026-01-04T00:00:00",)
    assert result is None


def test_log_benchmark_and_strategy_match_simple_inputs() -> None:
    strategy_values = np.asarray([0.02, 0.01, -0.01, 0.03])
    benchmark_values = np.asarray([0.01, 0.00, -0.005, 0.02])
    strategy_simple = _series(strategy_values)
    benchmark_simple = _series(benchmark_values)
    strategy_log = _series(
        np.log1p(strategy_values),
        convention=ReturnConvention.LOG,
    )
    benchmark_log = _series(
        np.log1p(benchmark_values),
        convention=ReturnConvention.LOG,
    )

    simple_result = calculate_benchmark_comparison(
        strategy_simple,
        benchmark_simple,
        assess_benchmark_alignment(strategy_simple, benchmark_simple),
        assess_sampling(strategy_simple),
        benchmark_id="market",
    )
    log_result = calculate_benchmark_comparison(
        strategy_log,
        benchmark_log,
        assess_benchmark_alignment(strategy_log, benchmark_log),
        assess_sampling(strategy_log),
        benchmark_id="market",
    )

    assert simple_result is not None and log_result is not None
    assert log_result.period_tracking_error == pytest.approx(
        simple_result.period_tracking_error
    )
    assert log_result.beta == pytest.approx(simple_result.beta)


def test_zero_benchmark_variance_preserves_other_evidence() -> None:
    strategy = _series(np.asarray([0.01, 0.02, 0.03]))
    benchmark = _series(np.asarray([0.0, 0.0, 0.0]))
    result = calculate_benchmark_comparison(
        strategy,
        benchmark,
        assess_benchmark_alignment(strategy, benchmark),
        assess_sampling(strategy),
        benchmark_id="cash",
    )

    assert result is not None
    assert result.beta is None
    assert result.period_arithmetic_alpha is None
    assert math.isfinite(result.period_tracking_error)
