import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.application.single_run_audit import audit_single_run
from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import FrequencyStatus, ReturnConvention
from backtest_auditor.domain.runs import StrategyRun
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec


def test_closed_form_single_run_reference_case() -> None:
    fixture = json.loads(
        Path("tests/fixtures/reference/independent_numerical_cases.json").read_text(
            encoding="utf-8"
        )
    )["single_run_closed_form"]
    inputs = fixture["inputs"]
    expected = fixture["expected"]
    result = audit_single_run(
        StrategyRun(
            run_id="independent-reference-case",
            returns=ReturnSeries(
                timestamps=pd.DatetimeIndex(inputs["timestamps"]),
                values=np.asarray(inputs["returns"], dtype=np.float64),
                convention=ReturnConvention.SIMPLE,
                sampling=SamplingSpec(
                    status=FrequencyStatus.DECLARED,
                    declared_frequency="D",
                    periods_per_year=inputs["periods_per_year"],
                ),
            ),
        ),
        sharpe_spec=SharpeRatioSpec(
            annual_risk_free_rate=inputs["annual_risk_free_rate"]
        ),
        psr_spec=ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=(
                inputs["benchmark_annualized_sharpe_ratio"]
            ),
            required_psr_confidence_level=0.75,
        ),
    )

    assert result.descriptive_statistics.mean_return == pytest.approx(
        expected["mean_return"], abs=1e-15
    )
    assert result.descriptive_statistics.sample_volatility == pytest.approx(
        expected["sample_volatility"], abs=1e-15
    )
    assert result.descriptive_statistics.cumulative_simple_return == pytest.approx(
        expected["cumulative_simple_return"], abs=1e-15
    )
    assert result.annualized_statistics is not None
    assert (
        result.annualized_statistics.annualized_arithmetic_mean_return
        == pytest.approx(expected["annualized_arithmetic_mean_return"], abs=1e-15)
    )
    assert result.annualized_statistics.annualized_sample_volatility == pytest.approx(
        expected["annualized_sample_volatility"], abs=1e-15
    )
    assert result.annualized_statistics.annualized_sharpe_ratio == pytest.approx(
        expected["annualized_sharpe_ratio"], abs=1e-15
    )
    assert result.distribution_statistics.sample_skewness == pytest.approx(
        expected["sample_skewness"], abs=1e-14
    )
    assert result.distribution_statistics.sample_excess_kurtosis == pytest.approx(
        expected["sample_excess_kurtosis"], abs=1e-14
    )
    assert result.distribution_statistics.sample_pearson_kurtosis == pytest.approx(
        expected["sample_pearson_kurtosis"], abs=1e-14
    )
    assert result.sharpe_uncertainty is not None
    assert result.sharpe_uncertainty.probabilistic_sharpe_ratio == pytest.approx(
        expected["probabilistic_sharpe_ratio"], abs=1e-14
    )
    assert result.performance_path.ending_wealth == pytest.approx(
        expected["ending_wealth"], abs=1e-15
    )
    assert result.performance_path.cagr == pytest.approx(expected["cagr"], abs=1e-15)
    assert result.performance_path.maximum_drawdown == pytest.approx(
        expected["maximum_drawdown"], abs=1e-15
    )
    assert (
        result.performance_path.maximum_drawdown_duration_observations
        == (expected["maximum_drawdown_duration_observations"])
    )
    assert (
        result.performance_path.longest_time_underwater_observations
        == (expected["longest_time_underwater_observations"])
    )
    assert (
        result.performance_path.maximum_drawdown_peak_timestamp.isoformat()
        == "2026-01-01T00:00:00"
    )
    assert (
        result.performance_path.maximum_drawdown_trough_timestamp.isoformat()
        == "2026-01-02T00:00:00"
    )
    assert (
        result.performance_path.maximum_drawdown_recovery_timestamp.isoformat()
        == "2026-01-04T00:00:00"
    )
