import numpy as np
import pandas as pd

from backtest_auditor.domain.enums import (
    FrequencyStatus,
    ReturnConvention,
)
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)
from backtest_auditor.statistics.sampling import assess_sampling


def _series(
    timestamps: list[str],
    *,
    sampling: SamplingSpec | None = None,
) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.DatetimeIndex(timestamps),
        values=np.zeros(len(timestamps)),
        convention=ReturnConvention.SIMPLE,
        sampling=sampling or SamplingSpec(),
    )


def test_fewer_than_three_observations_is_ambiguous() -> None:
    assessment = assess_sampling(_series(["2026-01-01", "2026-01-02"]))

    assert assessment.status is FrequencyStatus.AMBIGUOUS
    assert assessment.interval_count == 1
    assert assessment.inferred_frequency is None
    assert assessment.minimum_interval_seconds == 86400.0
    assert assessment.maximum_interval_seconds == 86400.0
    assert assessment.annualization_eligible is False


def test_declaration_does_not_remove_small_sample_ambiguity() -> None:
    assessment = assess_sampling(
        _series(
            ["2026-01-01", "2026-01-02"],
            sampling=SamplingSpec(
                status=FrequencyStatus.DECLARED,
                declared_frequency="D",
                periods_per_year=365,
            ),
        )
    )

    assert assessment.status is FrequencyStatus.AMBIGUOUS
    assert assessment.declared_frequency == "D"
    assert assessment.annualization_eligible is False


def test_regular_daily_frequency_is_inferred() -> None:
    assessment = assess_sampling(
        _series(
            [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
            ]
        )
    )

    assert assessment.status is FrequencyStatus.INFERRED_REGULAR
    assert assessment.inferred_frequency == "D"
    assert assessment.annualization_eligible is False


def test_inferred_regular_frequency_with_scale_is_eligible() -> None:
    assessment = assess_sampling(
        _series(
            [
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
            ],
            sampling=SamplingSpec(periods_per_year=365),
        )
    )

    assert assessment.periods_per_year == 365
    assert assessment.annualization_eligible is True


def test_irregular_frequency_is_reported_with_interval_range() -> None:
    assessment = assess_sampling(
        _series(
            [
                "2026-01-01",
                "2026-01-02",
                "2026-01-04",
            ]
        )
    )

    assert assessment.status is FrequencyStatus.IRREGULAR
    assert assessment.inferred_frequency is None
    assert assessment.minimum_interval_seconds == 86400.0
    assert assessment.maximum_interval_seconds == 172800.0
    assert assessment.annualization_eligible is False


def test_matching_declared_business_frequency_is_confirmed() -> None:
    assessment = assess_sampling(
        _series(
            [
                "2026-01-02",
                "2026-01-05",
                "2026-01-06",
            ],
            sampling=SamplingSpec(
                status=FrequencyStatus.DECLARED,
                declared_frequency="B",
                periods_per_year=252,
            ),
        )
    )

    assert assessment.status is FrequencyStatus.DECLARED
    assert assessment.declared_frequency == "B"
    assert assessment.inferred_frequency == "B"
    assert assessment.annualization_eligible is True


def test_conflicting_declared_frequency_is_rejected() -> None:
    assessment = assess_sampling(
        _series(
            [
                "2026-01-02",
                "2026-01-05",
                "2026-01-06",
            ],
            sampling=SamplingSpec(
                status=FrequencyStatus.DECLARED,
                declared_frequency="D",
                periods_per_year=365,
            ),
        )
    )

    assert assessment.status is FrequencyStatus.DECLARED_CONFLICT
    assert assessment.annualization_eligible is False


def test_calendar_verification_does_not_bypass_the_observation_guard() -> None:
    """Declaring a calendar must not turn a working audit into a failure.

    A single observation trivially verifies against a 24/7 calendar, because
    the expected date range is built from the observed dates themselves. The
    CALENDAR_VERIFIED short circuit skipped _determine_frequency_status, whose
    first rule returns AMBIGUOUS below three timestamps, so
    annualization_eligible became True at n = 1 and the annualized statistics
    then raised. The same file audited cleanly without --observation-calendar.
    """

    import pandas as pd

    from backtest_auditor.domain.enums import (
        ObservationCalendarSource,
        ObservationCalendarStatus,
        ReturnConvention,
    )
    from backtest_auditor.domain.results import ObservationCalendarAssessmentResult
    from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
    from backtest_auditor.statistics.sampling import assess_sampling

    verified = ObservationCalendarAssessmentResult(
        status=ObservationCalendarStatus.VERIFIED,
        calendar_name="24/7",
        source=ObservationCalendarSource.BUILT_IN_24_7,
        calendar_timezone="UTC",
        timestamp_timezone=None,
        observation_count=1,
        observed_session_count=1,
        expected_session_count=1,
        missing_session_dates=(),
        unexpected_session_dates=(),
    )
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=1, freq="D"),
        values=np.asarray([0.01]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency=None, periods_per_year=252),
    )

    assessment = assess_sampling(series, calendar_assessment=verified)

    assert assessment.annualization_eligible is False
