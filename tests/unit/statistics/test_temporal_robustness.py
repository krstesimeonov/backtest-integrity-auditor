import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import TemporalRobustnessSpec
from backtest_auditor.domain.enums import (
    ReturnConvention,
    RobustnessPerformanceMetric,
    RobustnessRankTieMethod,
    RobustnessSliceStatus,
    RobustnessWinnerTiePolicy,
    SelectionDirection,
    TemporalRobustnessStatus,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (
    ExperimentFamily,
    ExperimentFamilyManifest,
    ExperimentSplit,
    ExperimentTrial,
    TrialParameter,
    TrialReturnMatrix,
)
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.statistics.temporal_robustness import (
    calculate_temporal_robustness,
)


_VALUES = np.asarray(
    [
        [0.040, 0.010, -0.020, 0.030],
        [-0.010, 0.020, 0.010, -0.020],
        [0.030, -0.010, 0.020, 0.010],
        [-0.020, 0.030, -0.010, 0.020],
        [0.010, -0.020, 0.040, -0.010],
        [0.020, 0.010, -0.020, 0.040],
        [-0.010, 0.040, 0.010, -0.020],
        [0.030, -0.010, 0.020, 0.010],
    ],
    dtype=np.float64,
)


def _spec(**overrides: object) -> TemporalRobustnessSpec:
    values = {
        "performance_metric": RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "annual_risk_free_rate": 0.0,
        "window_count": 4,
        "rank_tie_method": RobustnessRankTieMethod.AVERAGE,
        "winner_tie_policy": RobustnessWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        "minimum_acceptable_top_half_fraction": 0.5,
        "maximum_acceptable_below_zero_fraction": 0.5,
    }
    values.update(overrides)
    return TemporalRobustnessSpec(**values)


def _family(
    values: np.ndarray = _VALUES,
    *,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
    periods_per_year: int | None = 252,
    selection_metric: str = "period_sharpe_ratio",
    splits: tuple[ExperimentSplit, ...] = (),
) -> ExperimentFamily:
    matrix = np.asarray(values, dtype=np.float64)
    trial_ids = tuple(f"trial-{index + 1}" for index in range(matrix.shape[1]))
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=periods_per_year)
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == 0,
            selection_score=float(len(trial_ids) - index),
            parameters=(TrialParameter("lookback", index + 1),),
        )
        for index, trial_id in enumerate(trial_ids)
    )
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="temporal-family",
            declared_total_attempted_trials=len(trials),
            search_complete=True,
            selected_trial_id="trial-1",
            selection_rule="maximize period Sharpe",
            selection_metric=selection_metric,
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
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
        splits=splits,
    )


def _two_splits() -> tuple[ExperimentSplit, ...]:
    timestamps = pd.date_range("2026-01-01", periods=8, freq="B")
    return (
        ExperimentSplit("fold-a", timestamps[:4], timestamps[4:]),
        ExperimentSplit("fold-b", timestamps[4:], timestamps[:4]),
    )


def test_temporal_robustness_reports_every_equal_window() -> None:
    result = calculate_temporal_robustness(_family(), _spec())

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.window_count == 4
    assert result.observations_per_window == 2
    assert result.valid_window_count == 4
    assert result.invalid_window_count == 0
    assert result.selected_top_half_fraction is not None
    assert result.selected_below_zero_fraction is not None
    assert result.selected_score_sample_standard_deviation is not None
    assert result.distinct_window_winner_trial_ids
    assert all(item.selected_rank_logit is not None for item in result.windows)


def test_temporal_robustness_is_deterministic() -> None:
    first = calculate_temporal_robustness(_family(), _spec())
    second = calculate_temporal_robustness(_family(), _spec())

    assert first == second


def test_declared_splits_replay_is_winners_into_oos() -> None:
    result = calculate_temporal_robustness(
        _family(splits=_two_splits()),
        _spec(),
    )

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.valid_external_split_count == 2
    assert result.invalid_external_split_count == 0
    assert [item.split_id for item in result.external_splits] == ["fold-a", "fold-b"]
    assert all(
        item.in_sample_winner_trial_id is not None for item in result.external_splits
    )
    assert all(
        item.selected_out_of_sample_rank is not None for item in result.external_splits
    )


def test_short_declared_split_is_preserved_without_invalidating_windows() -> None:
    timestamps = pd.date_range("2026-01-01", periods=8, freq="B")
    split = ExperimentSplit("short-is", timestamps[:1], timestamps[1:])
    result = calculate_temporal_robustness(
        _family(splits=(split,)),
        _spec(),
    )

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.valid_window_count == 4
    assert result.invalid_external_split_count == 1
    assert result.external_splits[0].status is (
        RobustnessSliceStatus.PERFORMANCE_METRIC_UNAVAILABLE
    )
    assert result.external_splits[0].unavailable_trial_ids == (
        "trial-1",
        "trial-2",
        "trial-3",
        "trial-4",
    )


def test_temporal_robustness_refuses_to_trim_a_remainder() -> None:
    values = np.vstack([_VALUES, _VALUES[0]])
    result = calculate_temporal_robustness(_family(values), _spec())

    assert result.status is (
        TemporalRobustnessStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_WINDOWS
    )
    assert result.windows == ()


def test_temporal_robustness_preserves_undefined_window_metrics() -> None:
    values = _VALUES.copy()
    values[:, 3] = 0.01
    result = calculate_temporal_robustness(_family(values), _spec())

    assert result.status is TemporalRobustnessStatus.INCOMPLETE_WINDOW_METRICS
    assert result.invalid_window_count == 4
    assert all(
        item.status is RobustnessSliceStatus.PERFORMANCE_METRIC_UNAVAILABLE
        for item in result.windows
    )
    assert all(item.unavailable_trial_ids == ("trial-4",) for item in result.windows)


@pytest.mark.parametrize(
    ("family", "spec", "status"),
    [
        (
            _family(periods_per_year=None),
            _spec(),
            TemporalRobustnessStatus.PERIODS_PER_YEAR_UNAVAILABLE,
        ),
        (
            _family(selection_metric="validation_sharpe"),
            _spec(),
            TemporalRobustnessStatus.SELECTION_RULE_INCOMPATIBLE,
        ),
        (
            _family(),
            _spec(window_count=8),
            TemporalRobustnessStatus.INSUFFICIENT_WINDOW_OBSERVATIONS,
        ),
    ],
)
def test_temporal_robustness_has_typed_ineligibility(
    family: ExperimentFamily,
    spec: TemporalRobustnessSpec,
    status: TemporalRobustnessStatus,
) -> None:
    assert calculate_temporal_robustness(family, spec).status is status


def test_log_and_simple_inputs_produce_equivalent_temporal_scores() -> None:
    simple = calculate_temporal_robustness(_family(), _spec())
    logged = calculate_temporal_robustness(
        _family(np.log1p(_VALUES), convention=ReturnConvention.LOG),
        _spec(),
    )

    assert logged.return_basis is ReturnConvention.SIMPLE
    assert [item.selected_period_sharpe_ratio for item in logged.windows] == (
        pytest.approx([item.selected_period_sharpe_ratio for item in simple.windows])
    )


def test_identical_window_scores_publish_exactly_zero_deviation() -> None:
    # The selected trial earns (0.01, 0.03) in every window, so its window
    # Sharpe is sqrt(2) seven times over and those scores have no dispersion.
    # np.std of seven copies of sqrt(2) is 2.4e-16, a rounding residue rather
    # than a measured deviation, so the published value must be exactly 0.0.
    values = np.vstack([_VALUES, _VALUES[:6]])
    values[:, 0] = [0.01, 0.03] * 7

    result = calculate_temporal_robustness(_family(values), _spec(window_count=7))

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.selected_score_sample_standard_deviation == 0.0
    assert result.selected_score_range == 0.0
