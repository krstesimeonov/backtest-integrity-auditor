"""Flat (zero-variation) inputs in the 1.0.0 statistics, on 1.5.0.

`np.std` of identical non-representable floats such as 0.001 is a ~2e-19 rounding
residue instead of 0.0, so a Sharpe ratio that should be undefined comes out near
1e15. 1.5.0 handles a constant that is exactly representable (0.25) correctly, so
each test asks for the same outcome whatever the constant's binary representation.
Main fixed these in 19a2eae and 3a9795e (statistics/degeneracy.py); 1.5.0 predates
that. Findings N02 and N03 in night7/FINDINGS_1.5.0.md.
"""

import numpy as np
import pandas as pd
import pytest
from .conftest import cscv_spec, dsr_spec

from backtest_auditor.domain.assumptions import BootstrapSpec, SharpeRatioSpec
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    BootstrapMetric,
    FrequencyStatus,
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
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import calculate_annualized_statistics
from backtest_auditor.statistics.bootstrap import (
    calculate_bootstrap_confidence_intervals,
)
from backtest_auditor.statistics.cscv import calculate_cscv
from backtest_auditor.statistics.deflated_sharpe import calculate_deflated_sharpe_ratio
from backtest_auditor.statistics.sampling import assess_sampling


def test_bootstrap_sharpe_interval_is_not_set_by_a_constant_replicate():
    """Returns [0.001]*9 + [0.002], moving blocks of 2. A replicate holding k copies of
    the 0.002 block has period Sharpe (1 + k/10)·sqrt(90/(k(10 − k))) ≤ 3.479 for
    k = 1..5; k = 0 is ten 0.001s, whose Sharpe is undefined and must not enter the
    interval (N02)."""
    values = np.asarray([0.001] * 9 + [0.002])
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=10, freq="D"),
        values=values,
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(
            status=FrequencyStatus.DECLARED,
            declared_frequency="D",
            periods_per_year=252,
        ),
    )
    sampling = assess_sampling(series)
    annualized = calculate_annualized_statistics(
        series, sampling, sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0)
    )
    result = calculate_bootstrap_confidence_intervals(
        series,
        sampling,
        annualized,
        None,
        spec=BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=2000,
            confidence_level=0.95,
            block_length=2,
            random_seed=42,
        ),
    )
    sharpe = next(
        m for m in result.metrics if m.metric is BootstrapMetric.PERIOD_SHARPE_RATIO
    )
    largest_valid = 1.1 * np.sqrt(90 / 9)
    assert sharpe.upper_bound is not None
    assert sharpe.upper_bound <= largest_valid * (1 + 1e-9), (
        f"period Sharpe interval [{sharpe.lower_bound:.4g}, {sharpe.upper_bound:.4g}]; "
        f"no valid replicate exceeds {largest_valid:.4f}"
    )


def _family(matrix) -> ExperimentFamily:
    """Complete family selected by period Sharpe, as conftest's builder does, except that
    a trial with no variation (all values equal) gets the declared score -1e300 instead
    of np.std's residue-driven ~1e15, so the declared winner is the best varying trial
    whatever the constant's binary representation."""
    values = np.asarray(matrix, dtype=float)
    flat = np.ptp(values, axis=0) == 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = values.mean(axis=0) / values.std(axis=0, ddof=1)
    scores = np.where(flat | ~np.isfinite(sharpe), -1e300, sharpe)
    winner = int(np.argmax(scores))
    ids = tuple(f"t{i + 1:03d}" for i in range(values.shape[1]))
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=252)
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="flat",
            declared_total_attempted_trials=len(ids),
            search_complete=True,
            selected_trial_id=ids[winner],
            selection_rule="maximize period Sharpe",
            selection_metric="period_sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("p",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=tuple(
            ExperimentTrial(
                trial_id=trial_id,
                attempt_index=i + 1,
                outcome=TrialOutcome.COMPLETED,
                included_in_selection=True,
                selected=i == winner,
                selection_score=float(scores[i]),
                parameters=(TrialParameter("p", i + 1),),
            )
            for i, trial_id in enumerate(ids)
        ),
        returns=TrialReturnMatrix(
            timestamps=pd.bdate_range("2026-01-01", periods=values.shape[0]),
            trial_ids=ids,
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


_SELECTED = [0.020, -0.005, 0.018, 0.004, 0.015, -0.002, 0.012, 0.006, 0.010, 0.003]


@pytest.mark.parametrize("constant", [-0.001, 0.001])
def test_dsr_treats_a_flat_trial_as_flat_whatever_its_binary_representation(constant):
    """A family whose second trial is constant has an undefined trial Sharpe, so the
    trial-Sharpe distribution is incomplete. 1.5.0 says so for 0.25; for ±0.001 it
    reports an eligible DSR of 0.0, or the wrong status (N03)."""
    reference = calculate_deflated_sharpe_ratio(
        _family(np.column_stack([_SELECTED, np.full(10, 0.25)])),
        dsr_spec(),
    )
    result = calculate_deflated_sharpe_ratio(
        _family(np.column_stack([_SELECTED, np.full(10, constant)])),
        dsr_spec(),
    )
    assert result.status is reference.status, (
        f"flat trial {constant}: status {result.status.value}, "
        f"DSR {[s.deflated_sharpe_ratio for s in result.scenarios]}; "
        f"with the representable constant 0.25: {reference.status.value}"
    )


def test_cscv_does_not_let_a_flat_trial_win_every_split():
    """Five noise trials over 240 bars give PBO 0.53. Adding a sixth trial that returns
    a constant 0.001 must not turn that into an eligible PBO of 0.0: its Sharpe is
    undefined in every split, as 1.5.0 recognises when the constant is 0.25 (N03)."""
    rng = np.random.default_rng(3)
    noise = 0.01 * rng.standard_normal((240, 5))
    reference = calculate_cscv(
        _family(np.column_stack([noise, np.full(240, 0.25)])),
        cscv_spec(8),
    )
    result = calculate_cscv(
        _family(np.column_stack([noise, np.full(240, 0.001)])),
        cscv_spec(8),
    )
    assert result.status is reference.status, (
        f"flat 0.001 trial: status {result.status.value}, PBO "
        f"{result.probability_of_backtest_overfitting}; with 0.25: {reference.status.value}, "
        f"PBO {reference.probability_of_backtest_overfitting}"
    )
