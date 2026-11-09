import math

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import CSCVSpec
from backtest_auditor.domain.enums import (
    CSCVMethod,
    CSCVPerformanceMetric,
    CSCVRankTieMethod,
    CSCVSplitStatus,
    CSCVStatus,
    CSCVWinnerTiePolicy,
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
from backtest_auditor.statistics.cscv import calculate_cscv

# Rows are periods, columns are trials. Every column takes a different value in
# every row, so every two-row half has a finite, non-zero-volatility Sharpe.
_MINIMAL = np.asarray(
    [
        [0.01, 0.02],
        [0.03, -0.01],
        [0.02, 0.01],
        [0.04, 0.03],
    ],
    dtype=np.float64,
)

# S = 2. Half 1: trial-1 = [0.01, 0.03] (Sharpe sqrt 2), trial-2 = [-0.01, 0.01]
# (mean exactly 0, Sharpe 0). Half 2: both trials are [0.02, -0.02] (mean
# exactly 0, Sharpe exactly 0, an exact tie).
#   split 1: IS winner trial-1; OOS tie at 0 -> average rank 1.5,
#            omega = 1.5 / 3 = 0.5, lambda = log(1) = 0, OOS Sharpe exactly 0.
#   split 2: IS tie at 0 -> trial-1 by attempt index; OOS best -> rank 2,
#            omega = 2 / 3, lambda = log 2, OOS Sharpe sqrt 2.
# PBO = 1 / 2 (lambda <= 0 in split 1 only); P(OOS Sharpe < 0) = 0.
_MEDIAN_TIE = np.asarray(
    [
        [0.01, -0.01],
        [0.03, 0.01],
        [0.02, 0.02],
        [-0.02, -0.02],
    ],
    dtype=np.float64,
)


def _spec(**overrides: object) -> CSCVSpec:
    values = {
        "method": CSCVMethod.COMBINATORIALLY_SYMMETRIC,
        "performance_metric": CSCVPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "partition_count": 2,
        "annual_risk_free_rate": 0.0,
        "maximum_combinations": 100,
        "rank_tie_method": CSCVRankTieMethod.AVERAGE,
        "winner_tie_policy": CSCVWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        "maximum_acceptable_pbo": 0.05,
    }
    values.update(overrides)
    return CSCVSpec(**values)


def _family(
    values: np.ndarray,
    *,
    periods_per_year: int | None = 252,
    search_complete: bool = True,
    selection_direction: SelectionDirection = SelectionDirection.MAXIMIZE,
) -> ExperimentFamily:
    matrix_values = np.asarray(values, dtype=np.float64)
    trial_ids = tuple(f"trial-{index + 1}" for index in range(matrix_values.shape[1]))
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == 0,
            selection_score=float(
                index + 1
                if selection_direction is SelectionDirection.MINIMIZE
                else matrix_values.shape[1] - index
            ),
            parameters=(TrialParameter("lookback", index + 1),),
        )
        for index, trial_id in enumerate(trial_ids)
    )
    sampling = SamplingSpec(periods_per_year=periods_per_year)
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="cscv-boundaries",
            declared_total_attempted_trials=len(trials),
            search_complete=search_complete,
            selected_trial_id="trial-1",
            selection_rule="maximize period Sharpe",
            selection_metric="period_sharpe_ratio",
            selection_direction=selection_direction,
            parameter_names=("lookback",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=pd.date_range("2026-01-01", periods=len(matrix_values)),
            trial_ids=trial_ids,
            values=matrix_values,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


@pytest.mark.parametrize("partition_count", [2, 4])
def test_two_trials_and_four_observations_meet_the_documented_minimum(
    partition_count: int,
) -> None:
    # CSCV_PBO_METHODOLOGY.md: "at least two ... selection-eligible trials",
    # "at least four exactly aligned observations", "at least two
    # observations per half-sample". T = 4 gives exactly two per half.
    result = calculate_cscv(_family(_MINIMAL), _spec(partition_count=partition_count))

    assert result.status is CSCVStatus.ELIGIBLE
    assert result.selection_eligible_trial_count == 2
    assert result.observation_count == 4
    assert result.valid_split_count == math.comb(partition_count, partition_count // 2)


@pytest.mark.parametrize(
    "values",
    [_MINIMAL[:, :1], _MINIMAL[:3, :]],
    ids=["one-trial", "three-observations"],
)
def test_one_below_the_documented_minimum_is_family_ineligible(
    values: np.ndarray,
) -> None:
    result = calculate_cscv(_family(values), _spec())

    assert result.status is CSCVStatus.FAMILY_INELIGIBLE
    assert result.splits == ()


def test_one_period_per_year_is_a_positive_declaration_and_runs() -> None:
    # Annual data declares periods_per_year = 1, which is positive. With a zero
    # risk-free rate the period Sharpe does not depend on the declaration, so
    # every split must match the daily declaration exactly.
    annual = calculate_cscv(_family(_MINIMAL, periods_per_year=1), _spec())
    daily = calculate_cscv(_family(_MINIMAL, periods_per_year=252), _spec())

    assert annual.status is CSCVStatus.ELIGIBLE
    assert annual.periods_per_year == 1
    assert annual.splits == daily.splits
    assert annual.probability_of_backtest_overfitting == (
        daily.probability_of_backtest_overfitting
    )


def test_combination_count_equal_to_the_maximum_does_not_exceed_it() -> None:
    # C(4, 2) = 6. A maximum of 6 is not exceeded; a maximum of 5 is.
    at_limit = calculate_cscv(
        _family(_MINIMAL),
        _spec(partition_count=4, maximum_combinations=6),
    )
    over_limit = calculate_cscv(
        _family(_MINIMAL),
        _spec(partition_count=4, maximum_combinations=5),
    )

    assert at_limit.status is CSCVStatus.ELIGIBLE
    assert at_limit.valid_split_count == 6
    assert over_limit.status is CSCVStatus.COMBINATION_LIMIT_EXCEEDED
    assert over_limit.splits == ()


def test_pbo_counts_a_median_oos_rank_as_an_overfit_event() -> None:
    # CSCV_PBO_METHODOLOGY.md step 8: PBO is the share of logits with
    # lambda <= 0, and "counts a median logit as an overfit event".
    result = calculate_cscv(_family(_MEDIAN_TIE), _spec())
    median_split, winning_split = result.splits

    assert result.status is CSCVStatus.ELIGIBLE
    assert median_split.selected_trial_id == "trial-1"
    assert median_split.out_of_sample_rank == 1.5
    assert median_split.relative_out_of_sample_rank == 0.5
    assert median_split.rank_logit == 0.0
    assert median_split.overfit_event is True
    assert winning_split.tied_in_sample_winner_trial_ids == ("trial-1", "trial-2")
    assert winning_split.selected_trial_id == "trial-1"
    assert winning_split.out_of_sample_rank == 2.0
    assert winning_split.rank_logit == pytest.approx(math.log(2.0))
    assert winning_split.overfit_event is False
    assert result.probability_of_backtest_overfitting == 0.5


def test_pbo_exactly_at_the_declared_maximum_is_within_tolerance() -> None:
    # maximum_acceptable_pbo is a maximum: a PBO equal to it is acceptable.
    at_maximum = calculate_cscv(
        _family(_MEDIAN_TIE),
        _spec(maximum_acceptable_pbo=0.5),
    )
    below_pbo = calculate_cscv(
        _family(_MEDIAN_TIE),
        _spec(maximum_acceptable_pbo=0.49),
    )

    assert at_maximum.probability_of_backtest_overfitting == 0.5
    assert at_maximum.pbo_requirement_met is True
    assert below_pbo.pbo_requirement_met is False


def test_a_selected_oos_sharpe_of_exactly_zero_is_not_below_zero() -> None:
    # Split 1's selected trial earns exactly the zero risk-free rate out of
    # sample: mean(0.02, -0.02) = 0, so its OOS Sharpe is 0 and it lost nothing.
    result = calculate_cscv(_family(_MEDIAN_TIE), _spec())
    zero_split, positive_split = result.splits

    assert zero_split.selected_out_of_sample_score == 0.0
    assert zero_split.selected_out_of_sample_score_below_zero is False
    assert positive_split.selected_out_of_sample_score == pytest.approx(math.sqrt(2))
    assert positive_split.selected_out_of_sample_score_below_zero is False
    assert result.probability_selected_oos_score_below_zero == 0.0


def test_a_winner_that_stays_best_out_of_sample_is_never_an_overfit_event() -> None:
    # trial-2 = trial-1 - 0.005 has the same volatility and a lower mean in
    # every half, so trial-1 wins IS and ranks N = 2 of 2 OOS in every split:
    # omega = 2 / 3, lambda = log 2 > 0, and PBO = 0.
    leader = np.asarray([0.012, -0.004, 0.009, 0.003, -0.006, 0.011, 0.002, 0.007])
    values = np.column_stack([leader, leader - 0.005])
    result = calculate_cscv(_family(values), _spec(partition_count=4))

    assert result.status is CSCVStatus.ELIGIBLE
    assert result.valid_split_count == 6
    assert all(split.selected_trial_id == "trial-1" for split in result.splits)
    assert [split.rank_logit for split in result.splits] == pytest.approx(
        [math.log(2.0)] * 6
    )
    assert not any(split.overfit_event for split in result.splits)
    assert result.probability_of_backtest_overfitting == 0.0


def test_a_trial_undefined_in_only_one_half_makes_both_splits_unavailable() -> None:
    # trial-2 is constant in half 1 (zero volatility, undefined Sharpe) and
    # varies in half 2. Each split uses half 1 as either IS or OOS, so neither
    # split can rank every trial and none may be silently kept.
    values = np.asarray(
        [
            [0.01, 0.01],
            [0.03, 0.01],
            [0.02, 0.02],
            [0.04, -0.01],
        ],
        dtype=np.float64,
    )
    result = calculate_cscv(_family(values), _spec())

    assert result.status is CSCVStatus.INCOMPLETE_SPLIT_METRICS
    assert result.invalid_split_count == 2
    assert result.valid_split_count == 0
    assert all(
        split.status is CSCVSplitStatus.PERFORMANCE_METRIC_UNAVAILABLE
        and split.unavailable_trial_ids == ("trial-2",)
        for split in result.splits
    )
    assert result.probability_of_backtest_overfitting is None


def test_degradation_regression_is_undefined_when_selected_is_scores_do_not_vary() -> (
    None
):
    # trial-1 is [0.01, 0.03] then [0.03, 0.01]: the same Sharpe (sqrt 2) in
    # both halves, and trial-2 = trial-1 - 0.01 is lower in both. Both splits
    # select trial-1 with IS Sharpe sqrt 2, so the OLS slope Sxy / Sxx has
    # Sxx = 0 and is not identified.
    values = np.asarray(
        [
            [0.01, 0.00],
            [0.03, 0.02],
            [0.03, 0.02],
            [0.01, 0.00],
        ],
        dtype=np.float64,
    )
    result = calculate_cscv(_family(values), _spec())

    assert result.status is CSCVStatus.ELIGIBLE
    assert [split.selected_in_sample_score for split in result.splits] == (
        pytest.approx([math.sqrt(2)] * 2)
    )
    assert result.performance_degradation_slope is None
    assert result.performance_degradation_intercept is None
    assert result.performance_degradation_r_squared is None


def test_degradation_line_is_flat_at_the_oos_score_when_oos_scores_do_not_vary() -> (
    None
):
    # Half 1: trial-1 [0.03, 0.05] (Sharpe 2 sqrt 2), trial-2 [0.01, 0.03]
    # (sqrt 2). Half 2: trial-1 [0.01, 0.03] (sqrt 2), trial-2 [0.02, 0.04]
    # (1.5 sqrt 2). Split 1 selects trial-1, split 2 selects trial-2, and both
    # score the identical pair [0.01, 0.03] OOS. Regressing a constant y on a
    # varying x gives slope 0 and intercept equal to that constant, sqrt 2.
    values = np.asarray(
        [
            [0.03, 0.01],
            [0.05, 0.03],
            [0.01, 0.02],
            [0.03, 0.04],
        ],
        dtype=np.float64,
    )
    result = calculate_cscv(_family(values), _spec())

    assert result.status is CSCVStatus.ELIGIBLE
    assert [split.selected_trial_id for split in result.splits] == [
        "trial-1",
        "trial-2",
    ]
    assert [split.selected_in_sample_score for split in result.splits] == (
        pytest.approx([2.0 * math.sqrt(2), 1.5 * math.sqrt(2)])
    )
    assert result.performance_degradation_slope == pytest.approx(0.0, abs=1e-12)
    assert result.performance_degradation_intercept == pytest.approx(math.sqrt(2))


@pytest.mark.parametrize(
    ("family", "spec", "status"),
    [
        (
            _family(_MINIMAL, search_complete=False),
            _spec(),
            CSCVStatus.FAMILY_INELIGIBLE,
        ),
        (
            _family(_MINIMAL, selection_direction=SelectionDirection.MINIMIZE),
            _spec(),
            CSCVStatus.SELECTION_RULE_INCOMPATIBLE,
        ),
        (
            _family(_MINIMAL, periods_per_year=None),
            _spec(),
            CSCVStatus.PERIODS_PER_YEAR_UNAVAILABLE,
        ),
        (
            _family(np.vstack([_MINIMAL, _MINIMAL[:1]])),
            _spec(partition_count=4),
            CSCVStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_PARTITIONS,
        ),
        (
            _family(_MINIMAL),
            _spec(partition_count=4, maximum_combinations=5),
            CSCVStatus.COMBINATION_LIMIT_EXCEEDED,
        ),
        (
            _family(np.column_stack([_MINIMAL[:, 0], np.full(4, 0.01)])),
            _spec(),
            CSCVStatus.INCOMPLETE_SPLIT_METRICS,
        ),
        (_family(_MINIMAL), _spec(), CSCVStatus.ELIGIBLE),
    ],
)
def test_split_counts_match_the_published_splits_for_every_status(
    family: ExperimentFamily,
    spec: CSCVSpec,
    status: CSCVStatus,
) -> None:
    # A family stopped before splitting attempted no splits, so both counts
    # must be zero rather than a default that claims otherwise.
    result = calculate_cscv(family, spec)
    eligible = sum(split.status is CSCVSplitStatus.ELIGIBLE for split in result.splits)

    assert result.status is status
    assert result.valid_split_count == eligible
    assert result.invalid_split_count == len(result.splits) - eligible
