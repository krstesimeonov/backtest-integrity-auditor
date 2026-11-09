import pytest

from backtest_auditor.audit.checks import (
    generate_sampling_findings,
)
from backtest_auditor.domain.enums import FrequencyStatus
from backtest_auditor.domain.results import (
    SamplingAssessmentResult,
)


def _assessment(
    status: FrequencyStatus,
    *,
    periods_per_year: int | None = None,
) -> SamplingAssessmentResult:
    return SamplingAssessmentResult(
        status=status,
        observation_count=3,
        interval_count=2,
        declared_frequency=(
            "D"
            if status
            in {
                FrequencyStatus.DECLARED,
                FrequencyStatus.DECLARED_CONFLICT,
            }
            else None
        ),
        inferred_frequency=(
            "D"
            if status
            in {
                FrequencyStatus.DECLARED,
                FrequencyStatus.INFERRED_REGULAR,
            }
            else None
        ),
        periods_per_year=periods_per_year,
        minimum_interval_seconds=86400.0,
        maximum_interval_seconds=86400.0,
        annualization_eligible=(
            periods_per_year is not None
            and status
            in {
                FrequencyStatus.DECLARED,
                FrequencyStatus.INFERRED_REGULAR,
            }
        ),
    )


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (
            FrequencyStatus.AMBIGUOUS,
            "AMBIGUOUS_SAMPLING_FREQUENCY",
        ),
        (
            FrequencyStatus.IRREGULAR,
            "IRREGULAR_SAMPLING_FREQUENCY",
        ),
        (
            FrequencyStatus.DECLARED_CONFLICT,
            "DECLARED_FREQUENCY_CONFLICT",
        ),
    ],
)
def test_ineligible_sampling_status_generates_finding(
    status: FrequencyStatus,
    expected_code: str,
) -> None:
    findings = generate_sampling_findings(_assessment(status, periods_per_year=252))

    assert [finding.code for finding in findings] == [expected_code]


def test_regular_sampling_without_scale_generates_finding() -> None:
    findings = generate_sampling_findings(_assessment(FrequencyStatus.INFERRED_REGULAR))

    assert [finding.code for finding in findings] == ["PERIODS_PER_YEAR_NOT_DECLARED"]


def test_eligible_sampling_generates_no_finding() -> None:
    findings = generate_sampling_findings(
        _assessment(
            FrequencyStatus.INFERRED_REGULAR,
            periods_per_year=252,
        )
    )

    assert findings == ()
