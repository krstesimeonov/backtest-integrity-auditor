from datetime import date
from pathlib import Path

import pandas as pd

from backtest_auditor.domain.enums import IssueSeverity
from backtest_auditor.domain.issues import (
    InputValidationError,
    ValidationIssue,
)
from backtest_auditor.ingestion.timestamp_offsets import (
    mixed_offset_message,
    parse_on_one_timeline,
)


def read_calendar_session_dates_csv(
    path: str | Path,
    *,
    session_column: str,
) -> tuple[date, ...]:
    """Read an authoritative, strictly ordered daily session schedule."""

    input_path = Path(path)
    try:
        frame = pd.read_csv(input_path)
    except FileNotFoundError as error:
        raise _error(
            "CALENDAR_SESSION_FILE_NOT_FOUND",
            f"Calendar session CSV does not exist: {input_path}",
            input_path,
        ) from error
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        UnicodeDecodeError,
        OSError,
    ) as error:
        raise _error(
            "CALENDAR_SESSION_CSV_READ_ERROR",
            f"Calendar session CSV could not be read: {input_path}",
            input_path,
        ) from error

    if session_column not in frame.columns:
        raise _error(
            "MISSING_CALENDAR_SESSION_COLUMN",
            f"Calendar session CSV is missing required column: {session_column}.",
            input_path,
        )

    parsed = parse_on_one_timeline(frame[session_column], errors="coerce")
    if parsed is None:
        raise _error(
            "INVALID_CALENDAR_SESSION_DATE",
            mixed_offset_message("Calendar session dates", list(frame[session_column])),
            input_path,
        )
    if parsed.isna().any() or len(parsed) == 0:
        raise _error(
            "INVALID_CALENDAR_SESSION_DATE",
            "Calendar session dates must be non-empty and parseable.",
            input_path,
        )

    dates = tuple(item.date() for item in parsed)
    if len(set(dates)) != len(dates):
        raise _error(
            "DUPLICATE_CALENDAR_SESSION_DATE",
            "Calendar session dates must be unique.",
            input_path,
        )
    if tuple(sorted(dates)) != dates:
        raise _error(
            "UNORDERED_CALENDAR_SESSION_DATES",
            "Calendar session dates must be strictly increasing.",
            input_path,
        )
    return dates


def _error(
    code: str,
    message: str,
    path: Path,
) -> InputValidationError:
    return InputValidationError(
        (
            ValidationIssue(
                code=code,
                message=message,
                severity=IssueSeverity.ERROR,
                blocking=True,
                location=str(path),
            ),
        )
    )
