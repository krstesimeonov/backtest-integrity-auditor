from datetime import date
from pathlib import Path

import pytest

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.ingestion.calendar_sessions import (
    read_calendar_session_dates_csv,
)


def test_calendar_session_csv_reads_strict_dates(tmp_path: Path) -> None:
    path = tmp_path / "sessions.csv"
    path.write_text(
        "session\n2026-01-02\n2026-01-05\n",
        encoding="utf-8",
    )

    result = read_calendar_session_dates_csv(
        path,
        session_column="session",
    )

    assert result == (date(2026, 1, 2), date(2026, 1, 5))


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("date\n2026-01-02\n", "MISSING_CALENDAR_SESSION_COLUMN"),
        (
            "session\n2026-01-02\nnot-a-date\n",
            "INVALID_CALENDAR_SESSION_DATE",
        ),
        (
            "session\n2026-01-02\n2026-01-02\n",
            "DUPLICATE_CALENDAR_SESSION_DATE",
        ),
        (
            "session\n2026-01-05\n2026-01-02\n",
            "UNORDERED_CALENDAR_SESSION_DATES",
        ),
    ],
)
def test_calendar_session_csv_rejects_unverifiable_schedule(
    tmp_path: Path,
    content: str,
    code: str,
) -> None:
    path = tmp_path / "sessions.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(InputValidationError) as error:
        read_calendar_session_dates_csv(path, session_column="session")

    assert error.value.issues[0].code == code
