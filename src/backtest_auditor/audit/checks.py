import math

from backtest_auditor.domain.assumptions import (
    BootstrapSpec,
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
)
from backtest_auditor.domain.enums import (
    BootstrapMetricStatus,
    BootstrapStatus,
    FrequencyStatus,
    SerialAdjustmentStatus,
    SerialDependenceStatus,
)
from backtest_auditor.domain.findings import (
    AuditFinding,
    FindingCategory,
)
from backtest_auditor.domain.results import (
    AnnualizedStatisticsResult,
    BootstrapResult,
    DescriptiveStatisticsResult,
    DistributionStatisticsResult,
    SamplingAssessmentResult,
    SerialAdjustmentResult,
    SerialDependenceResult,
    SharpeUncertaintyResult,
    TrackRecordLengthResult,
)
from backtest_auditor.domain.series import ReturnSeries

# The declared periods per year may differ from the rate the timestamps imply
# by this factor either way before it is reported: 252 for a business-day
# series (about 261 weekdays a year) passes, 252 for a daily 24/7 series
# (365) and 365 for a business-day series do not.
PERIODS_PER_YEAR_TOLERANCE = 1.2
# Shorter spans let one weekend move the implied rate by more than that.
PERIODS_PER_YEAR_MINIMUM_SPAN_DAYS = 28.0
_SECONDS_PER_YEAR = 365.25 * 86_400.0


def generate_sampling_findings(
    assessment: SamplingAssessmentResult,
) -> tuple[AuditFinding, ...]:
    if assessment.status is FrequencyStatus.AMBIGUOUS:
        return (
            AuditFinding(
                code="AMBIGUOUS_SAMPLING_FREQUENCY",
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "The sample contains too few timestamps "
                    "to assess observation frequency."
                ),
                implication=(
                    "Annualized statistics are not eligible "
                    "because sampling regularity is unverified."
                ),
                remediation=("Provide at least three timestamped return observations."),
            ),
        )

    if assessment.status is FrequencyStatus.IRREGULAR:
        return (
            AuditFinding(
                code="IRREGULAR_SAMPLING_FREQUENCY",
                category=FindingCategory.DATA_QUALITY,
                claim=("The timestamps do not form a regular observation sequence."),
                implication=(
                    "A single periods-per-year scale cannot be "
                    "applied safely to annualized statistics."
                ),
                remediation=(
                    "Inspect missing or extra observations and "
                    "supply a regular return series."
                ),
            ),
        )

    if assessment.status is FrequencyStatus.DECLARED_CONFLICT:
        return (
            AuditFinding(
                code="DECLARED_FREQUENCY_CONFLICT",
                category=FindingCategory.DATA_QUALITY,
                claim=(
                    "The observed timestamps do not follow the "
                    "declared sampling frequency."
                ),
                implication=(
                    "Annualization based on the declaration "
                    "would misrepresent the observed sample."
                ),
                remediation=(
                    "Correct the declaration or repair the timestamp sequence."
                ),
            ),
        )

    if assessment.periods_per_year is None:
        return (
            AuditFinding(
                code="PERIODS_PER_YEAR_NOT_DECLARED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "Sampling is regular, but no periods-per-year "
                    "assumption was supplied."
                ),
                implication=(
                    "Annualized statistics remain ineligible; "
                    "regular timestamps alone do not choose a "
                    "financial annualization convention."
                ),
                remediation=(
                    "Supply the intended positive periods-per-year value explicitly."
                ),
            ),
        )

    return ()


def generate_periods_per_year_findings(
    series: ReturnSeries,
    assessment: SamplingAssessmentResult,
) -> tuple[AuditFinding, ...]:
    """Compare the declared periods per year with the rate the timestamps imply.

    The declaration is still used verbatim; this only reports when the two
    disagree by more than PERIODS_PER_YEAR_TOLERANCE, because every annualized
    figure then carries the wrong square-root-of-time factor.
    """

    declared = assessment.periods_per_year
    if not assessment.annualization_eligible or declared is None:
        return ()
    span_seconds = float((series.timestamps[-1] - series.timestamps[0]).total_seconds())
    if (
        assessment.interval_count < 2
        or span_seconds < PERIODS_PER_YEAR_MINIMUM_SPAN_DAYS * 86_400.0
    ):
        return ()
    implied = assessment.interval_count * _SECONDS_PER_YEAR / span_seconds
    ratio = declared / implied
    if 1.0 / PERIODS_PER_YEAR_TOLERANCE <= ratio <= PERIODS_PER_YEAR_TOLERANCE:
        return ()
    return (
        AuditFinding(
            code="PERIODS_PER_YEAR_SAMPLING_MISMATCH",
            category=FindingCategory.METHODOLOGICAL_RISK,
            claim=(
                f"The declared {declared} periods per year differ from the "
                f"{implied:.1f} observations per year the timestamps imply "
                f"({assessment.interval_count} intervals over "
                f"{span_seconds / 86_400.0:.0f} days) by {abs(ratio - 1.0):.0%}."
            ),
            implication=(
                f"Every annualized figure uses {declared}. At the observed rate "
                "the annualized Sharpe ratio and volatility would be "
                f"{math.sqrt(implied / declared):.3f} times the published "
                f"values and the annualized mean {implied / declared:.3f} times."
            ),
            remediation=(
                "Declare the periods per year that matches the sampling: 365 for "
                "a daily 24/7 series, about 252 for exchange sessions, 52 for "
                "weekly and 12 for monthly observations."
            ),
        ),
    )


def generate_basic_statistical_findings(
    statistics: DescriptiveStatisticsResult,
) -> tuple[AuditFinding, ...]:
    findings: list[AuditFinding] = []

    if statistics.sample_volatility is None:
        findings.append(
            AuditFinding(
                code=("INSUFFICIENT_OBSERVATIONS_FOR_SAMPLE_VOLATILITY"),
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "The sample contains too few "
                    "observations to estimate sample volatility."
                ),
                implication=(
                    "Statistics requiring an estimated "
                    "return variance are not eligible."
                ),
                remediation=("Provide at least two valid return observations."),
            )
        )

    elif statistics.sample_volatility == 0.0:
        findings.append(
            AuditFinding(
                code="ZERO_SAMPLE_VOLATILITY",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=("All supplied returns have zero sample variation."),
                implication=(
                    "Risk-adjusted ratios that divide by "
                    "volatility cannot be interpreted normally."
                ),
                remediation=(
                    "Verify the return construction and "
                    "source data before further inference."
                ),
            )
        )

    return tuple(findings)


def generate_serial_dependence_findings(
    annualized: AnnualizedStatisticsResult | None,
    serial_dependence: SerialDependenceResult | None,
    *,
    spec: SerialDependenceSpec | None = None,
) -> tuple[AuditFinding, ...]:
    if spec is None:
        if annualized is None:
            return ()

        return (
            AuditFinding(
                code="SERIAL_DEPENDENCE_DIAGNOSTIC_NOT_CONFIGURED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "Annualized statistics were calculated without "
                    "an explicit serial-dependence diagnostic."
                ),
                implication=(
                    "Square-root-of-time scaling and the current "
                    "Sharpe uncertainty framework rely on IID-style "
                    "assumptions that have not been checked."
                ),
                remediation=(
                    "Supply an explicit maximum lag and significance "
                    "level for the Ljung-Box diagnostic."
                ),
            ),
        )

    if serial_dependence is not None:
        if serial_dependence.status is SerialDependenceStatus.INSUFFICIENT_OBSERVATIONS:
            return (
                AuditFinding(
                    code=("INSUFFICIENT_OBSERVATIONS_FOR_SERIAL_DEPENDENCE"),
                    category=FindingCategory.SAMPLE_SUFFICIENCY,
                    claim=(
                        "The selected maximum lag is not below the "
                        "number of return observations."
                    ),
                    implication=(
                        "Autocorrelations and the Ljung-Box statistic "
                        "cannot be calculated at the requested lag."
                    ),
                    remediation=(
                        "Provide more observations or select a smaller "
                        "positive maximum lag."
                    ),
                ),
            )

        if serial_dependence.status is SerialDependenceStatus.ZERO_VARIANCE:
            return (
                AuditFinding(
                    code=("SERIAL_DEPENDENCE_UNDEFINED_FOR_ZERO_VARIANCE"),
                    category=FindingCategory.STATISTICAL_EVIDENCE,
                    claim=(
                        "Serial dependence is undefined because the "
                        "return series has zero variation."
                    ),
                    implication=(
                        "The sample autocorrelation denominator is "
                        "zero, so the Ljung-Box diagnostic is "
                        "unavailable."
                    ),
                    remediation=(
                        "Verify the return construction and source "
                        "data before interpreting time-series "
                        "behavior."
                    ),
                ),
            )

    dependence_findings: list[AuditFinding] = []
    if serial_dependence is not None and serial_dependence.serial_dependence_detected:
        dependence_findings.append(
            AuditFinding(
                code="SERIAL_DEPENDENCE_DETECTED",
                category=FindingCategory.ROBUSTNESS,
                claim=(
                    "The Ljung-Box test rejects zero autocorrelation "
                    "through the explicitly selected maximum lag."
                ),
                implication=(
                    "Square-root-of-time volatility scaling and the "
                    "current IID-style Sharpe, PSR, and MinTRL "
                    "interpretations may overstate or understate the "
                    "strategy evidence."
                ),
                remediation=(
                    "Inspect the reported lag autocorrelations and "
                    "use a separately specified serial-dependence "
                    "adjustment when interpreting the affected metrics."
                ),
            )
        )

    if serial_dependence is not None and serial_dependence.runs_dependence_detected:
        dependence_findings.append(
            AuditFinding(
                code="RUNS_DEPENDENCE_DETECTED",
                category=FindingCategory.ROBUSTNESS,
                claim="The median-sign runs test rejects sequential independence.",
                implication="Return signs cluster or alternate more than expected under independence.",
                remediation="Inspect the sign sequence alongside ACF, PACF, and HAC evidence.",
            )
        )
    if serial_dependence is not None and any(
        item.dependence_detected is True for item in serial_dependence.variance_ratios
    ):
        dependence_findings.append(
            AuditFinding(
                code="VARIANCE_RATIO_DEPENDENCE_DETECTED",
                category=FindingCategory.ROBUSTNESS,
                claim="At least one heteroskedasticity-robust variance-ratio test rejects the random-walk increment restriction.",
                implication="Multi-period return variance is inconsistent with independent increments at a tested horizon.",
                remediation="Inspect every reported horizon and avoid selecting horizons after seeing their p-values.",
            )
        )

    return tuple(dependence_findings)


def generate_annualized_statistical_findings(
    statistics: AnnualizedStatisticsResult | None,
) -> tuple[AuditFinding, ...]:
    if statistics is not None and statistics.annual_risk_free_rate is None:
        return (
            AuditFinding(
                code="ANNUAL_RISK_FREE_RATE_NOT_SUPPLIED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "Annualized return and volatility were "
                    "calculated without a supplied annual "
                    "risk-free rate."
                ),
                implication=(
                    "The Sharpe ratio remains undefined; "
                    "assuming a zero risk-free rate would be an "
                    "undocumented methodological choice."
                ),
                remediation=(
                    "Supply the intended effective annual risk-free rate explicitly."
                ),
            ),
        )

    return ()


def generate_serial_adjustment_findings(
    serial_dependence: SerialDependenceResult | None,
    adjustment: SerialAdjustmentResult | None,
    *,
    spec: SerialAdjustmentSpec | None = None,
) -> tuple[AuditFinding, ...]:
    if spec is None:
        if (
            serial_dependence is None
            or not serial_dependence.serial_dependence_detected
        ):
            return ()

        return (
            AuditFinding(
                code=("SERIAL_DEPENDENCE_ADJUSTMENT_NOT_CONFIGURED"),
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "Serial dependence was detected, but no HAC "
                    "adjustment bandwidth and kernel were supplied."
                ),
                implication=(
                    "The reported IID-style annualized Sharpe, PSR, "
                    "and MinTRL remain potentially distorted by "
                    "serial dependence."
                ),
                remediation=(
                    "Supply an explicit positive HAC maximum lag "
                    "and supported kernel, then compare the adjusted "
                    "evidence with the IID-style results."
                ),
            ),
        )

    if adjustment is None:
        return ()

    status_findings = {
        SerialAdjustmentStatus.SHARPE_UNAVAILABLE: AuditFinding(
            code="SERIAL_ADJUSTMENT_SHARPE_UNAVAILABLE",
            category=FindingCategory.STATISTICAL_EVIDENCE,
            claim=(
                "The HAC adjustment was configured, but the period "
                "Sharpe ratio is unavailable."
            ),
            implication=(
                "Neither HAC annualization nor HAC-adjusted Sharpe "
                "uncertainty can be calculated."
            ),
            remediation=(
                "Resolve sampling, risk-free-rate, or zero-volatility "
                "issues before applying the adjustment."
            ),
        ),
        SerialAdjustmentStatus.INSUFFICIENT_OBSERVATIONS: AuditFinding(
            code=("INSUFFICIENT_OBSERVATIONS_FOR_SERIAL_ADJUSTMENT"),
            category=FindingCategory.SAMPLE_SUFFICIENCY,
            claim=(
                "The selected HAC maximum lag is not below the "
                "number of return observations."
            ),
            implication=(
                "The requested long-run variance estimates cannot "
                "be calculated at that bandwidth."
            ),
            remediation=(
                "Provide more observations or select a smaller "
                "positive HAC maximum lag."
            ),
        ),
        (SerialAdjustmentStatus.NON_POSITIVE_RETURN_LONG_RUN_VARIANCE): AuditFinding(
            code="NON_POSITIVE_RETURN_LONG_RUN_VARIANCE",
            category=FindingCategory.STATISTICAL_EVIDENCE,
            claim=(
                "The Bartlett-HAC return long-run variance ratio is "
                "not positive and finite."
            ),
            implication=(
                "A real-valued HAC annualization factor and adjusted "
                "annualized Sharpe ratio are unavailable."
            ),
            remediation=(
                "Inspect the return sequence and bandwidth; treat "
                "extreme finite-sample autocorrelations cautiously."
            ),
        ),
        (SerialAdjustmentStatus.SHARPE_UNCERTAINTY_UNAVAILABLE): AuditFinding(
            code="HAC_SHARPE_UNCERTAINTY_UNAVAILABLE",
            category=FindingCategory.SAMPLE_SUFFICIENCY,
            claim=(
                "HAC annualization was calculated, but the base "
                "higher-moment Sharpe uncertainty is unavailable."
            ),
            implication=("HAC-adjusted PSR and MinTRL cannot be calculated."),
            remediation=(
                "Provide at least four valid, varying observations "
                "and resolve the base Sharpe variance estimate."
            ),
        ),
        SerialAdjustmentStatus.ZERO_INFLUENCE_VARIANCE: AuditFinding(
            code="ZERO_SHARPE_INFLUENCE_VARIANCE",
            category=FindingCategory.STATISTICAL_EVIDENCE,
            claim=("The estimated Sharpe influence series has zero variation."),
            implication=(
                "Its autocorrelation and HAC uncertainty adjustment are undefined."
            ),
            remediation=(
                "Inspect the return construction and use later "
                "resampling analysis before interpreting confidence."
            ),
        ),
        (SerialAdjustmentStatus.NON_POSITIVE_SHARPE_LONG_RUN_VARIANCE): AuditFinding(
            code="NON_POSITIVE_SHARPE_LONG_RUN_VARIANCE",
            category=FindingCategory.STATISTICAL_EVIDENCE,
            claim=(
                "The Bartlett-HAC Sharpe long-run variance ratio is "
                "not positive and finite."
            ),
            implication=(
                "HAC-adjusted Sharpe standard error, PSR, and MinTRL are unavailable."
            ),
            remediation=(
                "Inspect the influence-series autocorrelations and "
                "bandwidth; use later resampling analysis as a "
                "robustness check."
            ),
        ),
    }

    if adjustment.status is not SerialAdjustmentStatus.ELIGIBLE:
        finding = status_findings.get(adjustment.status)
        return () if finding is None else (finding,)

    if adjustment.hac_confidence_requirement_met is False:
        additional = adjustment.hac_additional_observations_required
        remediation = (
            "Reassess the strategy evidence or benchmark because "
            "the observed Sharpe does not support a finite adjusted "
            "track-record requirement."
            if additional is None
            else (
                "Collect at least "
                f"{additional} additional observations under an "
                "unchanged strategy and HAC specification, then "
                "re-audit; the estimate remains conditional."
            )
        )
        return (
            AuditFinding(
                code="HAC_PSR_CONFIDENCE_REQUIREMENT_NOT_MET",
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "The HAC-adjusted Probabilistic Sharpe Ratio is "
                    "below the explicitly required confidence level."
                ),
                implication=(
                    "After accounting for serial dependence through "
                    "the selected bandwidth, the track record does "
                    "not satisfy the evidence requirement."
                ),
                remediation=remediation,
            ),
        )

    return ()


def generate_sharpe_uncertainty_findings(
    annualized: AnnualizedStatisticsResult | None,
    distribution: DistributionStatisticsResult,
    uncertainty: SharpeUncertaintyResult | None,
    *,
    psr_spec: ProbabilisticSharpeRatioSpec | None = None,
) -> tuple[AuditFinding, ...]:
    if annualized is None or annualized.annualized_sharpe_ratio is None:
        return ()

    if (
        distribution.sample_skewness is None
        or distribution.sample_pearson_kurtosis is None
    ):
        return (
            AuditFinding(
                code=("INSUFFICIENT_OBSERVATIONS_FOR_SHARPE_UNCERTAINTY"),
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "At least four varying returns are required "
                    "to estimate both sample skewness and "
                    "sample kurtosis."
                ),
                implication=(
                    "The higher-moment-adjusted Sharpe standard "
                    "error and Probabilistic Sharpe Ratio are "
                    "not eligible."
                ),
                remediation=(
                    "Provide at least four valid, varying return observations."
                ),
            ),
        )

    if uncertainty is not None and uncertainty.period_sharpe_standard_error is None:
        return (
            AuditFinding(
                code="NON_POSITIVE_SHARPE_VARIANCE_ESTIMATE",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    "The higher-moment Sharpe variance estimate "
                    "is not positive and finite."
                ),
                implication=(
                    "Sharpe uncertainty and PSR cannot be "
                    "interpreted from this asymptotic formula."
                ),
                remediation=(
                    "Inspect the return distribution and use a "
                    "later robust or resampling-based analysis."
                ),
            ),
        )

    if uncertainty is not None and psr_spec is None:
        return (
            AuditFinding(
                code="ANNUALIZED_SHARPE_BENCHMARK_NOT_SUPPLIED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "Sharpe uncertainty was estimated without an "
                    "explicit annualized Sharpe benchmark."
                ),
                implication=(
                    "The Probabilistic Sharpe Ratio remains "
                    "undefined; assuming a zero benchmark would "
                    "be an undocumented methodological choice."
                ),
                remediation=(
                    "Supply the annualized Sharpe ratio benchmark "
                    "that the strategy must exceed."
                ),
            ),
        )

    return ()


def generate_track_record_findings(
    uncertainty: SharpeUncertaintyResult | None,
    track_record: TrackRecordLengthResult | None,
    *,
    psr_spec: ProbabilisticSharpeRatioSpec | None = None,
) -> tuple[AuditFinding, ...]:
    if uncertainty is None or uncertainty.probabilistic_sharpe_ratio is None:
        return ()

    if psr_spec is not None and psr_spec.required_psr_confidence_level is None:
        return (
            AuditFinding(
                code="PSR_CONFIDENCE_LEVEL_NOT_SUPPLIED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "PSR was calculated without an explicit confidence requirement."
                ),
                implication=(
                    "The auditor cannot determine whether the "
                    "track record satisfies the intended evidence "
                    "standard or estimate its minimum required length."
                ),
                remediation=(
                    "Supply a required PSR confidence level strictly "
                    "between 0.5 and 1.0."
                ),
            ),
        )

    if track_record is None:
        return ()

    if track_record.observed_period_sharpe_difference <= 0.0:
        return (
            AuditFinding(
                code="OBSERVED_SHARPE_NOT_ABOVE_BENCHMARK",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    "The observed Sharpe ratio does not exceed the "
                    "selected Sharpe benchmark."
                ),
                implication=(
                    "No finite track-record length can achieve a PSR "
                    "confidence above 0.5 if the estimated Sharpe and "
                    "distribution characteristics remain unchanged."
                ),
                remediation=(
                    "Reassess the strategy evidence or justify a "
                    "different benchmark independently of this result."
                ),
            ),
        )

    if track_record.minimum_required_observations is None:
        return (
            AuditFinding(
                code="NON_FINITE_MINIMUM_TRACK_RECORD_LENGTH",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    "The minimum track-record length estimate is not "
                    "finite under the supplied evidence requirement."
                ),
                implication=(
                    "A usable observation requirement cannot be "
                    "reported from the asymptotic formula."
                ),
                remediation=(
                    "Inspect the Sharpe-to-benchmark difference and "
                    "use a later robust or resampling-based analysis."
                ),
            ),
        )

    if not track_record.confidence_requirement_met:
        additional = track_record.additional_observations_required
        return (
            AuditFinding(
                code="PSR_CONFIDENCE_REQUIREMENT_NOT_MET",
                category=FindingCategory.SAMPLE_SUFFICIENCY,
                claim=(
                    "The IID-style observed Probabilistic Sharpe "
                    "Ratio is below the explicitly required "
                    "confidence level."
                ),
                implication=(
                    "Under the base IID-style uncertainty framework, "
                    "the current track record does not yet satisfy "
                    "the selected evidence requirement."
                ),
                remediation=(
                    "Collect at least "
                    f"{additional} additional observations under an "
                    "unchanged strategy and methodology, then "
                    "re-audit; this IID-style estimate is conditional, "
                    "not a guarantee."
                ),
            ),
        )

    return ()


def generate_bootstrap_findings(
    sampling: SamplingAssessmentResult,
    bootstrap: BootstrapResult | None,
    *,
    spec: BootstrapSpec | None = None,
) -> tuple[AuditFinding, ...]:
    regular_sampling = sampling.status in {
        FrequencyStatus.DECLARED,
        FrequencyStatus.INFERRED_REGULAR,
        FrequencyStatus.CALENDAR_VERIFIED,
    }

    if spec is None:
        if not regular_sampling:
            return ()

        return (
            AuditFinding(
                code="BOOTSTRAP_ANALYSIS_NOT_CONFIGURED",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=(
                    "The regular return series was audited without an "
                    "explicit bootstrap specification."
                ),
                implication=(
                    "Resampling-based uncertainty intervals are "
                    "unavailable, so the report relies on point and "
                    "asymptotic evidence."
                ),
                remediation=(
                    "Supply the bootstrap method, interval method, "
                    "replication count, confidence level, block length, "
                    "and random seed explicitly."
                ),
            ),
        )

    if bootstrap is None:
        return ()

    status_findings = {
        BootstrapStatus.SAMPLING_INELIGIBLE: AuditFinding(
            code="BOOTSTRAP_SAMPLING_INELIGIBLE",
            category=FindingCategory.DATA_QUALITY,
            claim=(
                "The configured dependent-data bootstrap does not have a "
                "regular observation sequence."
            ),
            implication=(
                "Consecutive index blocks cannot be interpreted as "
                "equal spans of time, so confidence intervals were not "
                "calculated."
            ),
            remediation=(
                "Repair or explicitly declare a regular sampling "
                "schedule before resampling the return sequence."
            ),
        ),
        BootstrapStatus.INSUFFICIENT_OBSERVATIONS: AuditFinding(
            code="INSUFFICIENT_OBSERVATIONS_FOR_BOOTSTRAP",
            category=FindingCategory.SAMPLE_SUFFICIENCY,
            claim=(
                "At least two observations are required for the "
                "configured bootstrap statistics."
            ),
            implication=(
                "A bootstrap distribution and sample volatility cannot be estimated."
            ),
            remediation="Provide at least two regular observations.",
        ),
        (BootstrapStatus.BLOCK_LENGTH_NOT_BELOW_OBSERVATION_COUNT): AuditFinding(
            code="BOOTSTRAP_BLOCK_LENGTH_NOT_BELOW_SAMPLE_SIZE",
            category=FindingCategory.METHODOLOGICAL_RISK,
            claim=(
                "The configured block length is not below the return observation count."
            ),
            implication=(
                "There is no set of distinct overlapping blocks from "
                "which to construct a useful bootstrap distribution."
            ),
            remediation=(
                "Choose a positive block length strictly below the observation count."
            ),
        ),
    }

    if bootstrap.status is not BootstrapStatus.ELIGIBLE:
        finding = status_findings.get(bootstrap.status)
        return () if finding is None else (finding,)

    findings: list[AuditFinding] = []
    if bootstrap.replications < 1_000:
        findings.append(
            AuditFinding(
                code="LOW_BOOTSTRAP_REPLICATION_COUNT",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=("The bootstrap uses fewer than 1,000 replications."),
                implication=(
                    "Estimated interval endpoints may have substantial "
                    "Monte Carlo variation."
                ),
                remediation=(
                    "Increase the explicit replication count and retain "
                    "the seed so the analysis remains reproducible."
                ),
            )
        )

    if bootstrap.block_length == 1:
        findings.append(
            AuditFinding(
                code="BOOTSTRAP_BLOCK_LENGTH_ONE",
                category=FindingCategory.METHODOLOGICAL_RISK,
                claim=("The configured bootstrap uses a block length of one."),
                implication=(
                    "This is equivalent to an IID bootstrap and does "
                    "not preserve observed serial dependence."
                ),
                remediation=(
                    "Choose and justify a block length greater than one "
                    "when serial dependence must be preserved."
                ),
            )
        )

    unavailable_metrics = [
        metric.metric.value
        for metric in bootstrap.metrics
        if metric.status is BootstrapMetricStatus.INSUFFICIENT_VALID_REPLICATIONS
    ]
    if unavailable_metrics:
        findings.append(
            AuditFinding(
                code="INSUFFICIENT_VALID_BOOTSTRAP_REPLICATIONS",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim=(
                    "Fewer than two valid bootstrap estimates were "
                    "available for: " + ", ".join(unavailable_metrics) + "."
                ),
                implication=(
                    "Those confidence intervals and bootstrap standard "
                    "errors are undefined."
                ),
                remediation=(
                    "Inspect degenerate resamples, the selected block "
                    "length, and any non-positive HAC variance ratios."
                ),
            )
        )

    partially_valid_metrics = [
        metric.metric.value
        for metric in bootstrap.metrics
        if (
            metric.status is BootstrapMetricStatus.ELIGIBLE
            and metric.successful_replications < metric.attempted_replications
        )
    ]
    if partially_valid_metrics:
        findings.append(
            AuditFinding(
                code="BOOTSTRAP_REPLICATIONS_DROPPED",
                category=FindingCategory.ROBUSTNESS,
                claim=(
                    "Some non-finite or undefined replication estimates "
                    "were excluded for: " + ", ".join(partially_valid_metrics) + "."
                ),
                implication=(
                    "The reported intervals condition on successful "
                    "replications and may be sensitive to the configured "
                    "bootstrap or HAC choices."
                ),
                remediation=(
                    "Review the successful-replication counts and test "
                    "reasonable alternative block or HAC bandwidths."
                ),
            )
        )

    return tuple(findings)
