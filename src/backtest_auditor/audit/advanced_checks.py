from backtest_auditor.domain.enums import (
    AdvancedRiskStatus,
    BenchmarkInferenceStatus,
    DataSnoopingStatus,
    PairedSeriesStatus,
)
from backtest_auditor.domain.findings import AuditFinding, FindingCategory
from backtest_auditor.domain.results import (
    AdvancedRiskStatisticsResult,
    BenchmarkAlphaInferenceResult,
    DataSnoopingResult,
    GrossNetCostDragResult,
    RegimeAnalysisResult,
    RiskFreeSeriesResult,
)


def generate_advanced_single_run_findings(
    advanced_risk: AdvancedRiskStatisticsResult | None,
    risk_free: RiskFreeSeriesResult | None,
    cost_drag: GrossNetCostDragResult | None,
    regimes: RegimeAnalysisResult | None,
    benchmark_inference: BenchmarkAlphaInferenceResult | None,
) -> tuple[AuditFinding, ...]:
    findings: list[AuditFinding] = []
    if (
        advanced_risk is not None
        and advanced_risk.status is AdvancedRiskStatus.DOWNSIDE_DEVIATION_ZERO
    ):
        findings.append(
            AuditFinding(
                code="DOWNSIDE_DEVIATION_ZERO",
                category=FindingCategory.STATISTICAL_EVIDENCE,
                claim="No observation fell below the declared minimum acceptable return.",
                implication="Sortino and Omega denominators cannot provide finite downside discrimination.",
                remediation="Preserve the result as undefined; do not substitute an arbitrary large ratio.",
            )
        )
    if (
        risk_free is not None
        and risk_free.alignment.status is PairedSeriesStatus.TIMESTAMP_MISMATCH
    ):
        findings.append(
            AuditFinding(
                code="RISK_FREE_TIMESTAMP_MISMATCH",
                category=FindingCategory.DATA_QUALITY,
                claim="The time-varying risk-free series does not exactly align with strategy returns.",
                implication="Excess-return evidence is withheld rather than inner-joined.",
                remediation="Supply exactly one risk-free observation for every strategy timestamp.",
            )
        )
    if cost_drag is not None:
        if cost_drag.alignment.status is PairedSeriesStatus.TIMESTAMP_MISMATCH:
            findings.append(
                AuditFinding(
                    code="GROSS_NET_TIMESTAMP_MISMATCH",
                    category=FindingCategory.DATA_QUALITY,
                    claim="Gross and net return timestamps do not exactly align.",
                    implication="Realized cost-drag evidence is withheld.",
                    remediation="Supply one gross return for every net return timestamp.",
                )
            )
        elif (cost_drag.periods_with_negative_cost_drag or 0) > 0:
            findings.append(
                AuditFinding(
                    code="NEGATIVE_REPORTED_COST_DRAG",
                    category=FindingCategory.METHODOLOGICAL_RISK,
                    claim="Net return exceeds gross return in at least one period.",
                    implication="The paired series may include rebates, inconsistent valuation, or mislabeled cost bases.",
                    remediation="Reconcile gross/net construction and document any legitimate negative costs.",
                )
            )
    if regimes is not None and regimes.status is PairedSeriesStatus.TIMESTAMP_MISMATCH:
        findings.append(
            AuditFinding(
                code="REGIME_TIMESTAMP_MISMATCH",
                category=FindingCategory.DATA_QUALITY,
                claim="Externally declared regime labels do not exactly align with returns.",
                implication="Conditional regime statistics are withheld.",
                remediation="Supply exactly one non-empty regime label per strategy timestamp.",
            )
        )
    if benchmark_inference is not None:
        if benchmark_inference.status is not BenchmarkInferenceStatus.ELIGIBLE:
            findings.append(
                AuditFinding(
                    code="BENCHMARK_ALPHA_HAC_INFERENCE_UNAVAILABLE",
                    category=FindingCategory.STATISTICAL_EVIDENCE,
                    claim="The configured HAC alpha inference is unavailable.",
                    implication=f"Inference status is {benchmark_inference.status.value}.",
                    remediation="Resolve benchmark alignment, sample size, or regression-design eligibility.",
                )
            )
        elif benchmark_inference.statistically_different_from_zero is False:
            findings.append(
                AuditFinding(
                    code="BENCHMARK_ALPHA_NOT_DIFFERENT_FROM_ZERO",
                    category=FindingCategory.STATISTICAL_EVIDENCE,
                    claim="HAC inference does not reject zero benchmark alpha at the declared confidence level.",
                    implication="The observed alpha is not statistically distinguished from sampling variation under this specification.",
                    remediation="Do not present the point alpha as established benchmark-relative skill.",
                )
            )
    return tuple(findings)


def generate_data_snooping_findings(
    result: DataSnoopingResult | None,
) -> tuple[AuditFinding, ...]:
    if result is None:
        return ()
    if result.status is not DataSnoopingStatus.ELIGIBLE:
        return (
            AuditFinding(
                code="DATA_SNOOPING_TESTS_UNAVAILABLE",
                category=FindingCategory.SELECTION_BIAS,
                claim="White Reality Check and Hansen SPA are unavailable.",
                implication=f"Data-snooping status is {result.status.value}.",
                remediation="Supply a complete eligible family and exactly aligned benchmark with enough observations.",
            ),
        )
    findings: list[AuditFinding] = []
    if result.white_reality_check_rejects_null is False:
        findings.append(
            AuditFinding(
                code="WHITE_REALITY_CHECK_NULL_NOT_REJECTED",
                category=FindingCategory.SELECTION_BIAS,
                claim="White's Reality Check does not reject that the best trial lacks benchmark superiority.",
                implication="The observed winner can be consistent with data-snooping variation across the tested family.",
                remediation="Treat superiority as unestablished under the declared bootstrap specification.",
            )
        )
    if result.hansen_spa_rejects_null is False:
        findings.append(
            AuditFinding(
                code="HANSEN_SPA_NULL_NOT_REJECTED",
                category=FindingCategory.SELECTION_BIAS,
                claim="Hansen's SPA test does not reject the no-superior-alternative null.",
                implication="Studentization and consistent recentering still do not establish benchmark superiority.",
                remediation="Treat the selected trial's superiority as statistically unestablished.",
            )
        )
    return tuple(findings)
