from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from backtest_auditor.domain.enums import (
    IssueSeverity,
    ReturnConvention,
)
from backtest_auditor.domain.issues import (
    InputValidationError,
    ValidationIssue,
)
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)
from backtest_auditor.ingestion.timestamp_offsets import (
    mixed_offset_message,
    parse_on_one_timeline,
)


@dataclass(frozen=True, slots=True)
class ReturnSeriesNormalizationResult:
    series: ReturnSeries
    issues: tuple[ValidationIssue, ...] = ()


def normalize_return_series(
    timestamps: Sequence[object],
    values: Sequence[object],
    *,
    convention: ReturnConvention,
    sampling: SamplingSpec,
    name: str | None = None,
) -> ReturnSeriesNormalizationResult:
    """Normalize parsed external values into a canonical ReturnSeries.

    This function is intentionally not a CSV reader. It accepts
    already parsed columns, validates boundary concerns, sorts unique
    observations when needed, and records the sort as a warning.
    """

    if len(timestamps) == 0 and len(values) == 0:
        raise InputValidationError(
            (
                ValidationIssue(
                    code="EMPTY_RETURN_SERIES",
                    message=("At least one return observation is required."),
                    severity=IssueSeverity.ERROR,
                    blocking=True,
                ),
            )
        )

    if len(timestamps) != len(values):
        raise InputValidationError(
            (
                ValidationIssue(
                    code="INPUT_LENGTH_MISMATCH",
                    message=("Timestamp and return columns have different lengths."),
                    severity=IssueSeverity.ERROR,
                    blocking=True,
                ),
            )
        )

    # format="ISO8601" rather than pandas inference. Inference reads the
    # format from the FIRST element only and defaults to month-first, so a
    # monthly series exported day-first (01/02/2023, 01/03/2023, ...) parsed
    # as 2 Jan, 3 Jan -- every row "succeeded", no issue was emitted, and the
    # report published wrong dates and a DAILY inferred frequency for a
    # monthly series. An audit tool must not guess a date format.
    raw_timestamps = list(timestamps)
    parsed_timestamps = parse_on_one_timeline(
        raw_timestamps,
        format="ISO8601",
        errors="coerce",
    )

    parsed_values = pd.to_numeric(
        pd.Series(list(values)),
        errors="coerce",
    )

    blocking_issues: list[ValidationIssue] = []

    one_timeline = parsed_timestamps is not None
    if not one_timeline:
        blocking_issues.append(
            ValidationIssue(
                code="INVALID_TIMESTAMP",
                message=mixed_offset_message("Timestamps", raw_timestamps),
                severity=IssueSeverity.ERROR,
                blocking=True,
                location="timestamp",
            )
        )
        # Rows that are not ISO 8601 at all are still reported: read every row
        # as an instant only to find them, never to build the series.
        invalid_mask = np.asarray(
            pd.isna(
                pd.to_datetime(
                    pd.Series(raw_timestamps, dtype=object),
                    format="ISO8601",
                    errors="coerce",
                    utc=True,
                )
            )
        )
    else:
        invalid_mask = np.asarray(pd.isna(parsed_timestamps))
    if invalid_mask.any():
        first = int(np.flatnonzero(np.asarray(invalid_mask))[0])
        blocking_issues.append(
            ValidationIssue(
                code="INVALID_TIMESTAMP",
                message=(
                    f"{int(np.asarray(invalid_mask).sum())} timestamp(s) are not "
                    f"ISO 8601. First at row {first + 1}: "
                    f"{raw_timestamps[first]!r}. Expected YYYY-MM-DD or "
                    "YYYY-MM-DDThh:mm:ss with an optional offset. Ambiguous "
                    "formats such as 01/02/2023 are rejected rather than "
                    "guessed, because the guess would silently change every "
                    "published date."
                ),
                severity=IssueSeverity.ERROR,
                blocking=True,
                location="timestamp",
            )
        )

    if parsed_values.isna().any() or not np.isfinite(parsed_values.to_numpy()).all():
        blocking_issues.append(
            ValidationIssue(
                code="NONFINITE_RETURN",
                message=("Return values must be numeric and finite."),
                severity=IssueSeverity.ERROR,
                blocking=True,
                location="return",
            )
        )

    if (
        convention is ReturnConvention.SIMPLE
        and not parsed_values.isna().any()
        and np.any(parsed_values.to_numpy() < -1.0)
    ):
        below = int(np.flatnonzero(parsed_values.to_numpy() < -1.0)[0])
        blocking_issues.append(
            ValidationIssue(
                code="SIMPLE_RETURN_BELOW_MINUS_ONE",
                message=(
                    "Simple returns cannot be less than -1.0 (a loss of more "
                    f"than 100 %). First at row {below + 1}: "
                    f"{float(parsed_values.iloc[below])!r}. Returns are read "
                    "as decimals (0.015 = 1.5 %); if the file holds percent "
                    "values (1.5 = 1.5 %), divide them by 100."
                ),
                severity=IssueSeverity.ERROR,
                blocking=True,
                location="return",
            )
        )

    # Only over successfully parsed values: several unparseable timestamps
    # all coerce to NaT, which pd.Index counts as duplicates, so the emitted
    # payload asserted a DUPLICATE_TIMESTAMP defect the input did not have.
    if one_timeline and pd.Index(parsed_timestamps[~invalid_mask]).has_duplicates:  # type: ignore[index]  # QUALITY.md
        blocking_issues.append(
            ValidationIssue(
                code="DUPLICATE_TIMESTAMP",
                message="Duplicate timestamps are not allowed.",
                severity=IssueSeverity.ERROR,
                blocking=True,
                location="timestamp",
            )
        )

    if blocking_issues:
        raise InputValidationError(tuple(blocking_issues))

    frame = pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(parsed_timestamps),
            "return": parsed_values.to_numpy(dtype=np.float64),
        }
    )

    issues: list[ValidationIssue] = []

    if not frame["timestamp"].is_monotonic_increasing:
        frame = frame.sort_values(
            "timestamp",
            kind="mergesort",
        ).reset_index(drop=True)

        issues.append(
            ValidationIssue(
                code="TIMESTAMPS_SORTED",
                message=(
                    "Input timestamps were not ordered and were sorted ascending."
                ),
                severity=IssueSeverity.WARNING,
                blocking=False,
                location="timestamp",
            )
        )

    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(frame["timestamp"]),
        values=frame["return"].to_numpy(dtype=np.float64),
        convention=convention,
        sampling=sampling,
        name=name,
    )

    return ReturnSeriesNormalizationResult(
        series=series,
        issues=tuple(issues),
    )
