"""A flat trial must not decide Hansen's SPA (night 7's N20).

3a9795e's structural test, carried to the 1.4.0 data-snooping code: a trial
whose active return is constant has bit-identical bootstrap means, but np.var
of them is a rounding residue for a constant like 0.0004 (not for 2**-11).
Studentising by the residue turned SPA p = 0.50 into a rejection at p = 0.002.
"""

import numpy as np
import pandas as pd

from backtest_auditor.audit.family_methodology import assess_experiment_family
from backtest_auditor.domain.assumptions import DataSnoopingSpec
from backtest_auditor.domain.enums import (
    DataSnoopingStatus,
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
from backtest_auditor.statistics.data_snooping import calculate_data_snooping_tests

OBSERVATIONS = 300


def _family(flat_constant: float) -> ExperimentFamily:
    rng = np.random.default_rng(23)
    noise = rng.standard_normal((OBSERVATIONS, 2)) * 0.01
    values = np.column_stack([noise, np.full(OBSERVATIONS, flat_constant)])
    trial_ids = ("trial-1", "trial-2", "trial-3")
    sharpes = values.mean(axis=0) / np.where(
        np.ptp(values, axis=0) == 0.0, np.inf, values.std(axis=0, ddof=1)
    )
    selected = int(np.argmax(sharpes))
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=252)
    timestamps = pd.date_range("2026-01-01", periods=OBSERVATIONS, freq="B")
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == selected,
            selection_score=float(sharpes[index]),
            parameters=(TrialParameter("lookback", 10 + index),),
        )
        for index, trial_id in enumerate(trial_ids)
    )
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="flat-trial-family",
            declared_total_attempted_trials=len(trial_ids),
            search_complete=True,
            selected_trial_id=trial_ids[selected],
            selection_rule="maximize observed Sharpe",
            selection_metric="sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
            benchmark_id="zero",
            benchmark_return_convention=ReturnConvention.SIMPLE,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=timestamps,
            trial_ids=trial_ids,
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        benchmark_returns=ReturnSeries(
            timestamps=timestamps,
            values=np.zeros(OBSERVATIONS),
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


def _spa(flat_constant: float):
    family = _family(flat_constant)
    assessment = assess_experiment_family(family)[0]
    spec = DataSnoopingSpec(
        replications=499,
        mean_block_length=5,
        random_seed=11,
        significance_level=0.05,
    )
    return calculate_data_snooping_tests(family, assessment, spec=spec)


def test_numpy_leaves_a_residue_for_identical_bootstrap_means_of_0_0004() -> None:
    means = np.full(499, np.mean(np.full(OBSERVATIONS, 0.0004)))
    assert float(np.var(means, ddof=1)) != 0.0
    assert float(np.var(np.full(499, 2.0**-11), ddof=1)) == 0.0


def test_spa_verdict_does_not_depend_on_the_flat_constants_representation() -> None:
    residue = _spa(0.0004)
    exact = _spa(2.0**-11)

    assert residue is not None and exact is not None
    assert residue.status is DataSnoopingStatus.ELIGIBLE
    assert residue.hansen_spa_p_value == exact.hansen_spa_p_value
    assert residue.hansen_spa_rejects_null == exact.hansen_spa_rejects_null
    assert residue.hansen_spa_rejects_null is False
