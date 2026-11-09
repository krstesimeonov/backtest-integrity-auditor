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
    calculate_bartlett_hac_ratio,
    calculate_serial_adjustment,
)
from backtest_auditor.statistics.sharpe_uncertainty import (
    calculate_sharpe_uncertainty,
)

# A mildly autocorrelated daily series with a clearly positive Sharpe
# (annualized about 16), so a benchmark can sit on either side of it.
VALUES = [
    0.012,
    0.004,
    0.009,
    -0.003,
    0.011,
    0.006,
    -0.001,
    0.008,
    0.010,
    0.002,
    0.007,
    -0.004,
    0.013,
    0.005,
    0.003,
    0.009,
    -0.002,
    0.006,
    0.011,
    0.001,
]


def _series(
    values: list[float],
    *,
    periods_per_year: int = 252,
) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range(
            "2026-01-01",
            periods=len(values),
            freq="D",
        ),
        values=np.asarray(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(periods_per_year=periods_per_year),
    )


def _adjust(
    values: list[float],
    *,
    benchmark: float,
    confidence: float | None = None,
    periods_per_year: int = 252,
    maximum_lag: int = 2,
):
    series = _series(values, periods_per_year=periods_per_year)
    psr_spec = ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=benchmark,
        required_psr_confidence_level=confidence,
    )
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
    result = calculate_serial_adjustment(
        series,
        annualized,
        uncertainty,
        spec=SerialAdjustmentSpec(
            maximum_lag=maximum_lag,
            kernel=HACKernel.BARTLETT,
        ),
        psr_spec=psr_spec,
    )
    return annualized, uncertainty, result


def test_hac_requirement_is_met_when_psr_equals_the_required_level() -> None:
    # README Part F/H: MinTRL is the length at which PSR reaches the required
    # confidence, and the finding for an unmet requirement says PSR "is below"
    # it. With c = Phi(d / SE_hac) and SE_hac = sqrt(A * D / (n - 1)),
    #   HAC MinTRL = 1 + A * D * (Phi^-1(c) / d)**2 = 1 + (n - 1) = n.
    # A non-zero benchmark makes (SR - SR*) and (SR + SR*) disagree.
    _, _, reference = _adjust(VALUES, benchmark=12.0)
    achieved = reference.hac_probabilistic_sharpe_ratio
    assert achieved is not None
    assert 0.5 < achieved < 1.0

    _, _, at_level = _adjust(VALUES, benchmark=12.0, confidence=achieved)
    _, _, above_level = _adjust(
        VALUES,
        benchmark=12.0,
        confidence=float(np.nextafter(achieved, 1.0)),
    )

    assert at_level.hac_confidence_requirement_met is True
    assert at_level.hac_minimum_track_record_length_observations == pytest.approx(
        len(VALUES), rel=1e-9
    )
    assert above_level.hac_confidence_requirement_met is False


def test_hac_mintrl_is_undefined_when_sharpe_equals_the_benchmark() -> None:
    # README Part F: "If the observed Sharpe does not exceed the selected
    # benchmark, no finite MinTRL is reported." Equality does not exceed.
    annualized, _, _ = _adjust(VALUES, benchmark=0.0)
    _, uncertainty, result = _adjust(
        VALUES,
        benchmark=annualized.annualized_sharpe_ratio,
        confidence=0.95,
    )

    assert uncertainty.period_sharpe_ratio == uncertainty.benchmark_period_sharpe_ratio
    assert result.status is SerialAdjustmentStatus.ELIGIBLE
    assert result.hac_probabilistic_sharpe_ratio == pytest.approx(0.5)
    assert result.hac_confidence_requirement_met is False
    assert result.hac_minimum_track_record_length_observations is None
    assert result.hac_minimum_required_observations is None
    assert result.hac_additional_observations_required is None
    assert result.hac_observations_above_minimum is None


def test_hac_shortfall_reports_additional_observations_and_no_surplus() -> None:
    # observation count + shortfall - surplus must equal the operational
    # minimum, and a record below the minimum has no surplus.
    #
    # Why this input falls short, by hand: the period Sharpe is about 1.07
    # against a benchmark of 12 / sqrt(252) = 0.756, so even the i.i.d. PSR is
    # only about Phi(1.08) = 0.86. Reaching 0.95 would need the HAC variance
    # ratio below about 0.43, so the requirement is unmet and the minimum
    # exceeds the sample -- which is what the first three asserts check.
    _, _, result = _adjust(VALUES, benchmark=12.0, confidence=0.95)

    assert result.hac_confidence_requirement_met is False
    minimum = result.hac_minimum_required_observations
    assert minimum is not None
    assert minimum > len(VALUES)
    assert result.hac_additional_observations_required == minimum - len(VALUES)
    assert result.hac_observations_above_minimum == 0
    assert (
        len(VALUES)
        + result.hac_additional_observations_required
        - result.hac_observations_above_minimum
        == minimum
    )


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_non_finite_return_long_run_variance_publishes_no_hac_sharpe() -> None:
    # Squared deviations of 1.5e154 overflow, so the return autocorrelations
    # are inf / inf. The ratio is unusable and must not reach the HAC Sharpe.
    _, _, result = _adjust(
        [3e154, 0.0] * 5,
        benchmark=0.0,
        periods_per_year=4,
        maximum_lag=1,
    )

    assert result.status is not SerialAdjustmentStatus.ELIGIBLE
    assert result.hac_annualization_factor is None
    assert result.hac_adjusted_annualized_sharpe_ratio is None
    assert result.hac_probabilistic_sharpe_ratio is None


def test_influence_series_with_unit_variance_is_not_degenerate() -> None:
    # The centred base is symmetric (+-0.005, +-0.015, +-0.025, +-0.035), so
    # with z = centred / sample sd: sum(z**3) = 0 and
    # sum((z**2 - 7/8)**2) = 14/3. For psi = z - (SR/2)(z**2 - 1) (README
    # Part H), population var(psi) = 7/8 + SR**2 * (14/3) / (4 * 8), which is
    # exactly 1 at SR = sqrt(6/7). A unit-variance influence series is not
    # degenerate, so the HAC PSR must be produced.
    base = np.asarray([0.02, -0.01, 0.03, 0.0, -0.02, 0.01, 0.04, -0.03])
    location = math.sqrt(6 / 7) * float(np.std(base, ddof=1)) - float(np.mean(base))
    values = (base + location).tolist()

    _, uncertainty, result = _adjust(
        values,
        benchmark=0.0,
        periods_per_year=4,
        maximum_lag=1,
    )

    assert uncertainty.period_sharpe_ratio == pytest.approx(math.sqrt(6 / 7))
    assert result.status is SerialAdjustmentStatus.ELIGIBLE
    assert result.hac_probabilistic_sharpe_ratio is not None
    assert 0.5 < result.hac_probabilistic_sharpe_ratio < 1.0


def test_bartlett_ratio_matches_hand_calculation_for_alternating_series() -> None:
    # Centred values +-0.5, sum of squares 1.
    #   rho_1 = 3 * (-0.25) / 1 = -0.75, rho_2 = 2 * 0.25 / 1 = 0.5
    #   w_1 = 1 - 1/3 = 2/3, w_2 = 1 - 2/3 = 1/3
    #   D = 1 + 2 * (2/3 * -0.75 + 1/3 * 0.5) = 1 + 2 * (-1/3) = 1/3
    estimates, ratio = calculate_bartlett_hac_ratio(
        np.asarray([0.5, -0.5, 0.5, -0.5]),
        maximum_lag=2,
    )

    assert [item.autocorrelation for item in estimates] == pytest.approx([-0.75, 0.5])
    assert [item.kernel_weight for item in estimates] == pytest.approx([2 / 3, 1 / 3])
    assert ratio == pytest.approx(1 / 3)


def test_bartlett_ratio_is_unusable_for_bit_identical_values() -> None:
    # Autocorrelation is 0 / 0 for a constant sample. np.full(10, 0.001)
    # centres to a ~1e-19 rounding residue rather than to zero (see
    # degeneracy.py), and a moving-block bootstrap replicate can be exactly
    # this, so callers must receive no estimates and a ratio they reject.
    estimates, ratio = calculate_bartlett_hac_ratio(
        np.full(10, 0.001),
        maximum_lag=2,
    )

    assert estimates == ()
    assert not (math.isfinite(ratio) and ratio > 0.0)
