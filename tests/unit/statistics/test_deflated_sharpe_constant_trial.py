import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.assumptions import DeflatedSharpeRatioSpec
from backtest_auditor.domain.enums import (
    DeflatedSharpeRatioMethod,
    DeflatedSharpeRatioStatus,
    DSRTrialCountPolicy,
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
from backtest_auditor.statistics.deflated_sharpe import (
    calculate_deflated_sharpe_ratio,
)

_SELECTED = [0.020, -0.005, 0.018, 0.004, 0.015, -0.002, 0.012, 0.006, 0.010, 0.003]


def _spec() -> DeflatedSharpeRatioSpec:
    return DeflatedSharpeRatioSpec(
        method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        annual_risk_free_rate=0.03,
        required_confidence_level=0.95,
    )


def _family_with_flat_trial(constant_return: float) -> ExperimentFamily:
    values = np.column_stack([_SELECTED, np.full(len(_SELECTED), constant_return)])
    trial_ids = ("trial-1", "trial-2")
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=252)
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="dsr-family",
            declared_total_attempted_trials=2,
            search_complete=True,
            selected_trial_id="trial-1",
            selection_rule="maximize observed Sharpe",
            selection_metric="sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("lookback",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=tuple(
            ExperimentTrial(
                trial_id=trial_id,
                attempt_index=index + 1,
                outcome=TrialOutcome.COMPLETED,
                included_in_selection=True,
                selected=index == 0,
                selection_score=(2.0 if index == 0 else 1.0),
                parameters=(TrialParameter("lookback", 10 + index),),
            )
            for index, trial_id in enumerate(trial_ids)
        ),
        returns=TrialReturnMatrix(
            timestamps=pd.date_range("2026-01-01", periods=len(values), freq="B"),
            trial_ids=trial_ids,
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


# 0.25 is exactly representable; 0.001 and -0.001 are not, and np.std of ten
# copies of them is a ~2.3e-19 rounding residue instead of 0.0 (the failure
# documented in statistics/degeneracy.py).
@pytest.mark.parametrize("constant_return", [0.25, 0.001, -0.001])
def test_flat_selection_trial_withholds_dsr_whatever_its_binary_representation(
    constant_return: float,
) -> None:
    # Every deviation of a constant series from its mean is zero, so its sample
    # volatility is exactly zero and its Sharpe ratio is undefined. The docs
    # then require status incomplete_trial_sharpe_distribution, and a Pearson
    # correlation with that trial is undefined too.
    result = calculate_deflated_sharpe_ratio(
        _family_with_flat_trial(constant_return),
        _spec(),
    )

    assert result.status is (
        DeflatedSharpeRatioStatus.INCOMPLETE_TRIAL_SHARPE_DISTRIBUTION
    )
    assert result.trial_sharpe_estimates[1].period_sharpe_ratio is None
    assert result.valid_selection_trial_sharpe_count == 1
    assert result.correlation_summary is None
    assert result.scenarios == ()
