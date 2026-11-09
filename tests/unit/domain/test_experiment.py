from dataclasses import replace
import math

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import (
    ReturnConvention,
    SelectionDirection,
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
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec


def _manifest(**overrides: object) -> ExperimentFamilyManifest:
    values = {
        "schema_version": "1.0",
        "family_id": "family-1",
        "declared_total_attempted_trials": 3,
        "search_complete": True,
        "selected_trial_id": "trial-2",
        "selection_rule": "maximize validation Sharpe",
        "selection_metric": "validation_sharpe",
        "selection_direction": SelectionDirection.MAXIMIZE,
        "parameter_names": ("lookback",),
        "return_convention": ReturnConvention.SIMPLE,
        "sampling": SamplingSpec(
            declared_frequency="D",
            periods_per_year=365,
            timezone="UTC",
        ),
    }
    values.update(overrides)
    return ExperimentFamilyManifest(**values)


def _trial(
    trial_id: str,
    attempt_index: int,
    *,
    selected: bool = False,
    outcome: TrialOutcome = TrialOutcome.COMPLETED,
    included: bool = True,
    reason: str | None = None,
) -> ExperimentTrial:
    return ExperimentTrial(
        trial_id=trial_id,
        attempt_index=attempt_index,
        outcome=outcome,
        included_in_selection=included,
        selected=selected,
        selection_score=(
            float(attempt_index) if outcome is TrialOutcome.COMPLETED else None
        ),
        parameters=(TrialParameter("lookback", attempt_index * 10),),
        reason=reason,
    )


def _raw_trial(**overrides: object) -> ExperimentTrial:
    values = {
        "trial_id": "trial-1",
        "attempt_index": 1,
        "outcome": TrialOutcome.COMPLETED,
        "included_in_selection": True,
        "selected": False,
        "selection_score": 1.0,
        "parameters": (TrialParameter("lookback", 10),),
    }
    values.update(overrides)
    return ExperimentTrial(**values)


def _matrix() -> TrialReturnMatrix:
    return TrialReturnMatrix(
        timestamps=pd.date_range("2026-01-01", periods=4, freq="D"),
        trial_ids=("trial-1", "trial-2"),
        values=np.asarray(
            [
                [0.01, 0.02],
                [-0.01, 0.0],
                [0.02, 0.03],
                [0.0, -0.01],
            ]
        ),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(periods_per_year=365),
    )


def _family(**overrides: object) -> ExperimentFamily:
    trials = (
        _trial("trial-1", 1),
        _trial("trial-2", 2, selected=True),
        _trial(
            "trial-3",
            3,
            outcome=TrialOutcome.FAILED,
            included=False,
            reason="engine failure",
        ),
    )
    values = {
        "manifest": _manifest(),
        "trials": trials,
        "returns": _matrix(),
    }
    values.update(overrides)
    return ExperimentFamily(**values)


@pytest.mark.parametrize(
    "value",
    [True, 10, 0.25, "fast"],
)
def test_trial_parameter_accepts_finite_json_scalars(value: object) -> None:
    parameter = TrialParameter(" mode ", value)

    assert parameter.name == "mode"
    assert parameter.value == value


@pytest.mark.parametrize("value", [None, [], {}, float("nan")])
def test_trial_parameter_rejects_noncanonical_values(value: object) -> None:
    with pytest.raises(ValueError):
        TrialParameter("mode", value)


def test_failed_trial_requires_reason_and_cannot_be_selected() -> None:
    with pytest.raises(ValueError, match="requires a reason"):
        _trial(
            "failed",
            1,
            outcome=TrialOutcome.FAILED,
            included=False,
        )

    with pytest.raises(ValueError, match="cannot be included"):
        _trial(
            "failed",
            1,
            outcome=TrialOutcome.FAILED,
            included=True,
            reason="failed",
        )


def test_completed_exclusion_requires_reason() -> None:
    with pytest.raises(ValueError, match="excluded from selection"):
        _trial("excluded", 1, included=False)


def test_trial_return_matrix_is_immutable_and_extracts_series() -> None:
    matrix = _matrix()
    extracted = matrix.series_for("trial-2")

    assert np.array_equal(extracted.values, matrix.values[:, 1])
    assert extracted.name == "trial-2"
    assert extracted.values.flags.writeable is False
    with pytest.raises(ValueError):
        matrix.values[0, 0] = 99.0
    with pytest.raises(KeyError):
        matrix.series_for("missing")


def test_trial_return_matrix_rejects_wrong_shape_and_simple_loss() -> None:
    with pytest.raises(ValueError, match="shape"):
        TrialReturnMatrix(
            timestamps=pd.date_range("2026-01-01", periods=2),
            trial_ids=("a", "b"),
            values=np.asarray([[0.01], [0.02]]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )
    with pytest.raises(ValueError, match="less than -1.0"):
        TrialReturnMatrix(
            timestamps=pd.date_range("2026-01-01", periods=1),
            trial_ids=("a",),
            values=np.asarray([[-1.01]]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )


def test_complete_family_enforces_attempt_sequence_and_winner() -> None:
    with pytest.raises(ValueError, match="every declared attempt index"):
        _family(
            trials=(
                _trial("trial-1", 1),
                _trial("trial-2", 3, selected=True),
            ),
            manifest=_manifest(declared_total_attempted_trials=3),
        )

    with pytest.raises(ValueError, match="does not match trial metadata"):
        _family(manifest=_manifest(selected_trial_id="trial-1"))


def test_family_requires_all_completed_and_no_failed_return_series() -> None:
    wrong_matrix = TrialReturnMatrix(
        timestamps=_matrix().timestamps,
        trial_ids=("trial-1", "trial-3"),
        values=_matrix().values,
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    with pytest.raises(ValueError, match="every completed trial"):
        _family(returns=wrong_matrix)


def test_family_requires_exact_parameter_schema() -> None:
    bad_trial = ExperimentTrial(
        trial_id="trial-1",
        attempt_index=1,
        outcome=TrialOutcome.COMPLETED,
        included_in_selection=True,
        selected=False,
        selection_score=1.0,
        parameters=(TrialParameter("threshold", 1.0),),
    )
    with pytest.raises(ValueError, match="parameter schema"):
        _family(
            trials=(
                bad_trial,
                _trial("trial-2", 2, selected=True),
                _trial(
                    "trial-3",
                    3,
                    outcome=TrialOutcome.FAILED,
                    included=False,
                    reason="failure",
                ),
            )
        )


def test_family_validates_complete_split_and_benchmark_alignment() -> None:
    timestamps = _matrix().timestamps
    split = ExperimentSplit(
        split_id="fold-1",
        in_sample_timestamps=timestamps[:2],
        out_of_sample_timestamps=timestamps[2:],
    )
    benchmark = ReturnSeries(
        timestamps=timestamps,
        values=np.asarray([0.0, 0.01, -0.01, 0.02]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )
    family = _family(
        manifest=_manifest(
            benchmark_id="market",
            benchmark_return_convention=ReturnConvention.SIMPLE,
        ),
        splits=(split,),
        benchmark_returns=benchmark,
    )

    assert family.splits[0].split_id == "fold-1"
    assert family.benchmark_returns is benchmark


def test_incomplete_search_can_preserve_missing_attempts() -> None:
    family = ExperimentFamily(
        manifest=_manifest(
            declared_total_attempted_trials=4,
            search_complete=False,
        ),
        trials=(
            _trial("trial-1", 1),
            _trial("trial-2", 2, selected=True),
        ),
        returns=_matrix(),
    )

    assert family.manifest.search_complete is False


def test_family_rejects_winner_that_is_not_declared_score_optimum() -> None:
    with pytest.raises(ValueError, match="optimum declared"):
        _family(
            trials=(
                replace(_trial("trial-1", 1), selection_score=3.0),
                _trial("trial-2", 2, selected=True),
                _trial(
                    "trial-3",
                    3,
                    outcome=TrialOutcome.FAILED,
                    included=False,
                    reason="failure",
                ),
            )
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"attempt_index": 0}, "positive integer"),
        ({"outcome": "invented"}, "outcome must be one of"),
        ({"included_in_selection": 1}, "must be a boolean"),
        ({"selected": 1}, "must be a boolean"),
        ({"selection_score": True}, "must be numeric"),
        ({"selection_score": "not-a-number"}, "must be numeric"),
        ({"selection_score": math.inf}, "must be finite"),
        (
            {
                "parameters": (
                    TrialParameter("lookback", 10),
                    TrialParameter("lookback", 20),
                )
            },
            "must be unique",
        ),
        (
            {
                "parameters": (
                    TrialParameter("threshold", 1),
                    TrialParameter("lookback", 10),
                )
            },
            "must be ordered",
        ),
        (
            {
                "outcome": TrialOutcome.FAILED,
                "included_in_selection": False,
                "selected": True,
                "selection_score": None,
                "reason": "engine failure",
            },
            "cannot be selected",
        ),
        (
            {
                "outcome": TrialOutcome.FAILED,
                "included_in_selection": False,
                "selection_score": 1.0,
                "reason": "engine failure",
            },
            "cannot have a selection score",
        ),
        (
            {"included_in_selection": False, "selected": True, "reason": "excluded"},
            "selected trial must be included",
        ),
        ({"source": 1}, "source must be a string"),
        ({"reason": "  "}, "reason must not be empty"),
    ],
)
def test_experiment_trial_rejects_invalid_public_contract_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _raw_trial(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"trial_ids": (1, 2)}, "IDs must be strings"),
        (
            {"timestamps": pd.DatetimeIndex([]), "values": np.empty((0, 2))},
            "cannot be empty",
        ),
        ({"trial_ids": ("", "trial-2")}, "non-empty trial IDs"),
        ({"trial_ids": ("trial-1", "trial-1")}, "IDs must be unique"),
        (
            {"timestamps": pd.DatetimeIndex([pd.NaT] * 4)},
            "must not contain missing",
        ),
        (
            {"timestamps": pd.DatetimeIndex(["2026-01-01"] * 4)},
            "must be unique",
        ),
        ({"timestamps": _matrix().timestamps[::-1]}, "strictly increasing"),
        ({"values": np.full((4, 2), np.nan)}, "must be finite"),
        ({"convention": "invented"}, "convention must be one of"),
    ],
)
def test_trial_return_matrix_rejects_invalid_contract_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_matrix(), **overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"declared_total_attempted_trials": True}, "positive integer"),
        ({"search_complete": 1}, "must be a boolean"),
        ({"selection_direction": "invented"}, "selection_direction must be one of"),
        ({"return_convention": "invented"}, "return_convention must be one of"),
        ({"parameter_names": (1,)}, "parameter names must be strings"),
        ({"parameter_names": ("",)}, "must not be empty"),
        ({"parameter_names": ("lookback", "lookback")}, "must be unique"),
        ({"parameter_names": ("threshold", "lookback")}, "ordered alphabetically"),
        ({"source": 1}, "source must be a string"),
        ({"benchmark_id": "market"}, "must be supplied together"),
        (
            {
                "benchmark_id": "market",
                "benchmark_return_convention": "invented",
            },
            "benchmark_return_convention must be one of",
        ),
    ],
)
def test_family_manifest_rejects_invalid_contract_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_manifest(), **overrides)


def test_experiment_split_rejects_overlaps_and_invalid_timestamp_subsets() -> None:
    timestamps = _matrix().timestamps
    with pytest.raises(ValueError, match="must be disjoint"):
        ExperimentSplit("fold", timestamps[:2], timestamps[1:])

    invalid_subsets = (
        pd.DatetimeIndex([]),
        pd.DatetimeIndex([pd.NaT]),
        pd.DatetimeIndex([timestamps[0], timestamps[0]]),
        timestamps[:2][::-1],
    )
    for subset in invalid_subsets:
        with pytest.raises(ValueError):
            ExperimentSplit("fold", subset, timestamps[2:])


def test_family_rejects_invalid_trial_identity_and_selection_contracts() -> None:
    valid = _family()
    invalid_cases = (
        ((), "requires trial metadata"),
        (
            (valid.trials[0], replace(valid.trials[1], trial_id="trial-1")),
            "trial IDs must be unique",
        ),
        (
            (valid.trials[0], replace(valid.trials[1], attempt_index=1)),
            "attempt indices must be unique",
        ),
        ((valid.trials[1], valid.trials[0]), "ordered by attempt index"),
        ((valid.trials[0], replace(valid.trials[1], attempt_index=4)), "cannot exceed"),
        ((replace(valid.trials[0], selected=True), valid.trials[1]), "exactly one"),
    )
    for trials, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            replace(
                valid,
                trials=trials,
                manifest=replace(valid.manifest, search_complete=False),
            )


def test_family_rejects_missing_selection_score_and_invalid_splits() -> None:
    valid = _family()
    with pytest.raises(ValueError, match="missing"):
        replace(
            valid,
            trials=(
                replace(valid.trials[0], selection_score=None),
                valid.trials[1],
                valid.trials[2],
            ),
        )

    timestamps = valid.returns.timestamps
    complete = ExperimentSplit("fold-1", timestamps[:2], timestamps[2:])
    with pytest.raises(ValueError, match="split IDs must be unique"):
        replace(valid, splits=(complete, complete))
    with pytest.raises(ValueError, match="ordered by split ID"):
        replace(
            valid,
            splits=(
                replace(complete, split_id="fold-2"),
                complete,
            ),
        )
    incomplete = ExperimentSplit("fold-1", timestamps[:1], timestamps[2:])
    with pytest.raises(ValueError, match="assign every matrix timestamp"):
        replace(valid, splits=(incomplete,))


def test_family_rejects_inconsistent_benchmark_declaration_and_data() -> None:
    valid = _family()
    benchmark = ReturnSeries(
        timestamps=valid.returns.timestamps,
        values=np.asarray([0.0, 0.01, -0.01, 0.02]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )
    with pytest.raises(ValueError, match="must match the manifest declaration"):
        replace(valid, benchmark_returns=benchmark)

    declared = replace(
        valid.manifest,
        benchmark_id="market",
        benchmark_return_convention=ReturnConvention.SIMPLE,
    )
    with pytest.raises(ValueError, match="timestamps must exactly match"):
        replace(
            valid,
            manifest=declared,
            benchmark_returns=replace(
                benchmark,
                timestamps=pd.date_range("2026-02-01", periods=4, freq="D"),
            ),
        )
    with pytest.raises(ValueError, match="convention must match"):
        replace(
            valid,
            manifest=declared,
            benchmark_returns=replace(
                benchmark,
                convention=ReturnConvention.LOG,
            ),
        )
