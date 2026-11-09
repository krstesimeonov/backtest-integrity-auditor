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
    convention: ReturnConvention = ReturnConvention.SIMPLE,
    periods_per_year: int | None = 252,
    search_complete: bool = True,
    selection_metric: str = "period_sharpe_ratio",
    parameters: tuple[tuple[object, object], ...] | None = None,
) -> ExperimentFamily:
    matrix = np.asarray(values, dtype=np.float64)
    trial_ids = ("trial-1", "trial-2", "trial-3", "trial-4")
    parameter_values = parameters or (
        (9, 0.5),
        (10, 0.5),
        (11, 0.5),
        (20, 0.5),
    )
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == 1,
            selection_score=(4.0 if index == 1 else float(3 - index)),
            parameters=(
                TrialParameter("lookback", parameter_values[index][0]),
                TrialParameter("threshold", parameter_values[index][1]),
            ),
        )
        for index, trial_id in enumerate(trial_ids)
    )
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=periods_per_year)
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="parameter-family",
            declared_total_attempted_trials=4,
            search_complete=search_complete,
            selected_trial_id="trial-2",
            selection_rule="maximize period Sharpe",
            selection_metric=selection_metric,
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback", "threshold"),
            return_convention=convention,
            sampling=sampling,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=pd.date_range("2026-01-01", periods=len(matrix), freq="B"),
            trial_ids=trial_ids,
            values=matrix,
            convention=convention,
            sampling=sampling,
        ),
    )


def test_parameter_robustness_maps_explicit_local_neighbors() -> None:
    result = calculate_parameter_robustness(_family(), _spec())

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    assert result.candidate_trial_count == 3
    assert result.neighbor_count == 2
    assert [item.trial_id for item in result.neighbors] == ["trial-1", "trial-3"]
    assert [item.standardized_distance for item in result.neighbors] == [0.5, 0.5]
    assert result.acceptable_neighbor_fraction == 1.0
    assert result.neighbor_fraction_requirement_met is True
    assert result.selected_is_local_maximum is True
    assert result.axis_sensitivities[0].closest_lower_trial_id == "trial-1"
    assert result.axis_sensitivities[0].closest_upper_trial_id == "trial-3"


def test_parameter_robustness_holds_unscaled_dimensions_fixed() -> None:
    parameters = ((9, 0.6), (10, 0.5), (11, 0.5), (20, 0.5))
    result = calculate_parameter_robustness(
        _family(parameters=parameters),
        _spec(minimum_neighbor_count=1),
    )

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    assert [item.trial_id for item in result.neighbors] == ["trial-3"]


def test_duplicate_selected_configuration_is_not_counted_as_a_neighbor() -> None:
    parameters = ((9, 0.5), (10, 0.5), (11, 0.5), (10, 0.5))
    result = calculate_parameter_robustness(_family(parameters=parameters), _spec())

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    assert result.duplicate_configuration_trial_ids == ("trial-4",)
    assert result.neighbor_count == 2


def test_parameter_robustness_reports_a_fragile_plateau_requirement() -> None:
    result = calculate_parameter_robustness(
        _family(),
        _spec(maximum_acceptable_score_difference=0.0),
    )

    assert result.status is ParameterRobustnessStatus.ELIGIBLE
    assert result.acceptable_neighbor_fraction == 0.0
    assert result.neighbor_fraction_requirement_met is False


def test_parameter_robustness_preserves_undefined_neighbor_score() -> None:
    values = _VALUES.copy()
    values[:, 2] = 0.01
    result = calculate_parameter_robustness(_family(values), _spec())

    assert result.status is ParameterRobustnessStatus.INCOMPLETE_NEIGHBOR_METRICS
    assert result.unavailable_neighbor_trial_ids == ("trial-3",)
    assert result.neighbors[1].period_sharpe_ratio is None
    assert result.acceptable_neighbor_fraction is None


def test_parameter_robustness_requires_the_declared_neighbor_density() -> None:
    result = calculate_parameter_robustness(
        _family(),
        _spec(maximum_distance=0.25),
    )

    assert result.status is ParameterRobustnessStatus.INSUFFICIENT_NEIGHBORS
    assert result.neighbors == ()


@pytest.mark.parametrize(
    ("family", "spec", "status"),
    [
        (
            _family(search_complete=False),
            _spec(),
            ParameterRobustnessStatus.FAMILY_INELIGIBLE,
        ),
        (
            _family(periods_per_year=None),
            _spec(),
            ParameterRobustnessStatus.PERIODS_PER_YEAR_UNAVAILABLE,
        ),
        (
            _family(selection_metric="validation_sharpe"),
            _spec(),
            ParameterRobustnessStatus.SELECTION_RULE_INCOMPATIBLE,
        ),
        (
            _family(),
            _spec(parameter_scales=(ParameterScale("missing", 1.0),)),
            ParameterRobustnessStatus.PARAMETER_SCHEMA_INCOMPATIBLE,
        ),
    ],
)
def test_parameter_robustness_has_typed_ineligibility(
    family: ExperimentFamily,
    spec: ParameterRobustnessSpec,
    status: ParameterRobustnessStatus,
) -> None:
    assert calculate_parameter_robustness(family, spec).status is status


def test_log_and_simple_inputs_produce_equivalent_neighborhood_scores() -> None:
    simple = calculate_parameter_robustness(_family(), _spec())
    logged = calculate_parameter_robustness(
        _family(np.log1p(_VALUES), convention=ReturnConvention.LOG),
        _spec(),
    )

    assert logged.return_basis is ReturnConvention.SIMPLE
    assert [item.period_sharpe_ratio for item in logged.neighbors] == pytest.approx(
        [item.period_sharpe_ratio for item in simple.neighbors]
    )


def test_exact_radius_neighbours_survive_decimal_grids() -> None:
    """A symmetric parameter grid must produce a symmetric neighbourhood.

    The documented rule is `d <= maximum_distance` on the EXACT standardized
    distance. Computed in floats on a decimal grid the result lands one or two
    ulp either side of the radius, and which side depends on which pair of
    decimals is subtracted. On the grid in
    PARAMETER_TEMPORAL_ROBUSTNESS_METHODOLOGY.md (threshold 0.7/0.8/0.9,
    scale 0.1) a raw `<=` admitted the 0.9 neighbour and rejected the 0.7 one,
    so the published neighbour count depended on representation error.
    """

    from backtest_auditor.statistics.parameter_robustness import _within_radius

    below = abs(0.7 - 0.8) / 0.1
    above = abs(0.9 - 0.8) / 0.1

    # The premise: these are not equal, and they straddle the radius.
    assert below > 1.0
    assert above < 1.0
    assert below != above

    assert _within_radius(below, 1.0)
    assert _within_radius(above, 1.0)


def test_radius_tolerance_does_not_admit_genuine_outsiders() -> None:
    """The tolerance is for rounding, not for widening the neighbourhood."""

    from backtest_auditor.statistics.parameter_robustness import _within_radius

    assert _within_radius(0.5, 1.0)
    assert _within_radius(1.0, 1.0)
    assert not _within_radius(1.5, 1.0)
    assert not _within_radius(abs(1.0 - 0.8) / 0.1, 1.0)  # exactly 2 steps out
    assert not _within_radius(1.000001, 1.0)
