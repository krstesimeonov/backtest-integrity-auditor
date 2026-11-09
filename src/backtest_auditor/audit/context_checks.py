import math

import numpy as np

from backtest_auditor.domain.enums import (
    BenchmarkAlignmentStatus,
    ObservationCalendarStatus,
    ReturnCostBasis,
    SeriesRole,
)
from backtest_auditor.domain.findings import (
    AuditFinding,
    FindingCategory,
)
from backtest_auditor.domain.results import (
    BenchmarkAlignmentResult,
    BenchmarkComparisonResult,
    ObservationCalendarAssessmentResult,
    PerformancePathResult,
    ReturnConstructionAssessmentResult,
)
from backtest_auditor.domain.series import ReturnSeries

# Mean absolute return above which percent units are the likelier reading of
# a daily or faster series (night 3, F04: about 100 % annualized volatility).
# Slower sampling scales it with the square root of the median interval in
# days, as volatility scales: about 0.13 weekly and 0.28 monthly.
PERCENT_UNITS_MEAN_ABSOLUTE_RETURN = 0.05


def generate_calendar_findings(
    assessment: ObservationCalendarAssessmentResult | None,
    *,
    role: SeriesRole,
) -> tuple[AuditFinding, ...]:
    prefix = _prefix(role)
    subject = role.value

    if assessment is None:
        return (
            AuditFinding(
                code=f"{prefix}OBSERVATION_CALENDAR_NOT_DECLARED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    f"No observation calendar was declared for the "
                    f"{subject} return series."
                ),
                implication=(
                    "Generic timestamp regularity cannot distinguish "
                    "valid exchange holidays from missing observations."
                ),
                remediation=(
                    "Declare a calendar and timezone; provide an "
                    "authoritative session file for named exchanges."
                ),
            ),
        )

    findings: list[AuditFinding] = []
    if assessment.timestamp_timezone is None:
        findings.append(
            AuditFinding(
                code=f"{prefix}TIMESTAMP_TIMEZONE_NOT_DECLARED",
                category=FindingCategory.DATA_QUALITY,
                claim=(f"The {subject} timestamps have no declared source timezone."),
                implication=(
                    "Mapping timestamps to local calendar sessions may be "
                    "ambiguous near date boundaries."
                ),
                remediation=(
                    "Declare the IANA timezone in which naive input "
                    "timestamps should be interpreted."
                ),
            )
        )

    status_finding = {
        ObservationCalendarStatus.DECLARED_UNVERIFIED: AuditFinding(
            code=f"{prefix}OBSERVATION_CALENDAR_UNVERIFIED",
            category=FindingCategory.METHODOLOGICAL_RISK,
            claim=(
                f"Calendar {assessment.calendar_name!r} was declared for "
                f"the {subject} series without verifiable sessions."
            ),
            implication=(
                "The auditor preserves the declaration but cannot verify "
                "missing or unexpected market sessions."
            ),
            remediation=(
                "Supply an authoritative, strictly ordered session-date "
                "CSV for this calendar."
            ),
        ),
        ObservationCalendarStatus.MISMATCH: AuditFinding(
            code=f"{prefix}OBSERVATION_CALENDAR_MISMATCH",
            category=FindingCategory.DATA_QUALITY,
            claim=(
                f"The {subject} observations do not match the declared "
                "calendar sessions."
            ),
            implication=(
                "Missing or unexpected sessions make annualization and "
                "path comparisons potentially misleading."
            ),
            remediation=(
                "Inspect the reported missing and unexpected dates, then "
                "repair the returns or calendar schedule."
            ),
        ),
        ObservationCalendarStatus.INTRADAY_UNSUPPORTED: AuditFinding(
            code=f"{prefix}INTRADAY_CALENDAR_VERIFICATION_UNSUPPORTED",
            category=FindingCategory.METHODOLOGICAL_RISK,
            claim=(
                f"The {subject} series contains multiple observations on "
                "at least one local session date."
            ),
            implication=(
                "A daily session list cannot verify intraday bar boundaries "
                "or exchange open/close semantics."
            ),
            remediation=(
                "Use one observation per session or defer intraday calendar "
                "verification until an explicit bar schedule is supported."
            ),
        ),
    }.get(assessment.status)
    if status_finding is not None:
        findings.append(status_finding)
    return tuple(findings)


def generate_return_construction_findings(
    assessment: ReturnConstructionAssessmentResult,
) -> tuple[AuditFinding, ...]:
    role = assessment.role
    prefix = _prefix(role)
    subject = role.value

    if not assessment.supplied:
        return (
            AuditFinding(
                code=f"{prefix}RETURN_CONSTRUCTION_METADATA_NOT_SUPPLIED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    f"No return-construction metadata was supplied for the "
                    f"{subject} series."
                ),
                implication=(
                    "The economic meaning, provenance, and leakage controls "
                    "behind the reported returns cannot be assessed."
                ),
                remediation=(
                    "Declare cost treatment, leverage, currency, price "
                    "adjustment, data provenance, stale/delisting treatment, "
                    "bias controls, and timing."
                ),
            ),
        )

    findings: list[AuditFinding] = []
    if assessment.cost_basis in {
        ReturnCostBasis.UNDECLARED,
        ReturnCostBasis.PARTIALLY_DECLARED,
        ReturnCostBasis.MIXED,
    }:
        findings.append(
            _missing_finding(
                f"{prefix}RETURN_COST_BASIS_INCOMPLETE",
                subject,
                "transaction-cost and fee inclusion",
                "gross-versus-net performance is not comparable",
            )
        )
    if assessment.leverage_policy is None:
        findings.append(
            _missing_finding(
                f"{prefix}LEVERAGE_POLICY_NOT_DECLARED",
                subject,
                "leverage policy",
                "returns cannot be separated from leverage choice",
            )
        )
    if assessment.currency is None:
        findings.append(
            _missing_finding(
                f"{prefix}RETURN_CURRENCY_NOT_DECLARED",
                subject,
                "return currency",
                "cross-currency effects cannot be identified",
            )
        )
    if assessment.price_adjustment_policy is None:
        findings.append(
            _missing_finding(
                f"{prefix}PRICE_ADJUSTMENT_POLICY_NOT_DECLARED",
                subject,
                "price adjustment policy",
                "splits and distributions may be handled inconsistently",
            )
        )
    if assessment.data_source is None or assessment.data_vintage is None:
        findings.append(
            _missing_finding(
                f"{prefix}DATA_PROVENANCE_INCOMPLETE",
                subject,
                "data source and vintage",
                "the historical information set is not reproducible",
            )
        )
    if assessment.stale_price_policy is None:
        findings.append(
            _missing_finding(
                f"{prefix}STALE_PRICE_POLICY_NOT_DECLARED",
                subject,
                "stale-price detection and treatment",
                "smoothed or repeated prices may understate risk",
            )
        )
    if assessment.delisting_return_policy is None:
        findings.append(
            _missing_finding(
                f"{prefix}DELISTING_RETURN_POLICY_NOT_DECLARED",
                subject,
                "delisting-return treatment",
                "terminal losses may be excluded from the return path",
            )
        )

    findings.extend(_bias_control_findings(assessment, prefix=prefix, subject=subject))
    if assessment.signal_timing is None or assessment.execution_timing is None:
        findings.append(
            _missing_finding(
                f"{prefix}SIGNAL_EXECUTION_TIMING_INCOMPLETE",
                subject,
                "signal and execution timing",
                "same-bar look-ahead and execution lag cannot be checked",
            )
        )
    return tuple(findings)


def generate_benchmark_comparability_findings(
    strategy: ReturnConstructionAssessmentResult,
    benchmark: ReturnConstructionAssessmentResult | None,
) -> tuple[AuditFinding, ...]:
    if benchmark is None:
        return ()

    findings: list[AuditFinding] = []
    if (
        strategy.currency is not None
        and benchmark.currency is not None
        and strategy.currency != benchmark.currency
    ):
        findings.append(
            AuditFinding(
                code="BENCHMARK_CURRENCY_MISMATCH",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim="Strategy and benchmark returns use different currencies.",
                implication=(
                    "Active returns combine market performance with an "
                    "unisolated currency exposure."
                ),
                remediation=(
                    "Supply both series in the same currency or provide an "
                    "explicit currency-hedging transformation."
                ),
            )
        )
    comparable_bases = {
        ReturnCostBasis.GROSS,
        ReturnCostBasis.NET_OF_TRANSACTION_COSTS,
        ReturnCostBasis.NET_OF_ALL_DECLARED_COSTS,
    }
    if (
        strategy.cost_basis in comparable_bases
        and benchmark.cost_basis in comparable_bases
        and strategy.cost_basis != benchmark.cost_basis
    ):
        findings.append(
            AuditFinding(
                code="BENCHMARK_COST_BASIS_MISMATCH",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "Strategy and benchmark returns use different cost inclusion bases."
                ),
                implication=(
                    "Reported active performance mixes investment results "
                    "with inconsistent cost treatment."
                ),
                remediation=(
                    "Reconstruct both series on a comparable gross or net "
                    "basis before interpreting relative metrics."
                ),
            )
        )
    return tuple(findings)


def generate_return_magnitude_findings(
    series: ReturnSeries,
) -> tuple[AuditFinding, ...]:
    """Warn when return magnitudes read more naturally as percent than decimals.

    The Sharpe ratio is scale-free, so percent input (1.5 = 1.5 %) passes every
    other check while each compounded figure treats 1.5 as 150 %.
    """

    if len(series.values) < 3:
        return ()
    intervals = (series.timestamps[1:] - series.timestamps[:-1]).total_seconds()
    interval_days = float(np.median(np.asarray(intervals, dtype=float))) / 86_400.0
    threshold = PERCENT_UNITS_MEAN_ABSOLUTE_RETURN * math.sqrt(max(interval_days, 1.0))
    mean_absolute = float(np.mean(np.abs(series.values)))
    if not mean_absolute > threshold:
        return ()
    return (
        AuditFinding(
            code="RETURN_MAGNITUDE_SUGGESTS_PERCENT_UNITS",
            category=FindingCategory.DATA_QUALITY,
            claim=(
                f"The mean absolute return is {mean_absolute:.4g} per period, "
                f"above {threshold:.3g} for a median sampling interval of "
                f"{interval_days:.3g} days; returns are read as decimals "
                "(0.01 = 1 %)."
            ),
            implication=(
                "If the values are percent, every compounded figure (cumulative "
                "return, drawdown, CAGR, the wealth path) is wrong by orders of "
                "magnitude, while the scale-free Sharpe ratio still looks plausible."
            ),
            remediation=(
                "Confirm the return units; divide percent returns by 100 before "
                "auditing."
            ),
        ),
    )


def generate_performance_path_findings(
    result: PerformancePathResult,
) -> tuple[AuditFinding, ...]:
    findings: list[AuditFinding] = []
    if result.ending_wealth is not None and result.ending_wealth <= 0.0:
        findings.append(
            AuditFinding(
                code="CAGR_UNDEFINED_FOR_NON_POSITIVE_WEALTH",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim="The return path ends with non-positive wealth.",
                implication=("A real-valued compound annual growth rate is undefined."),
                remediation=(
                    "Inspect total-loss observations and the return "
                    "construction before interpreting compound growth."
                ),
            )
        )
    if result.maximum_drawdown is not None and result.maximum_drawdown <= -1.0:
        findings.append(
            AuditFinding(
                code="TOTAL_WEALTH_LOSS_OBSERVED",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim="The audited path reaches a 100% drawdown.",
                implication=(
                    "The strategy is economically insolvent at that point; "
                    "subsequent percentage returns cannot restore lost wealth."
                ),
                remediation=(
                    "Verify the observation and treat the strategy path as "
                    "terminated unless external capital is explicitly modeled."
                ),
            )
        )
    return tuple(findings)


def generate_benchmark_findings(
    alignment: BenchmarkAlignmentResult | None,
    comparison: BenchmarkComparisonResult | None,
) -> tuple[AuditFinding, ...]:
    if alignment is None:
        return ()
    if alignment.status is BenchmarkAlignmentStatus.TIMESTAMP_MISMATCH:
        return (
            AuditFinding(
                code="BENCHMARK_TIMESTAMP_MISMATCH",
                category=FindingCategory.DATA_QUALITY,
                claim=("Strategy and benchmark timestamps are not exactly aligned."),
                implication=(
                    "Relative metrics are withheld; silently intersecting "
                    "dates could introduce selection and stale-price bias."
                ),
                remediation=(
                    "Resolve every strategy-only and benchmark-only timestamp "
                    "before re-running the comparison."
                ),
            ),
        )
    if comparison is None:
        return ()

    findings: list[AuditFinding] = []
    if comparison.observation_count < 2:
        findings.append(
            AuditFinding(
                code="INSUFFICIENT_OBSERVATIONS_FOR_BENCHMARK_STATISTICS",
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "Fewer than two aligned strategy and benchmark returns "
                    "were supplied."
                ),
                implication=(
                    "Tracking error, information ratio, correlation, beta, "
                    "and alpha are unavailable."
                ),
                remediation="Provide at least two exactly aligned observations.",
            )
        )
    elif comparison.period_tracking_error == 0.0:
        findings.append(
            AuditFinding(
                code="ZERO_ACTIVE_RETURN_VOLATILITY",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim="All aligned active returns are identical.",
                implication=(
                    "The information ratio is undefined because tracking error is zero."
                ),
                remediation=(
                    "Verify benchmark construction and alignment before "
                    "interpreting relative performance."
                ),
            )
        )
    if comparison.observation_count >= 2 and comparison.beta is None:
        findings.append(
            AuditFinding(
                code="ZERO_BENCHMARK_VARIANCE",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim="The aligned benchmark returns have zero variance.",
                implication="Beta and arithmetic alpha are undefined.",
                remediation=(
                    "Verify that the benchmark series contains genuine "
                    "period returns rather than a constant or stale value."
                ),
            )
        )
    if comparison.relative_wealth_return is None:
        findings.append(
            AuditFinding(
                code="RELATIVE_WEALTH_UNDEFINED",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim="The benchmark path ends with non-positive wealth.",
                implication=(
                    "A strategy-to-benchmark terminal wealth ratio is undefined."
                ),
                remediation="Inspect benchmark total-loss observations.",
            )
        )
    return tuple(findings)


def _bias_control_findings(
    assessment: ReturnConstructionAssessmentResult,
    *,
    prefix: str,
    subject: str,
) -> tuple[AuditFinding, ...]:
    findings: list[AuditFinding] = []
    for attribute, label, code_label in (
        (
            "survivorship_bias_controlled",
            "survivorship-bias control",
            "SURVIVORSHIP_BIAS_CONTROL",
        ),
        (
            "lookahead_bias_controlled",
            "look-ahead-bias control",
            "LOOKAHEAD_BIAS_CONTROL",
        ),
    ):
        value = getattr(assessment, attribute)
        if value is None:
            findings.append(
                _missing_finding(
                    f"{prefix}{code_label}_NOT_DECLARED",
                    subject,
                    label,
                    "the auditor cannot verify that future information was excluded",
                )
            )
        elif value is False:
            findings.append(
                AuditFinding(
                    code=f"{prefix}{code_label}_FAILED",
                    category=FindingCategory.METHODOLOGICAL_RISK,
                    claim=f"The {subject} declares that {label} was not satisfied.",
                    implication=(
                        "Reported performance may contain a material upward bias."
                    ),
                    remediation=(
                        "Repair the data/research process and regenerate returns "
                        "before relying on statistical evidence."
                    ),
                )
            )
    return tuple(findings)


def _missing_finding(
    code: str,
    subject: str,
    missing_evidence: str,
    implication: str,
) -> AuditFinding:
    return AuditFinding(
        code=code,
        category=FindingCategory.METHODOLOGICAL_RISK,
        claim=(
            f"The {subject} return construction does not fully declare "
            f"{missing_evidence}."
        ),
        implication=implication.capitalize() + ".",
        remediation=f"Supply the missing {missing_evidence} declaration.",
    )


def _prefix(role: SeriesRole) -> str:
    return "" if role is SeriesRole.STRATEGY else "BENCHMARK_"
