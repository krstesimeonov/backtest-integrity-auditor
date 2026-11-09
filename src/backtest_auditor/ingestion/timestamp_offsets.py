"""One timeline per input file (F06).

pandas cannot place timestamps with different UTC offsets on one timeline
without a conversion the input did not ask for: pandas 3 raises ValueError
("Mixed timezones detected") and pandas 2 returns object dtype. Every reader
turns that into its own blocking issue instead of letting the exception leave
the validation contract.
"""

from collections.abc import Sequence
from typing import Any

import pandas as pd

MIXED_OFFSET_ADVICE = (
    "Supply every timestamp with the same offset, for example all in UTC; "
    "the auditor does not choose a common timeline for the input."
)


def parse_on_one_timeline(values: Any, **options: Any) -> Any | None:
    """Return ``pd.to_datetime(values, **options)``, or None when the values
    do not share one UTC offset (or mix offsets with offset-free values)."""

    try:
        parsed = pd.to_datetime(values, **options)
    except ValueError:
        return None
    dtype = getattr(parsed, "dtype", None)
    if dtype is None or not pd.api.types.is_datetime64_any_dtype(dtype):
        return None
    return parsed


def mixed_offset_message(subject: str, raw_timestamps: Sequence[object]) -> str:
    """The blocking message for values that are not on one timeline: names the
    first two rows whose offsets differ, or says only that pandas could not
    place them on one timeline when no such rows exist."""

    change = describe_offset_change(raw_timestamps)
    if change is None:
        return f"{subject} could not be placed on one timeline. {MIXED_OFFSET_ADVICE}"
    return f"{subject} carry more than one UTC offset ({change}). {MIXED_OFFSET_ADVICE}"


def describe_offset_change(raw_timestamps: Sequence[object]) -> str | None:
    """Name the first data row whose UTC offset differs from the first row's."""

    first: tuple[int, str] | None = None
    for row, value in enumerate(raw_timestamps, start=1):
        try:
            stamp = pd.Timestamp(str(value))
        except (TypeError, ValueError):
            continue
        if pd.isna(stamp):
            continue
        label = "no offset" if stamp.tzinfo is None else stamp.isoformat()[-6:]
        if first is None:
            first = (row, label)
        elif label != first[1]:
            return f"row {first[0]} has {first[1]}, row {row} has {label}"
    return None
