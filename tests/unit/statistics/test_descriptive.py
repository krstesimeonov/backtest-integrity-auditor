import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)
from backtest_auditor.statistics.descriptive import (
    calculate_descriptive_statistics,
)


def test_simple_cumulative_return_compounds() -> None:
    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]),
        values=np.array([0.10, -0.10]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    result = calculate_descriptive_statistics(series)

    assert result.cumulative_simple_return == pytest.approx(-0.01)


def test_log_returns_produce_same_total_wealth_return() -> None:
    values = np.log(np.array([1.10, 0.90]))

    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]),
        values=values,
        convention=ReturnConvention.LOG,
        sampling=SamplingSpec(),
    )

    result = calculate_descriptive_statistics(series)

    assert result.cumulative_simple_return == pytest.approx(-0.01)


def test_sample_volatility_uses_n_minus_one() -> None:
    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]),
        values=np.array([0.00, 0.02]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    result = calculate_descriptive_statistics(series)

    assert result.sample_volatility == pytest.approx(0.01414213562373095)


def test_one_observation_has_no_sample_volatility() -> None:
    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01"]),
        values=np.array([0.01]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    result = calculate_descriptive_statistics(series)

    assert result.observation_count == 1
    assert result.mean_return == pytest.approx(0.01)
    assert result.sample_volatility is None


def test_total_loss_produces_minus_one_cumulative_return() -> None:
    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]),
        values=np.array([0.10, -1.0]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    result = calculate_descriptive_statistics(series)

    assert result.cumulative_simple_return == -1.0


@pytest.mark.filterwarnings("error")
def test_total_loss_is_exact_without_a_floating_point_warning() -> None:
    # (1 + 0.10) * (1 - 1.0) * (1 + 0.05) - 1 = -1.0: nothing compounds back
    # from zero wealth. The total loss is a closed-form case, so it must not be
    # reached through log1p(-1.0) = -inf, which warns "divide by zero" on the
    # user's terminal and aborts the audit under `python -W error`.
    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01", "2026-01-02", "2026-01-03"]),
        values=np.array([0.10, -1.0, 0.05]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    result = calculate_descriptive_statistics(series)

    assert result.cumulative_simple_return == -1.0
