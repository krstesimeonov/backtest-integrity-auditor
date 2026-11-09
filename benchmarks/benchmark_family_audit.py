"""Reproducible, non-gating scalability benchmark for family assessment."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence

import numpy as np
import pandas as pd

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.domain.enums import (
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
from backtest_auditor.domain.series import SamplingSpec


def build_synthetic_family(
    *,
    trial_count: int,
    observation_count: int,
    seed: int,
) -> ExperimentFamily:
    """Construct a canonical aligned family without file-I/O timing noise."""

    if trial_count < 2:
        raise ValueError("trial_count must be at least 2.")
    if observation_count < 4:
        raise ValueError("observation_count must be at least 4.")
    sampling = SamplingSpec(
        status=FrequencyStatus.DECLARED,
        declared_frequency="B",
        periods_per_year=252,
        timezone="UTC",
    )
    trial_ids = tuple(f"trial-{index:05d}" for index in range(1, trial_count + 1))
    rng = np.random.default_rng(seed)
    values = rng.normal(
        loc=0.0002,
        scale=0.01,
        size=(observation_count, trial_count),
    )
    scores = tuple(
        float(np.mean(values[:, index]) / np.std(values[:, index], ddof=1))
        for index in range(trial_count)
    )
    selected_index = int(np.argmax(scores))
    selected_id = trial_ids[selected_index]
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=trial_id == selected_id,
            selection_score=scores[index - 1],
            parameters=(TrialParameter(name="configuration", value=index),),
            source="deterministic synthetic benchmark",
        )
        for index, trial_id in enumerate(trial_ids, start=1)
    )
    matrix = TrialReturnMatrix(
        timestamps=pd.date_range(
            "2000-01-03",
            periods=observation_count,
            freq="B",
            tz="UTC",
        ),
        trial_ids=trial_ids,
        values=values,
        convention=ReturnConvention.SIMPLE,
        sampling=sampling,
    )
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="synthetic-scalability-benchmark",
            declared_total_attempted_trials=trial_count,
            search_complete=True,
            selected_trial_id=selected_id,
            selection_rule="maximum deterministic period Sharpe",
            selection_metric="period_sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("configuration",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
            source="benchmarks/benchmark_family_audit.py",
        ),
        trials=trials,
        returns=matrix,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=128)
    parser.add_argument("--observations", type=int, default=1_024)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--repeats", type=int, default=3)
    arguments = parser.parse_args(argv)
    if arguments.repeats <= 0:
        parser.error("--repeats must be positive")

    family = build_synthetic_family(
        trial_count=arguments.trials,
        observation_count=arguments.observations,
        seed=arguments.seed,
    )
    durations = []
    last_result = None
    for _ in range(arguments.repeats):
        started = time.perf_counter()
        last_result = audit_experiment_family(family)
        durations.append(time.perf_counter() - started)
    assert last_result is not None
    print(
        json.dumps(
            {
                "audit_status": last_result.assessment.status.value,
                "median_seconds": float(np.median(durations)),
                "observation_count": arguments.observations,
                "repeats": arguments.repeats,
                "seed": arguments.seed,
                "trial_count": arguments.trials,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
