"""Human-readable rendering of the versioned V1.5I report."""

from __future__ import annotations

from backtest_auditor.implementation_risk.domain.reporting import (
    ImplementationRiskAuditResult,
)


def render_implementation_risk_markdown(result: ImplementationRiskAuditResult) -> str:
    """Render a result as a deterministic Markdown report.

    Raises:
        ValueError: If ``result`` is not an ``ImplementationRiskAuditResult``.
    """

    if not isinstance(result, ImplementationRiskAuditResult):
        raise ValueError("result must be an ImplementationRiskAuditResult.")
    scope = result.assessment.scope
    lines = [
        "# Backtest Implementation-Risk Report",
        "",
        f"- Report schema: `{result.report_schema_version}`",
        f"- Reconciliation: `{_escape(scope.reconciliation_id)}`",
        f"- Reference: `{_escape(scope.reference_run.run_id)}` "
        f"({_escape(scope.reference_run.engine_name)})",
        f"- Candidates: {len(scope.candidate_runs)}",
        "- Overall status: not produced",
        "",
        "> " + result.interpretation_boundary,
        "",
        "## Policy identity",
        "",
        "| Policy | SHA-256 |",
        "|---|---|",
        f"| Normalization | `{result.assessment.normalization_plan_sha256}` |",
        f"| Comparison | `{result.assessment.comparison_policy_sha256}` |",
        f"| Measurement | `{result.assessment.measurement_policy_sha256}` |",
        f"| Assessment | `{result.assessment.assessment_policy_sha256}` |",
    ]
    for compared, measured, assessed in zip(
        result.comparison.candidates,
        result.divergence.candidates,
        result.assessment.candidates,
        strict=True,
    ):
        lines.extend(
            [
                "",
                f"## Candidate `{_escape(compared.candidate_run.run_id)}`",
                "",
                f"- Engine: {_escape(compared.candidate_run.engine_name)}",
                "- Implementation-risk score: "
                + (
                    "withheld"
                    if assessed.implementation_risk_score is None
                    else assessed.implementation_risk_score
                ),
                f"- Uncertainty: {assessed.uncertainty.value}",
            ]
        )
        if assessed.score_withheld_reason is not None:
            lines.append(f"- Score note: {_escape(assessed.score_withheld_reason)}")
        lines.extend(
            [
                "",
                "### Comparison levels",
                "",
                "| Level | Status | Alignment | Exact match | Records |",
                "|---|---|---|---:|---:|",
            ]
        )
        for level in compared.levels:
            lines.append(
                f"| {level.level.value} | {level.status.value} "
                f"| {level.alignment_mode.value} "
                f"| {_optional(level.exact_match)} | {len(level.records)} |"
            )
        lines.extend(
            [
                "",
                "### Divergence families",
                "",
                "| Family | Status | Maximum threshold ratio | Score contribution |",
                "|---|---|---:|---:|",
            ]
        )
        for family, assessment in zip(
            measured.families, assessed.families, strict=True
        ):
            lines.append(
                f"| {family.family.value} | {family.status.value} "
                f"| {_optional(assessment.maximum_threshold_ratio)} "
                f"| {_optional(assessment.score_contribution)} |"
            )
            for item in assessment.assessments:
                lines.append(
                    f"\n- `{_escape(item.observation.level.value)}` "
                    f"`{_escape(item.observation.alignment_key)}` "
                    f"`{_escape(item.observation.field)}`: delta "
                    f"`{_escape(item.observation.decimal_delta)}`, "
                    f"{item.materiality.value} at `{item.threshold_ratio}×` threshold."
                )
        lines.extend(["", "### Attribution hypotheses", ""])
        if assessed.attributions:
            lines.extend(
                [
                    "| Hypothesis | Source | Target | Status |",
                    "|---|---|---|---|",
                    *[
                        f"| {_escape(item.hypothesis_code)} "
                        f"| {item.source_family.value} | {item.target_family.value} "
                        f"| {item.status.value} |"
                        for item in assessed.attributions
                    ],
                ]
            )
        else:
            lines.append("No attribution hypotheses were configured.")
    lines.extend(["", "## Independent findings", ""])
    if result.findings:
        lines.extend(
            [
                "| Code | Kind | Candidate | Family | Summary | Limitation | Action |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for finding in result.findings:
            lines.append(
                f"| {_escape(finding.code)} | {finding.kind.value} "
                f"| {_escape(finding.candidate_run_id)} "
                f"| {'' if finding.family is None else finding.family.value} "
                f"| {_escape(finding.summary)} | {_escape(finding.limitation)} "
                f"| {_escape(finding.recommended_action or '')} |"
            )
    else:
        lines.append("No independent findings were generated.")
    lines.extend(["", "## Run manifest", ""])
    if result.run_manifest is None:
        lines.append("Not requested.")
    else:
        lines.extend(
            [
                f"- Audit ID: `{_escape(result.run_manifest.audit_id)}`",
                f"- Audit timestamp: `{result.run_manifest.audit_timestamp_utc}`",
                f"- Git identity: `{_escape(result.run_manifest.git_commit)}`",
                f"- Manifest SHA-256: `{result.run_manifest.manifest_sha256}`",
            ]
        )
    return "\n".join(lines) + "\n"


def _optional(value: object | None) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


__all__ = ["render_implementation_risk_markdown"]
