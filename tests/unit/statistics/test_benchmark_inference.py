import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import BenchmarkInferenceSpec
from backtest_auditor.domain.enums import BenchmarkInferenceStatus, ReturnConvention
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.benchmark import assess_benchmark_alignment
from backtest_auditor.statistics.benchmark_inference import (
    calculate_benchmark_alpha_inference,
)


def _series(values: list[float], *, start: str = "2026-01-01") -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range(start, periods=len(values), freq="D"),
        values=np.asarray(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )


def test_hac_alpha_inference_matches_ols_coefficients_and_is_deterministic() -> None:
    benchmark = _series([-0.03, -0.01, 0.00, 0.01, 0.02, 0.04, -0.02, 0.03])
    strategy = _series([-0.041, -0.010, 0.004, 0.019, 0.029, 0.064, -0.026, 0.049])
    alignment = assess_benchmark_alignment(strategy, benchmark)
    spec = BenchmarkInferenceSpec(2, 0.95)

    first = calculate_benchmark_alpha_inference(
        strategy, benchmark, alignment, spec=spec
    )
    second = calculate_benchmark_alpha_inference(
        strategy, benchmark, alignment, spec=spec
    )
    expected = np.linalg.lstsq(
        np.column_stack((np.ones(8), benchmark.values)), strategy.values, rcond=None
    )[0]

    assert first == second
    assert first is not None
    assert first.status is BenchmarkInferenceStatus.ELIGIBLE
    assert first.period_alpha == pytest.approx(expected[0])
    assert first.beta == pytest.approx(expected[1])
    assert first.hac_standard_error > 0.0
    assert 0.0 <= first.two_sided_p_value <= 1.0
    assert first.confidence_interval_lower < first.period_alpha
    assert first.confidence_interval_upper > first.period_alpha


def test_hac_alpha_inference_reports_every_structural_ineligibility() -> None:
    strategy = _series([0.01, 0.02, 0.03, 0.04])
    benchmark = _series([0.00, 0.01, 0.02, 0.03])
    spec = BenchmarkInferenceSpec(1, 0.95)

    unavailable = calculate_benchmark_alpha_inference(strategy, None, None, spec=spec)
    mismatch_benchmark = _series([0.00, 0.01, 0.02, 0.03], start="2026-01-02")
    mismatch = calculate_benchmark_alpha_inference(
        strategy,
        mismatch_benchmark,
        assess_benchmark_alignment(strategy, mismatch_benchmark),
        spec=spec,
    )
    short = _series([0.01, 0.02])
    insufficient = calculate_benchmark_alpha_inference(
        short,
        _series([0.00, 0.01]),
        assess_benchmark_alignment(short, _series([0.00, 0.01])),
        spec=spec,
    )
    constant_benchmark = _series([0.01, 0.01, 0.01, 0.01])
    singular = calculate_benchmark_alpha_inference(
        strategy,
        constant_benchmark,
        assess_benchmark_alignment(strategy, constant_benchmark),
        spec=spec,
    )
    zero_strategy = _series([0.0, 0.0, 0.0, 0.0])
    no_variance = calculate_benchmark_alpha_inference(
        zero_strategy,
        benchmark,
        assess_benchmark_alignment(zero_strategy, benchmark),
        spec=spec,
    )

    assert unavailable.status is BenchmarkInferenceStatus.BENCHMARK_UNAVAILABLE
    assert mismatch.status is BenchmarkInferenceStatus.TIMESTAMP_MISMATCH
    assert insufficient.status is BenchmarkInferenceStatus.INSUFFICIENT_OBSERVATIONS
    assert singular.status is BenchmarkInferenceStatus.SINGULAR_DESIGN
    assert no_variance.status is BenchmarkInferenceStatus.NON_POSITIVE_VARIANCE
    assert no_variance.period_alpha == pytest.approx(0.0)


def test_hac_alpha_inference_is_opt_in() -> None:
    strategy = _series([0.01, 0.02, 0.03])
    assert calculate_benchmark_alpha_inference(strategy, None, None) is None
