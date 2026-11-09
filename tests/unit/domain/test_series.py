import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import (
    RegimeSeries,
    ReturnSeries,
    SamplingSpec,
)


def test_return_series_copies_and_freezes_values() -> None:
    source = np.array(
        [0.01, -0.02],
        dtype=np.float64,
    )

    series = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]),
        values=source,
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    source[0] = 99.0

    assert series.values[0] == pytest.approx(0.01)

    with pytest.raises(ValueError):
        series.values[0] = 0.0


@pytest.mark.parametrize(
    ("timestamps", "values", "message"),
    [
        (
            ["2026-01-01"],
            [],
            "equal length",
        ),
        (
            ["2026-01-01", "2026-01-01"],
            [0.0, 0.1],
            "unique",
        ),
        (
            ["2026-01-02", "2026-01-01"],
            [0.0, 0.1],
            "increasing",
        ),
        (
            ["2026-01-01"],
            [np.nan],
            "finite",
        ),
    ],
)
def test_return_series_rejects_invalid_inputs(
    timestamps: list[str],
    values: list[float],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ReturnSeries(
            timestamps=pd.DatetimeIndex(timestamps),
            values=np.asarray(
                values,
                dtype=np.float64,
            ),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )


def test_simple_return_cannot_be_below_minus_one() -> None:
    with pytest.raises(
        ValueError,
        match="less than -1.0",
    ):
        ReturnSeries(
            timestamps=pd.DatetimeIndex(["2026-01-01"]),
            values=np.array([-1.01]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        )


def test_sampling_spec_canonicalizes_declared_frequency() -> None:
    sampling = SamplingSpec(declared_frequency="1D")

    assert sampling.declared_frequency == "D"


@pytest.mark.parametrize(
    "periods_per_year",
    [0, -1],
)
def test_sampling_spec_requires_positive_periods_per_year(
    periods_per_year: int,
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        SamplingSpec(periods_per_year=periods_per_year)


def test_sampling_spec_rejects_invalid_declared_frequency() -> None:
    with pytest.raises(ValueError, match="offset alias"):
        SamplingSpec(declared_frequency="not-a-frequency")


def test_sampling_spec_validates_timestamp_timezone() -> None:
    assert SamplingSpec(timezone="Europe/Skopje").timezone == ("Europe/Skopje")

    with pytest.raises(ValueError, match="IANA"):
        SamplingSpec(timezone="Mars/Olympus")


def test_regime_series_normalizes_labels_and_name() -> None:
    series = RegimeSeries(
        pd.DatetimeIndex(["2026-01-01", "2026-01-02"]),
        (" risk-on ", "risk-off"),
        " declared ",
    )

    assert series.labels == ("risk-on", "risk-off")
    assert series.name == "declared"


@pytest.mark.parametrize(
    ("timestamps", "labels", "name", "message"),
    [
        ([], (), "regime", "cannot be empty"),
        ([pd.NaT], ("a",), "regime", "missing"),
        (["2026-01-01", "2026-01-01"], ("a", "b"), "regime", "unique"),
        (["2026-01-02", "2026-01-01"], ("a", "b"), "regime", "increasing"),
        (["2026-01-01"], (1,), "regime", "strings"),
        (["2026-01-01"], ("a", "b"), "regime", "equal length"),
        (["2026-01-01"], (" ",), "regime", "must not be empty"),
        (["2026-01-01"], ("a",), " ", "name must not be empty"),
    ],
)
def test_regime_series_rejects_invalid_inputs(
    timestamps: list[object],
    labels: tuple[object, ...],
    name: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RegimeSeries(pd.DatetimeIndex(timestamps), labels, name)  # type: ignore[arg-type]
