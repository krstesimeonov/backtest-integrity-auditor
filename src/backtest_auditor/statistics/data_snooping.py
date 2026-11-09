import math
from typing import Any

import numpy as np

from backtest_auditor.domain.assumptions import DataSnoopingSpec
from backtest_auditor.domain.enums import DataSnoopingStatus, ExperimentFamilyStatus
from backtest_auditor.domain.experiment import ExperimentFamily
from backtest_auditor.domain.results import (
    DataSnoopingResult,
    ExperimentFamilyAssessmentResult,
)
from backtest_auditor.statistics.degeneracy import columns_with_zero_sample_variation
from backtest_auditor.statistics.resampling import stationary_bootstrap_indices
from backtest_auditor.statistics.return_basis import to_simple_returns


def calculate_data_snooping_tests(
    family: ExperimentFamily,
    assessment: ExperimentFamilyAssessmentResult,
    *,
    spec: DataSnoopingSpec | None = None,
) -> DataSnoopingResult | None:
    """Calculate White RC and consistent Hansen SPA against a shared benchmark."""

    if spec is None:
        return None
    eligible_trials = tuple(
        trial
        for trial in family.trials
        if trial.included_in_selection and trial.outcome.value == "completed"
    )
    base: dict[str, Any] = {
        "observation_count": assessment.observation_count,
        "selection_eligible_trial_count": len(eligible_trials),
        "benchmark_id": family.manifest.benchmark_id,
        "replications": spec.replications,
        "mean_block_length": spec.mean_block_length,
        "random_seed": spec.random_seed,
        "significance_level": spec.significance_level,
        "selected_trial_id": family.manifest.selected_trial_id,
    }
    if assessment.status is not ExperimentFamilyStatus.ELIGIBLE:
        return _empty(DataSnoopingStatus.FAMILY_INELIGIBLE, **base)
    if family.benchmark_returns is None:
        return _empty(DataSnoopingStatus.BENCHMARK_UNAVAILABLE, **base)
    if assessment.observation_count <= spec.mean_block_length:
        return _empty(DataSnoopingStatus.INSUFFICIENT_OBSERVATIONS, **base)
    if not eligible_trials:
        return _empty(DataSnoopingStatus.NO_VALID_TRIALS, **base)

    benchmark = to_simple_returns(family.benchmark_returns)
    active = np.column_stack(
        [
            to_simple_returns(family.returns.series_for(trial.trial_id)) - benchmark
            for trial in eligible_trials
        ]
    )
    observation_count = active.shape[0]
    observed_means = np.mean(active, axis=0)
    root_n = math.sqrt(observation_count)
    observed_white = max(0.0, root_n * float(np.max(observed_means)))

    rng = np.random.default_rng(spec.random_seed)
    bootstrap_means = np.empty((spec.replications, active.shape[1]), dtype=np.float64)
    for replication in range(spec.replications):
        indices = stationary_bootstrap_indices(
            observation_count,
            mean_block_length=spec.mean_block_length,
            rng=rng,
        )
        bootstrap_means[replication] = np.mean(active[indices], axis=0)

    white_distribution = np.maximum(
        0.0,
        root_n * np.max(bootstrap_means - observed_means, axis=1),
    )
    white_p = _corrected_p_value(white_distribution, observed_white)

    long_run_standard_deviation = np.sqrt(
        observation_count * np.var(bootstrap_means, axis=0, ddof=1)
    )
    # A trial whose active return is constant has bit-identical bootstrap
    # means, but np.var of them is a rounding residue (2.9e-39 for 0.0004),
    # not 0.0. Studentising by that residue gave the flat trial a statistic
    # near 1e17 and turned SPA p = 0.50 into a rejection at p = 0.002. Test
    # the data, as the family audit does (3a9795e).
    valid = (
        np.isfinite(long_run_standard_deviation)
        & (long_run_standard_deviation > 0.0)
        & ~columns_with_zero_sample_variation(active)
    )
    if not np.any(valid):
        return _empty(DataSnoopingStatus.NO_VALID_TRIALS, **base)
    means = observed_means[valid]
    deviations = long_run_standard_deviation[valid]
    observed_spa = max(0.0, float(np.max(root_n * means / deviations)))
    threshold_scale = math.sqrt(2.0 * math.log(math.log(observation_count)))
    mean_recenter = np.where(
        root_n * means <= -deviations * threshold_scale, means, 0.0
    )
    spa_distribution = np.maximum(
        0.0,
        np.max(
            root_n * (bootstrap_means[:, valid] - means + mean_recenter) / deviations,
            axis=1,
        ),
    )
    spa_p = _corrected_p_value(spa_distribution, observed_spa)

    maximum = float(np.max(observed_means))
    maximum_ids = tuple(
        trial.trial_id
        for trial, mean in zip(eligible_trials, observed_means, strict=True)
        if math.isclose(float(mean), maximum, rel_tol=1e-12, abs_tol=1e-15)
    )
    selected_index = tuple(trial.trial_id for trial in eligible_trials).index(
        family.manifest.selected_trial_id
    )
    return DataSnoopingResult(
        status=DataSnoopingStatus.ELIGIBLE,
        selected_mean_active_return=float(observed_means[selected_index]),
        observed_maximum_mean_active_return=maximum,
        observed_maximum_trial_ids=maximum_ids,
        white_reality_check_p_value=white_p,
        white_reality_check_rejects_null=white_p < spec.significance_level,
        hansen_spa_p_value=spa_p,
        hansen_spa_rejects_null=spa_p < spec.significance_level,
        **base,
    )


def _corrected_p_value(distribution: np.ndarray, observed: float) -> float:
    exceedances = int(np.count_nonzero(distribution >= observed))
    return (exceedances + 1.0) / (len(distribution) + 1.0)


def _empty(status: DataSnoopingStatus, **base: Any) -> DataSnoopingResult:
    return DataSnoopingResult(
        status=status,
        selected_mean_active_return=None,
        observed_maximum_mean_active_return=None,
        observed_maximum_trial_ids=(),
        white_reality_check_p_value=None,
        white_reality_check_rejects_null=None,
        hansen_spa_p_value=None,
        hansen_spa_rejects_null=None,
        **base,
    )
