"""Adversarial tests for statistics.benchmark (alpha, beta, IR, tracking error) vs statsmodels OLS."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("statsmodels")
import statsmodels.api as sm

from .conftest import make_series, ref

from backtest_auditor.statistics.benchmark import (
    assess_benchmark_alignment,
    calculate_benchmark_comparison,
)
from backtest_auditor.statistics.sampling import assess_sampling


@pytest.mark.parametrize("seed", range(20))
def test_alpha_beta_ir_match_ols_and_reference(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(30, 600))
    b = 0.01 * rng.standard_normal(n) + 0.0003
    s = 0.0002 + 0.8 * b + 0.006 * rng.standard_normal(n)
    strategy = make_series(s)
    benchmark = make_series(b)
    alignment = assess_benchmark_alignment(strategy, benchmark)
    res = calculate_benchmark_comparison(
        strategy, benchmark, alignment, assess_sampling(strategy), benchmark_id="bm"
    )
    ols = sm.OLS(s, sm.add_constant(b)).fit()
    assert res.beta == pytest.approx(ols.params[1], rel=1e-9)
    assert res.period_arithmetic_alpha == pytest.approx(
        ols.params[0], rel=1e-9, abs=1e-15
    )
    alpha, beta = ref.ols_alpha_beta(s, b)
    assert res.beta == pytest.approx(beta, rel=1e-12)
    assert res.period_arithmetic_alpha == pytest.approx(alpha, rel=1e-12, abs=1e-15)
    te, ir = ref.information_ratio(s, b)
    assert res.period_tracking_error == pytest.approx(te, rel=1e-12)
    assert res.period_information_ratio == pytest.approx(ir, rel=1e-12)
    assert res.annualized_information_ratio == pytest.approx(
        ir * math.sqrt(252), rel=1e-12
    )
    assert res.annualized_arithmetic_alpha == pytest.approx(
        alpha * 252, rel=1e-12, abs=1e-15
    )
    assert res.return_correlation == pytest.approx(np.corrcoef(s, b)[0, 1], rel=1e-12)
    assert res.relative_wealth_return == pytest.approx(
        np.prod(1 + s) / np.prod(1 + b) - 1, rel=1e-12
    )


def test_misaligned_timestamps_yield_no_comparison():
    rng = np.random.default_rng(1)
    s = make_series(0.01 * rng.standard_normal(50))
    b = make_series(0.01 * rng.standard_normal(50), start="2015-01-02")
    alignment = assess_benchmark_alignment(s, b)
    assert alignment.status.value == "timestamp_mismatch"
    assert (
        calculate_benchmark_comparison(
            s, b, alignment, assess_sampling(s), benchmark_id="bm"
        )
        is None
    )
