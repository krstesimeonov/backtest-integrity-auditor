from __future__ import annotations

import pytest

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    EngineRunReference,
    LevelEligibility,
    LevelEligibilityStatus,
    PairScopeAssessment,
    ReconciliationScope,
    RunEvidenceProfile,
    ScopeAssessment,
    assess_reconciliation_scope,
)


def _run(
    run_id: str,
    *,
    engine_name: str = "Example Engine",
    engine_version: str | None = "1.0",
    digest_character: str = "a",
) -> EngineRunReference:
    return EngineRunReference(
        run_id=run_id,
        engine_name=engine_name,
        engine_version=engine_version,
        source_sha256=digest_character * 64,
    )


def _scope(
    *,
    reference: EngineRunReference | None = None,
    candidates: tuple[EngineRunReference, ...] | None = None,
    levels: tuple[ComparisonLevel, ...] | None = None,
) -> ReconciliationScope:
    return ReconciliationScope(
        reconciliation_id="scope-1",
        reference_run=reference or _run("reference"),
        candidate_runs=(
            candidates
            if candidates is not None
            else (_run("candidate", digest_character="b"),)
        ),
        requested_levels=(
            levels
            if levels is not None
            else (
                ComparisonLevel.STRATEGY_SPECIFICATION,
                ComparisonLevel.FILL,
            )
        ),
    )


def test_engine_run_reference_normalizes_text_and_digest() -> None:
    run = EngineRunReference(
        run_id="  run-1  ",
        engine_name="  vectorbt  ",
        engine_version="  0.28.1  ",
        source_sha256="A" * 64,
    )

    assert run.run_id == "run-1"
    assert run.engine_name == "vectorbt"
    assert run.engine_version == "0.28.1"
    assert run.source_sha256 == "a" * 64


def test_engine_run_reference_preserves_unknown_engine_version() -> None:
    run = _run("run-1", engine_version=None)

    assert run.engine_version is None


def test_engine_run_reference_rejects_non_string_identifier() -> None:
    with pytest.raises(ValueError, match="run_id must be a string"):
        EngineRunReference(
            run_id=1,  # type: ignore[arg-type]
            engine_name="engine",
            engine_version="1.0",
            source_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", ""),
        ("run_id", "run\n1"),
        ("run_id", "x" * 129),
        ("engine_name", "  "),
        ("engine_name", "x" * 257),
        ("engine_version", "\x7f"),
        ("engine_version", "x" * 257),
    ],
)
def test_engine_run_reference_rejects_invalid_text(field: str, value: str) -> None:
    values: dict[str, object] = {
        "run_id": "run-1",
        "engine_name": "engine",
        "engine_version": "1.0",
        "source_sha256": "a" * 64,
    }
    values[field] = value

    with pytest.raises(ValueError):
        EngineRunReference(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "digest",
    ["", "a" * 63, "a" * 65, "g" * 64, 123],
)
def test_engine_run_reference_rejects_invalid_sha256(digest: object) -> None:
    with pytest.raises(ValueError, match="source_sha256"):
        EngineRunReference(
            run_id="run-1",
            engine_name="engine",
            engine_version="1.0",
            source_sha256=digest,  # type: ignore[arg-type]
        )


def test_scope_canonicalizes_level_order_and_accepts_runtime_strings() -> None:
    scope = _scope(
        levels=(
            "return",  # type: ignore[arg-type]
            "strategy_specification",  # type: ignore[arg-type]
            "fill",  # type: ignore[arg-type]
        )
    )

    assert scope.requested_levels == (
        ComparisonLevel.STRATEGY_SPECIFICATION,
        ComparisonLevel.FILL,
        ComparisonLevel.RETURN,
    )


def test_scope_allows_same_engine_for_version_reconciliation() -> None:
    reference = _run("old", engine_version="1.0")
    candidate = _run("new", engine_version="2.0", digest_character="b")

    scope = _scope(reference=reference, candidates=(candidate,))

    assert scope.reference_run.engine_name == scope.candidate_runs[0].engine_name


@pytest.mark.parametrize(
    "candidates",
    [(), None],
)
def test_scope_requires_a_candidate(candidates) -> None:
    reference = _run("reference")
    supplied_candidates = candidates
    if candidates is None:
        supplied_candidates = None  # deliberately non-iterable

    with pytest.raises(ValueError, match="candidate_runs"):
        ReconciliationScope(
            reconciliation_id="scope-1",
            reference_run=reference,
            candidate_runs=supplied_candidates,  # type: ignore[arg-type]
            requested_levels=(ComparisonLevel.EQUITY,),
        )


def test_scope_rejects_duplicate_run_ids() -> None:
    reference = _run("same")
    candidate = _run("same", digest_character="b")

    with pytest.raises(ValueError, match="run_id"):
        _scope(reference=reference, candidates=(candidate,))


def test_scope_rejects_invalid_reference_or_candidate_types() -> None:
    with pytest.raises(ValueError, match="reference_run"):
        ReconciliationScope(
            reconciliation_id="scope-1",
            reference_run="reference",  # type: ignore[arg-type]
            candidate_runs=(_run("candidate"),),
            requested_levels=(ComparisonLevel.EQUITY,),
        )

    with pytest.raises(ValueError, match="candidate_runs"):
        ReconciliationScope(
            reconciliation_id="scope-1",
            reference_run=_run("reference"),
            candidate_runs=("candidate",),  # type: ignore[arg-type]
            requested_levels=(ComparisonLevel.EQUITY,),
        )


def test_scope_rejects_empty_duplicate_or_unknown_levels() -> None:
    with pytest.raises(ValueError, match="at least one"):
        _scope(levels=())

    with pytest.raises(ValueError, match="duplicates"):
        _scope(levels=(ComparisonLevel.FILL, ComparisonLevel.FILL))

    with pytest.raises(ValueError, match="must be one of"):
        _scope(levels=("unknown",))  # type: ignore[arg-type]


def test_scope_rejects_non_iterable_levels() -> None:
    with pytest.raises(ValueError, match="iterable"):
        ReconciliationScope(
            reconciliation_id="scope-1",
            reference_run=_run("reference"),
            candidate_runs=(_run("candidate", digest_character="b"),),
            requested_levels=None,  # type: ignore[arg-type]
        )


def test_evidence_profile_canonicalizes_levels_and_allows_none_available() -> None:
    run = _run("run-1")
    populated = RunEvidenceProfile(
        run=run,
        available_levels=(ComparisonLevel.RETURN, ComparisonLevel.ORDER),
    )
    empty = RunEvidenceProfile(run=run, available_levels=())

    assert populated.available_levels == (
        ComparisonLevel.ORDER,
        ComparisonLevel.RETURN,
    )
    assert empty.available_levels == ()


def test_evidence_profile_rejects_invalid_run_and_duplicate_levels() -> None:
    with pytest.raises(ValueError, match="EngineRunReference"):
        RunEvidenceProfile(
            run="run",  # type: ignore[arg-type]
            available_levels=(),
        )

    with pytest.raises(ValueError, match="duplicates"):
        RunEvidenceProfile(
            run=_run("run"),
            available_levels=(ComparisonLevel.FILL, ComparisonLevel.FILL),
        )


def test_level_eligibility_normalizes_runtime_strings() -> None:
    item = LevelEligibility(
        level="fill",  # type: ignore[arg-type]
        status="eligible",  # type: ignore[arg-type]
    )

    assert item.level is ComparisonLevel.FILL
    assert item.status is LevelEligibilityStatus.ELIGIBLE
    assert item.eligible is True


@pytest.mark.parametrize(
    ("level", "status", "message"),
    [
        ("unknown", LevelEligibilityStatus.ELIGIBLE, "level"),
        (ComparisonLevel.FILL, "unknown", "status"),
    ],
)
def test_level_eligibility_rejects_unknown_values(level, status, message) -> None:
    with pytest.raises(ValueError, match=message):
        LevelEligibility(level=level, status=status)


def test_pair_assessment_validates_and_canonicalizes_levels() -> None:
    candidate = _run("candidate")
    pair = PairScopeAssessment(
        candidate_run=candidate,
        levels=(
            LevelEligibility(
                ComparisonLevel.RETURN,
                LevelEligibilityStatus.BOTH_UNAVAILABLE,
            ),
            LevelEligibility(
                ComparisonLevel.FILL,
                LevelEligibilityStatus.ELIGIBLE,
            ),
        ),
    )

    assert tuple(item.level for item in pair.levels) == (
        ComparisonLevel.FILL,
        ComparisonLevel.RETURN,
    )


@pytest.mark.parametrize(
    ("candidate", "levels", "message"),
    [
        ("candidate", (), "candidate_run"),
        (_run("candidate"), None, "iterable"),
        (_run("candidate"), (), "at least one"),
        (_run("candidate"), ("fill",), "LevelEligibility"),
        (
            _run("candidate"),
            (
                LevelEligibility(
                    ComparisonLevel.FILL,
                    LevelEligibilityStatus.ELIGIBLE,
                ),
                LevelEligibility(
                    ComparisonLevel.FILL,
                    LevelEligibilityStatus.BOTH_UNAVAILABLE,
                ),
            ),
            "duplicate",
        ),
    ],
)
def test_pair_assessment_rejects_invalid_contract(candidate, levels, message) -> None:
    with pytest.raises(ValueError, match=message):
        PairScopeAssessment(candidate_run=candidate, levels=levels)


def test_assessment_types_every_availability_combination_independently() -> None:
    reference = _run("reference")
    candidate = _run("candidate", digest_character="b")
    scope = _scope(
        reference=reference,
        candidates=(candidate,),
        levels=(
            ComparisonLevel.STRATEGY_SPECIFICATION,
            ComparisonLevel.SIGNAL,
            ComparisonLevel.ORDER,
            ComparisonLevel.FILL,
        ),
    )
    profiles = (
        RunEvidenceProfile(
            run=reference,
            available_levels=(
                ComparisonLevel.STRATEGY_SPECIFICATION,
                ComparisonLevel.SIGNAL,
            ),
        ),
        RunEvidenceProfile(
            run=candidate,
            available_levels=(
                ComparisonLevel.STRATEGY_SPECIFICATION,
                ComparisonLevel.ORDER,
            ),
        ),
    )

    assessment = assess_reconciliation_scope(scope, reversed(profiles))

    pair = assessment.pairs[0]
    assert tuple(item.status for item in pair.levels) == (
        LevelEligibilityStatus.ELIGIBLE,
        LevelEligibilityStatus.CANDIDATE_UNAVAILABLE,
        LevelEligibilityStatus.REFERENCE_UNAVAILABLE,
        LevelEligibilityStatus.BOTH_UNAVAILABLE,
    )
    assert pair.eligible_levels == (ComparisonLevel.STRATEGY_SPECIFICATION,)
    assert pair.unavailable_levels == (
        ComparisonLevel.SIGNAL,
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
    )
    assert pair.is_fully_eligible is False
    assert assessment.has_any_eligible_comparison is True
    assert assessment.is_fully_eligible is False


def test_assessment_preserves_declared_candidate_order() -> None:
    reference = _run("reference")
    first = _run("first", digest_character="b")
    second = _run("second", digest_character="c")
    scope = _scope(
        reference=reference,
        candidates=(first, second),
        levels=(ComparisonLevel.EQUITY,),
    )
    profiles = tuple(
        RunEvidenceProfile(run=run, available_levels=(ComparisonLevel.EQUITY,))
        for run in (second, reference, first)
    )

    assessment = assess_reconciliation_scope(scope, profiles)

    assert tuple(pair.candidate_run.run_id for pair in assessment.pairs) == (
        "first",
        "second",
    )
    assert assessment.is_fully_eligible is True


def test_assessment_can_report_no_eligible_comparisons() -> None:
    reference = _run("reference")
    candidate = _run("candidate", digest_character="b")
    scope = _scope(reference=reference, candidates=(candidate,))

    assessment = assess_reconciliation_scope(
        scope,
        (
            RunEvidenceProfile(run=reference, available_levels=()),
            RunEvidenceProfile(run=candidate, available_levels=()),
        ),
    )

    assert assessment.has_any_eligible_comparison is False
    assert assessment.is_fully_eligible is False


def test_scope_assessment_validates_its_result_contract() -> None:
    scope = _scope(levels=(ComparisonLevel.EQUITY,))
    pair = PairScopeAssessment(
        candidate_run=scope.candidate_runs[0],
        levels=(
            LevelEligibility(
                ComparisonLevel.EQUITY,
                LevelEligibilityStatus.ELIGIBLE,
            ),
        ),
    )

    assessment = ScopeAssessment(scope=scope, pairs=[pair])  # type: ignore[arg-type]

    assert assessment.pairs == (pair,)


@pytest.mark.parametrize(
    ("scope_value", "pairs", "message"),
    [
        ("scope", (), "ReconciliationScope"),
        (_scope(), None, "iterable"),
        (_scope(), ("pair",), "PairScopeAssessment"),
        (_scope(), (), "declared order"),
    ],
)
def test_scope_assessment_rejects_invalid_scope_or_pairs(
    scope_value,
    pairs,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        ScopeAssessment(scope=scope_value, pairs=pairs)


def test_scope_assessment_rejects_candidate_order_or_level_mismatch() -> None:
    first = _run("first", digest_character="b")
    second = _run("second", digest_character="c")
    scope = _scope(
        candidates=(first, second),
        levels=(ComparisonLevel.FILL, ComparisonLevel.EQUITY),
    )

    def pair(candidate, levels):
        return PairScopeAssessment(
            candidate_run=candidate,
            levels=tuple(
                LevelEligibility(level, LevelEligibilityStatus.ELIGIBLE)
                for level in levels
            ),
        )

    with pytest.raises(ValueError, match="declared order"):
        ScopeAssessment(
            scope=scope,
            pairs=(
                pair(second, scope.requested_levels),
                pair(first, scope.requested_levels),
            ),
        )

    with pytest.raises(ValueError, match="requested levels"):
        ScopeAssessment(
            scope=scope,
            pairs=(
                pair(first, (ComparisonLevel.FILL,)),
                pair(second, scope.requested_levels),
            ),
        )


def test_assessment_rejects_wrong_scope_or_profile_collection() -> None:
    with pytest.raises(ValueError, match="ReconciliationScope"):
        assess_reconciliation_scope("scope", ())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="iterable"):
        assess_reconciliation_scope(_scope(), None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="RunEvidenceProfile"):
        assess_reconciliation_scope(_scope(), ("profile",))  # type: ignore[arg-type]


def test_assessment_rejects_duplicate_profile_run_ids() -> None:
    reference = _run("reference")
    duplicate = RunEvidenceProfile(run=reference, available_levels=())

    with pytest.raises(ValueError, match="one profile"):
        assess_reconciliation_scope(_scope(reference=reference), (duplicate, duplicate))


@pytest.mark.parametrize(
    "profiles",
    [
        lambda reference, candidate, extra: (
            RunEvidenceProfile(run=reference, available_levels=()),
        ),
        lambda reference, candidate, extra: (
            RunEvidenceProfile(run=reference, available_levels=()),
            RunEvidenceProfile(run=candidate, available_levels=()),
            RunEvidenceProfile(run=extra, available_levels=()),
        ),
    ],
)
def test_assessment_requires_exact_scoped_profile_ids(profiles) -> None:
    reference = _run("reference")
    candidate = _run("candidate", digest_character="b")
    extra = _run("extra", digest_character="c")
    scope = _scope(reference=reference, candidates=(candidate,))

    with pytest.raises(ValueError, match="exactly match"):
        assess_reconciliation_scope(scope, profiles(reference, candidate, extra))


def test_assessment_rejects_profile_identity_mismatch_for_same_run_id() -> None:
    reference = _run("reference")
    candidate = _run("candidate", digest_character="b")
    mismatched_candidate = _run(
        "candidate",
        engine_name="Different Engine",
        digest_character="b",
    )
    scope = _scope(reference=reference, candidates=(candidate,))

    with pytest.raises(ValueError, match="identity does not match"):
        assess_reconciliation_scope(
            scope,
            (
                RunEvidenceProfile(run=reference, available_levels=()),
                RunEvidenceProfile(run=mismatched_candidate, available_levels=()),
            ),
        )
