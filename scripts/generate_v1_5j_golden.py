"""Generate or verify the cross-platform V1.5J golden corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    CanonicalRunArtifacts,
    ImplementationRiskAuditService,
    comparison_policy_to_json,
    divergence_policy_to_json,
    normalization_plan_to_json,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_to_json,
)
from scripts.generate_v1_5i_report_example import _bundle, build_policies


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = ROOT / "tests" / "fixtures" / "v1_5j_golden"
CASE_NAMES = ("exact", "divergent", "incomplete")


def _candidate(case_name: str) -> CanonicalRunArtifacts:
    reference = _bundle(candidate=False)
    candidate = _bundle(candidate=True)
    if case_name == "divergent":
        return candidate
    if case_name == "incomplete":
        return replace(candidate, equity=None)
    if case_name != "exact":
        raise ValueError(f"unknown V1.5J golden case {case_name!r}.")
    assert reference.orders is not None and candidate.orders is not None
    assert reference.costs is not None and candidate.costs is not None
    assert reference.equity is not None and candidate.equity is not None
    assert reference.returns is not None and candidate.returns is not None
    return replace(
        candidate,
        orders=(replace(candidate.orders[0], quantity=reference.orders[0].quantity),),
        costs=(
            replace(
                candidate.costs[0],
                pnl_impact=reference.costs[0].pnl_impact,
            ),
        ),
        equity=(
            replace(
                candidate.equity[0],
                total_equity=reference.equity[0].total_equity,
            ),
        ),
        returns=(replace(candidate.returns[0], value=reference.returns[0].value),),
    )


def _generate_case(destination: Path, case_name: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    adapter = CanonicalArtifactFileBundleAdapter()
    reference = _bundle(candidate=False)
    candidate = _candidate(case_name)
    adapter.write(reference, destination / "reference-bundle.zip", overwrite=True)
    adapter.write(candidate, destination / "candidate-bundle.zip", overwrite=True)
    policies = tuple(
        replace(policy, reconciliation_id=f"v1-5j-golden-{case_name}")
        for policy in build_policies(reference, candidate)
    )
    normalization, comparison, measurement, assessment = policies
    documents = {
        "case.json": json.dumps(
            {
                "case_id": case_name,
                "manifest_included": False,
                "purpose": (
                    "Cross-platform frozen output used only for regression testing."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "normalization-plan.json": normalization_plan_to_json(normalization) + "\n",
        "comparison-policy.json": comparison_policy_to_json(comparison) + "\n",
        "measurement-policy.json": divergence_policy_to_json(measurement) + "\n",
        "assessment-policy.json": risk_policy_to_json(assessment) + "\n",
    }
    result = ImplementationRiskAuditService(adapter).audit(
        (reference, candidate),
        normalization,
        comparison,
        measurement,
        assessment,
    )
    documents["report.json"] = render_implementation_risk_json(result)
    documents["report.md"] = render_implementation_risk_markdown(result)
    for name, content in documents.items():
        (destination / name).write_text(content, encoding="utf-8", newline="\n")


def generate_golden(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for case_name in CASE_NAMES:
        _generate_case(destination / case_name, case_name)
    entries = []
    for path in sorted(item for item in destination.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {path.relative_to(destination).as_posix()}")
    (destination / "SHA256SUMS").write_text(
        "\n".join(entries) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _files(root: Path) -> set[Path]:
    return {item.relative_to(root) for item in root.rglob("*") if item.is_file()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if not arguments.check:
        generate_golden(GOLDEN_ROOT)
        return
    with tempfile.TemporaryDirectory() as temporary:
        generated = Path(temporary)
        generate_golden(generated)
        expected_files = _files(GOLDEN_ROOT)
        actual_files = _files(generated)
        if expected_files != actual_files:
            raise SystemExit("stale V1.5J golden file set")
        for relative in sorted(expected_files):
            if (generated / relative).read_bytes() != (
                GOLDEN_ROOT / relative
            ).read_bytes():
                raise SystemExit(f"stale V1.5J golden file: {relative}")


if __name__ == "__main__":
    main()
