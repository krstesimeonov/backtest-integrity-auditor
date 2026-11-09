import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.distribution import (
    calculate_distribution_statistics,
)


def _series(
    values: list[float],
    *,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range(
            "2026-01-01",
            periods=len(values),
            freq="D",
        ),
        values=np.asarray(values),
        convention=convention,
        sampling=SamplingSpec(),
    )


def test_symmetric_sample_has_corrected_shape_estimates() -> None:
    result = calculate_distribution_statistics(_series([-0.02, -0.01, 0.0, 0.01, 0.02]))

    assert result.return_basis is ReturnConvention.SIMPLE
    assert result.sample_skewness == pytest.approx(0.0)
    assert result.sample_excess_kurtosis == pytest.approx(-1.2)
    assert result.sample_pearson_kurtosis == pytest.approx(1.8)


def test_log_and_simple_inputs_produce_equivalent_shape() -> None:
    simple_values = [-0.02, -0.01, 0.0, 0.01, 0.03]
    simple = calculate_distribution_statistics(_series(simple_values))
    log = calculate_distribution_statistics(
        _series(
            np.log1p(simple_values).tolist(),
            convention=ReturnConvention.LOG,
        )
    )

    assert log.sample_skewness == pytest.approx(simple.sample_skewness)
    assert log.sample_excess_kurtosis == pytest.approx(simple.sample_excess_kurtosis)
    assert log.sample_pearson_kurtosis == pytest.approx(simple.sample_pearson_kurtosis)


def test_three_observations_define_skewness_but_not_kurtosis() -> None:
    result = calculate_distribution_statistics(_series([-0.01, 0.0, 0.02]))

    assert result.sample_skewness is not None
    assert result.sample_excess_kurtosis is None
    assert result.sample_pearson_kurtosis is None


def test_constant_returns_have_undefined_shape() -> None:
    result = calculate_distribution_statistics(_series([0.01, 0.01, 0.01, 0.01]))

    assert result.sample_skewness is None
    assert result.sample_excess_kurtosis is None
    assert result.sample_pearson_kurtosis is None
