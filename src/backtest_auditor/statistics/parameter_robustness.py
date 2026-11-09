import math
from typing import Any

import numpy as np

from backtest_auditor.domain.assumptions import ParameterRobustnessSpec
from backtest_auditor.domain.enums import (
    ParameterRobustnessStatus,
    ReturnConvention,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (
    ExperimentFamily,
    ExperimentTrial,
    ParameterScalar,
)
from backtest_auditor.domain.results import (
    ParameterAxisSensitivityResult,
    ParameterNeighborResult,
    ParameterRobustnessResult,
)
from backtest_auditor.statistics.family_metrics import (
    period_sharpe_scores,
)
from backtest_auditor.statistics.return_basis import (
    annual_to_period_rate,
    to_simple_returns,
)


def calculate_parameter_robustness(
    family: ExperimentFamily,
    spec: ParameterRobustnessSpec,
) -> ParameterRobustnessResult:
    """Audit the selected trial inside an explicit standardized neighborhood."""

    eligible = _selection_eligible_trials(family)
    common: dict[str, Any] = {"selection_eligible_trial_count": len(eligible)}
    if not _family_is_eligible(family, eligible):
        return _unavailable_result(
            family,
            spec,
            status=ParameterRobustnessStatus.FAMILY_INELIGIBLE,
            **common,
        )
    if (
        family.manifest.selection_direction is not SelectionDirection.MAXIMIZE
        or family.manifest.selection_metric != spec.selection_metric_name
    ):
        return _unavailable_result(
            family,
            spec,
            status=ParameterRobustnessStatus.SELECTION_RULE_INCOMPATIBLE,
            **common,
        )
    periods_per_year = family.returns.sampling.periods_per_year
    if periods_per_year is None or periods_per_year <= 0:
        return _unavailable_result(
            family,
            spec,
            status=ParameterRobustnessStatus.PERIODS_PER_YEAR_UNAVAILABLE,
            **common,
        )
    period_rate = annual_to_period_rate(
        spec.annual_risk_free_rate,
        periods_per_year,
    )
    period_values: dict[str, Any] = {
        "periods_per_year": periods_per_year,
        "period_risk_free_rate_value": period_rate,
    }
    scale_names = tuple(item.name for item in spec.parameter_scales)
    if not _parameter_schema_is_compatible(family, eligible, scale_names):
        return _unavailable_result(
            family,
            spec,
            status=ParameterRobustnessStatus.PARAMETER_SCHEMA_INCOMPATIBLE,
            **common,
            **period_values,
        )

    selected = next(trial for trial in eligible if trial.selected)
    selected_values = _parameter_values(selected)
    matrix = np.column_stack(
        [
            to_simple_returns(family.returns.series_for(trial.trial_id))
            for trial in eligible
        ]
    )
    scores = period_sharpe_scores(
        matrix,
        period_risk_free_rate_value=period_rate,
    )
    selected_index = eligible.index(selected)
    selected_score = float(scores[selected_index])
    if not math.isfinite(selected_score):
        return _unavailable_result(
            family,
            spec,
            status=ParameterRobustnessStatus.SELECTED_SCORE_UNAVAILABLE,
            selected_period_sharpe_ratio=None,
            **common,
            **period_values,
        )

    fixed_names = tuple(
        name for name in family.manifest.parameter_names if name not in scale_names
    )
    scales = {item.name: item.scale for item in spec.parameter_scales}
    duplicates: list[str] = []
    raw_neighbors: list[tuple[ExperimentTrial, float, tuple[str, ...]]] = []
    for trial in eligible:
        if trial.selected:
            continue
        values = _parameter_values(trial)
        if any(values[name] != selected_values[name] for name in fixed_names):
            continue
        changed = tuple(
            name for name in scale_names if values[name] != selected_values[name]
        )
        distance = math.sqrt(
            sum(
                ((float(values[name]) - float(selected_values[name])) / scales[name])
                ** 2
                for name in scale_names
            )
        )
        if distance == 0.0:
            duplicates.append(trial.trial_id)
        elif _within_radius(distance, spec.maximum_distance):
            raw_neighbors.append((trial, distance, changed))

    neighbors = tuple(
        _neighbor_result(
            trial,
            distance=distance,
            changed=changed,
            score=float(scores[eligible.index(trial)]),
            selected_score=selected_score,
            tolerance=spec.maximum_acceptable_score_difference,
        )
        for trial, distance, changed in raw_neighbors
    )
    unavailable_ids = tuple(
        item.trial_id for item in neighbors if item.period_sharpe_ratio is None
    )
    base_values: dict[str, Any] = {
        "selected_period_sharpe_ratio": selected_score,
        "candidate_trial_count": len(eligible) - 1,
        "duplicate_configuration_trial_ids": tuple(duplicates),
        "neighbors": neighbors,
        "unavailable_neighbor_trial_ids": unavailable_ids,
        **common,
        **period_values,
    }
    if len(neighbors) < spec.minimum_neighbor_count:
        return _unavailable_result(
            family,
            spec,
            status=ParameterRobustnessStatus.INSUFFICIENT_NEIGHBORS,
            **base_values,
        )
    if unavailable_ids:
        return _unavailable_result(
            family,
            spec,
            status=ParameterRobustnessStatus.INCOMPLETE_NEIGHBOR_METRICS,
            **base_values,
        )

    neighbor_scores = np.asarray(
        [item.period_sharpe_ratio for item in neighbors],
        dtype=float,
    )
    differences = np.asarray(
        [item.score_difference_from_selected for item in neighbors],
        dtype=float,
    )
    acceptable_count = sum(
        item.within_acceptable_score_difference is True for item in neighbors
    )
    acceptable_fraction = acceptable_count / len(neighbors)
    return ParameterRobustnessResult(
        status=ParameterRobustnessStatus.ELIGIBLE,
        performance_metric=spec.performance_metric,
        declared_selection_metric=family.manifest.selection_metric,
        confirmed_selection_metric=spec.selection_metric_name,
        distance_metric=spec.distance_metric,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_rate,
        selected_trial_id=family.manifest.selected_trial_id,
        selected_period_sharpe_ratio=selected_score,
        parameter_scales=tuple(
            (item.name, item.scale) for item in spec.parameter_scales
        ),
        maximum_distance=spec.maximum_distance,
        minimum_neighbor_count=spec.minimum_neighbor_count,
        maximum_acceptable_score_difference=(spec.maximum_acceptable_score_difference),
        minimum_acceptable_neighbor_fraction=(
            spec.minimum_acceptable_neighbor_fraction
        ),
        selection_eligible_trial_count=len(eligible),
        candidate_trial_count=len(eligible) - 1,
        neighbor_count=len(neighbors),
        duplicate_configuration_trial_ids=tuple(duplicates),
        neighbors=neighbors,
        unavailable_neighbor_trial_ids=(),
        acceptable_neighbor_count=acceptable_count,
        acceptable_neighbor_fraction=acceptable_fraction,
        neighbor_fraction_requirement_met=(
            acceptable_fraction >= spec.minimum_acceptable_neighbor_fraction
        ),
        selected_is_local_maximum=bool(np.all(neighbor_scores <= selected_score)),
        minimum_neighbor_score=float(np.min(neighbor_scores)),
        maximum_neighbor_score=float(np.max(neighbor_scores)),
        mean_neighbor_score=float(np.mean(neighbor_scores)),
        maximum_degradation=max(0.0, float(-np.min(differences))),
        maximum_improvement=max(0.0, float(np.max(differences))),
        steepest_absolute_score_change_per_distance=max(
            abs(item.score_difference_from_selected) / item.standardized_distance
            for item in neighbors
            if item.score_difference_from_selected is not None
        ),
        axis_sensitivities=_axis_sensitivities(
            spec,
            selected_values=selected_values,
            raw_neighbors=raw_neighbors,
            neighbors=neighbors,
        ),
    )


def _neighbor_result(
    trial: ExperimentTrial,
    *,
    distance: float,
    changed: tuple[str, ...],
    score: float,
    selected_score: float,
    tolerance: float,
) -> ParameterNeighborResult:
    finite_score = score if math.isfinite(score) else None
    difference = None if finite_score is None else finite_score - selected_score
    return ParameterNeighborResult(
        trial_id=trial.trial_id,
        attempt_index=trial.attempt_index,
        standardized_distance=distance,
        changed_parameter_names=changed,
        period_sharpe_ratio=finite_score,
        score_difference_from_selected=difference,
        within_acceptable_score_difference=(
            None if difference is None else abs(difference) <= tolerance
        ),
    )


def _axis_sensitivities(
    spec: ParameterRobustnessSpec,
    *,
    selected_values: dict[str, ParameterScalar],
    raw_neighbors: list[tuple[ExperimentTrial, float, tuple[str, ...]]],
    neighbors: tuple[ParameterNeighborResult, ...],
) -> tuple[ParameterAxisSensitivityResult, ...]:
    results_by_id = {item.trial_id: item for item in neighbors}
    output = []
    for scale in spec.parameter_scales:
        axis = tuple(
            (trial, distance, results_by_id[trial.trial_id])
            for trial, distance, changed in raw_neighbors
            if changed == (scale.name,)
        )
        lower = tuple(
            item
            for item in axis
            if float(_parameter_values(item[0])[scale.name])
            < float(selected_values[scale.name])
        )
        upper = tuple(
            item
            for item in axis
            if float(_parameter_values(item[0])[scale.name])
            > float(selected_values[scale.name])
        )
        closest_lower = min(lower, key=lambda item: item[1], default=None)
        closest_upper = min(upper, key=lambda item: item[1], default=None)
        valid_slopes = tuple(
            abs(item[2].score_difference_from_selected) / item[1]
            for item in axis
            if item[2].score_difference_from_selected is not None
        )
        output.append(
            ParameterAxisSensitivityResult(
                parameter_name=scale.name,
                one_axis_neighbor_count=len(axis),
                closest_lower_trial_id=(
                    None if closest_lower is None else closest_lower[0].trial_id
                ),
                closest_lower_score_difference=(
                    None
                    if closest_lower is None
                    else closest_lower[2].score_difference_from_selected
                ),
                closest_upper_trial_id=(
                    None if closest_upper is None else closest_upper[0].trial_id
                ),
                closest_upper_score_difference=(
                    None
                    if closest_upper is None
                    else closest_upper[2].score_difference_from_selected
                ),
                maximum_absolute_score_change_per_scaled_unit=(
                    None if not valid_slopes else max(valid_slopes)
                ),
            )
        )
    return tuple(output)


def _selection_eligible_trials(
    family: ExperimentFamily,
) -> tuple[ExperimentTrial, ...]:
    return tuple(
        trial
        for trial in family.trials
        if trial.outcome is TrialOutcome.COMPLETED and trial.included_in_selection
    )


def _family_is_eligible(
    family: ExperimentFamily,
    eligible: tuple[ExperimentTrial, ...],
) -> bool:
    return (
        family.manifest.search_complete
        and len(family.trials) == family.manifest.declared_total_attempted_trials
        and len(eligible) >= 2
        and len(family.returns.timestamps) >= 4
    )


def _parameter_schema_is_compatible(
    family: ExperimentFamily,
    eligible: tuple[ExperimentTrial, ...],
    scale_names: tuple[str, ...],
) -> bool:
    declared = set(family.manifest.parameter_names)
    if any(name not in declared for name in scale_names):
        return False
    return all(
        _is_numeric_parameter(_parameter_values(trial)[name])
        for trial in eligible
        for name in scale_names
    )


def _is_numeric_parameter(value: ParameterScalar) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _within_radius(distance: float, maximum_distance: float) -> bool:
    """Admit a neighbour whose EXACT standardized distance is <= the radius.

    The documented rule is `d <= maximum_distance` on the exact distance, but
    the float arithmetic lands one or two ulp either side of it on a decimal
    parameter grid, and which side depends on which pair of decimals is
    subtracted. On the grid in PARAMETER_TEMPORAL_ROBUSTNESS_METHODOLOGY.md
    (threshold 0.7/0.8/0.9, --parameter-scale threshold=0.1):

        |0.8 - 0.7| / 0.1 = 1.0000000000000009  -> excluded by a raw <=
        |0.9 - 0.8| / 0.1 = 0.9999999999999998  -> included

    so a symmetric grid produced an asymmetric neighbourhood, and the reported
    neighbour count and fraction depended on representation error rather than
    on the parameter grid. The tolerance is relative and tiny; it changes no
    neighbour whose distance differs from the radius by more than rounding.
    """

    return distance < maximum_distance or math.isclose(
        distance,
        maximum_distance,
        rel_tol=1e-9,
    )


def _parameter_values(trial: ExperimentTrial) -> dict[str, ParameterScalar]:
    return {parameter.name: parameter.value for parameter in trial.parameters}


def _unavailable_result(
    family: ExperimentFamily,
    spec: ParameterRobustnessSpec,
    *,
    status: ParameterRobustnessStatus,
    periods_per_year: int | None = None,
    period_risk_free_rate_value: float | None = None,
    selected_period_sharpe_ratio: float | None = None,
    selection_eligible_trial_count: int,
    candidate_trial_count: int = 0,
    duplicate_configuration_trial_ids: tuple[str, ...] = (),
    neighbors: tuple[ParameterNeighborResult, ...] = (),
    unavailable_neighbor_trial_ids: tuple[str, ...] = (),
) -> ParameterRobustnessResult:
    return ParameterRobustnessResult(
        status=status,
        performance_metric=spec.performance_metric,
        declared_selection_metric=family.manifest.selection_metric,
        confirmed_selection_metric=spec.selection_metric_name,
        distance_metric=spec.distance_metric,
        return_basis=ReturnConvention.SIMPLE,
        annual_risk_free_rate=spec.annual_risk_free_rate,
        periods_per_year=periods_per_year,
        period_risk_free_rate=period_risk_free_rate_value,
        selected_trial_id=family.manifest.selected_trial_id,
        selected_period_sharpe_ratio=selected_period_sharpe_ratio,
        parameter_scales=tuple(
            (item.name, item.scale) for item in spec.parameter_scales
        ),
        maximum_distance=spec.maximum_distance,
        minimum_neighbor_count=spec.minimum_neighbor_count,
        maximum_acceptable_score_difference=(spec.maximum_acceptable_score_difference),
        minimum_acceptable_neighbor_fraction=(
            spec.minimum_acceptable_neighbor_fraction
        ),
        selection_eligible_trial_count=selection_eligible_trial_count,
        candidate_trial_count=candidate_trial_count,
        neighbor_count=len(neighbors),
        duplicate_configuration_trial_ids=duplicate_configuration_trial_ids,
        neighbors=neighbors,
        unavailable_neighbor_trial_ids=unavailable_neighbor_trial_ids,
        acceptable_neighbor_count=None,
        acceptable_neighbor_fraction=None,
        neighbor_fraction_requirement_met=None,
        selected_is_local_maximum=None,
        minimum_neighbor_score=None,
        maximum_neighbor_score=None,
        mean_neighbor_score=None,
        maximum_degradation=None,
        maximum_improvement=None,
        steepest_absolute_score_change_per_distance=None,
        axis_sensitivities=(),
    )
