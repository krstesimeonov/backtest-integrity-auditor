from __future__ import annotations

import random
from dataclasses import replace
from decimal import Decimal

from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    CanonicalRunArtifacts,
    ImplementationRiskAuditService,
    implementation_risk_audit_to_dict,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
)
from scripts.generate_v1_5i_report_example import _bundle, build_policies


def _candidate(
    scale: Decimal, direction: Decimal = Decimal(1)
) -> CanonicalRunArtifacts:
    reference = _bundle(candidate=False)
    candidate = _bundle(candidate=True)
    assert reference.orders is not None and candidate.orders is not None
    assert reference.costs is not None and candidate.costs is not None
    assert reference.equity is not None and candidate.equity is not None
    assert reference.returns is not None and candidate.returns is not None
    return replace(
        candidate,
        orders=(
            replace(
                candidate.orders[0],
                quantity=reference.orders[0].quantity + direction * scale * Decimal(2),
            ),
        ),
        costs=(
            replace(
                candidate.costs[0],
                pnl_impact=reference.costs[0].pnl_impact
                - direction * scale * Decimal("0.25"),
            ),
        ),
        equity=(
            replace(
                candidate.equity[0],
                total_equity=reference.equity[0].total_equity
                - direction * scale * Decimal("2.5"),
            ),
        ),
        returns=(
            replace(
                candidate.returns[0],
                value=reference.returns[0].value
                - direction * scale * Decimal("0.000025"),
            ),
        ),
    )


def _audit(scale: Decimal, direction: Decimal = Decimal(1)):
    reference = _bundle(candidate=False)
    candidate = _candidate(scale, direction)
    return ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
        (reference, candidate),
        *build_policies(reference, candidate),
    )


def _risk_projection(scale: Decimal, direction: Decimal = Decimal(1)) -> dict:
    candidate = implementation_risk_audit_to_dict(_audit(scale, direction))[
        "candidates"
    ][0]
    return {
        "score": candidate["implementation_risk_score"],
        "uncertainty": candidate["uncertainty"],
        "families": [
            {
                "maximum_threshold_ratio": family["maximum_threshold_ratio"],
                "score_contribution": family["score_contribution"],
                "materialities": [
                    item["materiality"] for item in family["assessments"]
                ],
            }
            for family in candidate["families"]
        ],
    }


def test_generated_complete_scores_are_always_bounded() -> None:
    generator = random.Random(20260821)
    scales = [Decimal(generator.randint(1, 20_000)) / 1_000 for _ in range(64)]

    for scale in scales:
        score = _risk_projection(scale)["score"]
        assert score is not None
        assert Decimal(score) >= 0
        assert Decimal(score) <= 100


def test_larger_absolute_divergence_never_reduces_the_bounded_score() -> None:
    scales = tuple(Decimal(value) for value in ("0.01", "0.1", "0.5", "1", "10"))
    scores = [Decimal(_risk_projection(scale)["score"]) for scale in scales]

    assert scores == sorted(scores)


def test_materiality_and_score_are_symmetric_in_delta_sign() -> None:
    for scale in (Decimal("0.1"), Decimal("1"), Decimal("4")):
        assert _risk_projection(scale, Decimal(1)) == _risk_projection(
            scale, Decimal(-1)
        )


def test_zero_divergence_is_not_misrepresented_as_a_certified_zero_score() -> None:
    report = implementation_risk_audit_to_dict(_audit(Decimal(0)))
    candidate = report["candidates"][0]

    assert all(item["exact_match"] is True for item in candidate["comparison_levels"])
    assert candidate["implementation_risk_score"] is None
    assert candidate["uncertainty"] == "not_assessed"
    assert not any(item["kind"] == "adverse" for item in report["findings"])
    assert report["overall_status"] is None


def test_renderers_are_pure_and_byte_deterministic_for_the_same_result() -> None:
    result = _audit(Decimal("1.25"))

    assert render_implementation_risk_json(result) == render_implementation_risk_json(
        result
    )
    assert render_implementation_risk_markdown(
        result
    ) == render_implementation_risk_markdown(result)
