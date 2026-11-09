import math

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    HACKernel,
    ReturnConvention,
    SerialAdjustmentStatus,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import (
    calculate_annualized_statistics,
)
from backtest_auditor.statistics.distribution import (
    calculate_distribution_statistics,
)
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.serial_adjustment import (
    calculate_serial_adjustment,
)
from backtest_auditor.statistics.sharpe_uncertainty import (
    calculate_sharpe_uncertainty,
)


def _series(
    values: list[float],
    *,
    periods_per_year: int = 4,
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
        sampling=SamplingSpec(periods_per_year=periods_per_year),
    )


def _inputs(
    series: ReturnSeries,
    *,
    psr_spec: ProbabilisticSharpeRatioSpec | None = None,
):
    annualized = calculate_annualized_statistics(
        series,
        assess_sampling(series),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )
    uncertainty = calculate_sharpe_uncertainty(
        annualized,
        calculate_distribution_statistics(series),
        psr_spec=psr_spec,
    )
    return annualized, uncertainty


def test_bartlett_hac_matches_hand_calculated_adjustments() -> None:
    series = _series([0.01, 0.02, 0.03, 0.04, 0.05])
    psr_spec = ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=0.0,
        required_psr_confidence_level=0.95,
    )
    annualized, uncertainty = _inputs(
        series,
        psr_spec=psr_spec,
    )

    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(
            maximum_lag=2,
            kernel=HACKernel.BARTLETT,
        ),
        psr_spec=psr_spec,
    )

    assert result is not None
    assert result.status is SerialAdjustmentStatus.ELIGIBLE
    assert [
        item.autocorrelation for item in result.return_autocorrelations
    ] == pytest.approx([0.4, -0.1])
    assert [
        item.kernel_weight for item in result.return_autocorrelations
    ] == pytest.approx([2 / 3, 1 / 3])
    assert result.return_long_run_variance_ratio == pytest.approx(22 / 15)
    assert result.iid_annualization_factor == pytest.approx(2.0)
    assert result.hac_annualization_factor == pytest.approx(math.sqrt(30 / 11))
    assert result.hac_adjusted_annualized_sharpe_ratio == (
        pytest.approx(3.1333978072025617)
    )

    assert [
        item.autocorrelation for item in result.influence_autocorrelations
    ] == pytest.approx([0.2659574468085107, -0.2340425531914893])
    assert result.sharpe_long_run_variance_ratio == pytest.approx(1.198581560283688)
    assert result.hac_period_sharpe_standard_error == pytest.approx(0.7179067285671492)
    assert result.effective_observation_count == pytest.approx(4.337278106508876)
    assert result.hac_probabilistic_sharpe_ratio == pytest.approx(0.9958902189215886)
    assert result.hac_minimum_required_observations == 4
    assert result.hac_additional_observations_required == 0


def test_full_annual_horizon_matches_lo_weighting() -> None:
    series = _series([0.01, 0.02, 0.03, 0.04, 0.05])
    annualized, uncertainty = _inputs(series)

    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(
            maximum_lag=3,
            kernel=HACKernel.BARTLETT,
        ),
    )

    assert result is not None
    assert result.full_lo_annual_horizon
    assert result.return_long_run_variance_ratio == pytest.approx(1.3)
    expected_lo_factor = 4 / math.sqrt(5.2)
    assert result.hac_annualization_factor == pytest.approx(expected_lo_factor)


def test_negative_dependence_can_increase_effective_evidence() -> None:
    series = _series([0.01, -0.02, 0.03, 0.005, 0.015])
    psr_spec = ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=0.0,
        required_psr_confidence_level=0.75,
    )
    annualized, uncertainty = _inputs(
        series,
        psr_spec=psr_spec,
    )

    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(
            maximum_lag=1,
            kernel=HACKernel.BARTLETT,
        ),
        psr_spec=psr_spec,
    )

    assert result is not None
    assert result.return_long_run_variance_ratio < 1.0
    assert result.sharpe_long_run_variance_ratio < 1.0
    assert (
        result.hac_adjusted_annualized_sharpe_ratio > result.iid_annualized_sharpe_ratio
    )
    assert result.hac_probabilistic_sharpe_ratio > result.iid_probabilistic_sharpe_ratio
    assert result.effective_observation_count > result.observation_count


def test_log_and_equivalent_simple_returns_match() -> None:
    simple_values = np.asarray([0.01, -0.02, 0.03, 0.005, 0.015])
    simple_series = _series(simple_values.tolist())
    log_series = _series(
        np.log1p(simple_values).tolist(),
        convention=ReturnConvention.LOG,
    )
    spec = SerialAdjustmentSpec(
        maximum_lag=1,
        kernel=HACKernel.BARTLETT,
    )

    simple_annualized, simple_uncertainty = _inputs(simple_series)
    log_annualized, log_uncertainty = _inputs(log_series)
    simple_result = calculate_serial_adjustment(
        simple_series,
        simple_annualized,
        simple_uncertainty,
        spec=spec,
    )
    log_result = calculate_serial_adjustment(
        log_series,
        log_annualized,
        log_uncertainty,
        spec=spec,
    )

    assert simple_result is not None
    assert log_result is not None
    assert log_result.return_basis is ReturnConvention.SIMPLE
    assert log_result.return_long_run_variance_ratio == pytest.approx(
        simple_result.return_long_run_variance_ratio
    )
    assert log_result.sharpe_long_run_variance_ratio == pytest.approx(
        simple_result.sharpe_long_run_variance_ratio
    )


def test_adjustment_is_not_calculated_without_spec() -> None:
    series = _series([0.01, 0.02, 0.03, 0.04])
    annualized, uncertainty = _inputs(series)

    assert (
        calculate_serial_adjustment(
            series,
            annualized,
            uncertainty,
        )
        is None
    )


def test_adjustment_preserves_insufficient_configuration() -> None:
    series = _series([0.01, 0.02, 0.03, 0.04])
    annualized, uncertainty = _inputs(series)

    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(
            maximum_lag=4,
            kernel=HACKernel.BARTLETT,
        ),
    )

    assert result is not None
    assert result.status is SerialAdjustmentStatus.INSUFFICIENT_OBSERVATIONS
    assert result.maximum_lag == 4
    assert result.kernel is HACKernel.BARTLETT


def test_adjustment_preserves_unavailable_sharpe_status() -> None:
    series = _series([0.01, 0.02, 0.03])

    result = calculate_serial_adjustment(
        series,
        None,
        None,
        spec=SerialAdjustmentSpec(
            maximum_lag=1,
            kernel=HACKernel.BARTLETT,
        ),
    )

    assert result is not None
    assert result.status is SerialAdjustmentStatus.SHARPE_UNAVAILABLE
    assert result.periods_per_year is None


def test_point_adjustment_survives_unavailable_uncertainty() -> None:
    series = _series([0.01, 0.02, 0.03])
    annualized, uncertainty = _inputs(series)
    assert uncertainty is None

    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(
            maximum_lag=1,
            kernel=HACKernel.BARTLETT,
        ),
    )

    assert result is not None
    assert result.status is SerialAdjustmentStatus.SHARPE_UNCERTAINTY_UNAVAILABLE
    assert result.hac_adjusted_annualized_sharpe_ratio is not None
    assert result.hac_period_sharpe_standard_error is None


def test_adjusted_psr_remains_undefined_without_benchmark() -> None:
    series = _series([0.01, 0.02, 0.03, 0.04, 0.05])
    annualized, uncertainty = _inputs(series)

    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(
            maximum_lag=1,
            kernel=HACKernel.BARTLETT,
        ),
    )

    assert result is not None
    assert result.status is SerialAdjustmentStatus.ELIGIBLE
    assert result.hac_period_sharpe_standard_error is not None
    assert result.hac_probabilistic_sharpe_ratio is None
    assert result.hac_minimum_required_observations is None


def test_adjustment_rejects_mismatched_psr_benchmark() -> None:
    series = _series([0.01, 0.02, 0.03, 0.04, 0.05])
    original_spec = ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0)
    annualized, uncertainty = _inputs(
        series,
        psr_spec=original_spec,
    )

    with pytest.raises(ValueError):
        calculate_serial_adjustment(
            series,
            annualized,
            uncertainty,
            spec=SerialAdjustmentSpec(
                maximum_lag=1,
                kernel=HACKernel.BARTLETT,
            ),
            psr_spec=ProbabilisticSharpeRatioSpec(
                benchmark_annualized_sharpe_ratio=1.0
            ),
        )
