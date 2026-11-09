from pathlib import Path

import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.csv_returns import (
    read_return_series_csv,
)


def test_csv_reader_uses_explicit_columns_and_normalizes(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "when,pnl_return\n2026-01-02,0.02\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    result = read_return_series_csv(
        input_path,
        timestamp_column="when",
        return_column="pnl_return",
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    assert result.series.values.tolist() == [0.01, 0.02]
    assert [issue.code for issue in result.issues] == ["TIMESTAMPS_SORTED"]


def test_csv_reader_reports_missing_required_column(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,value\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as exc_info:
        read_return_series_csv(
            input_path,
            timestamp_column="timestamp",
            return_column="return",
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )

    assert [issue.code for issue in exc_info.value.issues] == [
        "MISSING_REQUIRED_COLUMN"
    ]


def test_csv_reader_reports_header_only_input_as_empty(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,return\n",
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as exc_info:
        read_return_series_csv(
            input_path,
            timestamp_column="timestamp",
            return_column="return",
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )

    assert [issue.code for issue in exc_info.value.issues] == ["EMPTY_RETURN_SERIES"]
