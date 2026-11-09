from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditService,
    comparison_policy_from_json,
    divergence_policy_from_json,
    implementation_risk_audit_to_dict,
    load_policy_json_file,
    normalization_plan_from_json,
    risk_policy_from_json,
)


ROOT = Path("tests/fixtures/v1_5j_golden")
EXPECTED = json.loads(
    Path("tests/fixtures/reference/v1_5_implementation_risk_cases.json").read_text(
        encoding="utf-8"
    )
)


def _run(case_name: str) -> dict[str, object]:
    case = ROOT / case_name
    adapter = CanonicalArtifactFileBundleAdapter()
    result = ImplementationRiskAuditService(adapter).audit(
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
    return implementation_risk_audit_to_dict(result)


@pytest.mark.parametrize("case_name", ("exact", "divergent", "incomplete"))
def test_independently_calculated_reference_case(case_name: str) -> None:
    report = _run(case_name)
    candidate = report["candidates"][0]
    expected = EXPECTED[case_name]
    families = candidate["families"]

    actual = {
        "attribution_statuses": [item["status"] for item in candidate["attributions"]],
        "comparison_exact_match": [
            item["exact_match"] for item in candidate["comparison_levels"]
        ],
        "family_score_contributions": [item["score_contribution"] for item in families],
        "finding_kind_counts": dict(
            sorted(Counter(item["kind"] for item in report["findings"]).items())
        ),
        "implementation_risk_score": candidate["implementation_risk_score"],
        "materialities": [
            assessment["materiality"]
            for family in families
            for assessment in family["assessments"]
        ],
        "score_withheld_reason": candidate["score_withheld_reason"],
        "threshold_ratios": [
            assessment["threshold_ratio"]
            for family in families
            for assessment in family["assessments"]
        ],
        "uncertainty": candidate["uncertainty"],
    }
    assert actual == expected


def test_reference_score_is_hand_calculable_from_capped_family_weights() -> None:
    expected = EXPECTED["divergent"]
    ratios = [2.5, 2.0, 0.5, 2.5]
    independently_calculated = sum(25 * min(ratio, 1) for ratio in ratios)

    assert independently_calculated == 87.5
    assert expected["implementation_risk_score"] == str(independently_calculated)
