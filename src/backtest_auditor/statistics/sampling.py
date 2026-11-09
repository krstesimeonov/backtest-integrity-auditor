import pandas as pd

from backtest_auditor.domain.enums import (
    FrequencyStatus,
    ObservationCalendarStatus,
)
from backtest_auditor.domain.results import (
    ObservationCalendarAssessmentResult,
    SamplingAssessmentResult,
)
from backtest_auditor.domain.series import ReturnSeries


def assess_sampling(
    series: ReturnSeries,
    calendar_assessment: ObservationCalendarAssessmentResult | None = None,
) -> SamplingAssessmentResult:
    """Assess timestamp regularity without assuming an annualization scale."""

    timestamps = series.timestamps
    observation_count = len(timestamps)
    interval_count = observation_count - 1

    minimum_interval_seconds: float | None = None
    maximum_interval_seconds: float | None = None

    if interval_count:
        interval_seconds = (timestamps[1:] - timestamps[:-1]).total_seconds()
        minimum_interval_seconds = float(interval_seconds.min())
        maximum_interval_seconds = float(interval_seconds.max())

    inferred_frequency = None if observation_count < 3 else pd.infer_freq(timestamps)

    # The calendar-verified short circuit must not skip the observation-count
    # precondition that _determine_frequency_status enforces for every other
    # path. A single observation trivially verifies against a 24/7 calendar,
    # because the expected date range is built from the observed dates
    # themselves, so annualization_eligible became True at n = 1 and
    # calculate_annualized_statistics then raised ValueError -- the same file
    # audited cleanly without --observation-calendar.
    status = (
        FrequencyStatus.CALENDAR_VERIFIED
        if (
            observation_count >= 3
            and calendar_assessment is not None
            and calendar_assessment.status is ObservationCalendarStatus.VERIFIED
        )
        else _determine_frequency_status(
            timestamps=timestamps,
            declared_frequency=(series.sampling.declared_frequency),
            inferred_frequency=inferred_frequency,
        )
    )

    annualization_eligible = (
        series.sampling.periods_per_year is not None
        and status
        in {
            FrequencyStatus.DECLARED,
            FrequencyStatus.INFERRED_REGULAR,
            FrequencyStatus.CALENDAR_VERIFIED,
        }
    )

    return SamplingAssessmentResult(
        status=status,
        observation_count=observation_count,
        interval_count=interval_count,
        declared_frequency=series.sampling.declared_frequency,
        inferred_frequency=inferred_frequency,
        periods_per_year=series.sampling.periods_per_year,
        minimum_interval_seconds=minimum_interval_seconds,
        maximum_interval_seconds=maximum_interval_seconds,
        annualization_eligible=annualization_eligible,
    )


def _determine_frequency_status(
    *,
    timestamps: pd.DatetimeIndex,
    declared_frequency: str | None,
    inferred_frequency: str | None,
) -> FrequencyStatus:
    if len(timestamps) < 3:
        return FrequencyStatus.AMBIGUOUS

    if declared_frequency is not None:
        expected_timestamps = pd.date_range(
            start=timestamps[0],
            periods=len(timestamps),
            freq=declared_frequency,
        )

        if expected_timestamps.equals(timestamps):
            return FrequencyStatus.DECLARED

        return FrequencyStatus.DECLARED_CONFLICT

    if inferred_frequency is not None:
        return FrequencyStatus.INFERRED_REGULAR

    return FrequencyStatus.IRREGULAR
