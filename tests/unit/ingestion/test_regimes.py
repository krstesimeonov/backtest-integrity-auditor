from pathlib import Path

import pytest

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.ingestion.regimes import read_regime_series_csv


def test_regime_csv_is_trimmed_sorted_and_warns(tmp_path: Path) -> None:
    path = tmp_path / "regimes.csv"
    path.write_text(
        "time,state\n2026-01-02, risk-off \n2026-01-01,risk-on\n",
        encoding="utf-8",
    )

    result = read_regime_series_csv(
        path, timestamp_column="time", regime_column="state"
    )

    assert result.series.labels == ("risk-on", "risk-off")
    assert result.issues[0].code == "REGIME_TIMESTAMPS_SORTED"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("wrong,columns\n1,2\n", "MISSING_REQUIRED_COLUMN"),
        ("timestamp,regime\nnot-a-date,a\n", "INVALID_REGIME_TIMESTAMP"),
        ("timestamp,regime\n2026-01-01,\n", "INVALID_REGIME_LABEL"),
        (
            "timestamp,regime\n2026-01-01,a\n2026-01-01,b\n",
            "DUPLICATE_REGIME_TIMESTAMP",
        ),
    ],
)
def test_regime_csv_rejects_malformed_evidence(
    tmp_path: Path, content: str, code: str
) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(InputValidationError) as error:
        read_regime_series_csv(path)

    assert code in {issue.code for issue in error.value.issues}


def test_regime_csv_wraps_file_read_failures(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError) as error:
        read_regime_series_csv(tmp_path / "missing.csv")

    assert error.value.issues[0].code == "REGIME_CSV_READ_ERROR"
