import itertools
import math
import numpy as np
import pandas as pd
import pytest
from scipy.stats import rankdata

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


def _spec(**overrides: object) -> CSCVSpec:
    values = {
        "method": CSCVMethod.COMBINATORIALLY_SYMMETRIC,
        "performance_metric": CSCVPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "partition_count": 4,
        "annual_risk_free_rate": 0.0,
        "maximum_combinations": 100,
        "rank_tie_method": CSCVRankTieMethod.AVERAGE,
        "winner_tie_policy": CSCVWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        "maximum_acceptable_pbo": 0.05,
    }
    values.update(overrides)
    return CSCVSpec(**values)


def _family(
    values: np.ndarray = _VALUES,
    *,
    convention: ReturnConvention = ReturnConvention.SIMPLE,
    periods_per_year: int | None = 252,
    search_complete: bool = True,
    selection_metric: str = "period_sharpe_ratio",
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
    sampling = SamplingSpec(
        declared_frequency="B",
        periods_per_year=periods_per_year,
    )
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="cscv-family",
            declared_total_attempted_trials=len(trials),
            search_complete=search_complete,
            selected_trial_id="trial-1",
            selection_rule="maximize period Sharpe",
            selection_metric=selection_metric,
            selection_direction=selection_direction,
            parameter_names=("lookback",),
            return_convention=convention,
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
            convention=convention,
            sampling=sampling,
        ),
    )


def _pypbo_reference(
    values: np.ndarray, partition_count: int
) -> tuple[float, list[float]]:
    partition_size = len(values) // partition_count
    partition_ids = tuple(range(partition_count))
    logits = []
    for selected_partitions in itertools.combinations(
        partition_ids,
        partition_count // 2,
    ):
        complement = tuple(
            item for item in partition_ids if item not in selected_partitions
        )
        selected_rows = np.concatenate(
            [
                np.arange(item * partition_size, (item + 1) * partition_size)
                for item in selected_partitions
            ]
        )
        complement_rows = np.concatenate(
            [
                np.arange(item * partition_size, (item + 1) * partition_size)
                for item in complement
            ]
        )
        in_sample = values[selected_rows]
        out_of_sample = values[complement_rows]
        in_sample_scores = np.mean(in_sample, axis=0) / np.std(
            in_sample,
            axis=0,
            ddof=1,
        )
        out_of_sample_scores = np.mean(out_of_sample, axis=0) / np.std(
            out_of_sample,
            axis=0,
            ddof=1,
        )
        winner = int(np.argmax(rankdata(in_sample_scores, method="average")))
        oos_rank = float(rankdata(out_of_sample_scores, method="average")[winner])
        relative_rank = oos_rank / (values.shape[1] + 1.0)
        logits.append(math.log(relative_rank / (1.0 - relative_rank)))
    return float(np.mean(np.asarray(logits) <= 0.0)), logits


def test_cscv_reproduces_paper_and_pypbo_rank_logit_algorithm() -> None:
    result = calculate_cscv(_family(), _spec())
    expected_pbo, expected_logits = _pypbo_reference(_VALUES, 4)

    assert expected_pbo == 1.0
    assert expected_logits == pytest.approx(
        [
            -0.8472978603872036,
            -1.3862943611198906,
            -1.3862943611198906,
            -1.3862943611198906,
            -1.3862943611198906,
            -0.4054651081081643,
        ]
    )
    assert result.status is CSCVStatus.ELIGIBLE
    assert result.total_combinations == math.comb(4, 2) == 6
    assert result.valid_split_count == 6
    assert result.invalid_split_count == 0
    assert result.probability_of_backtest_overfitting == pytest.approx(expected_pbo)
    assert [item.rank_logit for item in result.splits] == pytest.approx(expected_logits)


def test_cscv_is_deterministic_and_reuses_each_half_as_its_complement() -> None:
    first = calculate_cscv(_family(), _spec())
    second = calculate_cscv(_family(), _spec())
    pairs = {
        (
            split.in_sample_partition_indices,
            split.out_of_sample_partition_indices,
        )
        for split in first.splits
    }

    assert first == second
    assert all((right, left) in pairs for left, right in pairs)


def test_cscv_reports_pbo_loss_and_degradation_evidence() -> None:
    result = calculate_cscv(_family(), _spec())

    assert result.probability_of_backtest_overfitting is not None
    assert result.pbo_requirement_met == (
        result.probability_of_backtest_overfitting <= 0.05
    )
    assert result.probability_selected_oos_score_below_zero is not None
    assert result.mean_rank_logit is not None
    assert result.median_rank_logit is not None
    assert result.performance_degradation_slope is not None
    assert result.performance_degradation_r_squared is not None


def test_log_and_simple_inputs_produce_equivalent_cscv() -> None:
    simple = calculate_cscv(_family(), _spec())
    logged = calculate_cscv(
        _family(np.log1p(_VALUES), convention=ReturnConvention.LOG),
        _spec(),
    )

    assert logged.return_basis is ReturnConvention.SIMPLE
    assert logged.probability_of_backtest_overfitting == (
        simple.probability_of_backtest_overfitting
    )
    assert [item.rank_logit for item in logged.splits] == pytest.approx(
        [item.rank_logit for item in simple.splits]
    )


def test_cscv_uses_only_selection_eligible_curves_without_fabricating_failures() -> (
    None
):
    base = _family()
    excluded = ExperimentTrial(
        trial_id="trial-5",
        attempt_index=5,
        outcome=TrialOutcome.COMPLETED,
        included_in_selection=False,
        selected=False,
        selection_score=0.0,
        parameters=(TrialParameter("lookback", 5),),
        reason="Predeclared turnover constraint",
    )
    failed = ExperimentTrial(
        trial_id="trial-6",
        attempt_index=6,
        outcome=TrialOutcome.FAILED,
        included_in_selection=False,
        selected=False,
        selection_score=None,
        parameters=(TrialParameter("lookback", 6),),
        reason="Engine rejected invalid configuration",
    )
    family = ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="cscv-family-with-exclusions",
            declared_total_attempted_trials=6,
            search_complete=True,
            selected_trial_id="trial-1",
            selection_rule="maximize period Sharpe",
            selection_metric="period_sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=base.manifest.sampling,
        ),
        trials=base.trials + (excluded, failed),
        returns=TrialReturnMatrix(
            timestamps=base.returns.timestamps,
            trial_ids=base.returns.trial_ids + ("trial-5",),
            values=np.column_stack([base.returns.values, np.mean(_VALUES, axis=1)]),
            convention=ReturnConvention.SIMPLE,
            sampling=base.returns.sampling,
        ),
    )
    result = calculate_cscv(family, _spec())

    assert result.status is CSCVStatus.ELIGIBLE
    assert result.declared_attempted_trial_count == 6
    assert result.completed_trial_count == 5
    assert result.selection_eligible_trial_count == 4
    assert all(split.selected_trial_id != "trial-5" for split in result.splits)
    assert all(split.out_of_sample_rank <= 4 for split in result.splits)


def test_cscv_preserves_tied_winners_and_uses_attempt_order() -> None:
    values = _VALUES.copy()
    values[:, 1] = values[:, 0]
    result = calculate_cscv(_family(values), _spec())

    tied = [
        item for item in result.splits if len(item.tied_in_sample_winner_trial_ids) > 1
    ]
    assert tied
    assert all(
        item.tied_in_sample_winner_trial_ids[:2] == ("trial-1", "trial-2")
        for item in tied
    )
    assert all(item.selected_trial_id == "trial-1" for item in tied)


def test_cscv_refuses_to_drop_an_unequal_partition_remainder() -> None:
    values = np.vstack([_VALUES, _VALUES[0]])
    result = calculate_cscv(_family(values), _spec())

    assert result.status is CSCVStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_PARTITIONS
    assert result.splits == ()


def test_cscv_stops_before_exceeding_explicit_combination_limit() -> None:
    result = calculate_cscv(
        _family(),
        _spec(partition_count=8, maximum_combinations=69),
    )

    assert result.status is CSCVStatus.COMBINATION_LIMIT_EXCEEDED
    assert result.total_combinations == 70
    assert result.splits == ()


def test_cscv_preserves_undefined_split_metrics_instead_of_filtering() -> None:
    values = _VALUES.copy()
    values[:, 3] = 0.01
    result = calculate_cscv(_family(values), _spec())

    assert result.status is CSCVStatus.INCOMPLETE_SPLIT_METRICS
    assert result.invalid_split_count == 6
    assert all(
        item.status is CSCVSplitStatus.PERFORMANCE_METRIC_UNAVAILABLE
        for item in result.splits
    )
    assert all(item.unavailable_trial_ids == ("trial-4",) for item in result.splits)


@pytest.mark.parametrize(
    ("family", "spec", "status"),
    [
        (_family(search_complete=False), _spec(), CSCVStatus.FAMILY_INELIGIBLE),
        (
            _family(periods_per_year=None),
            _spec(),
            CSCVStatus.PERIODS_PER_YEAR_UNAVAILABLE,
        ),
        (
            _family(selection_metric="validation_sharpe"),
            _spec(),
            CSCVStatus.SELECTION_RULE_INCOMPATIBLE,
        ),
        (
            _family(selection_direction=SelectionDirection.MINIMIZE),
            _spec(),
            CSCVStatus.SELECTION_RULE_INCOMPATIBLE,
        ),
    ],
)
def test_cscv_returns_typed_ineligibility(
    family: ExperimentFamily,
    spec: CSCVSpec,
    status: CSCVStatus,
) -> None:
    assert calculate_cscv(family, spec).status is status


@pytest.mark.parametrize(
    "overrides",
    [
        {"partition_count": 3},
        {"maximum_combinations": 0},
        {"annual_risk_free_rate": -1.0},
        {"selection_metric_name": " "},
        {"maximum_acceptable_pbo": 1.0},
    ],
)
def test_cscv_spec_rejects_invalid_explicit_choices(overrides: dict) -> None:
    with pytest.raises(ValueError):
        _spec(**overrides)


def test_a_flat_trial_is_unavailable_whether_or_not_its_constant_is_representable() -> (
    None
):
    # A trial with no variation has no Sharpe ratio, so it can neither win nor
    # lose a split. np.std of a constant 0.001 over 12 rows is a rounding
    # residue, not 0.0, which once scored the trial near 4e15: it won every
    # split and CSCV published PBO = 0.0, a clean bill of health produced by
    # binary representation. A constant 0.25 leaves no residue and was always
    # handled correctly, so the two verdicts must agree.
    base = np.vstack([_VALUES, _VALUES[::-1], _VALUES])
    for constant in (0.25, 0.001):
        values = base.copy()
        values[:, 3] = constant
        result = calculate_cscv(_family(values), spec=_spec())

        assert result.status is CSCVStatus.INCOMPLETE_SPLIT_METRICS
        assert result.probability_of_backtest_overfitting is None


def test_perfectly_linear_degradation_is_recovered_exactly() -> None:
    from backtest_auditor.statistics.cscv import _linear_degradation

    # By hand: both vectors centre to (-0.5, 0.5, -0.5, 0.5), so Sxx = Syy =
    # Sxy = 1. Slope Sxy/Sxx = 1, intercept 1.5 - 1 * 0 = 1.5, and R-squared
    # Sxy**2 / (Sxx * Syy) = 1. A sum of squares of exactly 1.0 is ordinary
    # variation, not degeneracy.
    intercept, slope, r_squared = _linear_degradation(
        np.array([-0.5, 0.5, -0.5, 0.5]), np.array([1.0, 2.0, 1.0, 2.0])
    )

    assert (intercept, slope, r_squared) == (1.5, 1.0, 1.0)


def test_linear_degradation_does_not_depend_on_binary_representation() -> None:
    from backtest_auditor.statistics.cscv import _linear_degradation

    varying = np.linspace(0.5, 5.0, 10)
    # Ten copies of 0.001 centre to a residue, not zeros; 0.25 centres exactly.
    # Flat in-sample scores leave the slope unidentified either way.
    for constant in (0.25, 0.001):
        assert _linear_degradation(np.full(10, constant), varying) == (
            None,
            None,
            None,
        )
    # Flat out-of-sample scores: whichever R-squared convention applies (an
    # open decision), it must not change with representability.
    exact = _linear_degradation(varying, np.full(10, 0.25))
    residue = _linear_degradation(varying, np.full(10, 0.001))
    assert exact[2] == residue[2]
