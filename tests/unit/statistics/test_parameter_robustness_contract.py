import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import (
    ParameterRobustnessSpec,
    ParameterScale,
)
from backtest_auditor.domain.enums import (
    ParameterDistanceMetric,
    ParameterRobustnessStatus,
    ReturnConvention,
    RobustnessPerformanceMetric,
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
from backtest_auditor.statistics.parameter_robustness import (
    calculate_parameter_robustness,
)


_VALUES = np.asarray(
    [
        [0.010, 0.015, 0.012, -0.010],
        [0.020, 0.025, 0.021, 0.030],
        [-0.010, -0.005, -0.008, 0.010],
        [0.030, 0.035, 0.031, -0.020],
        [0.010, 0.012, 0.009, 0.020],
        [0.020, 0.022, 0.019, -0.010],
        [-0.005, -0.002, -0.004, 0.025],
        [0.025, 0.028, 0.024, 0.005],
    ],
    dtype=np.float64,
)
_TRIAL_IDS = ("trial-1", "trial-2", "trial-3", "trial-4")
_SELECTED = 1


def _spec(**overrides: object) -> ParameterRobustnessSpec:
    values = {
        "performance_metric": RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "annual_risk_free_rate": 0.0,
        "distance_metric": ParameterDistanceMetric.STANDARDIZED_EUCLIDEAN,
        "parameter_scales": (ParameterScale("lookback", 2.0),),
        "maximum_distance": 1.0,
        "minimum_neighbor_count": 2,
        "maximum_acceptable_score_difference": 100.0,
        "minimum_acceptable_neighbor_fraction": 1.0,
    }
    values.update(overrides)
    return ParameterRobustnessSpec(**values)


def _family(
    values: np.ndarray = _VALUES,
    *,
    periods_per_year: int | None = 252,
    parameters: tuple[tuple[object, object], ...] = (
        (9, 0.5),
        (10, 0.5),
        (11, 0.5),
        (20, 0.5),
    ),
    excluded: tuple[str, ...] = (),
) -> ExperimentFamily:
    """Four completed trials; trial-2 is selected; `excluded` are completed but
    deliberately left out of the selection (each with a recorded reason)."""

    matrix = np.asarray(values, dtype=np.float64)
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=trial_id not in excluded,
            selected=index == _SELECTED,
            selection_score=(4.0 if index == _SELECTED else float(3 - index)),
            parameters=(
                TrialParameter("lookback", parameters[index][0]),
                TrialParameter("threshold", parameters[index][1]),
            ),
            reason=("excluded after review" if trial_id in excluded else None),
        )
        for index, trial_id in enumerate(_TRIAL_IDS)
    )
    sampling = SamplingSpec(periods_per_year=periods_per_year)
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="parameter-family",
            declared_total_attempted_trials=4,
            search_complete=True,
            selected_trial_id="trial-2",
            selection_rule="maximize period Sharpe",
            selection_metric="period_sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback", "threshold"),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=pd.date_range("2026-01-01", periods=len(matrix), freq="B"),
            trial_ids=_TRIAL_IDS,
            values=matrix,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


def test_annual_sampling_is_a_positive_periods_per_year() -> None:
    # Methodology: "a positive periods_per_year". 1 is positive, and at one
    # period a year the period rate is the annual rate: (1 + r) ** (1 / 1) - 1 = r.
    result = calculate_parameter_robustness(
        _family(periods_per_year=1),
        _spec(annual_risk_free_rate=0.03),
    )

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    assert result.periods_per_year == 1
    assert result.period_risk_free_rate == pytest.approx(0.03)


def test_four_aligned_observations_are_enough_and_three_are_not() -> None:
    # Methodology: "at least four aligned observations".
    four = calculate_parameter_robustness(_family(_VALUES[:4]), _spec())
    three = calculate_parameter_robustness(_family(_VALUES[:3]), _spec())

    assert four.status is ParameterRobustnessStatus.ELIGIBLE
    assert three.status is ParameterRobustnessStatus.FAMILY_INELIGIBLE


@pytest.mark.parametrize(
    ("values", "spec", "status"),
    [
        (_VALUES, _spec(), ParameterRobustnessStatus.ELIGIBLE),
        (
            _VALUES,
            _spec(maximum_distance=0.25),
            ParameterRobustnessStatus.INSUFFICIENT_NEIGHBORS,
        ),
        (
            np.column_stack([_VALUES[:, :2], np.full(8, 0.01), _VALUES[:, 3]]),
            _spec(),
            ParameterRobustnessStatus.INCOMPLETE_NEIGHBOR_METRICS,
        ),
    ],
)
def test_once_neighbours_are_screened_every_other_eligible_trial_is_a_candidate(
    values: np.ndarray,
    spec: ParameterRobustnessSpec,
    status: ParameterRobustnessStatus,
) -> None:
    # Four selection-eligible trials minus the selected one: 3 candidates,
    # however many of them end up inside the radius. This holds only for the
    # statuses reached AFTER neighbour screening; the early exits report 0
    # candidates beside 4 selection-eligible trials, which is an open reporting
    # question rather than a property to pin.
    result = calculate_parameter_robustness(_family(values), spec)

    assert result.status is status
    assert result.selection_eligible_trial_count == 4
    assert result.candidate_trial_count == 3


def test_a_lone_selection_eligible_trial_has_no_candidates() -> None:
    result = calculate_parameter_robustness(
        _family(excluded=("trial-1", "trial-3", "trial-4")),
        _spec(),
    )

    assert result.status is ParameterRobustnessStatus.FAMILY_INELIGIBLE
    assert result.selection_eligible_trial_count == 1
    assert result.candidate_trial_count == 0


def test_a_trial_excluded_from_selection_is_not_a_neighbor() -> None:
    # Methodology: only a tested *selection-eligible* trial can be a neighbor.
    # trial-3 sits at distance 0.5 but was excluded from the selection.
    result = calculate_parameter_robustness(
        _family(excluded=("trial-3",)),
        _spec(minimum_neighbor_count=1),
    )

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    assert result.selection_eligible_trial_count == 3
    assert result.candidate_trial_count == 2
    assert [item.trial_id for item in result.neighbors] == ["trial-1"]


@pytest.mark.parametrize("bad_value", [True, "0.5"])
def test_a_boolean_or_text_scaled_parameter_is_schema_incompatible(
    bad_value: object,
) -> None:
    # Methodology: a scaled parameter must be "numeric and non-boolean for every
    # selection-eligible trial". "0.5" must not be silently coerced to 0.5.
    parameters = ((9, 0.5), (10, 0.5), (11, bad_value), (20, 0.5))
    result = calculate_parameter_robustness(
        _family(parameters=parameters),
        _spec(
            parameter_scales=(
                ParameterScale("lookback", 2.0),
                ParameterScale("threshold", 0.1),
            ),
        ),
    )

    assert result.status is ParameterRobustnessStatus.PARAMETER_SCHEMA_INCOMPATIBLE


def test_closest_lower_neighbor_is_the_one_at_the_smallest_distance() -> None:
    # Selected lookback 10, scale 2: trial-1 at 8 is d = 1.0, trial-3 at 9 is
    # d = 0.5, trial-4 at 11 is d = 0.5. The closest lower point is trial-3.
    parameters = ((8, 0.5), (10, 0.5), (9, 0.5), (11, 0.5))
    result = calculate_parameter_robustness(_family(parameters=parameters), _spec())

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    by_id = {item.trial_id: item for item in result.neighbors}
    assert by_id["trial-1"].standardized_distance == 1.0
    assert by_id["trial-3"].standardized_distance == 0.5

    axis = result.axis_sensitivities[0]
    assert axis.one_axis_neighbor_count == 3
    assert axis.closest_lower_trial_id == "trial-3"
    assert axis.closest_lower_score_difference == (
        by_id["trial-3"].score_difference_from_selected
    )
    assert axis.closest_upper_trial_id == "trial-4"


def _selected_returns_copied_to_trial_3() -> np.ndarray:
    values = _VALUES.copy()
    values[:, 2] = values[:, _SELECTED]
    return values


def test_a_score_difference_equal_to_the_tolerance_is_acceptable() -> None:
    # The CLI defines the tolerance as the "Maximum absolute period-Sharpe
    # difference counted as plateau-like", so the maximum itself is counted.
    # trial-3 returns exactly what the selected trial returns: difference 0.0,
    # which a tolerance of 0.0 must accept.
    result = calculate_parameter_robustness(
        _family(_selected_returns_copied_to_trial_3()),
        _spec(maximum_acceptable_score_difference=0.0),
    )

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    by_id = {item.trial_id: item for item in result.neighbors}
    assert by_id["trial-3"].score_difference_from_selected == 0.0
    assert by_id["trial-3"].within_acceptable_score_difference is True
    assert by_id["trial-1"].within_acceptable_score_difference is False
    assert result.acceptable_neighbor_count == 1
    assert result.acceptable_neighbor_fraction == 0.5


def test_a_neighbor_that_ties_the_winner_does_not_unseat_it() -> None:
    # A False flag raises SELECTED_TRIAL_NOT_LOCAL_SHARPE_MAXIMUM, whose claim is
    # "At least one configured neighbor has a higher recalculated Sharpe". An
    # exact tie is not higher, so a tied winner is still a local maximum.
    result = calculate_parameter_robustness(
        _family(_selected_returns_copied_to_trial_3()),
        _spec(),
    )

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    by_id = {item.trial_id: item for item in result.neighbors}
    assert by_id["trial-3"].period_sharpe_ratio == result.selected_period_sharpe_ratio
    assert by_id["trial-1"].score_difference_from_selected < 0.0
    assert result.maximum_neighbor_score == result.selected_period_sharpe_ratio
    assert result.selected_is_local_maximum is True
