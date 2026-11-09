from pathlib import Path

import pandas as pd

from backtest_auditor.domain.enums import (
    IssueSeverity,
    ReturnConvention,
)
from backtest_auditor.domain.issues import (
    InputValidationError,
    ValidationIssue,
)
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.normalization import (
    ReturnSeriesNormalizationResult,
    normalize_return_series,
)


def read_return_series_csv(
    path: str | Path,
    *,
    timestamp_column: str,
    return_column: str,
    convention: ReturnConvention,
    sampling: SamplingSpec,
    name: str | None = None,
) -> ReturnSeriesNormalizationResult:
    """Read a CSV adapter input and normalize it to the canonical model."""

    input_path = Path(path)

    try:
        frame = pd.read_csv(input_path)
    except FileNotFoundError as error:
        raise _single_issue_error(
            code="INPUT_FILE_NOT_FOUND",
            message=f"Input CSV file does not exist: {input_path}",
            location=str(input_path),
        ) from error
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        UnicodeDecodeError,
        OSError,
    ) as error:
        raise _single_issue_error(
            code="CSV_READ_ERROR",
            message=f"Input CSV file could not be read: {input_path}",
            location=str(input_path),
        ) from error

    required_columns = (timestamp_column, return_column)
    missing_columns = tuple(
        column for column in required_columns if column not in frame.columns
    )

    if missing_columns:
        formatted_columns = ", ".join(missing_columns)
        raise _single_issue_error(
            code="MISSING_REQUIRED_COLUMN",
            message=(f"Input CSV is missing required column(s): {formatted_columns}."),
            location=str(input_path),
        )

    return normalize_return_series(
        frame[timestamp_column].tolist(),
        frame[return_column].tolist(),
        convention=convention,
        sampling=sampling,
        name=name,
    )


def _single_issue_error(
    *,
    code: str,
    message: str,
    location: str,
) -> InputValidationError:
    return InputValidationError(
        (
            ValidationIssue(
                code=code,
                message=message,
                severity=IssueSeverity.ERROR,
                blocking=True,
                location=location,
            ),
        )
    )
