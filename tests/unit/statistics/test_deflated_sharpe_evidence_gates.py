import math

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import DeflatedSharpeRatioSpec
from backtest_auditor.domain.enums import (
    DeflatedSharpeRatioMethod,
    DeflatedSharpeRatioStatus,
    DSRTrialCountBasis,
    DSRTrialCountPolicy,
    ReturnConvention,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (
    ExperimentFamily,
    ExperimentFamilyManifest,
    ExperimentTrial,
    TrialParameter,
    TrialReturnMatrix,
)
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.statistics.deflated_sharpe import (
    calculate_deflated_sharpe_ratio,
)

_VALUES = np.asarray(
    [
        [0.020, 0.010],
        [-0.005, -0.010],
        [0.018, 0.005],
        [0.004, 0.003],
        [0.015, 0.004],
        [-0.002, -0.008],
        [0.012, 0.006],
        [0.006, 0.002],
    ],
    dtype=np.float64,
)


def _spec(
    *,
    annual_risk_free_rate: float = 0.03,
    required_confidence_level: float = 0.95,
    effective_count: int | None = None,
) -> DeflatedSharpeRatioSpec:
    return DeflatedSharpeRatioSpec(
        method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        annual_risk_free_rate=annual_risk_free_rate,
        required_confidence_level=required_confidence_level,
        effective_independent_trial_count=effective_count,
        effective_trial_count_methodology=(
            None if effective_count is None else "predeclared cluster count"
        ),
    )


def _family(
    values: np.ndarray = _VALUES,
    *,
    selected_index: int = 0,
    periods_per_year: int | None = 252,
    search_complete: bool = True,
    declared_total: int = 2,
) -> ExperimentFamily:
    matrix_values = np.asarray(values, dtype=np.float64)
    trial_ids = ("trial-1", "trial-2")
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == selected_index,
            selection_score=(2.0 if index == selected_index else 1.0),
            parameters=(TrialParameter("lookback", 10 + index),),
        )
        for index, trial_id in enumerate(trial_ids)
    )
    sampling = SamplingSpec(
        declared_frequency="B",
        periods_per_year=periods_per_year,
    )
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="dsr-family",
            declared_total_attempted_trials=declared_total,
            search_complete=search_complete,
            selected_trial_id=trial_ids[selected_index],
            selection_rule="maximize observed Sharpe",
            selection_metric="sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=len(matrix_values),
                freq="B",
            ),
            trial_ids=trial_ids,
            values=matrix_values,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


def _valid_selection_sharpes_reported(result) -> int:
    return sum(
        1
        for estimate in result.trial_sharpe_estimates
        if estimate.included_in_selection and estimate.period_sharpe_ratio is not None
    )


def test_undeclared_complete_search_is_ineligible_even_with_every_attempt_listed() -> (
    None
):
    # Every declared attempt is documented (2 of 2), but the author has not
    # declared the search complete. The gate needs both.
    result = calculate_deflated_sharpe_ratio(
        _family(search_complete=False, declared_total=2),
        _spec(),
    )

    assert result.status is DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE
    assert result.scenarios == ()


@pytest.mark.parametrize(
    ("observation_count", "expected_status"),
    [
        (3, DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE),
        (4, DeflatedSharpeRatioStatus.ELIGIBLE),
    ],
)
def test_evidence_gate_requires_at_least_four_observations(
    observation_count: int,
    expected_status: DeflatedSharpeRatioStatus,
) -> None:
    # docs/DEFLATED_SHARPE_RATIO_METHODOLOGY.md: "at least four exactly aligned
    # observations exist".
    result = calculate_deflated_sharpe_ratio(
        _family(_VALUES[:observation_count]),
        _spec(),
    )

    assert result.observation_count == observation_count
    assert result.status is expected_status
    if expected_status is DeflatedSharpeRatioStatus.ELIGIBLE:
        # SE(SR) = sqrt(A / (n - 1)) with n - 1 = 3.
        assert result.selected_period_sharpe_standard_error == pytest.approx(
            math.sqrt(result.selected_sharpe_variance_adjustment / 3.0)
        )


def test_one_period_per_year_is_a_positive_explicit_sampling_rate() -> None:
    result = calculate_deflated_sharpe_ratio(
        _family(periods_per_year=1),
        _spec(annual_risk_free_rate=0.03),
    )

    assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE
    assert result.periods_per_year == 1
    # With one period per year the period rate is the annual rate, and the
    # IID sqrt(1) scaling leaves every Sharpe unchanged.
    assert result.period_risk_free_rate == pytest.approx(0.03)
    assert result.selected_iid_annualized_sharpe_ratio == pytest.approx(
        result.selected_period_sharpe_ratio
    )
    primary = result.scenarios[0]
    assert primary.expected_maximum_iid_annualized_sharpe_ratio == pytest.approx(
        primary.expected_maximum_period_sharpe_ratio
    )


def test_effective_count_equal_to_the_selection_set_reproduces_the_primary_dsr() -> (
    None
):
    # The docs only forbid an effective count that EXCEEDS the selection set.
    # At N_eff = N the expected maximum, and therefore the DSR, is unchanged.
    result = calculate_deflated_sharpe_ratio(
        _family(),
        _spec(effective_count=2),
    )

    assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE
    primary, _declared, effective = result.scenarios
    assert effective.trial_count_basis is DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE
    assert effective.trial_count == primary.trial_count == 2
    assert effective.expected_maximum_standard_normal == pytest.approx(
        primary.expected_maximum_standard_normal
    )
    assert effective.deflated_sharpe_ratio == pytest.approx(
        primary.deflated_sharpe_ratio
    )


@pytest.mark.parametrize("sharpe_ratio", [0.5, 1.0, 2.0])
def test_dsr_is_withheld_unless_the_variance_adjustment_is_positive(
    sharpe_ratio: float,
) -> None:
    # Selected returns sit at mean +/- d, two of each, with a zero risk-free
    # rate. By hand, for n = 4:
    #   sample sd  = sqrt(4 d^2 / 3) = d * sqrt(4 / 3)
    #   skewness   = 0                        (symmetric deviations)
    #   b2         = m4 / m2^2 = d^4 / d^4 = 1
    #   kurtosis   = 3 + (n-1)/((n-2)(n-3)) * ((n+1) b2 - 3(n-1))
    #              = 3 + 1.5 * (5 - 9) = -3
    #   A          = 1 - 0 * SR + (-3 - 1) / 4 * SR^2 = 1 - SR^2
    # so SR = 0.5, 1, 2 give A = 0.75, 0, -3. With d a power of two every
    # moment is exact in binary, so A = 0 is exactly zero, not merely small.
    d = 2.0**-6
    mean = sharpe_ratio * d * math.sqrt(4.0 / 3.0)
    selected = [mean - d, mean - d, mean + d, mean + d]
    other = [0.01, -0.02, 0.03, -0.01]
    expected_adjustment = 1.0 - sharpe_ratio**2

    result = calculate_deflated_sharpe_ratio(
        _family(np.column_stack([selected, other])),
        _spec(annual_risk_free_rate=0.0),
    )

    assert result.selected_period_sharpe_ratio == pytest.approx(sharpe_ratio)
    assert result.selected_sample_skewness == pytest.approx(0.0, abs=1e-12)
    assert result.selected_sample_pearson_kurtosis == pytest.approx(-3.0)
    assert result.selected_sharpe_variance_adjustment == pytest.approx(
        expected_adjustment, abs=1e-12
    )
    # docs: DSR requires the adjustment to be "finite and positive".
    if expected_adjustment > 0.0:
        assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE
        assert result.selected_period_sharpe_standard_error == pytest.approx(
            math.sqrt(expected_adjustment / 3.0)
        )
    else:
        assert result.status is (
            DeflatedSharpeRatioStatus.NON_POSITIVE_SHARPE_VARIANCE_ADJUSTMENT
        )
        assert result.selected_period_sharpe_standard_error is None
        assert result.scenarios == ()


def test_confidence_requirement_is_met_exactly_at_the_required_level() -> None:
    # docs: "The confidence requirement is met when DSR >= required_confidence_level".
    # The level is a decision threshold, not an input to the DSR itself, so
    # moving it onto the DSR must leave the DSR unchanged.
    baseline = calculate_deflated_sharpe_ratio(_family(), _spec())
    dsr = baseline.scenarios[0].deflated_sharpe_ratio
    assert 0.5 < dsr < 1.0

    at_level = calculate_deflated_sharpe_ratio(
        _family(),
        _spec(required_confidence_level=dsr),
    )
    just_above = calculate_deflated_sharpe_ratio(
        _family(),
        _spec(required_confidence_level=math.nextafter(dsr, 1.0)),
    )

    for scenario in at_level.scenarios:
        assert scenario.deflated_sharpe_ratio == dsr
        assert scenario.confidence_requirement_met is True
    for scenario in just_above.scenarios:
        assert scenario.deflated_sharpe_ratio == dsr
        assert scenario.confidence_requirement_met is False


@pytest.mark.parametrize(
    ("family", "expected_status"),
    [
        (
            _family(search_complete=False, declared_total=2),
            DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE,
        ),
        (
            _family(periods_per_year=None),
            DeflatedSharpeRatioStatus.PERIODS_PER_YEAR_UNAVAILABLE,
        ),
        (
            _family(np.column_stack([_VALUES[:, 0], np.full(8, 0.25)])),
            DeflatedSharpeRatioStatus.INCOMPLETE_TRIAL_SHARPE_DISTRIBUTION,
        ),
        (_family(), DeflatedSharpeRatioStatus.ELIGIBLE),
    ],
)
def test_valid_sharpe_count_matches_the_reported_estimates(
    family: ExperimentFamily,
    expected_status: DeflatedSharpeRatioStatus,
) -> None:
    result = calculate_deflated_sharpe_ratio(family, _spec())

    assert result.status is expected_status
    assert result.valid_selection_trial_sharpe_count == (
        _valid_selection_sharpes_reported(result)
    )


@pytest.mark.parametrize(
    "family",
    [
        _family(search_complete=False, declared_total=2),
        _family(_VALUES[:3]),
    ],
)
def test_withheld_result_still_reports_the_declared_periods_per_year(
    family: ExperimentFamily,
) -> None:
    result = calculate_deflated_sharpe_ratio(family, _spec())

    assert result.status is DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE
    assert result.periods_per_year == 252


@pytest.mark.parametrize(
    ("family", "effective_count", "expected_status", "expected_verified"),
    [
        (
            _family(search_complete=False, declared_total=2),
            None,
            DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE,
            None,
        ),
        (
            _family(search_complete=False, declared_total=2),
            1,
            DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE,
            False,
        ),
        (
            _family(),
            3,
            DeflatedSharpeRatioStatus.INVALID_EFFECTIVE_TRIAL_COUNT,
            False,
        ),
    ],
)
def test_withheld_result_never_claims_the_effective_count_was_verified(
    family: ExperimentFamily,
    effective_count: int | None,
    expected_status: DeflatedSharpeRatioStatus,
    expected_verified: bool | None,
) -> None:
    # docs: the count is reported as user-supplied and the auditor "does not
    # claim to verify" it: None when absent, False when supplied, never True.
    result = calculate_deflated_sharpe_ratio(
        family,
        _spec(effective_count=effective_count),
    )

    assert result.status is expected_status
    assert result.effective_trial_count_verified is expected_verified


def test_correlation_is_reported_for_a_trial_with_unit_sample_volatility() -> None:
    # A sample volatility of exactly 1.0 is ordinary variation, not degeneracy.
    #   x = [0, 0, 0, 2]: mean 0.5, deviations (-.5, -.5, -.5, 1.5), sum sq 3
    #                     -> sample sd sqrt(3 / 3) = 1
    #   y = [0, 0, 1, 1]: mean 0.5, deviations (-.5, -.5, .5, .5), sum sq 1
    #   sum dx*dy = .25 + .25 - .25 + .75 = 1
    #   r = 1 / sqrt(3 * 1) = 1 / sqrt(3)
    values = np.column_stack([[0.0, 0.0, 0.0, 2.0], [0.0, 0.0, 1.0, 1.0]])

    result = calculate_deflated_sharpe_ratio(
        _family(values, selected_index=1),
        _spec(annual_risk_free_rate=0.0),
    )

    assert result.trial_sharpe_estimates[0].period_sample_volatility == 1.0
    correlation = result.correlation_summary
    assert correlation is not None
    assert correlation.minimum_correlation == pytest.approx(1.0 / math.sqrt(3.0))
    assert correlation.maximum_correlation == pytest.approx(1.0 / math.sqrt(3.0))
