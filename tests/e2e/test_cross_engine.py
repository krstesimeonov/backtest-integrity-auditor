"""All five engines against each other in one implementation-risk audit.

This is the product's own use: one engine's bundle is the reference run and
the others are candidates. vectorbt is the reference here; any engine would
do. Fills and costs are the levels every adapter supplies, and all five
engines must agree on them exactly. Equity shows what a client sees when
engines record it on different schedules.
"""

from __future__ import annotations

from collections import Counter

import pytest

from backtest_auditor.implementation_risk import ComparisonLevel

from e2e import (
    harness,
    test_backtrader,
    test_bt,
    test_lean,
    test_nautilustrader,
    test_vectorbt,
)


@pytest.fixture(scope="module")
def bundles(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cross-engine")
    return {
        "vectorbt": test_vectorbt.mapped_bundle(tmp / "vectorbt", lag=1)[1],
        "bt": test_bt.mapped_bundle(tmp / "bt", lag=1)[1],
        "backtrader": test_backtrader.mapped_bundle(tmp / "backtrader")[1],
        "lean": test_lean.mapped_bundle(tmp / "lean", lag=1)[1],
        "nautilustrader": test_nautilustrader.mapped_bundle(tmp / "nautilus", lag=1)[1],
    }


def _statuses(run: harness.RiskRun, run_id: str, level: ComparisonLevel) -> Counter:
    candidate = next(
        item
        for item in run.result.comparison.candidates
        if item.candidate_run.run_id == run_id
    )
    compared = next(item for item in candidate.levels if item.level is level)
    return Counter(item.status.value for item in compared.records)


def test_all_five_engines_agree_on_fills_and_costs(bundles, tmp_path) -> None:
    reference, *candidates = bundles.values()
    levels = (ComparisonLevel.FILL, ComparisonLevel.COST)
    run = harness.implementation_risk(
        reference, candidates, levels, report_path=tmp_path / "cross-engine.json"
    )
    assert len(run.result.comparison.candidates) == 4
    for candidate in candidates:
        for level in levels:
            statuses = _statuses(run, candidate.run.run_id, level)
            assert sum(statuses.values()) == 10, (candidate.run.run_id, level, statuses)
            assert set(statuses) <= {"matched_equal", "matched_different"}, (
                candidate.run.run_id,
                level,
                statuses,
            )
    assert not run.adverse, run.adverse
    assert not run.gaps, run.gaps


def test_per_bar_equity_agrees_between_vectorbt_and_backtrader(bundles) -> None:
    run = harness.implementation_risk(
        bundles["vectorbt"], bundles["backtrader"], (ComparisonLevel.EQUITY,)
    )
    statuses = _statuses(run, bundles["backtrader"].run.run_id, ComparisonLevel.EQUITY)
    assert sum(statuses.values()) == 400 and "candidate_only" not in statuses
    harness.assert_no_implementation_defect(run)


def test_equity_schedules_differ_without_any_value_disagreeing(bundles) -> None:
    """bt adds its virtual first row; LEAN samples at every New York midnight.

    Against vectorbt's 400 per-bar points those records are one-sided, so the
    report shows evidence gaps for bt and LEAN, but no equity value disagrees.
    """

    run = harness.implementation_risk(
        bundles["vectorbt"],
        [bundles["bt"], bundles["lean"]],
        (ComparisonLevel.EQUITY,),
    )
    bt = _statuses(run, bundles["bt"].run.run_id, ComparisonLevel.EQUITY)
    lean = _statuses(run, bundles["lean"].run.run_id, ComparisonLevel.EQUITY)
    assert (
        bt["candidate_only"] == 1
        and bt["matched_equal"] + bt["matched_different"] == 400
    )
    assert lean["candidate_only"] == 560
    assert lean["matched_equal"] + lean["matched_different"] == 400
    assert not run.adverse, run.adverse
    assert {item.split(":")[0] for item in run.gaps} >= {
        "IMPLEMENTATION_FAMILY_EVIDENCE_IMPAIRED"
    }
