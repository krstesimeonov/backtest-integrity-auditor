import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.performance_path import (
    calculate_performance_path,
)
from backtest_auditor.statistics.sampling import assess_sampling


def _result(
    values: list[float],
    *,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
):
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=np.asarray(values),
        convention=convention,
        sampling=SamplingSpec(periods_per_year=4),
    )
    return calculate_performance_path(series, assess_sampling(series))


def test_performance_path_reproduces_wealth_drawdown_and_recovery() -> None:
    result = _result([0.10, -0.20, 0.10, 0.20])

    assert result.ending_wealth == pytest.approx(1.1616)
    assert result.cumulative_simple_return == pytest.approx(0.1616)
    assert result.cagr == pytest.approx(0.1616)
    assert result.maximum_drawdown == pytest.approx(-0.20)
    assert result.maximum_drawdown_peak_timestamp == pd.Timestamp("2026-01-01")
    assert result.maximum_drawdown_trough_timestamp == pd.Timestamp("2026-01-02")
    assert result.maximum_drawdown_recovery_timestamp == pd.Timestamp("2026-01-04")
    assert result.maximum_drawdown_duration_observations == 3
    assert result.longest_time_underwater_observations == 2


def test_initial_loss_preserves_virtual_initial_peak() -> None:
    result = _result([-0.10, 0.05])

    assert result.maximum_drawdown_peak_timestamp is None
    assert result.maximum_drawdown_recovery_timestamp is None
    assert not result.maximum_drawdown_recovered
    assert result.maximum_drawdown_duration_observations == 2
    assert result.longest_time_underwater_observations == 2


def test_log_and_simple_paths_are_equivalent() -> None:
    simple = np.asarray([0.10, -0.20, 0.10, 0.20])

    simple_result = _result(simple.tolist())
    log_result = _result(
        np.log1p(simple).tolist(),
        convention=ReturnConvention.LOG,
    )

    assert log_result.ending_wealth == pytest.approx(simple_result.ending_wealth)
    assert log_result.maximum_drawdown == pytest.approx(simple_result.maximum_drawdown)


def test_total_loss_makes_cagr_undefined() -> None:
    result = _result([0.10, -1.0, 0.50])

    assert result.ending_wealth == 0.0
    assert result.cagr is None
    assert result.maximum_drawdown == -1.0
