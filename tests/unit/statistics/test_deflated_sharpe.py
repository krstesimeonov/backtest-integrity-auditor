import math
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest
from scipy.stats import kurtosis, skew

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
    effective_count: int | None = None,
) -> DeflatedSharpeRatioSpec:
    return DeflatedSharpeRatioSpec(
        method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        annual_risk_free_rate=0.03,
        required_confidence_level=0.95,
        effective_independent_trial_count=effective_count,
        effective_trial_count_methodology=(
            None if effective_count is None else "predeclared cluster count"
        ),
    )


def _family(
    values: np.ndarray = _VALUES,
    *,
    selected_index: int = 0,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
    periods_per_year: int | None = 252,
    search_complete: bool = True,
    declared_total: int = 2,
    include_excluded_and_failed: bool = False,
) -> ExperimentFamily:
    matrix_values = np.asarray(values, dtype=np.float64)
    completed_ids = ["trial-1", "trial-2"]
    trials = [
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == selected_index,
            selection_score=(2.0 if index == selected_index else 1.0),
            parameters=(TrialParameter("lookback", 10 + index),),
        )
        for index, trial_id in enumerate(completed_ids)
    ]
    if include_excluded_and_failed:
        completed_ids.append("trial-3")
        excluded_values = np.mean(matrix_values[:, :2], axis=1)
        matrix_values = np.column_stack([matrix_values, excluded_values])
        trials.extend(
            [
                ExperimentTrial(
                    trial_id="trial-3",
                    attempt_index=3,
                    outcome=TrialOutcome.COMPLETED,
                    included_in_selection=False,
                    selected=False,
                    selection_score=0.5,
                    parameters=(TrialParameter("lookback", 12),),
                    reason="Predeclared turnover constraint",
                ),
                ExperimentTrial(
                    trial_id="trial-4",
                    attempt_index=4,
                    outcome=TrialOutcome.FAILED,
                    included_in_selection=False,
                    selected=False,
                    selection_score=None,
                    parameters=(TrialParameter("lookback", 13),),
                    reason="Engine rejected invalid configuration",
                ),
            ]
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
            selected_trial_id=f"trial-{selected_index + 1}",
            selection_rule="maximize observed Sharpe",
            selection_metric="sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
            return_convention=convention,
            sampling=sampling,
        ),
        trials=tuple(trials),
        returns=TrialReturnMatrix(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=len(matrix_values),
                freq="B",
            ),
            trial_ids=tuple(completed_ids),
            values=matrix_values,
            convention=convention,
            sampling=sampling,
        ),
    )


def test_classic_dsr_reproduces_independent_reference_calculation() -> None:
    result = calculate_deflated_sharpe_ratio(_family(), _spec())

    period_rf = math.expm1(math.log1p(0.03) / 252)
    sharpes = np.asarray(
        [
            (np.mean(_VALUES[:, index]) - period_rf) / np.std(_VALUES[:, index], ddof=1)
            for index in range(2)
        ]
    )
    selected = sharpes[0]
    cross_trial_std = float(np.std(sharpes, ddof=1))
    expected_maximum_z = (1.0 - 0.5772156649015329) * NormalDist().inv_cdf(
        1.0 - 1.0 / 2.0
    ) + 0.5772156649015329 * NormalDist().inv_cdf(1.0 - 1.0 / (2.0 * math.e))
    selected_skew = float(skew(_VALUES[:, 0], bias=False))
    selected_kurtosis = float(kurtosis(_VALUES[:, 0], fisher=False, bias=False))
    variance_adjustment = (
        1.0 - selected_skew * selected + (selected_kurtosis - 1.0) / 4.0 * selected**2
    )
    standard_error = math.sqrt(variance_adjustment / 7.0)
    expected_threshold = cross_trial_std * expected_maximum_z
    expected_dsr = NormalDist().cdf((selected - expected_threshold) / standard_error)
    primary = result.scenarios[0]

    assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE
    assert result.effective_trial_count_verified is None
    assert result.period_risk_free_rate == pytest.approx(period_rf)
    assert result.selected_period_sharpe_ratio == pytest.approx(selected)
    assert result.cross_trial_sample_standard_deviation == pytest.approx(
        cross_trial_std
    )
    assert result.selected_sample_skewness == pytest.approx(selected_skew)
    assert result.selected_sample_pearson_kurtosis == pytest.approx(selected_kurtosis)
    assert primary.trial_count_basis is (DSRTrialCountBasis.SELECTION_ELIGIBLE)
    assert primary.expected_maximum_standard_normal == pytest.approx(expected_maximum_z)
    assert primary.expected_maximum_period_sharpe_ratio == pytest.approx(
        expected_threshold
    )
    assert primary.deflated_sharpe_ratio == pytest.approx(expected_dsr)


def test_declared_attempt_sensitivity_retains_failed_and_excluded_attempts() -> None:
    result = calculate_deflated_sharpe_ratio(
        _family(
            declared_total=4,
            include_excluded_and_failed=True,
        ),
        _spec(),
    )
    primary, declared = result.scenarios

    assert result.completed_trial_count == 3
    assert result.selection_eligible_trial_count == 2
    assert result.declared_attempted_trial_count == 4
    assert primary.trial_count == 2
    assert declared.trial_count_basis is DSRTrialCountBasis.DECLARED_ATTEMPTS
    assert declared.trial_count == 4
    assert declared.expected_maximum_period_sharpe_ratio > (
        primary.expected_maximum_period_sharpe_ratio
    )
    assert declared.deflated_sharpe_ratio < primary.deflated_sharpe_ratio


def test_user_supplied_effective_count_is_a_separate_unverified_scenario() -> None:
    result = calculate_deflated_sharpe_ratio(
        _family(),
        _spec(effective_count=1),
    )
    effective = result.scenarios[2]

    assert effective.trial_count_basis is (DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE)
    assert effective.trial_count == 1
    assert effective.expected_maximum_standard_normal == 0.0
    assert effective.deflated_sharpe_ratio > (result.scenarios[0].deflated_sharpe_ratio)
    assert result.effective_trial_count_verified is False


def test_trial_correlation_summary_reproduces_aligned_return_evidence() -> None:
    result = calculate_deflated_sharpe_ratio(_family(), _spec())
    expected = float(np.corrcoef(_VALUES, rowvar=False)[0, 1])
    correlation = result.correlation_summary

    assert correlation is not None
    assert correlation.pair_count == 1
    assert correlation.minimum_correlation == pytest.approx(expected)
    assert correlation.maximum_correlation == pytest.approx(expected)
    assert correlation.strongest_absolute_correlation == pytest.approx(abs(expected))
    assert correlation.strongest_absolute_correlation_trial_ids == (
        "trial-1",
        "trial-2",
    )


def test_log_and_simple_family_inputs_produce_equivalent_dsr() -> None:
    simple = calculate_deflated_sharpe_ratio(_family(), _spec())
    logged = calculate_deflated_sharpe_ratio(
        _family(
            values=np.log1p(_VALUES),
            convention=ReturnConvention.LOG,
        ),
        _spec(),
    )

    assert logged.return_basis is ReturnConvention.SIMPLE
    assert logged.selected_period_sharpe_ratio == pytest.approx(
        simple.selected_period_sharpe_ratio
    )
    assert logged.scenarios[0].deflated_sharpe_ratio == pytest.approx(
        simple.scenarios[0].deflated_sharpe_ratio
    )


def test_incomplete_family_preserves_configured_ineligible_result() -> None:
    result = calculate_deflated_sharpe_ratio(
        _family(search_complete=False, declared_total=3),
        _spec(),
    )

    assert result.status is DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE
    assert result.annual_risk_free_rate == 0.03
    assert result.required_confidence_level == 0.95
    assert result.scenarios == ()


def test_missing_periods_per_year_withholds_period_risk_free_conversion() -> None:
    result = calculate_deflated_sharpe_ratio(
        _family(periods_per_year=None),
        _spec(),
    )

    assert result.status is (DeflatedSharpeRatioStatus.PERIODS_PER_YEAR_UNAVAILABLE)
    assert result.period_risk_free_rate is None
    assert result.trial_sharpe_estimates == ()


def test_zero_volatility_selection_trial_is_not_silently_removed() -> None:
    values = _VALUES.copy()
    values[:, 1] = 0.001
    result = calculate_deflated_sharpe_ratio(
        _family(values=values),
        _spec(),
    )

    assert result.status is (
        DeflatedSharpeRatioStatus.INCOMPLETE_TRIAL_SHARPE_DISTRIBUTION
    )
    assert result.valid_selection_trial_sharpe_count == 1
    assert result.trial_sharpe_estimates[1].period_sharpe_ratio is None
    assert result.correlation_summary is None


def test_non_maximum_selected_trial_withholds_classical_winner_dsr() -> None:
    result = calculate_deflated_sharpe_ratio(
        _family(selected_index=1),
        _spec(),
    )

    assert result.status is (
        DeflatedSharpeRatioStatus.SELECTED_TRIAL_NOT_MAXIMUM_SHARPE
    )
    assert result.selected_is_observed_maximum is False
    assert result.observed_maximum_trial_ids == ("trial-1",)
    assert result.scenarios == ()


def test_effective_count_cannot_exceed_documented_selection_set() -> None:
    result = calculate_deflated_sharpe_ratio(
        _family(),
        _spec(effective_count=3),
    )

    assert result.status is (DeflatedSharpeRatioStatus.INVALID_EFFECTIVE_TRIAL_COUNT)
    assert result.effective_independent_trial_count == 3
    assert result.scenarios == ()


def test_identical_trial_sharpes_have_zero_selection_threshold() -> None:
    values = np.column_stack([_VALUES[:, 0], _VALUES[:, 0]])
    result = calculate_deflated_sharpe_ratio(
        _family(values=values),
        _spec(),
    )

    assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE
    assert result.cross_trial_sample_standard_deviation == pytest.approx(0.0)
    assert result.scenarios[0].expected_maximum_period_sharpe_ratio == 0.0


@pytest.mark.parametrize(
    ("effective_count", "methodology"),
    [(1, None), (None, "cluster count"), (0, "cluster count")],
)
def test_dsr_spec_rejects_incomplete_or_invalid_effective_count(
    effective_count: int | None,
    methodology: str | None,
) -> None:
    with pytest.raises(ValueError):
        DeflatedSharpeRatioSpec(
            method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
            trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
            annual_risk_free_rate=0.0,
            required_confidence_level=0.95,
            effective_independent_trial_count=effective_count,
            effective_trial_count_methodology=methodology,
        )
