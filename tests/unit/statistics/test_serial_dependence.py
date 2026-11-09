import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2

from backtest_auditor.domain.assumptions import (
    SerialDependenceSpec,
)
from backtest_auditor.domain.enums import (
    ReturnConvention,
    SerialDependenceStatus,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.serial_dependence import (
    calculate_serial_dependence,
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


def test_serial_dependence_matches_hand_calculated_acf_and_ljung_box() -> None:
    result = calculate_serial_dependence(
        _series([0.01, 0.02, 0.03, 0.04, 0.05]),
        spec=SerialDependenceSpec(
            maximum_lag=2,
            significance_level=0.05,
        ),
    )

    assert result is not None
    assert [
        estimate.autocorrelation for estimate in result.autocorrelations
    ] == pytest.approx([0.4, -0.1])

    expected_q = 5 * 7 * ((0.4**2 / 4) + (0.1**2 / 3))
    assert result.ljung_box_statistic == pytest.approx(expected_q)
    assert result.p_value == pytest.approx(chi2.sf(expected_q, 2))
    assert result.degrees_of_freedom == 2
    assert result.strongest_absolute_autocorrelation_lag == 1
    assert result.strongest_absolute_autocorrelation == pytest.approx(0.4)
    assert not result.serial_dependence_detected
    assert [item.lag for item in result.partial_autocorrelations] == [1, 2]
    assert result.acf_confidence_bound == pytest.approx(1.95996398454 / np.sqrt(5))
    assert result.mean_long_run_variance_ratio == pytest.approx(1.52)
    assert result.mean_effective_observation_count == pytest.approx(5 / 1.52)
    assert result.runs_count is not None
    assert [item.horizon for item in result.variance_ratios] == [2]
    assert result.variance_ratios[0].heteroskedastic_robust_standard_error is not None


def test_serial_dependence_detects_joint_autocorrelation() -> None:
    result = calculate_serial_dependence(
        _series([value / 1000 for value in range(1, 31)]),
        spec=SerialDependenceSpec(
            maximum_lag=3,
            significance_level=0.05,
        ),
    )

    assert result is not None
    assert result.p_value < 0.05
    assert result.serial_dependence_detected


def test_log_and_equivalent_simple_returns_match() -> None:
    simple_values = np.asarray([0.01, -0.02, 0.03, 0.005, 0.015])
    spec = SerialDependenceSpec(
        maximum_lag=2,
        significance_level=0.05,
    )

    simple_result = calculate_serial_dependence(
        _series(simple_values.tolist()),
        spec=spec,
    )
    log_result = calculate_serial_dependence(
        _series(
            np.log1p(simple_values).tolist(),
            convention=ReturnConvention.LOG,
        ),
        spec=spec,
    )

    assert simple_result is not None
    assert log_result is not None
    assert log_result.return_basis is ReturnConvention.SIMPLE
    assert [
        estimate.autocorrelation for estimate in log_result.autocorrelations
    ] == pytest.approx(
        [estimate.autocorrelation for estimate in simple_result.autocorrelations]
    )
    assert log_result.ljung_box_statistic == pytest.approx(
        simple_result.ljung_box_statistic
    )


def test_serial_dependence_is_not_calculated_without_spec() -> None:
    assert calculate_serial_dependence(_series([0.01, 0.02, 0.03])) is None


def test_serial_dependence_requires_more_observations_than_lags() -> None:
    result = calculate_serial_dependence(
        _series([0.01, 0.02, 0.03]),
        spec=SerialDependenceSpec(
            maximum_lag=3,
            significance_level=0.05,
        ),
    )

    assert result is not None
    assert result.status is SerialDependenceStatus.INSUFFICIENT_OBSERVATIONS
    assert result.maximum_lag == 3
    assert result.significance_level == 0.05
    assert result.p_value is None


def test_serial_dependence_is_undefined_for_zero_variance() -> None:
    result = calculate_serial_dependence(
        _series([0.01, 0.01, 0.01]),
        spec=SerialDependenceSpec(
            maximum_lag=1,
            significance_level=0.05,
        ),
    )

    assert result is not None
    assert result.status is SerialDependenceStatus.ZERO_VARIANCE
    assert result.maximum_lag == 1
    assert result.significance_level == 0.05
    assert result.p_value is None


def test_runs_and_variance_ratio_preserve_degenerate_subtest_boundaries() -> None:
    result = calculate_serial_dependence(
        _series([1.0, 0.0, 0.0, -1.0]),
        spec=SerialDependenceSpec(maximum_lag=2, significance_level=0.05),
    )

    assert result is not None
    assert result.status is SerialDependenceStatus.ELIGIBLE
    assert result.runs_observation_count == 2
    assert result.runs_count == 2
    assert result.runs_z_statistic is None
    assert result.variance_ratios[0].heteroskedastic_robust_standard_error is None
    assert result.variance_ratios[0].p_value is None

    single_sign = calculate_serial_dependence(
        _series([0.0, 0.0, 0.0, 1.0]),
        spec=SerialDependenceSpec(maximum_lag=2, significance_level=0.05),
    )
    assert single_sign is not None
    assert single_sign.runs_observation_count == 1
    assert single_sign.runs_count is None
