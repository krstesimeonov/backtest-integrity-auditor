from datetime import date

import pandas as pd

from backtest_auditor.domain.enums import (
    IssueSeverity,
    ObservationCalendarSource,
    ObservationCalendarStatus,
)
from backtest_auditor.domain.issues import (
    InputValidationError,
    ValidationIssue,
)
from backtest_auditor.domain.metadata import ObservationCalendarSpec
from backtest_auditor.domain.results import (
    ObservationCalendarAssessmentResult,
)
from backtest_auditor.domain.series import ReturnSeries

# Which exception a DST fold or gap raises depends on the pandas version.
# pandas 3 raises its own AmbiguousTimeError / NonExistentTimeError, which are
# ValueError subclasses. pandas 2.x raises pytz's, whose shared base is
# InvalidTimeError and which are NOT ValueErrors -- so catching ValueError
# alone let the raw traceback escape on every supported pandas 2 release.
try:
    from pytz.exceptions import InvalidTimeError as _PytzInvalidTimeError
except ImportError:  # pandas 3 no longer depends on pytz
    _LOCALIZATION_ERRORS: tuple[type[Exception], ...] = (ValueError,)
else:
    _LOCALIZATION_ERRORS = (ValueError, _PytzInvalidTimeError)


_CONTINUOUS_NAMES = {"24/7", "24_7", "continuous"}
_WEEKDAY_NAMES = {"weekday", "weekdays"}


def assess_observation_calendar(
    series: ReturnSeries,
    spec: ObservationCalendarSpec | None,
) -> ObservationCalendarAssessmentResult | None:
    """Compare daily observations with an explicit session policy.

    Intraday calendars need open/close and bar-boundary semantics that are not
    part of this increment, so multiple observations on one local session date
    remain visible as an ineligible status.
    """

    if spec is None:
        return None

    observed_dates = _local_observation_dates(series, spec.timezone)
    timestamp_timezone = (
        str(series.timestamps.tz)
        if series.timestamps.tz is not None
        else series.sampling.timezone
    )
    unique_observed_dates = tuple(dict.fromkeys(observed_dates))
    source, expected_dates = _expected_dates(spec, unique_observed_dates)

    if len(unique_observed_dates) != len(observed_dates):
        return ObservationCalendarAssessmentResult(
            status=ObservationCalendarStatus.INTRADAY_UNSUPPORTED,
            calendar_name=spec.calendar_name,
            source=source,
            calendar_timezone=spec.timezone,
            timestamp_timezone=timestamp_timezone,
            observation_count=len(series.timestamps),
            observed_session_count=len(unique_observed_dates),
            expected_session_count=(
                None if expected_dates is None else len(expected_dates)
            ),
            missing_session_dates=(),
            unexpected_session_dates=(),
        )

    if expected_dates is None:
        return ObservationCalendarAssessmentResult(
            status=ObservationCalendarStatus.DECLARED_UNVERIFIED,
            calendar_name=spec.calendar_name,
            source=source,
            calendar_timezone=spec.timezone,
            timestamp_timezone=timestamp_timezone,
            observation_count=len(series.timestamps),
            observed_session_count=len(unique_observed_dates),
            expected_session_count=None,
            missing_session_dates=(),
            unexpected_session_dates=(),
        )

    observed_set = set(unique_observed_dates)
    expected_set = set(expected_dates)
    missing = tuple(item.isoformat() for item in sorted(expected_set - observed_set))
    unexpected = tuple(item.isoformat() for item in sorted(observed_set - expected_set))
    status = (
        ObservationCalendarStatus.VERIFIED
        if not missing and not unexpected
        else ObservationCalendarStatus.MISMATCH
    )

    return ObservationCalendarAssessmentResult(
        status=status,
        calendar_name=spec.calendar_name,
        source=source,
        calendar_timezone=spec.timezone,
        timestamp_timezone=timestamp_timezone,
        observation_count=len(series.timestamps),
        observed_session_count=len(unique_observed_dates),
        expected_session_count=len(expected_dates),
        missing_session_dates=missing,
        unexpected_session_dates=unexpected,
    )


def _local_observation_dates(
    series: ReturnSeries,
    calendar_timezone: str,
) -> tuple[date, ...]:
    timestamps = series.timestamps
    if timestamps.tz is not None:
        localized = timestamps.tz_convert(calendar_timezone)
    elif series.sampling.timezone is not None:
        try:
            localized = timestamps.tz_localize(series.sampling.timezone).tz_convert(
                calendar_timezone
            )
        except _LOCALIZATION_ERRORS as error:
            # A naive wall-clock timestamp inside a DST fold or gap has no
            # single UTC instant, and choosing one silently would change the
            # observed session dates. Reject with the typed blocking issue
            # contract instead of escaping as a raw pandas traceback.
            raise InputValidationError(
                (
                    ValidationIssue(
                        code="AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIMESTAMP",
                        message=(
                            "Naive timestamps could not be localized to "
                            f"{series.sampling.timezone}: {error}. Supply "
                            "timezone-aware timestamps, or a timezone without "
                            "a daylight-saving transition in the sample."
                        ),
                        severity=IssueSeverity.ERROR,
                        location=str(series.sampling.timezone),
                        blocking=True,
                    ),
                )
            ) from error
    else:
        localized = timestamps

    return tuple(item.date() for item in localized)


def _expected_dates(
    spec: ObservationCalendarSpec,
    observed_dates: tuple[date, ...],
) -> tuple[ObservationCalendarSource, tuple[date, ...] | None]:
    if spec.expected_session_dates is not None:
        lower = observed_dates[0]
        upper = observed_dates[-1]
        dates = tuple(
            item for item in spec.expected_session_dates if lower <= item <= upper
        )
        return ObservationCalendarSource.SESSION_FILE, dates

    normalized_name = spec.calendar_name.casefold()
    start = observed_dates[0]
    end = observed_dates[-1]

    if normalized_name in _CONTINUOUS_NAMES:
        dates = tuple(pd.date_range(start, end, freq="D").date)
        return ObservationCalendarSource.BUILT_IN_24_7, dates

    if normalized_name in _WEEKDAY_NAMES:
        dates = tuple(pd.date_range(start, end, freq="B").date)
        return ObservationCalendarSource.BUILT_IN_WEEKDAYS, dates

    return ObservationCalendarSource.DECLARATION_ONLY, None
