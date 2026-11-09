from dataclasses import dataclass

from backtest_auditor import REPORT_SCHEMA_VERSION
from backtest_auditor.application.run_manifest import (
    build_experiment_family_manifest,
    canonical_configuration,
)
from backtest_auditor.audit.evidence_profile import (
    build_experiment_family_evidence_profile,
)
from backtest_auditor.audit.advanced_checks import generate_data_snooping_findings

from backtest_auditor.audit.family_checks import (
    generate_experiment_family_findings,
)
from backtest_auditor.audit.family_methodology import (
    assess_experiment_family,
)
from backtest_auditor.domain.assumptions import (
    CSCVSpec,
    DeflatedSharpeRatioSpec,
    DataSnoopingSpec,
    ParameterRobustnessSpec,
    TemporalRobustnessSpec,
)
from backtest_auditor.domain.experiment import ExperimentFamily
from backtest_auditor.domain.evidence import EvidenceProfileResult
from backtest_auditor.domain.findings import AuditFinding
from backtest_auditor.domain.issues import ValidationIssue
from backtest_auditor.domain.reproducibility import (
    AuditRunManifestResult,
    AuditRunSpec,
    InputArtifactHash,
)
from backtest_auditor.domain.results import (
    CSCVResult,
    DeflatedSharpeRatioResult,
    DataSnoopingResult,
    ExperimentFamilyAssessmentResult,
    ExperimentSplitAssessmentResult,
    ExperimentTrialAssessmentResult,
    ParameterRobustnessResult,
    TemporalRobustnessResult,
)
from backtest_auditor.statistics.cscv import calculate_cscv
from backtest_auditor.statistics.deflated_sharpe import (
    calculate_deflated_sharpe_ratio,
)
from backtest_auditor.statistics.data_snooping import calculate_data_snooping_tests
from backtest_auditor.statistics.parameter_robustness import (
    calculate_parameter_robustness,
)
from backtest_auditor.statistics.temporal_robustness import (
    calculate_temporal_robustness,
)


@dataclass(frozen=True, slots=True)
class ExperimentFamilyAuditResult:
    family_id: str
    assessment: ExperimentFamilyAssessmentResult
    trials: tuple[ExperimentTrialAssessmentResult, ...]
    splits: tuple[ExperimentSplitAssessmentResult, ...]
    deflated_sharpe_ratio: DeflatedSharpeRatioResult | None
    cscv: CSCVResult | None
    parameter_robustness: ParameterRobustnessResult | None
    temporal_robustness: TemporalRobustnessResult | None
    data_snooping: DataSnoopingResult | None
    evidence_profile: EvidenceProfileResult
    run_manifest: AuditRunManifestResult | None
    findings: tuple[AuditFinding, ...]
    input_issues: tuple[ValidationIssue, ...] = ()


def audit_experiment_family(
    family: ExperimentFamily,
    *,
    input_issues: tuple[ValidationIssue, ...] = (),
    dsr_spec: DeflatedSharpeRatioSpec | None = None,
    cscv_spec: CSCVSpec | None = None,
    parameter_robustness_spec: ParameterRobustnessSpec | None = None,
    temporal_robustness_spec: TemporalRobustnessSpec | None = None,
    data_snooping_spec: DataSnoopingSpec | None = None,
    run_manifest_spec: AuditRunSpec | None = None,
    input_artifacts: tuple[InputArtifactHash, ...] = (),
) -> ExperimentFamilyAuditResult:
    """Audit the complete family of trials behind a selected strategy.

    The family is first assessed for completeness and structural eligibility.
    Each selection-bias method runs only when its specification is supplied,
    and its evidence is only as good as the family is complete: trials that
    were run but not supplied cannot be accounted for.

    Args:
        family: The validated experiment family (manifest, trials, aligned
            returns, optional splits and benchmark).
        input_issues: Non-blocking validation issues found while reading the
            input, carried into the report.
        dsr_spec: Configuration of the Deflated Sharpe Ratio.
        cscv_spec: Configuration of CSCV and the Probability of Backtest
            Overfitting.
        parameter_robustness_spec: Parameter scales and neighbourhood radius.
        temporal_robustness_spec: Equal temporal windows and their
            acceptance thresholds.
        data_snooping_spec: Configuration of White's Reality Check and
            Hansen's SPA test.
        run_manifest_spec: Explicit audit identity; without it no manifest is
            produced and nothing is inferred.
        input_artifacts: SHA-256 identities of the raw input files.

    Returns:
        The complete experiment-family audit result.
    """

    assessment, trials, splits = assess_experiment_family(family)
    dsr = (
        None if dsr_spec is None else calculate_deflated_sharpe_ratio(family, dsr_spec)
    )
    cscv = None if cscv_spec is None else calculate_cscv(family, cscv_spec)
    parameter_robustness = (
        None
        if parameter_robustness_spec is None
        else calculate_parameter_robustness(family, parameter_robustness_spec)
    )
    temporal_robustness = (
        None
        if temporal_robustness_spec is None
        else calculate_temporal_robustness(family, temporal_robustness_spec)
    )
    data_snooping = calculate_data_snooping_tests(
        family,
        assessment,
        spec=data_snooping_spec,
    )
    findings = generate_experiment_family_findings(
        assessment,
        dsr,
        cscv,
        parameter_robustness,
        temporal_robustness,
        external_splits_supplied=bool(family.splits),
    ) + generate_data_snooping_findings(data_snooping)
    evidence_profile = build_experiment_family_evidence_profile(
        assessment=assessment,
        dsr=dsr,
        cscv=cscv,
        parameter_robustness=parameter_robustness,
        temporal_robustness=temporal_robustness,
        data_snooping=data_snooping,
        input_issue_codes=tuple(issue.code for issue in input_issues),
        run_manifest_configured=run_manifest_spec is not None,
    )
    run_manifest = None
    if run_manifest_spec is not None:
        configured_methods = [
            "audit_run_manifest",
            "evidence_profile",
            "experiment_family_assessment",
        ]
        if dsr_spec is not None:
            configured_methods.append("deflated_sharpe_ratio")
        if cscv_spec is not None:
            configured_methods.append("cscv_pbo")
        if parameter_robustness_spec is not None:
            configured_methods.append("parameter_neighborhood_robustness")
        if temporal_robustness_spec is not None:
            configured_methods.append("temporal_and_fold_robustness")
        if data_snooping_spec is not None:
            configured_methods.extend(("white_reality_check", "hansen_spa"))
        run_manifest = build_experiment_family_manifest(
            spec=run_manifest_spec,
            input_artifacts=input_artifacts,
            family=family,
            report_schema_version=REPORT_SCHEMA_VERSION,
            audit_configuration=canonical_configuration(
                {
                    "family_declarations": {
                        "schema_version": family.manifest.schema_version,
                        "selection_rule": family.manifest.selection_rule,
                        "selection_metric": family.manifest.selection_metric,
                        "selection_direction": (family.manifest.selection_direction),
                        "sampling": family.manifest.sampling,
                        "return_convention": (family.manifest.return_convention),
                        "split_metadata_supplied": bool(family.splits),
                        "benchmark_id": family.manifest.benchmark_id,
                    },
                    "audit_specs": {
                        "deflated_sharpe_ratio": dsr_spec,
                        "cscv": cscv_spec,
                        "parameter_robustness": parameter_robustness_spec,
                        "temporal_robustness": temporal_robustness_spec,
                        "data_snooping": data_snooping_spec,
                    },
                }
            ),
            configured_method_names=tuple(configured_methods),
            findings=findings,
            input_issues=tuple(input_issues),
            random_seeds=(
                ()
                if data_snooping_spec is None
                else (("data_snooping", data_snooping_spec.random_seed),)
            ),
        )
    return ExperimentFamilyAuditResult(
        family_id=family.manifest.family_id,
        assessment=assessment,
        trials=trials,
        splits=splits,
        deflated_sharpe_ratio=dsr,
        cscv=cscv,
        parameter_robustness=parameter_robustness,
        temporal_robustness=temporal_robustness,
        data_snooping=data_snooping,
        evidence_profile=evidence_profile,
        run_manifest=run_manifest,
        findings=findings,
        input_issues=tuple(input_issues),
    )
