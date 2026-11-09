import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import (
    SerialDependenceSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    ReturnConvention,
    SerialDependenceStatus,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import (
    calculate_annualized_statistics,
)
from backtest_auditor.statistics.degeneracy import (
    columns_with_zero_sample_variation,
    has_zero_sample_variation,
)
from backtest_auditor.statistics.descriptive import (
    calculate_descriptive_statistics,
)
from backtest_auditor.statistics.distribution import (
    calculate_distribution_statistics,
)
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.serial_dependence import (
    calculate_serial_dependence,
)

# 0.001 has no exact binary representation, so centring a constant sample of it
# leaves a rounding residue. This is the value that broke every `== 0.0` gate.
UNREPRESENTABLE = 0.001
# 0.25 is exactly representable, so it centres to exact zero and always worked.
REPRESENTABLE = 0.25


def _series(values: list[float], *, periods_per_year: int | None = 252) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=np.asarray(values, dtype=float),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(
            declared_frequency="D",
            periods_per_year=periods_per_year,
        ),
    )


def test_numpy_std_of_a_constant_series_is_not_exactly_zero() -> None:
    """The premise of the bug: this is why `std != 0.0` admitted a flat series."""

    residue = float(np.std([UNREPRESENTABLE] * 10, ddof=1))
    assert residue != 0.0
    assert residue == pytest.approx(2.29e-19, rel=0.05)
    assert float(np.std([REPRESENTABLE] * 10, ddof=1)) == 0.0


def test_predicate_is_exact_and_representation_independent() -> None:
    assert has_zero_sample_variation(np.array([UNREPRESENTABLE] * 10))
    assert has_zero_sample_variation(np.array([REPRESENTABLE] * 10))
    assert not has_zero_sample_variation(np.array([0.001, 0.001, 0.0010000000001]))
    assert not has_zero_sample_variation(np.array([]))


def test_constant_series_publishes_no_sharpe_ratio() -> None:
    series = _series([UNREPRESENTABLE] * 300)
    sampling = assess_sampling(series)
    result = calculate_annualized_statistics(
        series,
        sampling,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )

    assert result is not None
    # Before the fix this was 7.3e16, produced by dividing by the residue.
    assert result.annualized_sharpe_ratio is None
    assert result.annualized_sample_volatility == 0.0


def test_constant_series_reports_exactly_zero_sample_volatility() -> None:
    result = calculate_descriptive_statistics(_series([UNREPRESENTABLE] * 300))

    # Exact zero is what makes the downstream ZERO_SAMPLE_VOLATILITY gate fire.
    assert result.sample_volatility == 0.0


def test_constant_series_publishes_no_higher_moments() -> None:
    result = calculate_distribution_statistics(_series([UNREPRESENTABLE] * 300))

    assert result.sample_skewness is None
    assert result.sample_excess_kurtosis is None
    assert result.sample_pearson_kurtosis is None


def test_constant_series_is_ineligible_for_serial_dependence() -> None:
    result = calculate_serial_dependence(
        _series([UNREPRESENTABLE] * 300),
        spec=SerialDependenceSpec(maximum_lag=5, significance_level=0.05),
    )

    # Before the fix this reported detected=True at p=0.0 from pure noise.
    assert result.status is SerialDependenceStatus.ZERO_VARIANCE
    assert result.serial_dependence_detected is None
    assert result.ljung_box_statistic is None


def test_varying_series_statistics_are_untouched_by_the_predicate() -> None:
    """The predicate must not perturb any series that genuinely varies."""

    values = [0.01, -0.005, 0.0075, 0.0025, -0.003] * 60
    series = _series(values)
    sampling = assess_sampling(series)

    annualized = calculate_annualized_statistics(
        series,
        sampling,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )
    assert annualized is not None
    assert annualized.annualized_sharpe_ratio is not None
    expected = float(np.std(np.asarray(values), ddof=1))
    assert calculate_descriptive_statistics(series).sample_volatility == expected
    assert calculate_distribution_statistics(series).sample_skewness is not None


def test_column_form_agrees_with_the_scalar_form_column_by_column() -> None:
    varying = [0.020, -0.005, 0.018, 0.004, 0.015, -0.002, 0.012, 0.006, 0.010, 0.003]
    # 0.001 and -0.001 over ten rows are the constants whose np.std is a
    # 2.29e-19 residue; 0.25 is exactly representable and leaves none.
    matrix = np.column_stack([varying, [0.001] * 10, [-0.001] * 10, [0.25] * 10])

    assert columns_with_zero_sample_variation(matrix).tolist() == [
        has_zero_sample_variation(matrix[:, index]) for index in range(4)
    ]
    assert columns_with_zero_sample_variation(matrix).tolist() == [
        False,
        True,
        True,
        True,
    ]


def test_an_empty_column_is_not_flat_in_either_form() -> None:
    empty = np.empty((0, 3))

    assert columns_with_zero_sample_variation(empty).tolist() == [False] * 3
    assert has_zero_sample_variation(empty[:, 0]) is False


def test_a_single_observation_spans_a_single_value() -> None:
    # The docstring's contract: true when "every supplied observation is
    # bit-identical", i.e. the sample "spans a single value". One observation
    # does; only the empty sample is excluded.
    assert has_zero_sample_variation(np.array([0.001]))
    assert has_zero_sample_variation(np.array([-0.25]))
    assert has_zero_sample_variation(np.array([0.001, 0.001]))
    assert not has_zero_sample_variation(np.array([0.001, 0.002]))
    assert not has_zero_sample_variation(np.array([]))
