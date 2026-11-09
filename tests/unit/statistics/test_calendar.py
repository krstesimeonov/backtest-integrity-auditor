from datetime import date

import numpy as np
import pandas as pd

from backtest_auditor.domain.enums import (
    FrequencyStatus,
    ObservationCalendarSource,
    ObservationCalendarStatus,
    ReturnConvention,
)
from backtest_auditor.domain.metadata import ObservationCalendarSpec
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.calendar import (
    assess_observation_calendar,
)
from backtest_auditor.statistics.sampling import assess_sampling


def _series(timestamps: list[str]) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.DatetimeIndex(timestamps),
        values=np.asarray([0.01] * len(timestamps)),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(
            periods_per_year=252,
            timezone="America/New_York",
        ),
    )


def test_authoritative_exchange_sessions_override_generic_irregularity() -> None:
    series = _series(["2026-01-02", "2026-01-05", "2026-01-06"])
    spec = ObservationCalendarSpec(
        calendar_name="XNYS",
        timezone="America/New_York",
        expected_session_dates=(
            date(2026, 1, 2),
            date(2026, 1, 5),
            date(2026, 1, 6),
        ),
    )

    calendar = assess_observation_calendar(series, spec)
    sampling = assess_sampling(series, calendar)

    assert calendar is not None
    assert calendar.status is ObservationCalendarStatus.VERIFIED
    assert calendar.source is ObservationCalendarSource.SESSION_FILE
    assert sampling.status is FrequencyStatus.CALENDAR_VERIFIED
    assert sampling.annualization_eligible


def test_missing_authoritative_session_is_reported_exactly() -> None:
    series = _series(["2026-01-02", "2026-01-06"])
    spec = ObservationCalendarSpec(
        calendar_name="XNYS",
        timezone="America/New_York",
        expected_session_dates=(
            date(2026, 1, 2),
            date(2026, 1, 5),
            date(2026, 1, 6),
        ),
    )

    result = assess_observation_calendar(series, spec)

    assert result is not None
    assert result.status is ObservationCalendarStatus.MISMATCH
    assert result.missing_session_dates == ("2026-01-05",)
    assert result.unexpected_session_dates == ()


def test_named_exchange_without_sessions_is_declared_unverified() -> None:
    result = assess_observation_calendar(
        _series(["2026-01-02", "2026-01-05"]),
        ObservationCalendarSpec(
            calendar_name="XNYS",
            timezone="America/New_York",
        ),
    )

    assert result is not None
    assert result.status is ObservationCalendarStatus.DECLARED_UNVERIFIED
    assert result.source is ObservationCalendarSource.DECLARATION_ONLY


def test_builtin_continuous_calendar_detects_missing_day() -> None:
    result = assess_observation_calendar(
        _series(["2026-01-01", "2026-01-03"]),
        ObservationCalendarSpec(
            calendar_name="24/7",
            timezone="UTC",
        ),
    )

    assert result is not None
    assert result.source is ObservationCalendarSource.BUILT_IN_24_7
    assert result.missing_session_dates == ("2026-01-02",)


def test_daily_session_contract_refuses_intraday_overclaim() -> None:
    result = assess_observation_calendar(
        _series(["2026-01-02 10:00", "2026-01-02 11:00"]),
        ObservationCalendarSpec(
            calendar_name="XNYS",
            timezone="America/New_York",
            expected_session_dates=(date(2026, 1, 2),),
        ),
    )

    assert result is not None
    assert result.status is ObservationCalendarStatus.INTRADAY_UNSUPPORTED


def test_embedded_timezone_is_preserved_as_timestamp_evidence() -> None:
    series = ReturnSeries(
        timestamps=pd.date_range(
            "2026-01-01",
            periods=2,
            freq="D",
            tz="UTC",
        ),
        values=np.asarray([0.01, 0.02]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(periods_per_year=365),
    )

    result = assess_observation_calendar(
        series,
        ObservationCalendarSpec(
            calendar_name="24/7",
            timezone="UTC",
        ),
    )

    assert result is not None
    assert result.timestamp_timezone == "UTC"
