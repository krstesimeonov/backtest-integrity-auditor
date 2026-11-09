from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pandas.tseries.frequencies import to_offset

from backtest_auditor.domain.enums import (
    FrequencyStatus,
    ReturnConvention,
)


@dataclass(frozen=True, slots=True)
class SamplingSpec:
    status: FrequencyStatus = FrequencyStatus.AMBIGUOUS
    declared_frequency: str | None = None
    periods_per_year: int | None = None
    timezone: str | None = None

    def __post_init__(self) -> None:
        if self.declared_frequency is not None:
            declared_frequency = self.declared_frequency.strip()

            if not declared_frequency:
                raise ValueError("declared_frequency must not be empty.")

            try:
                canonical_frequency = to_offset(declared_frequency).freqstr
            except ValueError as error:
                raise ValueError(
                    "declared_frequency must be a valid pandas offset alias."
                ) from error

            object.__setattr__(
                self,
                "declared_frequency",
                canonical_frequency,
            )

        if self.periods_per_year is not None and self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive when supplied.")

        if self.timezone is not None:
            timezone = self.timezone.strip()
            if not timezone:
                raise ValueError("timezone must not be empty.")
            try:
                ZoneInfo(timezone)
            except ZoneInfoNotFoundError as error:
                raise ValueError(
                    "timezone must be a valid IANA timezone name."
                ) from error
            object.__setattr__(self, "timezone", timezone)


@dataclass(frozen=True, slots=True)
class ReturnSeries:
    timestamps: pd.DatetimeIndex
    values: NDArray[np.float64]
    convention: ReturnConvention
    sampling: SamplingSpec
    name: str | None = None

    def __post_init__(self) -> None:
        timestamps = pd.DatetimeIndex(self.timestamps)
        values = np.asarray(self.values, dtype=np.float64)

        if len(timestamps) == 0:
            raise ValueError("ReturnSeries cannot be empty.")

        if len(timestamps) != len(values):
            raise ValueError("timestamps and values must have equal length.")

        if timestamps.hasnans:
            raise ValueError("timestamps must not contain missing values.")

        if not timestamps.is_unique:
            raise ValueError("timestamps must be unique.")

        if not timestamps.is_monotonic_increasing:
            raise ValueError("timestamps must be strictly increasing.")

        if not np.isfinite(values).all():
            raise ValueError("return values must be finite.")

        if self.convention is ReturnConvention.SIMPLE and np.any(values < -1.0):
            raise ValueError("simple returns cannot be less than -1.0.")

        immutable_values = values.copy()
        immutable_values.setflags(write=False)

        object.__setattr__(
            self,
            "timestamps",
            timestamps.copy(),
        )
        object.__setattr__(
            self,
            "values",
            immutable_values,
        )


@dataclass(frozen=True, slots=True)
class RegimeSeries:
    """Externally supplied categorical labels aligned to return observations."""

    timestamps: pd.DatetimeIndex
    labels: tuple[str, ...]
    name: str = "regime"

    def __post_init__(self) -> None:
        timestamps = pd.DatetimeIndex(self.timestamps)
        if len(timestamps) == 0:
            raise ValueError("RegimeSeries cannot be empty.")
        if timestamps.hasnans:
            raise ValueError("regime timestamps must not contain missing values.")
        if not timestamps.is_unique:
            raise ValueError("regime timestamps must be unique.")
        if not timestamps.is_monotonic_increasing:
            raise ValueError("regime timestamps must be strictly increasing.")
        if any(not isinstance(label, str) for label in self.labels):
            raise ValueError("regime labels must be strings.")
        labels = tuple(label.strip() for label in self.labels)
        if len(labels) != len(timestamps):
            raise ValueError("regime timestamps and labels must have equal length.")
        if any(not label for label in labels):
            raise ValueError("regime labels must not be empty.")
        name = self.name.strip()
        if not name:
            raise ValueError("regime series name must not be empty.")
        object.__setattr__(self, "timestamps", timestamps.copy())
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "name", name)
