import math
from statistics import NormalDist
from typing import Any

import numpy as np

from backtest_auditor.domain.assumptions import DeflatedSharpeRatioSpec
from backtest_auditor.domain.enums import (
    DeflatedSharpeRatioStatus,
    DSRTrialCountBasis,
    ReturnConvention,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import ExperimentFamily
from backtest_auditor.domain.results import (
    DeflatedSharpeRatioResult,
    DeflatedSharpeScenarioResult,
    TrialCorrelationSummaryResult,
    TrialSharpeEstimate,
)
from backtest_auditor.statistics.degeneracy import (
    columns_with_zero_sample_variation,
    has_zero_sample_variation,
)
from backtest_auditor.statistics.distribution import (
    calculate_distribution_statistics,
)
from backtest_auditor.statistics.return_basis import (
    annual_to_period_rate,
    to_simple_returns,
)

_EULER_MASCHERONI = 0.5772156649015329


def calculate_deflated_sharpe_ratio(
    family: ExperimentFamily,
    spec: DeflatedSharpeRatioSpec,
) -> DeflatedSharpeRatioResult:
    """Calculate classical location-only DSR for a complete trial family."""

    manifest = family.manifest
    completed = tuple(
        trial for trial in family.trials if trial.outcome is TrialOutcome.COMPLETED
    )
    selection_eligible = tuple(
        trial for trial in completed if trial.included_in_selection
    )
    observation_count = len(family.returns.timestamps)
    complete_search_history = (
        manifest.search_complete
        and len(family.trials) == manifest.declared_total_attempted_trials
    )

    if (
        not complete_search_history
        or len(selection_eligible) < 2
        or observation_count < 4
    ):
        return _unavailable_result(
            family,
            spec,
            status=DeflatedSharpeRatioStatus.FAMILY_INELIGIBLE,
            completed_trial_count=len(completed),
            selection_eligible_trial_count=len(selection_eligible),
        )

    periods_per_year = family.returns.sampling.periods_per_year
    if periods_per_year is None or periods_per_year <= 0:
        return _unavailable_result(
            family,
            spec,
            status=(DeflatedSharpeRatioStatus.PERIODS_PER_YEAR_UNAVAILABLE),
            completed_trial_count=len(completed),
            selection_eligible_trial_count=len(selection_eligible),
        )

    period_risk_free_rate = annual_to_period_rate(
        spec.annual_risk_free_rate,
        periods_per_year,
    )
    square_root_of_periods = math.sqrt(periods_per_year)
    estimates = _calculate_trial_sharpe_estimates(
        family,
        completed,
        period_risk_free_rate=period_risk_free_rate,
        square_root_of_periods=square_root_of_periods,
    )
    estimate_by_id = {item.trial_id: item for item in estimates}
    eligible_estimates = tuple(
        estimate_by_id[trial.trial_id] for trial in selection_eligible
    )
    valid_eligible = tuple(
        item for item in eligible_estimates if item.period_sharpe_ratio is not None
    )
    correlation_summary = _calculate_correlation_summary(
        family,
        selection_eligible,
    )

    common: dict[str, Any] = {
        "periods_per_year": periods_per_year,
        "period_risk_free_rate": period_risk_free_rate,
        "completed_trial_count": len(completed),
        "selection_eligible_trial_count": len(selection_eligible),
        "valid_selection_trial_sharpe_count": len(valid_eligible),
        "trial_sharpe_estimates": estimates,
        "correlation_summary": correlation_summary,
    }
    if len(valid_eligible) != len(selection_eligible):
        return _unavailable_result(
            family,
            spec,
            status=(DeflatedSharpeRatioStatus.INCOMPLETE_TRIAL_SHARPE_DISTRIBUTION),
            **common,
        )

    effective_count = spec.effective_independent_trial_count
    if effective_count is not None and effective_count > len(selection_eligible):
        return _unavailable_result(
            family,
            spec,
            status=(DeflatedSharpeRatioStatus.INVALID_EFFECTIVE_TRIAL_COUNT),
            **common,
        )

    eligible_sharpes = np.asarray(
        [item.period_sharpe_ratio for item in valid_eligible],
        dtype=np.float64,
    )
    selected_estimate = estimate_by_id[manifest.selected_trial_id]
    assert selected_estimate.period_sharpe_ratio is not None
    selected_sharpe = selected_estimate.period_sharpe_ratio
    observed_maximum = float(np.max(eligible_sharpes))
    maximum_trial_ids = tuple(
        item.trial_id
        for item in valid_eligible
        if math.isclose(
            item.period_sharpe_ratio,  # type: ignore[arg-type]  # QUALITY.md
            observed_maximum,
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
    )
    selected_is_maximum = manifest.selected_trial_id in maximum_trial_ids
    cross_trial_mean = float(np.mean(eligible_sharpes))
    cross_trial_std = (
        0.0
        if has_zero_sample_variation(np.asarray(eligible_sharpes))
        else float(np.std(eligible_sharpes, ddof=1))
    )
    selection_values: dict[str, Any] = {
        "selected_period_sharpe_ratio": selected_sharpe,
        "selected_iid_annualized_sharpe_ratio": (
            selected_estimate.iid_annualized_sharpe_ratio
        ),
        "observed_maximum_period_sharpe_ratio": observed_maximum,
        "observed_maximum_trial_ids": maximum_trial_ids,
        "selected_is_observed_maximum": selected_is_maximum,
        "cross_trial_mean_period_sharpe_ratio": cross_trial_mean,
        "cross_trial_sample_standard_deviation": cross_trial_std,
    }
    if not selected_is_maximum:
        return _unavailable_result(
            family,
            spec,
            status=(DeflatedSharpeRatioStatus.SELECTED_TRIAL_NOT_MAXIMUM_SHARPE),
            **common,
            **selection_values,
        )

    selected_series = family.returns.series_for(manifest.selected_trial_id)
    distribution = calculate_distribution_statistics(selected_series)
    skewness = distribution.sample_skewness
    pearson_kurtosis = distribution.sample_pearson_kurtosis
    if skewness is None or pearson_kurtosis is None:
        return _unavailable_result(
            family,
            spec,
            status=(DeflatedSharpeRatioStatus.SELECTED_RETURN_MOMENTS_UNAVAILABLE),
            **common,
            **selection_values,
        )

    variance_adjustment = (
        1.0
        - skewness * selected_sharpe
        + (pearson_kurtosis - 1.0) / 4.0 * selected_sharpe**2
    )
    moment_values: dict[str, Any] = {
        "selected_sample_skewness": skewness,
        "selected_sample_pearson_kurtosis": pearson_kurtosis,
        "selected_sharpe_variance_adjustment": variance_adjustment,
    }
    if not math.isfinite(variance_adjustment) or variance_adjustment <= 0.0:
        return _unavailable_result(
            family,
            spec,
            status=(DeflatedSharpeRatioStatus.NON_POSITIVE_SHARPE_VARIANCE_ADJUSTMENT),
            **common,
            **selection_values,
            **moment_values,
        )

    standard_error = math.sqrt(variance_adjustment / (observation_count - 1))
    scenarios = [
        _calculate_scenario(
            basis=DSRTrialCountBasis.SELECTION_ELIGIBLE,
            trial_count=len(selection_eligible),
            cross_trial_standard_deviation=cross_trial_std,
            selected_period_sharpe_ratio=selected_sharpe,
            selected_period_standard_error=standard_error,
            square_root_of_periods=square_root_of_periods,
            required_confidence_level=spec.required_confidence_level,
        ),
        _calculate_scenario(
            basis=DSRTrialCountBasis.DECLARED_ATTEMPTS,
            trial_count=manifest.declared_total_attempted_trials,
            cross_trial_standard_deviation=cross_trial_std,
            selected_period_sharpe_ratio=selected_sharpe,
            selected_period_standard_error=standard_error,
            square_root_of_periods=square_root_of_periods,
            required_confidence_level=spec.required_confidence_level,
        ),
    ]
    if effective_count is not None:
        scenarios.append(
            _calculate_scenario(
                basis=DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE,
                trial_count=effective_count,
                cross_trial_standard_deviation=cross_trial_std,
                selected_period_sharpe_ratio=selected_sharpe,
                selected_period_standard_error=standard_error,
                square_root_of_periods=square_root_of_periods,
                required_confidence_level=spec.required_confidence_level,
            )
        )

    return DeflatedSharpeRatioResult(
        status=DeflatedSharpeRatioStatus.ELIGIBLE,
        method=spec.method,
        trial_count_policy=spec.trial_count_policy,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        required_confidence_level=spec.required_confidence_level,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_risk_free_rate,
        observation_count=observation_count,
        declared_attempted_trial_count=(manifest.declared_total_attempted_trials),
        completed_trial_count=len(completed),
        selection_eligible_trial_count=len(selection_eligible),
        valid_selection_trial_sharpe_count=len(valid_eligible),
        selected_trial_id=manifest.selected_trial_id,
        trial_sharpe_estimates=estimates,
        selected_period_sharpe_ratio=selected_sharpe,
        selected_iid_annualized_sharpe_ratio=(
            selected_estimate.iid_annualized_sharpe_ratio
        ),
        observed_maximum_period_sharpe_ratio=observed_maximum,
        observed_maximum_trial_ids=maximum_trial_ids,
        selected_is_observed_maximum=True,
        cross_trial_mean_period_sharpe_ratio=cross_trial_mean,
        cross_trial_sample_standard_deviation=cross_trial_std,
        selected_sample_skewness=skewness,
        selected_sample_pearson_kurtosis=pearson_kurtosis,
        selected_sharpe_variance_adjustment=variance_adjustment,
        selected_period_sharpe_standard_error=standard_error,
        correlation_summary=correlation_summary,
        effective_independent_trial_count=effective_count,
        effective_trial_count_methodology=(spec.effective_trial_count_methodology),
        effective_trial_count_verified=(None if effective_count is None else False),
        scenarios=tuple(scenarios),
    )


def _calculate_trial_sharpe_estimates(
    family: ExperimentFamily,
    completed: tuple,
    *,
    period_risk_free_rate: float,
    square_root_of_periods: float,
) -> tuple[TrialSharpeEstimate, ...]:
    estimates: list[TrialSharpeEstimate] = []
    for trial in completed:
        values = to_simple_returns(family.returns.series_for(trial.trial_id))
        mean_excess = float(np.mean(values) - period_risk_free_rate)
        # Normalised at the source, as descriptive.py does: np.std of a flat
        # trial is a rounding residue that would otherwise be published as its
        # volatility and turned into a Sharpe of about -4.9e15.
        sample_volatility = (
            0.0 if has_zero_sample_variation(values) else float(np.std(values, ddof=1))
        )
        period_sharpe = (
            None if sample_volatility == 0.0 else mean_excess / sample_volatility
        )
        estimates.append(
            TrialSharpeEstimate(
                trial_id=trial.trial_id,
                included_in_selection=trial.included_in_selection,
                selected=trial.selected,
                observation_count=len(values),
                period_mean_excess_return=mean_excess,
                period_sample_volatility=sample_volatility,
                period_sharpe_ratio=period_sharpe,
                iid_annualized_sharpe_ratio=(
                    None
                    if period_sharpe is None
                    else period_sharpe * square_root_of_periods
                ),
            )
        )
    return tuple(estimates)


def _calculate_correlation_summary(
    family: ExperimentFamily,
    selection_eligible: tuple,
) -> TrialCorrelationSummaryResult | None:
    values = np.column_stack(
        [
            to_simple_returns(family.returns.series_for(trial.trial_id))
            for trial in selection_eligible
        ]
    )
    if bool(np.any(columns_with_zero_sample_variation(values))) or any(
        float(np.std(values[:, index], ddof=1)) == 0.0
        for index in range(values.shape[1])
    ):
        return None

    matrix = np.corrcoef(values, rowvar=False)
    pairs: list[tuple[str, str, float]] = []
    for left in range(len(selection_eligible)):
        for right in range(left + 1, len(selection_eligible)):
            correlation = float(matrix[left, right])  # type: ignore[index]  # QUALITY.md
            if not math.isfinite(correlation):
                return None
            pairs.append(
                (
                    selection_eligible[left].trial_id,
                    selection_eligible[right].trial_id,
                    correlation,
                )
            )

    correlations = np.asarray([item[2] for item in pairs])
    strongest = max(pairs, key=lambda item: abs(item[2]))
    return TrialCorrelationSummaryResult(
        trial_count=len(selection_eligible),
        pair_count=len(pairs),
        minimum_correlation=float(np.min(correlations)),
        maximum_correlation=float(np.max(correlations)),
        mean_correlation=float(np.mean(correlations)),
        median_correlation=float(np.median(correlations)),
        strongest_absolute_correlation=abs(strongest[2]),
        strongest_absolute_correlation_trial_ids=(
            strongest[0],
            strongest[1],
        ),
    )


def _calculate_scenario(
    *,
    basis: DSRTrialCountBasis,
    trial_count: int,
    cross_trial_standard_deviation: float,
    selected_period_sharpe_ratio: float,
    selected_period_standard_error: float,
    square_root_of_periods: float,
    required_confidence_level: float,
) -> DeflatedSharpeScenarioResult:
    expected_standard_normal = _expected_maximum_standard_normal(trial_count)
    expected_period_sharpe = cross_trial_standard_deviation * expected_standard_normal
    test_statistic = (
        selected_period_sharpe_ratio - expected_period_sharpe
    ) / selected_period_standard_error
    probability = NormalDist().cdf(test_statistic)
    return DeflatedSharpeScenarioResult(
        trial_count_basis=basis,
        trial_count=trial_count,
        expected_maximum_standard_normal=expected_standard_normal,
        expected_maximum_period_sharpe_ratio=expected_period_sharpe,
        expected_maximum_iid_annualized_sharpe_ratio=(
            expected_period_sharpe * square_root_of_periods
        ),
        test_statistic=test_statistic,
        deflated_sharpe_ratio=probability,
        confidence_requirement_met=(probability >= required_confidence_level),
    )


def _expected_maximum_standard_normal(trial_count: int) -> float:
    if trial_count == 1:
        return 0.0
    normal = NormalDist()
    return (1.0 - _EULER_MASCHERONI) * normal.inv_cdf(
        1.0 - 1.0 / trial_count
    ) + _EULER_MASCHERONI * normal.inv_cdf(1.0 - 1.0 / (trial_count * math.e))


def _unavailable_result(
    family: ExperimentFamily,
    spec: DeflatedSharpeRatioSpec,
    *,
    status: DeflatedSharpeRatioStatus,
    completed_trial_count: int,
    selection_eligible_trial_count: int,
    periods_per_year: int | None = None,
    period_risk_free_rate: float | None = None,
    valid_selection_trial_sharpe_count: int = 0,
    trial_sharpe_estimates: tuple[TrialSharpeEstimate, ...] = (),
    selected_period_sharpe_ratio: float | None = None,
    selected_iid_annualized_sharpe_ratio: float | None = None,
    observed_maximum_period_sharpe_ratio: float | None = None,
    observed_maximum_trial_ids: tuple[str, ...] = (),
    selected_is_observed_maximum: bool | None = None,
    cross_trial_mean_period_sharpe_ratio: float | None = None,
    cross_trial_sample_standard_deviation: float | None = None,
    selected_sample_skewness: float | None = None,
    selected_sample_pearson_kurtosis: float | None = None,
    selected_sharpe_variance_adjustment: float | None = None,
    selected_period_sharpe_standard_error: float | None = None,
    correlation_summary: TrialCorrelationSummaryResult | None = None,
) -> DeflatedSharpeRatioResult:
    if periods_per_year is None:
        periods_per_year = family.returns.sampling.periods_per_year
    return DeflatedSharpeRatioResult(
        status=status,
        method=spec.method,
        trial_count_policy=spec.trial_count_policy,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        required_confidence_level=spec.required_confidence_level,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_risk_free_rate,
        observation_count=len(family.returns.timestamps),
        declared_attempted_trial_count=(
            family.manifest.declared_total_attempted_trials
        ),
        completed_trial_count=completed_trial_count,
        selection_eligible_trial_count=selection_eligible_trial_count,
        valid_selection_trial_sharpe_count=(valid_selection_trial_sharpe_count),
        selected_trial_id=family.manifest.selected_trial_id,
        trial_sharpe_estimates=trial_sharpe_estimates,
        selected_period_sharpe_ratio=selected_period_sharpe_ratio,
        selected_iid_annualized_sharpe_ratio=(selected_iid_annualized_sharpe_ratio),
        observed_maximum_period_sharpe_ratio=(observed_maximum_period_sharpe_ratio),
        observed_maximum_trial_ids=observed_maximum_trial_ids,
        selected_is_observed_maximum=selected_is_observed_maximum,
        cross_trial_mean_period_sharpe_ratio=(cross_trial_mean_period_sharpe_ratio),
        cross_trial_sample_standard_deviation=(cross_trial_sample_standard_deviation),
        selected_sample_skewness=selected_sample_skewness,
        selected_sample_pearson_kurtosis=(selected_sample_pearson_kurtosis),
        selected_sharpe_variance_adjustment=(selected_sharpe_variance_adjustment),
        selected_period_sharpe_standard_error=(selected_period_sharpe_standard_error),
        correlation_summary=correlation_summary,
        effective_independent_trial_count=(spec.effective_independent_trial_count),
        effective_trial_count_methodology=(spec.effective_trial_count_methodology),
        effective_trial_count_verified=(
            None if spec.effective_independent_trial_count is None else False
        ),
        scenarios=(),
    )
