from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, NoReturn

import numpy as np
import pandas as pd

from backtest_auditor.domain.enums import (
    FrequencyStatus,
    IssueSeverity,
    ReturnConvention,
    SelectionDirection,
    SplitRole,
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
from backtest_auditor.domain.issues import (
    InputValidationError,
    ValidationIssue,
)
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.csv_returns import (
    read_return_series_csv,
)
from backtest_auditor.ingestion.timestamp_offsets import (
    mixed_offset_message,
    parse_on_one_timeline,
)


EXPERIMENT_FAMILY_INPUT_SCHEMA_VERSION = "1.0"

_MANIFEST_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "family_id",
        "declared_total_attempted_trials",
        "search_complete",
        "selected_trial_id",
        "selection_rule",
        "selection_metric",
        "selection_direction",
        "parameter_names",
        "return_convention",
    }
)
_MANIFEST_OPTIONAL_FIELDS = frozenset(
    {
        "declared_frequency",
        "periods_per_year",
        "timezone",
        "source",
        "benchmark_id",
        "benchmark_return_convention",
    }
)
_TRIAL_REQUIRED_COLUMNS = (
    "trial_id",
    "attempt_index",
    "outcome",
    "included_in_selection",
    "selected",
    "selection_score",
    "parameters",
)
_TRIAL_OPTIONAL_COLUMNS = ("source", "reason")
_RETURN_COLUMNS = ("timestamp", "trial_id", "return")
_SPLIT_COLUMNS = ("split_id", "timestamp", "role")


@dataclass(frozen=True, slots=True)
class ExperimentFamilyNormalizationResult:
    family: ExperimentFamily
    issues: tuple[ValidationIssue, ...] = ()


def read_experiment_family_files(
    manifest_path: str | Path,
    trials_path: str | Path,
    returns_path: str | Path,
    *,
    splits_path: str | Path | None = None,
    benchmark_path: str | Path | None = None,
) -> ExperimentFamilyNormalizationResult:
    """Normalize the canonical file-first experiment-family contract."""

    manifest = read_experiment_family_manifest_json(manifest_path)
    trials, trial_issues = read_experiment_trials_csv(
        trials_path,
        manifest=manifest,
    )
    matrix, matrix_issues = read_experiment_return_matrix_csv(
        returns_path,
        manifest=manifest,
        trials=trials,
    )
    splits: tuple[ExperimentSplit, ...] = ()
    split_issues: tuple[ValidationIssue, ...] = ()
    if splits_path is not None:
        splits, split_issues = read_experiment_splits_csv(
            splits_path,
            expected_timestamps=matrix.timestamps,
        )

    benchmark_returns = None
    benchmark_issues: tuple[ValidationIssue, ...] = ()
    benchmark_declared = manifest.benchmark_id is not None
    if benchmark_declared != (benchmark_path is not None):
        raise _error(
            code="INCOMPLETE_FAMILY_BENCHMARK_CONTRACT",
            message=(
                "The manifest benchmark declaration and --benchmark-csv "
                "must be supplied together."
            ),
            location=str(manifest_path),
        )
    if benchmark_path is not None:
        assert manifest.benchmark_return_convention is not None
        normalized_benchmark = read_return_series_csv(
            benchmark_path,
            timestamp_column="timestamp",
            return_column="return",
            convention=manifest.benchmark_return_convention,
            sampling=manifest.sampling,
            name=manifest.benchmark_id,
        )
        benchmark_returns = normalized_benchmark.series
        benchmark_issues = normalized_benchmark.issues
        if not benchmark_returns.timestamps.equals(matrix.timestamps):
            raise _error(
                code="FAMILY_BENCHMARK_TIMESTAMP_MISMATCH",
                message=(
                    "Benchmark timestamps must exactly equal the canonical "
                    "experiment-family timestamps."
                ),
                location=str(benchmark_path),
            )

    try:
        family = ExperimentFamily(
            manifest=manifest,
            trials=trials,
            returns=matrix,
            splits=splits,
            benchmark_returns=benchmark_returns,
        )
    except ValueError as error:
        raise _error(
            code="INVALID_EXPERIMENT_FAMILY_CONTRACT",
            message=str(error),
            location=str(manifest_path),
        ) from error

    return ExperimentFamilyNormalizationResult(
        family=family,
        issues=(trial_issues + matrix_issues + split_issues + benchmark_issues),
    )


def read_experiment_family_manifest_json(
    path: str | Path,
) -> ExperimentFamilyManifest:
    input_path = Path(path)
    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise _error(
            code="INPUT_FILE_NOT_FOUND",
            message=f"Manifest file does not exist: {input_path}",
            location=str(input_path),
        ) from error
    except (UnicodeDecodeError, OSError) as error:
        raise _error(
            code="MANIFEST_READ_ERROR",
            message=f"Manifest file could not be read: {input_path}",
            location=str(input_path),
        ) from error

    try:
        payload = json.loads(raw_text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise _error(
            code="INVALID_FAMILY_MANIFEST_JSON",
            message="Experiment-family manifest must contain valid JSON.",
            location=str(input_path),
        ) from error
    if not isinstance(payload, dict):
        raise _error(
            code="INVALID_FAMILY_MANIFEST_ROOT",
            message="Experiment-family manifest root must be an object.",
            location=str(input_path),
        )

    payload_fields = set(payload)
    missing_fields = sorted(_MANIFEST_REQUIRED_FIELDS - payload_fields)
    unknown_fields = sorted(
        payload_fields - _MANIFEST_REQUIRED_FIELDS - _MANIFEST_OPTIONAL_FIELDS
    )
    issues: list[ValidationIssue] = []
    if missing_fields:
        issues.append(
            _issue(
                code="MISSING_FAMILY_MANIFEST_FIELD",
                message=(
                    "Manifest is missing required field(s): "
                    + ", ".join(missing_fields)
                    + "."
                ),
                location=str(input_path),
            )
        )
    if unknown_fields:
        issues.append(
            _issue(
                code="UNKNOWN_FAMILY_MANIFEST_FIELD",
                message=(
                    "Manifest contains unsupported field(s): "
                    + ", ".join(unknown_fields)
                    + "."
                ),
                location=str(input_path),
            )
        )
    if issues:
        raise InputValidationError(tuple(issues))

    schema_version = payload["schema_version"]
    if schema_version != EXPERIMENT_FAMILY_INPUT_SCHEMA_VERSION:
        raise _error(
            code="UNSUPPORTED_FAMILY_INPUT_SCHEMA_VERSION",
            message=(
                "Supported experiment-family input schema is "
                f"{EXPERIMENT_FAMILY_INPUT_SCHEMA_VERSION!r}; received "
                f"{schema_version!r}."
            ),
            location=str(input_path),
        )
    parameter_names = payload["parameter_names"]
    if not isinstance(parameter_names, list) or any(
        not isinstance(item, str) for item in parameter_names
    ):
        raise _error(
            code="INVALID_FAMILY_PARAMETER_SCHEMA",
            message="parameter_names must be an array of strings.",
            location=str(input_path),
        )
    if not isinstance(payload["search_complete"], bool):
        raise _error(
            code="INVALID_FAMILY_SEARCH_COMPLETENESS",
            message="search_complete must be a JSON boolean.",
            location=str(input_path),
        )

    required_text_fields = (
        "schema_version",
        "family_id",
        "selected_trial_id",
        "selection_rule",
        "selection_metric",
        "selection_direction",
        "return_convention",
    )
    optional_text_fields = (
        "declared_frequency",
        "timezone",
        "source",
        "benchmark_id",
        "benchmark_return_convention",
    )
    invalid_text_fields = [
        field_name
        for field_name in required_text_fields
        if not isinstance(payload[field_name], str)
    ] + [
        field_name
        for field_name in optional_text_fields
        if payload.get(field_name) is not None
        and not isinstance(payload[field_name], str)
    ]
    total_attempts = payload["declared_total_attempted_trials"]
    periods_per_year = payload.get("periods_per_year")
    invalid_integer_fields = []
    if isinstance(total_attempts, bool) or not isinstance(
        total_attempts,
        int,
    ):
        invalid_integer_fields.append("declared_total_attempted_trials")
    if periods_per_year is not None and (
        isinstance(periods_per_year, bool) or not isinstance(periods_per_year, int)
    ):
        invalid_integer_fields.append("periods_per_year")
    if invalid_text_fields or invalid_integer_fields:
        invalid_fields = sorted(invalid_text_fields + invalid_integer_fields)
        raise _error(
            code="INVALID_FAMILY_MANIFEST_VALUE",
            message=(
                "Manifest field(s) have invalid primitive types: "
                + ", ".join(invalid_fields)
                + "."
            ),
            location=str(input_path),
        )

    declared_frequency = payload.get("declared_frequency")
    timezone = payload.get("timezone")
    try:
        sampling = SamplingSpec(
            status=(
                FrequencyStatus.DECLARED
                if declared_frequency is not None
                else FrequencyStatus.AMBIGUOUS
            ),
            declared_frequency=declared_frequency,
            periods_per_year=periods_per_year,
            timezone=timezone,
        )
        manifest = ExperimentFamilyManifest(
            schema_version=schema_version,
            family_id=payload["family_id"],
            declared_total_attempted_trials=(
                payload["declared_total_attempted_trials"]
            ),
            search_complete=payload["search_complete"],
            selected_trial_id=payload["selected_trial_id"],
            selection_rule=payload["selection_rule"],
            selection_metric=payload["selection_metric"],
            selection_direction=SelectionDirection(payload["selection_direction"]),
            parameter_names=tuple(parameter_names),
            return_convention=ReturnConvention(payload["return_convention"]),
            sampling=sampling,
            source=payload.get("source"),
            benchmark_id=payload.get("benchmark_id"),
            benchmark_return_convention=(
                None
                if payload.get("benchmark_return_convention") is None
                else ReturnConvention(payload["benchmark_return_convention"])
            ),
        )
    except (TypeError, ValueError) as error:
        raise _error(
            code="INVALID_FAMILY_MANIFEST_VALUE",
            message=str(error),
            location=str(input_path),
        ) from error
    return manifest


def read_experiment_trials_csv(
    path: str | Path,
    *,
    manifest: ExperimentFamilyManifest,
) -> tuple[tuple[ExperimentTrial, ...], tuple[ValidationIssue, ...]]:
    input_path = Path(path)
    frame = _read_csv(input_path)
    _validate_columns(
        frame,
        required=_TRIAL_REQUIRED_COLUMNS,
        optional=_TRIAL_OPTIONAL_COLUMNS,
        location=input_path,
    )
    if frame.empty:
        raise _error(
            code="EMPTY_TRIAL_METADATA",
            message="Trial metadata must contain at least one row.",
            location=str(input_path),
        )

    trials: list[ExperimentTrial] = []
    issues: list[ValidationIssue] = []
    for zero_index, row in frame.iterrows():
        row_number = int(zero_index) + 2
        location = f"{input_path}:row {row_number}"
        try:
            parameters = _parse_parameters(
                row["parameters"],
                expected_names=manifest.parameter_names,
            )
            trial = ExperimentTrial(
                trial_id=_required_text(row["trial_id"], "trial_id"),
                attempt_index=_positive_integer_value(
                    row["attempt_index"],
                    "attempt_index",
                ),
                outcome=TrialOutcome(_required_text(row["outcome"], "outcome")),
                included_in_selection=_boolean_value(
                    row["included_in_selection"],
                    "included_in_selection",
                ),
                selected=_boolean_value(row["selected"], "selected"),
                selection_score=_optional_finite_number(
                    row["selection_score"],
                    "selection_score",
                ),
                parameters=parameters,
                source=_optional_text(row.get("source")),
                reason=_optional_text(row.get("reason")),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            issues.append(
                _issue(
                    code="INVALID_TRIAL_METADATA",
                    message=str(error),
                    location=location,
                )
            )
        else:
            trials.append(trial)
    if issues:
        raise InputValidationError(tuple(issues))

    trial_ids = tuple(item.trial_id for item in trials)
    attempt_indices = tuple(item.attempt_index for item in trials)
    duplicate_issues: list[ValidationIssue] = []
    duplicate_ids = _duplicates(trial_ids)
    duplicate_indices = _duplicates(attempt_indices)
    if duplicate_ids:
        duplicate_issues.append(
            _issue(
                code="DUPLICATE_TRIAL_ID",
                message=(
                    "Trial IDs must be unique; duplicate(s): "
                    + ", ".join(str(item) for item in duplicate_ids)
                    + "."
                ),
                location=str(input_path),
            )
        )
    if duplicate_indices:
        duplicate_issues.append(
            _issue(
                code="DUPLICATE_ATTEMPT_INDEX",
                message=(
                    "Attempt indices must be unique; duplicate(s): "
                    + ", ".join(str(item) for item in duplicate_indices)
                    + "."
                ),
                location=str(input_path),
            )
        )
    if duplicate_issues:
        raise InputValidationError(tuple(duplicate_issues))

    sorted_trials = tuple(sorted(trials, key=lambda item: item.attempt_index))
    normalization_issues: tuple[ValidationIssue, ...] = ()
    if tuple(trials) != sorted_trials:
        normalization_issues = (
            ValidationIssue(
                code="TRIAL_METADATA_SORTED",
                message=("Trial metadata was reordered by ascending attempt_index."),
                severity=IssueSeverity.WARNING,
                blocking=False,
                location=str(input_path),
            ),
        )
    return sorted_trials, normalization_issues


def read_experiment_return_matrix_csv(
    path: str | Path,
    *,
    manifest: ExperimentFamilyManifest,
    trials: tuple[ExperimentTrial, ...],
) -> tuple[TrialReturnMatrix, tuple[ValidationIssue, ...]]:
    input_path = Path(path)
    frame = _read_csv(input_path)
    _validate_columns(
        frame,
        required=_RETURN_COLUMNS,
        optional=(),
        location=input_path,
    )
    if frame.empty:
        raise _error(
            code="EMPTY_EXPERIMENT_RETURN_MATRIX",
            message="Experiment returns must contain at least one row.",
            location=str(input_path),
        )

    raw_timestamps = frame["timestamp"].tolist()
    parsed_timestamps = parse_on_one_timeline(raw_timestamps, errors="coerce")
    if parsed_timestamps is None:
        raise _error(
            code="INVALID_FAMILY_TIMESTAMP",
            message=mixed_offset_message("Family timestamps", raw_timestamps),
            location=f"{input_path}:timestamp",
        )
    parsed_values = pd.to_numeric(frame["return"], errors="coerce")
    trial_ids = tuple(str(item).strip() for item in frame["trial_id"])
    blocking_issues: list[ValidationIssue] = []
    if pd.isna(parsed_timestamps).any():
        blocking_issues.append(
            _issue(
                code="INVALID_FAMILY_TIMESTAMP",
                message="At least one family timestamp could not be parsed.",
                location=f"{input_path}:timestamp",
            )
        )
    if any(not item for item in trial_ids):
        blocking_issues.append(
            _issue(
                code="EMPTY_FAMILY_TRIAL_ID",
                message="Return rows require non-empty trial IDs.",
                location=f"{input_path}:trial_id",
            )
        )
    numeric_values = parsed_values.to_numpy(dtype=np.float64)
    if parsed_values.isna().any() or not np.isfinite(numeric_values).all():
        blocking_issues.append(
            _issue(
                code="NONFINITE_FAMILY_RETURN",
                message="Family returns must be numeric and finite.",
                location=f"{input_path}:return",
            )
        )
    if (
        manifest.return_convention is ReturnConvention.SIMPLE
        and not parsed_values.isna().any()
        and np.any(numeric_values < -1.0)
    ):
        blocking_issues.append(
            _issue(
                code="FAMILY_SIMPLE_RETURN_BELOW_MINUS_ONE",
                message=(
                    "Simple family returns cannot be less than -1.0 (a loss "
                    "of more than 100 %). Returns are read as decimals "
                    "(0.015 = 1.5 %); if the file holds percent values "
                    "(1.5 = 1.5 %), divide them by 100."
                ),
                location=f"{input_path}:return",
            )
        )
    if blocking_issues:
        raise InputValidationError(tuple(blocking_issues))

    timestamps = pd.DatetimeIndex(parsed_timestamps)
    row_keys = pd.MultiIndex.from_arrays(
        [trial_ids, timestamps],
        names=["trial_id", "timestamp"],
    )
    if row_keys.has_duplicates:
        raise _error(
            code="DUPLICATE_FAMILY_RETURN_OBSERVATION",
            message=("Each (trial_id, timestamp) pair must appear exactly once."),
            location=str(input_path),
        )

    metadata_by_id = {trial.trial_id: trial for trial in trials}
    unknown_ids = sorted(set(trial_ids) - set(metadata_by_id))
    failed_ids = sorted(
        {
            trial_id
            for trial_id in trial_ids
            if trial_id in metadata_by_id
            and metadata_by_id[trial_id].outcome is TrialOutcome.FAILED
        }
    )
    if unknown_ids or failed_ids:
        invalid_issues: list[ValidationIssue] = []
        if unknown_ids:
            invalid_issues.append(
                _issue(
                    code="RETURN_SERIES_WITHOUT_TRIAL_METADATA",
                    message=(
                        "Return rows reference undocumented trial(s): "
                        + ", ".join(unknown_ids)
                        + "."
                    ),
                    location=str(input_path),
                )
            )
        if failed_ids:
            invalid_issues.append(
                _issue(
                    code="FAILED_TRIAL_HAS_RETURN_SERIES",
                    message=(
                        "Failed trial(s) cannot have supplied returns: "
                        + ", ".join(failed_ids)
                        + "."
                    ),
                    location=str(input_path),
                )
            )
        raise InputValidationError(tuple(invalid_issues))

    completed_ids = tuple(
        trial.trial_id for trial in trials if trial.outcome is TrialOutcome.COMPLETED
    )
    if not completed_ids:
        raise _error(
            code="NO_COMPLETED_EXPERIMENT_TRIALS",
            message=("At least one documented trial must have outcome completed."),
            location=str(input_path),
        )
    supplied_ids = set(trial_ids)
    missing_completed = tuple(
        trial_id for trial_id in completed_ids if trial_id not in supplied_ids
    )
    if missing_completed:
        raise _error(
            code="COMPLETED_TRIAL_RETURN_SERIES_MISSING",
            message=(
                "Every completed trial requires a return series; missing: "
                + ", ".join(missing_completed)
                + "."
            ),
            location=str(input_path),
        )

    normalized_frame = pd.DataFrame(
        {
            "trial_id": trial_ids,
            "timestamp": timestamps,
            "return": numeric_values,
        }
    )
    reference_id = completed_ids[0]
    reference_timestamps = pd.DatetimeIndex(
        normalized_frame.loc[
            normalized_frame["trial_id"] == reference_id,
            "timestamp",
        ]
    ).sort_values()
    alignment_issues: list[ValidationIssue] = []
    reference_set = set(reference_timestamps)
    for trial_id in completed_ids[1:]:
        trial_timestamps = set(
            normalized_frame.loc[
                normalized_frame["trial_id"] == trial_id,
                "timestamp",
            ]
        )
        if trial_timestamps != reference_set:
            missing = sorted(reference_set - trial_timestamps)
            unexpected = sorted(trial_timestamps - reference_set)
            alignment_issues.append(
                _issue(
                    code="FAMILY_RETURN_TIMESTAMPS_NOT_ALIGNED",
                    message=(
                        f"Trial {trial_id!r} does not match reference trial "
                        f"{reference_id!r}: {len(missing)} missing and "
                        f"{len(unexpected)} unexpected timestamp(s)."
                    ),
                    location=str(input_path),
                )
            )
    if alignment_issues:
        raise InputValidationError(tuple(alignment_issues))

    value_columns: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    for trial_id in completed_ids:
        trial_frame = (
            normalized_frame.loc[
                normalized_frame["trial_id"] == trial_id,
                ["timestamp", "return"],
            ]
            .set_index("timestamp")
            .reindex(reference_timestamps)
        )
        value_columns.append(trial_frame["return"].to_numpy(dtype=np.float64))
    values = np.column_stack(value_columns)

    canonical_pairs = tuple(
        (trial_id, timestamp)
        for trial_id in completed_ids
        for timestamp in reference_timestamps
    )
    supplied_pairs = tuple(zip(trial_ids, timestamps, strict=True))
    normalization_issues: tuple[ValidationIssue, ...] = ()
    if supplied_pairs != canonical_pairs:
        normalization_issues = (
            ValidationIssue(
                code="FAMILY_RETURNS_SORTED",
                message=(
                    "Family return rows were normalized by attempt index "
                    "and ascending timestamp."
                ),
                severity=IssueSeverity.WARNING,
                blocking=False,
                location=str(input_path),
            ),
        )

    matrix = TrialReturnMatrix(
        timestamps=reference_timestamps,
        trial_ids=completed_ids,
        values=values,
        convention=manifest.return_convention,
        sampling=manifest.sampling,
    )
    return matrix, normalization_issues


def read_experiment_splits_csv(
    path: str | Path,
    *,
    expected_timestamps: pd.DatetimeIndex,
) -> tuple[tuple[ExperimentSplit, ...], tuple[ValidationIssue, ...]]:
    input_path = Path(path)
    frame = _read_csv(input_path)
    _validate_columns(
        frame,
        required=_SPLIT_COLUMNS,
        optional=(),
        location=input_path,
    )
    if frame.empty:
        raise _error(
            code="EMPTY_EXPERIMENT_SPLITS",
            message="Split membership file must contain at least one row.",
            location=str(input_path),
        )

    raw_timestamps = frame["timestamp"].tolist()
    parsed_timestamps = parse_on_one_timeline(raw_timestamps, errors="coerce")
    if parsed_timestamps is None:
        raise _error(
            code="INVALID_SPLIT_TIMESTAMP",
            message=mixed_offset_message("Split timestamps", raw_timestamps),
            location=f"{input_path}:timestamp",
        )
    split_ids = tuple(str(item).strip() for item in frame["split_id"])
    if pd.isna(parsed_timestamps).any():
        raise _error(
            code="INVALID_SPLIT_TIMESTAMP",
            message="At least one split timestamp could not be parsed.",
            location=f"{input_path}:timestamp",
        )
    if any(not item for item in split_ids):
        raise _error(
            code="EMPTY_SPLIT_ID",
            message="Split rows require non-empty split IDs.",
            location=f"{input_path}:split_id",
        )
    roles: list[SplitRole] = []
    role_issues: list[ValidationIssue] = []
    for index, value in enumerate(frame["role"], start=2):
        try:
            roles.append(SplitRole(str(value).strip()))
        except ValueError:
            role_issues.append(
                _issue(
                    code="INVALID_SPLIT_ROLE",
                    message=("Split role must be in_sample or out_of_sample."),
                    location=f"{input_path}:row {index}",
                )
            )
    if role_issues:
        raise InputValidationError(tuple(role_issues))

    timestamps = pd.DatetimeIndex(parsed_timestamps)
    keys = pd.MultiIndex.from_arrays(
        [split_ids, timestamps],
        names=["split_id", "timestamp"],
    )
    if keys.has_duplicates:
        raise _error(
            code="DUPLICATE_SPLIT_MEMBERSHIP",
            message=("Each (split_id, timestamp) pair must appear exactly once."),
            location=str(input_path),
        )
    unexpected = timestamps.difference(expected_timestamps)
    if len(unexpected) > 0:
        raise _error(
            code="SPLIT_TIMESTAMP_NOT_IN_RETURN_MATRIX",
            message=(
                f"Split file contains {len(unexpected)} timestamp(s) not "
                "present in the family return matrix."
            ),
            location=str(input_path),
        )

    normalized_frame = pd.DataFrame(
        {
            "split_id": split_ids,
            "timestamp": timestamps,
            "role": roles,
        }
    )
    splits: list[ExperimentSplit] = []
    split_issues: list[ValidationIssue] = []
    for split_id in sorted(set(split_ids)):
        split_frame = normalized_frame.loc[normalized_frame["split_id"] == split_id]
        assigned = pd.DatetimeIndex(split_frame["timestamp"]).sort_values()
        missing = expected_timestamps.difference(assigned)
        if len(missing) > 0:
            split_issues.append(
                _issue(
                    code="INCOMPLETE_SPLIT_MEMBERSHIP",
                    message=(
                        f"Split {split_id!r} omits {len(missing)} family timestamp(s)."
                    ),
                    location=str(input_path),
                )
            )
            continue
        in_sample = pd.DatetimeIndex(
            split_frame.loc[
                split_frame["role"] == SplitRole.IN_SAMPLE,
                "timestamp",
            ]
        ).sort_values()
        out_of_sample = pd.DatetimeIndex(
            split_frame.loc[
                split_frame["role"] == SplitRole.OUT_OF_SAMPLE,
                "timestamp",
            ]
        ).sort_values()
        if len(in_sample) == 0 or len(out_of_sample) == 0:
            split_issues.append(
                _issue(
                    code="SPLIT_REQUIRES_BOTH_ROLES",
                    message=(
                        f"Split {split_id!r} requires at least one in-sample "
                        "and one out-of-sample timestamp."
                    ),
                    location=str(input_path),
                )
            )
            continue
        splits.append(
            ExperimentSplit(
                split_id=split_id,
                in_sample_timestamps=in_sample,
                out_of_sample_timestamps=out_of_sample,
            )
        )
    if split_issues:
        raise InputValidationError(tuple(split_issues))

    canonical_rows_list: list[tuple[str, pd.Timestamp, SplitRole]] = []
    for split in splits:
        canonical_rows_list.extend(
            (split.split_id, timestamp, SplitRole.IN_SAMPLE)
            for timestamp in split.in_sample_timestamps
        )
        canonical_rows_list.extend(
            (split.split_id, timestamp, SplitRole.OUT_OF_SAMPLE)
            for timestamp in split.out_of_sample_timestamps
        )
    canonical_rows = tuple(canonical_rows_list)
    supplied_rows = tuple(zip(split_ids, timestamps, roles, strict=True))
    normalization_issues: tuple[ValidationIssue, ...] = ()
    if supplied_rows != canonical_rows:
        normalization_issues = (
            ValidationIssue(
                code="SPLIT_MEMBERSHIP_SORTED",
                message=(
                    "Split membership was normalized by split ID, role, "
                    "and ascending timestamp."
                ),
                severity=IssueSeverity.WARNING,
                blocking=False,
                location=str(input_path),
            ),
        )
    return tuple(splits), normalization_issues


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        # dtype=str disables type inference. Without it a trial_id column
        # whose values all look numeric became int64, so the zero-padded
        # grid-search id '007' was published as '7' and '1e3' as '1000.0',
        # with input_issues empty -- the report's identifiers no longer
        # matched the input file. Worse, the same literal id parsed
        # differently in two files when one of them contained a single
        # non-numeric id, so trials and splits stopped joining. Every
        # numeric column here is re-parsed from text downstream by
        # _positive_integer_value / _optional_finite_number, so this changes
        # no statistical value.
        return pd.read_csv(path, keep_default_na=False, dtype=str)
    except FileNotFoundError as error:
        raise _error(
            code="INPUT_FILE_NOT_FOUND",
            message=f"Input CSV file does not exist: {path}",
            location=str(path),
        ) from error
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        UnicodeDecodeError,
        OSError,
    ) as error:
        raise _error(
            code="CSV_READ_ERROR",
            message=f"Input CSV file could not be read: {path}",
            location=str(path),
        ) from error


def _validate_columns(
    frame: pd.DataFrame,
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    location: Path,
) -> None:
    supplied = set(frame.columns)
    missing = sorted(set(required) - supplied)
    unknown = sorted(supplied - set(required) - set(optional))
    issues: list[ValidationIssue] = []
    if missing:
        issues.append(
            _issue(
                code="MISSING_REQUIRED_COLUMN",
                message=(
                    "Input CSV is missing required column(s): "
                    + ", ".join(missing)
                    + "."
                ),
                location=str(location),
            )
        )
    if unknown:
        issues.append(
            _issue(
                code="UNKNOWN_CANONICAL_COLUMN",
                message=(
                    "Input CSV contains unsupported column(s): "
                    + ", ".join(unknown)
                    + "."
                ),
                location=str(location),
            )
        )
    if issues:
        raise InputValidationError(tuple(issues))


def _parse_parameters(
    raw_value: object,
    *,
    expected_names: tuple[str, ...],
) -> tuple[TrialParameter, ...]:
    text = str(raw_value).strip()
    if not text:
        raise ValueError("parameters must contain a JSON object.")
    payload = json.loads(text, parse_constant=_reject_json_constant)
    if not isinstance(payload, dict):
        raise ValueError("parameters must contain a JSON object.")
    if any(not isinstance(name, str) for name in payload):
        raise ValueError("parameter names must be strings.")
    supplied_names = tuple(sorted(payload))
    if supplied_names != expected_names:
        missing = sorted(set(expected_names) - set(supplied_names))
        unexpected = sorted(set(supplied_names) - set(expected_names))
        raise ValueError(
            f"parameter schema mismatch: missing={missing}, unexpected={unexpected}."
        )
    return tuple(
        TrialParameter(name=name, value=payload[name]) for name in supplied_names
    )


def _required_text(value: object, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _positive_integer_value(value: object, field_name: str) -> int:
    text = str(value).strip()
    try:
        parsed = int(text)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a positive integer.") from error
    if str(parsed) != text or parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return parsed


def _boolean_value(value: object, field_name: str) -> bool:
    normalized = str(value).strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{field_name} must be true or false.")


def _optional_finite_number(
    value: object,
    field_name: str,
) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError as error:
        raise ValueError(f"{field_name} must be numeric.") from error
    if not np.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite.")
    return parsed


def _duplicates(values: tuple[Any, ...]) -> tuple[Any, ...]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates, key=str))


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _issue(
    *,
    code: str,
    message: str,
    location: str,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        severity=IssueSeverity.ERROR,
        blocking=True,
        location=location,
    )


def _error(
    *,
    code: str,
    message: str,
    location: str,
) -> InputValidationError:
    return InputValidationError(
        (
            _issue(
                code=code,
                message=message,
                location=location,
            ),
        )
    )
