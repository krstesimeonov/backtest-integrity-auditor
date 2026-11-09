from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_auditor.domain.enums import IssueSeverity
from backtest_auditor.domain.issues import InputValidationError, ValidationIssue
from backtest_auditor.domain.series import RegimeSeries
from backtest_auditor.ingestion.timestamp_offsets import (
    mixed_offset_message,
    parse_on_one_timeline,
)


@dataclass(frozen=True, slots=True)
class RegimeSeriesNormalizationResult:
    series: RegimeSeries
    issues: tuple[ValidationIssue, ...] = ()


def read_regime_series_csv(
    path: str | Path,
    *,
    timestamp_column: str = "timestamp",
    regime_column: str = "regime",
) -> RegimeSeriesNormalizationResult:
    input_path = Path(path)
    try:
        # dtype=str and keep_default_na=False, as for the experiment-family
        # CSVs (0718043): inference turned the label "01" into 1 and the label
        # "NA" into a missing value, so the report's regimes no longer matched
        # the file.
        frame = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    except (
        FileNotFoundError,
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        OSError,
    ) as error:
        raise _error(
            "REGIME_CSV_READ_ERROR", "Regime CSV could not be read.", str(input_path)
        ) from error
    missing = [
        name for name in (timestamp_column, regime_column) if name not in frame.columns
    ]
    if missing:
        raise _error(
            "MISSING_REQUIRED_COLUMN",
            f"Regime CSV is missing required column(s): {', '.join(missing)}.",
            str(input_path),
        )
    # format="ISO8601", as in normalize_return_series (0718043): inference
    # reads the format from the first row and defaults to month-first, so a
    # day-first file was silently re-dated instead of rejected.
    raw_timestamps = list(frame[timestamp_column])
    timestamps = parse_on_one_timeline(
        frame[timestamp_column], format="ISO8601", errors="coerce"
    )
    if timestamps is None:
        raise InputValidationError(
            (
                _issue(
                    "INVALID_REGIME_TIMESTAMP",
                    mixed_offset_message("Regime timestamps", raw_timestamps),
                    "timestamp",
                ),
            )
        )
    labels = frame[regime_column]
    issues: list[ValidationIssue] = []
    blocking: list[ValidationIssue] = []
    invalid_mask = np.asarray(timestamps.isna())
    if invalid_mask.any():
        first = int(np.flatnonzero(invalid_mask)[0])
        blocking.append(
            _issue(
                "INVALID_REGIME_TIMESTAMP",
                (
                    f"{int(invalid_mask.sum())} regime timestamp(s) are not "
                    f"ISO 8601. First at row {first + 1}: "
                    f"{raw_timestamps[first]!r}. Expected YYYY-MM-DD or "
                    "YYYY-MM-DDThh:mm:ss with an optional offset."
                ),
                "timestamp",
            )
        )
    if labels.isna().any() or any(not str(value).strip() for value in labels):
        blocking.append(
            _issue(
                "INVALID_REGIME_LABEL",
                "Regime labels must be non-empty strings.",
                "regime",
            )
        )
    # Over parsed values only: every unparseable value is NaT, so two bad
    # timestamps also raised a false duplicate.
    if pd.Index(timestamps.dropna()).has_duplicates:
        blocking.append(
            _issue(
                "DUPLICATE_REGIME_TIMESTAMP",
                "Regime timestamps must be unique.",
                "timestamp",
            )
        )
    if blocking:
        raise InputValidationError(tuple(blocking))
    normalized = pd.DataFrame(
        {"timestamp": timestamps, "regime": [str(value).strip() for value in labels]}
    )
    if not normalized["timestamp"].is_monotonic_increasing:
        normalized = normalized.sort_values("timestamp", kind="mergesort").reset_index(
            drop=True
        )
        issues.append(
            ValidationIssue(
                code="REGIME_TIMESTAMPS_SORTED",
                message="Regime timestamps were sorted ascending.",
                severity=IssueSeverity.WARNING,
                blocking=False,
                location="timestamp",
            )
        )
    return RegimeSeriesNormalizationResult(
        series=RegimeSeries(
            timestamps=pd.DatetimeIndex(normalized["timestamp"]),
            labels=tuple(normalized["regime"]),
        ),
        issues=tuple(issues),
    )


def _issue(code: str, message: str, location: str) -> ValidationIssue:
    return ValidationIssue(code, message, IssueSeverity.ERROR, True, location)


def _error(code: str, message: str, location: str) -> InputValidationError:
    return InputValidationError((_issue(code, message, location),))
