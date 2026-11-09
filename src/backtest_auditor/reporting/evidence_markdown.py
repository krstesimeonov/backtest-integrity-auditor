import json

from backtest_auditor.domain.evidence import EvidenceProfileResult
from backtest_auditor.domain.reproducibility import AuditRunManifestResult


def append_evidence_profile_section(
    lines: list[str],
    result: EvidenceProfileResult,
) -> None:
    lines.extend(
        [
            "## Dimensioned evidence profile",
            "",
            f"- Method: `{result.method}`",
            "- Overall status: `not calculated`",
            f"- Interpretation boundary: {_escape(result.interpretation_boundary)}",
            "",
            (
                "| Dimension | Status | Summary | Supporting evidence | "
                "Adverse evidence | Unavailable evidence | Assumptions | "
                "Next evidence required |"
            ),
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    lines.extend(
        (
            f"| {item.dimension.value} | {item.status.value} | "
            f"{_escape(item.summary)} | "
            f"{_codes(item.supporting_evidence_codes)} | "
            f"{_codes(item.adverse_evidence_codes)} | "
            f"{_codes(item.unavailable_evidence_codes)} | "
            f"{_codes(item.assumption_codes)} | "
            f"{_texts(item.next_evidence_required)} |"
        )
        for item in result.dimensions
    )


def append_run_manifest_section(
    lines: list[str],
    result: AuditRunManifestResult | None,
) -> None:
    lines.extend(["", "## Audit-run manifest", ""])
    if result is None:
        lines.append(
            "No deterministic run manifest was configured. Audit ID, timestamp, "
            "and Git revision are never inferred."
        )
        return
    lines.extend(
        [
            "| Property | Value |",
            "|---|---|",
            f"| Manifest schema | {result.manifest_schema_version} |",
            f"| Audit ID | {_escape(result.audit_id)} |",
            f"| Audit timestamp UTC | {_escape(result.audit_timestamp_utc)} |",
            f"| Audit type | {result.audit_type} |",
            f"| Subject ID | {_escape(result.subject_id)} |",
            f"| Package version | {result.package_version} |",
            f"| Report schema | {result.report_schema_version} |",
            f"| Git commit | {_escape(result.git_commit)} |",
            f"| Normalized-data encoding | {result.normalized_data_encoding} |",
            f"| Normalized-data SHA-256 | `{result.normalized_data_sha256}` |",
            f"| Configuration SHA-256 | `{result.configuration_sha256}` |",
            f"| Manifest SHA-256 | `{result.manifest_sha256}` |",
            f"| Python | {_escape(result.python_implementation)} {_escape(result.python_version)} |",
            f"| Platform | {_escape(result.platform_system)} / {_escape(result.platform_machine)} |",
        ]
    )
    lines.extend(
        [
            "",
            "### Raw input hashes",
            "",
            "| Role | File | Bytes | SHA-256 |",
            "|---|---|---:|---|",
        ]
    )
    lines.extend(
        (
            f"| {_escape(item.role)} | {_escape(item.file_name)} | "
            f"{item.size_bytes} | `{item.sha256}` |"
        )
        for item in result.input_artifacts
    )
    lines.extend(
        [
            "",
            "### Method and dependency versions",
            "",
            "| Type | Name | Version |",
            "|---|---|---|",
        ]
    )
    lines.extend(
        f"| method | {_escape(item.name)} | {_escape(item.version)} |"
        for item in result.method_versions
    )
    lines.extend(
        f"| dependency | {_escape(item.name)} | {_escape(item.version)} |"
        for item in result.dependencies
    )
    lines.extend(["", "### Random seeds", ""])
    if result.random_seeds:
        lines.extend(
            [
                "| Purpose | Seed |",
                "|---|---:|",
            ]
        )
        lines.extend(
            f"| {_escape(name)} | {seed} |" for name, seed in result.random_seeds
        )
    else:
        lines.append("No stochastic method was configured.")
    lines.extend(["", "### Preserved warning codes", ""])
    if result.warnings:
        lines.extend(
            [
                "| Source | Code |",
                "|---|---|",
            ]
        )
        lines.extend(
            f"| {_escape(item.source)} | {_escape(item.code)} |"
            for item in result.warnings
        )
    else:
        lines.append("No input issue or audit finding code was recorded.")
    configuration = json.dumps(
        json.loads(result.configuration_json),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    lines.extend(
        [
            "",
            "### Normalized audit configuration",
            "",
            "```json",
            configuration,
            "```",
        ]
    )


def _codes(values: tuple[str, ...]) -> str:
    return "none" if not values else _escape(", ".join(values))


def _texts(values: tuple[str, ...]) -> str:
    return "none" if not values else _escape(" ".join(values))


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("\r", " ")
        .replace("\n", " ")
    )
