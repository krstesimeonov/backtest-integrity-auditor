from dataclasses import dataclass
import math
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from backtest_auditor.domain.enums import (
    ReturnConvention,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec


ParameterScalar = bool | int | float | str


@dataclass(frozen=True, slots=True)
class TrialParameter:
    name: str
    value: ParameterScalar

    def __post_init__(self) -> None:
        name = _normalize_required_text(self.name, "parameter name")

        value = self.value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError(f"parameter {name!r} must not be an empty string.")
        elif isinstance(value, bool):
            pass
        elif isinstance(value, int):
            pass
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"parameter {name!r} must be finite.")
        else:
            raise ValueError(f"parameter {name!r} must be a JSON scalar.")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class ExperimentTrial:
    trial_id: str
    attempt_index: int
    outcome: TrialOutcome
    included_in_selection: bool
    selected: bool
    selection_score: float | None
    parameters: tuple[TrialParameter, ...]
    source: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        trial_id = _normalize_required_text(self.trial_id, "trial_id")
        if (
            isinstance(self.attempt_index, bool)
            or not isinstance(self.attempt_index, int)
            or self.attempt_index <= 0
        ):
            raise ValueError("attempt_index must be a positive integer.")
        try:
            outcome = TrialOutcome(self.outcome)
        except ValueError as error:
            supported = ", ".join(item.value for item in TrialOutcome)
            raise ValueError(f"outcome must be one of: {supported}.") from error
        if not isinstance(self.included_in_selection, bool):
            raise ValueError("included_in_selection must be a boolean.")
        if not isinstance(self.selected, bool):
            raise ValueError("selected must be a boolean.")
        selection_score = self.selection_score
        if selection_score is not None:
            if isinstance(selection_score, bool):
                raise ValueError("selection_score must be numeric.")
            try:
                selection_score = float(selection_score)
            except (TypeError, ValueError) as error:
                raise ValueError("selection_score must be numeric.") from error
            if not math.isfinite(selection_score):
                raise ValueError("selection_score must be finite.")

        parameters = tuple(self.parameters)
        parameter_names = tuple(item.name for item in parameters)
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("trial parameter names must be unique.")
        if tuple(sorted(parameter_names)) != parameter_names:
            raise ValueError("trial parameters must be ordered by parameter name.")

        source = _normalize_optional_text(self.source, "source")
        reason = _normalize_optional_text(self.reason, "reason")

        if outcome is TrialOutcome.FAILED:
            if self.included_in_selection:
                raise ValueError("a failed trial cannot be included in selection.")
            if self.selected:
                raise ValueError("a failed trial cannot be selected.")
            if selection_score is not None:
                raise ValueError("a failed trial cannot have a selection score.")
            if reason is None:
                raise ValueError("a failed trial requires a reason.")
        elif not self.included_in_selection and reason is None:
            raise ValueError(
                "a completed trial excluded from selection requires a reason."
            )

        if self.selected and not self.included_in_selection:
            raise ValueError("the selected trial must be included in selection.")

        object.__setattr__(self, "trial_id", trial_id)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "selection_score", selection_score)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class TrialReturnMatrix:
    timestamps: pd.DatetimeIndex
    trial_ids: tuple[str, ...]
    values: NDArray[np.float64]
    convention: ReturnConvention
    sampling: SamplingSpec

    def __post_init__(self) -> None:
        timestamps = pd.DatetimeIndex(self.timestamps)
        if any(not isinstance(item, str) for item in self.trial_ids):
            raise ValueError("trial return matrix IDs must be strings.")
        trial_ids = tuple(item.strip() for item in self.trial_ids)
        values = np.asarray(self.values, dtype=np.float64)

        if len(timestamps) == 0:
            raise ValueError("trial return matrix cannot be empty.")
        if not trial_ids or any(not item for item in trial_ids):
            raise ValueError("trial return matrix requires non-empty trial IDs.")
        if len(set(trial_ids)) != len(trial_ids):
            raise ValueError("trial return matrix IDs must be unique.")
        if timestamps.hasnans:
            raise ValueError("matrix timestamps must not contain missing values.")
        if not timestamps.is_unique:
            raise ValueError("matrix timestamps must be unique.")
        if not timestamps.is_monotonic_increasing:
            raise ValueError("matrix timestamps must be strictly increasing.")
        expected_shape = (len(timestamps), len(trial_ids))
        if values.ndim != 2 or values.shape != expected_shape:
            raise ValueError(
                "matrix values must have shape "
                f"{expected_shape}; received {values.shape}."
            )
        if not np.isfinite(values).all():
            raise ValueError("matrix return values must be finite.")
        try:
            convention = ReturnConvention(self.convention)
        except ValueError as error:
            supported = ", ".join(item.value for item in ReturnConvention)
            raise ValueError(f"convention must be one of: {supported}.") from error
        if convention is ReturnConvention.SIMPLE and np.any(values < -1.0):
            raise ValueError("simple returns cannot be less than -1.0.")

        immutable_values = values.copy()
        immutable_values.setflags(write=False)
        object.__setattr__(self, "timestamps", timestamps.copy())
        object.__setattr__(self, "trial_ids", trial_ids)
        object.__setattr__(self, "values", immutable_values)
        object.__setattr__(self, "convention", convention)

    def series_for(self, trial_id: str) -> ReturnSeries:
        try:
            column_index = self.trial_ids.index(trial_id)
        except ValueError as error:
            raise KeyError(trial_id) from error
        return ReturnSeries(
            timestamps=self.timestamps,
            values=self.values[:, column_index],
            convention=self.convention,
            sampling=self.sampling,
            name=trial_id,
        )


@dataclass(frozen=True, slots=True)
class ExperimentSplit:
    split_id: str
    in_sample_timestamps: pd.DatetimeIndex
    out_of_sample_timestamps: pd.DatetimeIndex

    def __post_init__(self) -> None:
        split_id = _normalize_required_text(self.split_id, "split_id")
        in_sample = _validated_timestamp_subset(
            self.in_sample_timestamps,
            name="in_sample_timestamps",
        )
        out_of_sample = _validated_timestamp_subset(
            self.out_of_sample_timestamps,
            name="out_of_sample_timestamps",
        )
        if len(in_sample.intersection(out_of_sample)) > 0:
            raise ValueError("in-sample and out-of-sample timestamps must be disjoint.")
        object.__setattr__(self, "split_id", split_id)
        object.__setattr__(self, "in_sample_timestamps", in_sample)
        object.__setattr__(self, "out_of_sample_timestamps", out_of_sample)


@dataclass(frozen=True, slots=True)
class ExperimentFamilyManifest:
    schema_version: str
    family_id: str
    declared_total_attempted_trials: int
    search_complete: bool
    selected_trial_id: str
    selection_rule: str
    selection_metric: str
    selection_direction: SelectionDirection
    parameter_names: tuple[str, ...]
    return_convention: ReturnConvention
    sampling: SamplingSpec
    source: str | None = None
    benchmark_id: str | None = None
    benchmark_return_convention: ReturnConvention | None = None

    def __post_init__(self) -> None:
        schema_version = _normalize_required_text(
            self.schema_version,
            "schema_version",
        )
        family_id = _normalize_required_text(self.family_id, "family_id")
        selected_trial_id = _normalize_required_text(
            self.selected_trial_id,
            "selected_trial_id",
        )
        selection_rule = _normalize_required_text(
            self.selection_rule,
            "selection_rule",
        )
        selection_metric = _normalize_required_text(
            self.selection_metric,
            "selection_metric",
        )
        if (
            isinstance(self.declared_total_attempted_trials, bool)
            or not isinstance(self.declared_total_attempted_trials, int)
            or self.declared_total_attempted_trials <= 0
        ):
            raise ValueError(
                "declared_total_attempted_trials must be a positive integer."
            )
        if not isinstance(self.search_complete, bool):
            raise ValueError("search_complete must be a boolean.")
        try:
            selection_direction = SelectionDirection(self.selection_direction)
        except ValueError as error:
            supported = ", ".join(item.value for item in SelectionDirection)
            raise ValueError(
                f"selection_direction must be one of: {supported}."
            ) from error
        try:
            return_convention = ReturnConvention(self.return_convention)
        except ValueError as error:
            supported = ", ".join(item.value for item in ReturnConvention)
            raise ValueError(
                f"return_convention must be one of: {supported}."
            ) from error

        if any(not isinstance(item, str) for item in self.parameter_names):
            raise ValueError("parameter names must be strings.")
        parameter_names = tuple(item.strip() for item in self.parameter_names)
        if any(not item for item in parameter_names):
            raise ValueError("parameter names must not be empty.")
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("parameter names must be unique.")
        if tuple(sorted(parameter_names)) != parameter_names:
            raise ValueError("parameter names must be ordered alphabetically.")

        source = _normalize_optional_text(self.source, "source")
        benchmark_id = _normalize_optional_text(
            self.benchmark_id,
            "benchmark_id",
        )
        benchmark_convention = self.benchmark_return_convention
        if (benchmark_id is None) != (benchmark_convention is None):
            raise ValueError(
                "benchmark_id and benchmark_return_convention must be "
                "supplied together."
            )
        if benchmark_convention is not None:
            try:
                benchmark_convention = ReturnConvention(benchmark_convention)
            except ValueError as error:
                supported = ", ".join(item.value for item in ReturnConvention)
                raise ValueError(
                    f"benchmark_return_convention must be one of: {supported}."
                ) from error

        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "family_id", family_id)
        object.__setattr__(self, "selected_trial_id", selected_trial_id)
        object.__setattr__(self, "selection_rule", selection_rule)
        object.__setattr__(self, "selection_metric", selection_metric)
        object.__setattr__(
            self,
            "selection_direction",
            selection_direction,
        )
        object.__setattr__(self, "parameter_names", parameter_names)
        object.__setattr__(
            self,
            "return_convention",
            return_convention,
        )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "benchmark_id", benchmark_id)
        object.__setattr__(
            self,
            "benchmark_return_convention",
            benchmark_convention,
        )


@dataclass(frozen=True, slots=True)
class ExperimentFamily:
    manifest: ExperimentFamilyManifest
    trials: tuple[ExperimentTrial, ...]
    returns: TrialReturnMatrix
    splits: tuple[ExperimentSplit, ...] = ()
    benchmark_returns: ReturnSeries | None = None

    def __post_init__(self) -> None:
        trials = tuple(self.trials)
        if not trials:
            raise ValueError("experiment family requires trial metadata.")
        trial_ids = tuple(item.trial_id for item in trials)
        attempt_indices = tuple(item.attempt_index for item in trials)
        if len(set(trial_ids)) != len(trial_ids):
            raise ValueError("trial IDs must be unique.")
        if len(set(attempt_indices)) != len(attempt_indices):
            raise ValueError("attempt indices must be unique.")
        if tuple(sorted(attempt_indices)) != attempt_indices:
            raise ValueError("trials must be ordered by attempt index.")
        if any(
            index > self.manifest.declared_total_attempted_trials
            for index in attempt_indices
        ):
            raise ValueError("attempt indices cannot exceed the declared trial count.")
        if self.manifest.search_complete:
            expected_indices = tuple(
                range(
                    1,
                    self.manifest.declared_total_attempted_trials + 1,
                )
            )
            if attempt_indices != expected_indices:
                raise ValueError(
                    "a complete search requires every declared attempt index."
                )

        selected_trials = tuple(item for item in trials if item.selected)
        if len(selected_trials) != 1:
            raise ValueError("exactly one documented trial must be selected.")
        if selected_trials[0].trial_id != self.manifest.selected_trial_id:
            raise ValueError(
                "manifest selected_trial_id does not match trial metadata."
            )

        selection_trials = tuple(
            trial
            for trial in trials
            if trial.outcome is TrialOutcome.COMPLETED and trial.included_in_selection
        )
        if self.manifest.selection_direction in (
            SelectionDirection.MAXIMIZE,
            SelectionDirection.MINIMIZE,
        ):
            missing_scores = tuple(
                trial.trial_id
                for trial in selection_trials
                if trial.selection_score is None
            )
            if missing_scores:
                raise ValueError(
                    "maximize/minimize selection requires a finite score for "
                    "every included completed trial; missing: "
                    + ", ".join(missing_scores)
                    + "."
                )
            scores = tuple(
                cast(float, trial.selection_score) for trial in selection_trials
            )
            assert all(score is not None for score in scores)
            selected_score = selected_trials[0].selection_score
            assert selected_score is not None
            optimum = (
                max(scores)
                if self.manifest.selection_direction is SelectionDirection.MAXIMIZE
                else min(scores)
            )
            if selected_score != optimum:
                raise ValueError(
                    "the selected trial does not have the optimum declared "
                    "selection score."
                )

        expected_parameters = self.manifest.parameter_names
        for trial in trials:
            if (
                tuple(parameter.name for parameter in trial.parameters)
                != expected_parameters
            ):
                raise ValueError(
                    f"trial {trial.trial_id!r} does not match the declared "
                    "parameter schema."
                )

        completed_trial_ids = tuple(
            item.trial_id for item in trials if item.outcome is TrialOutcome.COMPLETED
        )
        if self.returns.trial_ids != completed_trial_ids:
            raise ValueError(
                "the return matrix must contain every completed trial and "
                "no failed trial, ordered by attempt index."
            )
        if self.returns.convention is not self.manifest.return_convention:
            raise ValueError("return matrix convention must match the manifest.")

        splits = tuple(self.splits)
        split_ids = tuple(item.split_id for item in splits)
        if len(set(split_ids)) != len(split_ids):
            raise ValueError("split IDs must be unique.")
        if tuple(sorted(split_ids)) != split_ids:
            raise ValueError("splits must be ordered by split ID.")
        expected_timestamps = self.returns.timestamps
        for split in splits:
            combined = split.in_sample_timestamps.union(split.out_of_sample_timestamps)
            if not combined.equals(expected_timestamps):
                raise ValueError(
                    f"split {split.split_id!r} must assign every matrix "
                    "timestamp exactly once."
                )

        benchmark = self.benchmark_returns
        if (self.manifest.benchmark_id is None) != (benchmark is None):
            raise ValueError("benchmark returns must match the manifest declaration.")
        if benchmark is not None:
            if not benchmark.timestamps.equals(self.returns.timestamps):
                raise ValueError(
                    "benchmark timestamps must exactly match the family matrix."
                )
            if benchmark.convention is not self.manifest.benchmark_return_convention:
                raise ValueError("benchmark return convention must match the manifest.")

        object.__setattr__(self, "trials", trials)
        object.__setattr__(self, "splits", splits)


def _normalize_optional_text(
    value: str | None,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when supplied.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty when supplied.")
    return normalized


def _normalize_required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _validated_timestamp_subset(
    values: pd.DatetimeIndex,
    *,
    name: str,
) -> pd.DatetimeIndex:
    timestamps = pd.DatetimeIndex(values)
    if len(timestamps) == 0:
        raise ValueError(f"{name} must not be empty.")
    if timestamps.hasnans:
        raise ValueError(f"{name} must not contain missing values.")
    if not timestamps.is_unique:
        raise ValueError(f"{name} must be unique.")
    if not timestamps.is_monotonic_increasing:
        raise ValueError(f"{name} must be strictly increasing.")
    return timestamps.copy()
