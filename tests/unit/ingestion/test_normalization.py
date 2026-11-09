import pytest

from backtest_auditor.domain.enums import (
    ReturnConvention,
)
from backtest_auditor.domain.issues import (
    InputValidationError,
)
from backtest_auditor.domain.series import (
    SamplingSpec,
)
from backtest_auditor.ingestion.normalization import (  # type: ignore
    normalize_return_series,
)


def test_normalization_sorts_and_reports_warning() -> None:
    result = normalize_return_series(
        ["2026-01-02", "2026-01-01"],
        [0.02, 0.01],
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    assert result.series.timestamps[0].isoformat() == "2026-01-01T00:00:00"

    assert result.series.values.tolist() == [
        0.01,
        0.02,
    ]

    assert [issue.code for issue in result.issues] == ["TIMESTAMPS_SORTED"]


def test_normalization_rejects_duplicate_timestamps() -> None:
    with pytest.raises(InputValidationError) as exc_info:
        normalize_return_series(
            ["2026-01-01", "2026-01-01"],
            [0.01, 0.02],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )

    assert [issue.code for issue in exc_info.value.issues] == ["DUPLICATE_TIMESTAMP"]


def test_normalization_rejects_unparseable_values() -> None:
    with pytest.raises(InputValidationError) as exc_info:
        normalize_return_series(
            ["bad timestamp"],
            ["not a number"],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )

    assert {issue.code for issue in exc_info.value.issues} == {
        "INVALID_TIMESTAMP",
        "NONFINITE_RETURN",
    }


def test_normalization_rejects_an_empty_series() -> None:
    with pytest.raises(InputValidationError) as exc_info:
        normalize_return_series(
            [],
            [],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )

    assert [issue.code for issue in exc_info.value.issues] == ["EMPTY_RETURN_SERIES"]


def test_normalization_rejects_simple_return_below_total_loss() -> None:
    with pytest.raises(InputValidationError) as exc_info:
        normalize_return_series(
            ["2026-01-01"],
            [-1.01],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )

    assert [issue.code for issue in exc_info.value.issues] == [
        "SIMPLE_RETURN_BELOW_MINUS_ONE"
    ]
