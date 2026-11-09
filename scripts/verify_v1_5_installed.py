"""Verify the V1.5 base wheel from outside the source tree."""

from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory

import backtest_auditor
from backtest_auditor import PACKAGE_VERSION
from backtest_auditor.cli import main as cli_main
from backtest_auditor.implementation_risk import (
    CANONICAL_BUNDLE_SCHEMA_FILES,
    IMPLEMENTATION_RISK_SCHEMA_FILES,
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditService,
    comparison_policy_from_json,
    divergence_policy_from_json,
    load_canonical_bundle_schema,
    load_implementation_risk_schema,
    load_policy_json_file,
    normalization_plan_from_json,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_from_json,
)
from backtest_auditor.reporting.schema_catalog import (
    PUBLIC_SCHEMA_FILES,
    load_public_schema,
)


CASE_NAMES = ("exact", "divergent", "incomplete")


def _arguments(case: Path, output: Path) -> list[str]:
    return [
        "implementation-risk",
        str(case / "reference-bundle.zip"),
        str(case / "candidate-bundle.zip"),
        "--normalization-plan",
        str(case / "normalization-plan.json"),
        "--comparison-policy",
        str(case / "comparison-policy.json"),
        "--measurement-policy",
        str(case / "measurement-policy.json"),
        "--assessment-policy",
        str(case / "assessment-policy.json"),
        "--format",
        "json",
        "--output",
        str(output),
    ]


def _audit(case: Path):
    adapter = CanonicalArtifactFileBundleAdapter()
    return ImplementationRiskAuditService(adapter).audit(
        (
            adapter.read(case / "reference-bundle.zip"),
            adapter.read(case / "candidate-bundle.zip"),
        ),
        normalization_plan_from_json(
            load_policy_json_file(case / "normalization-plan.json")
        ),
        comparison_policy_from_json(
            load_policy_json_file(case / "comparison-policy.json")
        ),
        divergence_policy_from_json(
            load_policy_json_file(case / "measurement-policy.json")
        ),
        risk_policy_from_json(load_policy_json_file(case / "assessment-policy.json")),
    )


def verify(
    project_root: Path,
    expected_version: str,
    *,
    require_base_environment: bool = True,
) -> dict[str, object]:
    source_root = project_root.resolve()
    installed_package = Path(backtest_auditor.__file__).resolve()
    if source_root in installed_package.parents:
        raise RuntimeError("backtest_auditor resolved from the source tree.")
    if (
        PACKAGE_VERSION != expected_version
        or version("backtest-integrity-auditor") != expected_version
    ):
        raise RuntimeError("installed distribution version mismatch.")

    v1_schemas = [load_public_schema(name) for name in PUBLIC_SCHEMA_FILES]
    file_schemas = [
        load_canonical_bundle_schema(name) for name in CANONICAL_BUNDLE_SCHEMA_FILES
    ]
    report_schemas = [
        load_implementation_risk_schema(name)
        for name in IMPLEMENTATION_RISK_SCHEMA_FILES
    ]
    all_schemas = (*v1_schemas, *file_schemas, *report_schemas)
    if (len(v1_schemas), len(file_schemas), len(report_schemas)) != (7, 4, 2):
        raise RuntimeError("installed schema catalog is incomplete.")
    if len({schema["$id"] for schema in all_schemas}) != 13:
        raise RuntimeError("installed schema identifiers are not unique.")

    optional_modules = (
        "backtrader",
        "bt",
        "nautilus_trader",
        "sqlalchemy",
        "streamlit",
        "vectorbt",
    )
    unexpected = [name for name in optional_modules if find_spec(name) is not None]
    if unexpected and require_base_environment:
        raise RuntimeError(f"base environment contains optional modules: {unexpected}")

    golden_root = source_root / "tests" / "fixtures" / "v1_5j_golden"
    for case_name in CASE_NAMES:
        case = golden_root / case_name
        result = _audit(case)
        if (
            render_implementation_risk_json(result).encode()
            != (case / "report.json").read_bytes()
        ):
            raise RuntimeError(f"installed JSON mismatch for {case_name}.")
        if (
            render_implementation_risk_markdown(result).encode()
            != (case / "report.md").read_bytes()
        ):
            raise RuntimeError(f"installed Markdown mismatch for {case_name}.")

    with TemporaryDirectory(prefix="backtest-auditor-installed-") as temporary:
        root = Path(temporary)
        case = golden_root / "divergent"
        first = root / "first.json"
        second = root / "second.json"
        if cli_main(_arguments(case, first)) != 0:
            raise RuntimeError("first installed CLI run failed.")
        if cli_main(_arguments(case, second)) != 0:
            raise RuntimeError("second installed CLI run failed.")
        if first.read_bytes() != second.read_bytes():
            raise RuntimeError("installed CLI output is not deterministic.")
        payload = json.loads(first.read_text(encoding="utf-8"))
        if payload["overall_status"] is not None:
            raise RuntimeError("installed report invented a global status.")

    return {
        "golden_case_count": len(CASE_NAMES),
        "installed_package": str(installed_package),
        "schema_count": len(all_schemas),
        "version": PACKAGE_VERSION,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--allow-optional-modules", action="store_true")
    arguments = parser.parse_args()
    try:
        result = verify(
            arguments.project_root,
            arguments.expected_version,
            require_base_environment=not arguments.allow_optional_modules,
        )
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"installed V1.5 verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
