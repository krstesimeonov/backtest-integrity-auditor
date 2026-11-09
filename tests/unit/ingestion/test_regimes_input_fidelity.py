"""0718043's input-fidelity rules, carried to the 1.4.0 regime reader.

read_regime_series_csv repeated the three patterns the original commit removed
from the return and family readers: dtype inference on a text column, a
guessed date format, and a duplicate check over coerced (NaT) timestamps.
"""

from pathlib import Path

import pytest

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.ingestion.regimes import read_regime_series_csv


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "regimes.csv"
    path.write_text(content, encoding="utf-8")
    return path


def _codes(error: InputValidationError) -> list[str]:
    return sorted(issue.code for issue in error.issues)


def test_numeric_looking_and_na_labels_are_kept_as_written(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "timestamp,regime\n2026-01-01,01\n2026-01-02,NA\n2026-01-03,1e3\n",
    )

    result = read_regime_series_csv(path)

    assert result.series.labels == ("01", "NA", "1e3")


def test_day_first_dates_are_rejected_not_guessed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "timestamp,regime\n01/02/2023,a\n01/03/2023,b\n01/04/2023,a\n",
    )

    with pytest.raises(InputValidationError) as caught:
        read_regime_series_csv(path)

    assert _codes(caught.value) == ["INVALID_REGIME_TIMESTAMP"]
    message = caught.value.issues[0].message
    assert "row 1" in message
    assert "01/02/2023" in message


def test_two_unparseable_timestamps_are_not_reported_as_duplicates(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "timestamp,regime\nnot-a-date,a\nalso-bad,b\n2026-01-03,a\n",
    )

    with pytest.raises(InputValidationError) as caught:
        read_regime_series_csv(path)

    assert _codes(caught.value) == ["INVALID_REGIME_TIMESTAMP"]


def test_genuine_duplicate_regime_timestamps_are_still_rejected(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "timestamp,regime\n2026-01-01,a\n2026-01-01,b\n",
    )

    with pytest.raises(InputValidationError) as caught:
        read_regime_series_csv(path)

    assert _codes(caught.value) == ["DUPLICATE_REGIME_TIMESTAMP"]


def test_iso8601_regime_timestamps_with_time_still_parse(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "timestamp,regime\n2026-01-01T00:00:00,a\n2026-01-02 00:00:00,b\n",
    )

    result = read_regime_series_csv(path)

    assert len(result.series.timestamps) == 2
