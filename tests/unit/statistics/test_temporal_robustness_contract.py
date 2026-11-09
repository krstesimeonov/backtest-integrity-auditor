import math

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
from backtest_auditor.domain.results import TemporalRobustnessResult
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.statistics.temporal_robustness import (
    calculate_temporal_robustness,
)


# Eight observations of three trials. Every column changes between any two
# consecutive rows, so every two-row window and every split role of two or
# more rows has a defined period Sharpe.
_BASE = np.asarray(
    [
        [0.020, 0.010, -0.010],
        [-0.010, 0.030, 0.020],
        [0.030, -0.020, 0.010],
        [0.010, 0.020, -0.020],
        [0.020, 0.010, 0.030],
        [-0.020, 0.030, 0.010],
        [0.010, -0.010, 0.020],
        [0.030, 0.020, -0.010],
    ],
    dtype=np.float64,
)


def _base_with_constant(trial: int, rows: slice) -> np.ndarray:
    values = _BASE.copy()
    values[rows, trial] = 0.01
    return values


# trial-3 is flat only in rows 2-3, so with four two-row windows only window 2
# is undefined, while a 4/4 split still sees a varying trial-3 in both roles.
_WINDOW_TWO_UNDEFINED = _base_with_constant(2, slice(2, 4))


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
    values: np.ndarray = _BASE,
    *,
    periods_per_year: int | None = 252,
    search_complete: bool = True,
    selection_metric: str = "period_sharpe_ratio",
    excluded: tuple[int, ...] = (),
    split_in_sample_counts: tuple[tuple[str, int], ...] = (),
) -> ExperimentFamily:
    """trial-1 is always selected; each split's IS role is its first k rows."""

    matrix = np.asarray(values, dtype=np.float64)
    trial_ids = tuple(f"trial-{index + 1}" for index in range(matrix.shape[1]))
    timestamps = pd.date_range("2026-01-01", periods=len(matrix), freq="B")
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=periods_per_year)
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=index not in excluded,
            selected=index == 0,
            selection_score=float(len(trial_ids) - index),
            parameters=(TrialParameter("lookback", index + 1),),
            reason="excluded before selection" if index in excluded else None,
        )
        for index, trial_id in enumerate(trial_ids)
    )
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="temporal-contract-family",
            declared_total_attempted_trials=len(trials),
            search_complete=search_complete,
            selected_trial_id="trial-1",
            selection_rule="maximize period Sharpe",
            selection_metric=selection_metric,
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=timestamps,
            trial_ids=trial_ids,
            values=matrix,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        splits=tuple(
            ExperimentSplit(split_id, timestamps[:count], timestamps[count:])
            for split_id, count in split_in_sample_counts
        ),
    )


def _two_role_values(
    in_sample_levels: tuple[float, ...],
    out_of_sample_levels: tuple[float, ...],
) -> np.ndarray:
    # Each trial earns (level, level - 0.02) in each two-row role. Every trial
    # then has the same standard deviation 0.02 / sqrt(2) and a mean of
    # level - 0.01, so period Sharpes are ordered exactly as the levels are.
    return np.asarray(
        [
            list(in_sample_levels),
            [level - 0.02 for level in in_sample_levels],
            list(out_of_sample_levels),
            [level - 0.02 for level in out_of_sample_levels],
        ],
        dtype=np.float64,
    )


_ONE_VALID_ONE_SHORT_SPLIT = (("a-half", 4), ("b-one-row", 1))


@pytest.mark.parametrize(
    "family",
    [
        pytest.param(_family(search_complete=False), id="incomplete-search"),
        pytest.param(_family(_BASE[:, :2], excluded=(1,)), id="one-eligible-trial"),
        pytest.param(_family(_BASE[:3]), id="three-observations"),
    ],
)
def test_family_below_the_documented_minimums_is_ineligible(
    family: ExperimentFamily,
) -> None:
    # Methodology "Shared eligibility": complete declared search history, at
    # least two selection-eligible trials, at least four aligned observations.
    result = calculate_temporal_robustness(family, _spec(window_count=2))

    assert result.status is TemporalRobustnessStatus.FAMILY_INELIGIBLE


def test_family_exactly_at_the_documented_minimums_is_eligible() -> None:
    # "At least two" trials and "at least four" observations include 2 and 4.
    result = calculate_temporal_robustness(
        _family(_BASE[:4, :2]),
        _spec(window_count=2),
    )

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.selection_eligible_trial_count == 2
    assert result.observation_count == 4


def test_one_period_per_year_is_a_positive_sampling_rate() -> None:
    # Annual data is positive periods_per_year, and (1 + r) ** (1 / 1) - 1 = r.
    result = calculate_temporal_robustness(
        _family(periods_per_year=1),
        _spec(annual_risk_free_rate=0.03),
    )

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.periods_per_year == 1
    assert result.period_risk_free_rate == pytest.approx(0.03)


def test_completed_trial_excluded_from_selection_is_never_ranked() -> None:
    # trial-3 earns (0.05, 0.04) in every window: Sharpe 0.045 / 0.00707 = 6.4,
    # far above any other trial's window Sharpe. It was excluded from the
    # selection, so it must not enter the comparison at all.
    values = _BASE.copy()
    values[:, 2] = [0.05, 0.04] * 4
    result = calculate_temporal_robustness(_family(values, excluded=(2,)), _spec())

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.selection_eligible_trial_count == 2
    assert "trial-3" not in result.distinct_window_winner_trial_ids
    assert all("trial-3" not in item.tied_best_trial_ids for item in result.windows)
    assert all(item.selected_rank in (1.0, 2.0) for item in result.windows)


def _assert_slice_counts_match_reported_slices(
    result: TemporalRobustnessResult,
) -> None:
    valid_windows = sum(
        item.status is RobustnessSliceStatus.ELIGIBLE for item in result.windows
    )
    valid_splits = sum(
        item.status is RobustnessSliceStatus.ELIGIBLE for item in result.external_splits
    )
    assert result.valid_window_count == valid_windows
    assert result.invalid_window_count == len(result.windows) - valid_windows
    assert result.valid_external_split_count == valid_splits
    assert result.invalid_external_split_count == (
        len(result.external_splits) - valid_splits
    )


@pytest.mark.parametrize(
    ("family", "spec", "status"),
    [
        (
            _family(
                search_complete=False,
                split_in_sample_counts=_ONE_VALID_ONE_SHORT_SPLIT,
            ),
            _spec(),
            TemporalRobustnessStatus.FAMILY_INELIGIBLE,
        ),
        (
            _family(
                selection_metric="validation_sharpe",
                split_in_sample_counts=_ONE_VALID_ONE_SHORT_SPLIT,
            ),
            _spec(),
            TemporalRobustnessStatus.SELECTION_RULE_INCOMPATIBLE,
        ),
        (
            _family(
                periods_per_year=None,
                split_in_sample_counts=_ONE_VALID_ONE_SHORT_SPLIT,
            ),
            _spec(),
            TemporalRobustnessStatus.PERIODS_PER_YEAR_UNAVAILABLE,
        ),
        (
            _family(split_in_sample_counts=_ONE_VALID_ONE_SHORT_SPLIT),
            _spec(window_count=3),
            TemporalRobustnessStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_WINDOWS,
        ),
        (
            _family(split_in_sample_counts=_ONE_VALID_ONE_SHORT_SPLIT),
            _spec(window_count=8),
            TemporalRobustnessStatus.INSUFFICIENT_WINDOW_OBSERVATIONS,
        ),
        (
            _family(
                _WINDOW_TWO_UNDEFINED,
                split_in_sample_counts=_ONE_VALID_ONE_SHORT_SPLIT,
            ),
            _spec(),
            TemporalRobustnessStatus.INCOMPLETE_WINDOW_METRICS,
        ),
        (
            _family(split_in_sample_counts=_ONE_VALID_ONE_SHORT_SPLIT),
            _spec(),
            TemporalRobustnessStatus.ELIGIBLE,
        ),
    ],
)
def test_valid_and_invalid_counts_agree_with_the_reported_slices(
    family: ExperimentFamily,
    spec: TemporalRobustnessSpec,
    status: TemporalRobustnessStatus,
) -> None:
    result = calculate_temporal_robustness(family, spec)

    assert result.status is status
    _assert_slice_counts_match_reported_slices(result)


def test_windows_partition_the_history_in_time_order_whatever_their_status() -> None:
    # Methodology: equal contiguous windows. With 8 rows and 4 windows, window
    # k (numbered from 1) covers rows 2(k-1) and 2k-1, defined or not.
    family = _family(_WINDOW_TWO_UNDEFINED)
    timestamps = family.returns.timestamps
    result = calculate_temporal_robustness(family, _spec())

    assert [item.status for item in result.windows] == [
        RobustnessSliceStatus.ELIGIBLE,
        RobustnessSliceStatus.PERFORMANCE_METRIC_UNAVAILABLE,
        RobustnessSliceStatus.ELIGIBLE,
        RobustnessSliceStatus.ELIGIBLE,
    ]
    for number, item in enumerate(result.windows, start=1):
        assert item.window_index == number
        assert item.observation_count == 2
        assert item.start_timestamp == timestamps[2 * (number - 1)]
        assert item.end_timestamp == timestamps[2 * number - 1]


def test_median_ranked_window_is_not_in_the_top_half() -> None:
    # Per window: trial-1 (0.03, 0.01) Sharpe sqrt(2); trial-2 (0.04, 0.00)
    # sqrt(2)/2; trial-3 (0.05, 0.03) 2*sqrt(2). trial-1 is rank 2 of 3, so
    # relative rank 2/4 = 0.5 and logit log(1) = 0. Methodology: "The strict
    # > 0 boundary means a median-ranked trial is not classified as top half."
    values = np.asarray(
        [
            [0.03, 0.04, 0.05],
            [0.01, 0.00, 0.03],
            [0.03, 0.04, 0.05],
            [0.01, 0.00, 0.03],
        ]
    )
    result = calculate_temporal_robustness(_family(values), _spec(window_count=2))

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    for item in result.windows:
        assert item.selected_rank == 2.0
        assert item.selected_rank_logit == 0.0
        assert item.selected_in_top_half is False
    assert result.selected_top_half_fraction == 0.0
    assert result.top_half_fraction_requirement_met is False


def test_zero_sharpe_window_is_not_below_zero() -> None:
    # Window 1: trial-1 earns (0.01, -0.01); the mean is exactly 0.0 in IEEE
    # arithmetic and the risk-free rate is 0, so its Sharpe is exactly 0.
    values = np.asarray(
        [
            [0.01, 0.02, -0.01],
            [-0.01, 0.00, 0.02],
            [0.02, 0.01, 0.00],
            [0.00, 0.03, 0.01],
        ]
    )
    result = calculate_temporal_robustness(_family(values), _spec(window_count=2))

    assert result.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.windows[0].selected_period_sharpe_ratio == 0.0
    assert result.windows[0].selected_score_below_zero is False
    assert result.selected_below_zero_fraction == 0.0


@pytest.mark.parametrize(
    ("maximum", "met"),
    [(0.5, True), (0.25, False)],
)
def test_below_zero_fraction_at_the_maximum_acceptable_meets_the_requirement(
    maximum: float,
    met: bool,
) -> None:
    # trial-1 earns (-0.01, -0.03) in window 1 and (0.02, 0.00) in window 2:
    # one of two windows below zero, a fraction of exactly 0.5. A *maximum
    # acceptable* fraction is itself acceptable, as for CSCV's maximum PBO.
    values = np.asarray(
        [
            [-0.01, 0.02, -0.01],
            [-0.03, 0.00, 0.02],
            [0.02, 0.01, 0.00],
            [0.00, 0.03, 0.01],
        ]
    )
    result = calculate_temporal_robustness(
        _family(values),
        _spec(window_count=2, maximum_acceptable_below_zero_fraction=maximum),
    )

    assert result.selected_below_zero_fraction == 0.5
    assert result.below_zero_fraction_requirement_met is met


@pytest.mark.parametrize("in_sample_count", [2, 6])
def test_split_role_with_exactly_two_observations_is_evaluated(
    in_sample_count: int,
) -> None:
    # Methodology: only "fewer than two observations in either role" makes a
    # declared split unavailable.
    result = calculate_temporal_robustness(
        _family(split_in_sample_counts=(("fold", in_sample_count),)),
        _spec(),
    )
    split = result.external_splits[0]

    assert split.status is RobustnessSliceStatus.ELIGIBLE
    assert split.in_sample_observation_count == in_sample_count
    assert split.out_of_sample_observation_count == 8 - in_sample_count
    assert split.unavailable_trial_ids == ()


@pytest.mark.parametrize(
    "flat_rows",
    [pytest.param(slice(0, 4), id="in-sample"), pytest.param(slice(4, 8), id="oos")],
)
def test_trial_undefined_in_only_one_split_role_makes_the_split_unavailable(
    flat_rows: slice,
) -> None:
    # Methodology: "any undefined eligible-trial score" retains the split as
    # performance_metric_unavailable -- one role is enough.
    result = calculate_temporal_robustness(
        _family(
            _base_with_constant(2, flat_rows),
            split_in_sample_counts=(("fold", 4),),
        ),
        _spec(),
    )
    split = result.external_splits[0]

    assert split.status is RobustnessSliceStatus.PERFORMANCE_METRIC_UNAVAILABLE
    assert split.unavailable_trial_ids == ("trial-3",)
    assert result.valid_external_split_count == 0


@pytest.mark.parametrize(
    ("in_sample_levels", "out_of_sample_levels", "rank", "top_half"),
    [
        # 3 trials: IS winner trial-1 is OOS rank 2 = (3 + 1) / 2, the median.
        ((0.05, 0.03, 0.04), (0.04, 0.03, 0.05), 2.0, False),
        # 4 trials: OOS rank 3 > (4 + 1) / 2; logit log(0.6 / 0.4) = 0.405.
        ((0.06, 0.03, 0.04, 0.05), (0.05, 0.03, 0.04, 0.06), 3.0, True),
    ],
)
def test_split_top_half_means_an_out_of_sample_rank_above_the_median(
    in_sample_levels: tuple[float, ...],
    out_of_sample_levels: tuple[float, ...],
    rank: float,
    top_half: bool,
) -> None:
    # top half <=> logit > 0 <=> rank / (n + 1) > 1/2 <=> rank > (n + 1) / 2.
    trial_count = len(in_sample_levels)
    result = calculate_temporal_robustness(
        _family(
            _two_role_values(in_sample_levels, out_of_sample_levels),
            split_in_sample_counts=(("fold", 2),),
        ),
        _spec(window_count=2),
    )
    split = result.external_splits[0]
    relative_rank = rank / (trial_count + 1)

    assert split.in_sample_winner_trial_id == "trial-1"
    assert split.selected_out_of_sample_rank == rank
    assert split.selected_out_of_sample_rank_logit == pytest.approx(
        math.log(relative_rank / (1.0 - relative_rank))
    )
    assert split.selected_out_of_sample_in_top_half is top_half


def test_zero_sharpe_out_of_sample_is_not_below_zero() -> None:
    # IS: trial-1 (0.05, 0.03) beats (0.03, 0.01) and (0.04, 0.02). OOS:
    # trial-1 earns (0.01, -0.01), a mean of exactly 0.0, so its Sharpe is 0.
    values = np.asarray(
        [
            [0.05, 0.03, 0.04],
            [0.03, 0.01, 0.02],
            [0.01, 0.03, 0.04],
            [-0.01, 0.01, 0.02],
        ]
    )
    result = calculate_temporal_robustness(
        _family(values, split_in_sample_counts=(("fold", 2),)),
        _spec(window_count=2),
    )
    split = result.external_splits[0]

    assert split.in_sample_winner_trial_id == "trial-1"
    assert split.selected_out_of_sample_score == 0.0
    assert split.selected_out_of_sample_score_below_zero is False
