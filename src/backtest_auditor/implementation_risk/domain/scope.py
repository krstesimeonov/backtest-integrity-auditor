"""Reconciliation scope and evidence-availability assessment.

This module deliberately stops before parsing or comparing engine artifacts.
It answers a narrower prerequisite question: which explicitly requested
evidence layers are actually comparable for each reference/candidate pair?
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from backtest_auditor.implementation_risk.domain.enums import (
    ComparisonLevel,
    LevelEligibilityStatus,
)
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_sha256,
    normalize_text,
)


_MAX_IDENTIFIER_LENGTH = 128
_MAX_ENGINE_TEXT_LENGTH = 256
_LEVEL_ORDER = {level: index for index, level in enumerate(ComparisonLevel)}


def _normalized_levels(
    levels: Iterable[ComparisonLevel],
    *,
    allow_empty: bool,
) -> tuple[ComparisonLevel, ...]:
    try:
        raw_levels = tuple(levels)
    except TypeError as error:
        raise ValueError("comparison levels must be an iterable.") from error

    normalized: list[ComparisonLevel] = []
    for raw_level in raw_levels:
        try:
            normalized.append(ComparisonLevel(raw_level))
        except (TypeError, ValueError) as error:
            supported = ", ".join(level.value for level in ComparisonLevel)
            raise ValueError(
                f"comparison level must be one of: {supported}."
            ) from error

    if not allow_empty and not normalized:
        raise ValueError("requested_levels must contain at least one level.")
    if len(set(normalized)) != len(normalized):
        raise ValueError("comparison levels must not contain duplicates.")
    return tuple(sorted(normalized, key=_LEVEL_ORDER.__getitem__))


@dataclass(frozen=True, slots=True)
class EngineRunReference:
    """Identity and provenance of one exported backtest run.

    ``source_sha256`` is calculated by an adapter from the source artifact
    bundle; the user is not expected to calculate or type it manually.
    ``engine_version`` may be absent when an export does not disclose it, but
    that absence remains visible instead of being replaced with a guess.
    """

    run_id: str
    engine_name: str
    engine_version: str | None
    source_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "run_id",
            normalize_text(
                self.run_id,
                field="run_id",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "engine_name",
            normalize_text(
                self.engine_name,
                field="engine_name",
                maximum_length=_MAX_ENGINE_TEXT_LENGTH,
            ),
        )
        if self.engine_version is not None:
            object.__setattr__(
                self,
                "engine_version",
                normalize_text(
                    self.engine_version,
                    field="engine_version",
                    maximum_length=_MAX_ENGINE_TEXT_LENGTH,
                ),
            )
        object.__setattr__(
            self,
            "source_sha256",
            normalize_sha256(self.source_sha256, field="source_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ReconciliationScope:
    """Explicit reference-to-candidates comparison plan.

    The reference is a baseline, never an assertion of truth.  A scope may
    compare different engines, different versions of one engine, or two
    configurations of the same engine.
    """

    reconciliation_id: str
    reference_run: EngineRunReference
    candidate_runs: tuple[EngineRunReference, ...]
    requested_levels: tuple[ComparisonLevel, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconciliation_id",
            normalize_text(
                self.reconciliation_id,
                field="reconciliation_id",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        if not isinstance(self.reference_run, EngineRunReference):
            raise ValueError("reference_run must be an EngineRunReference.")

        try:
            candidates = tuple(self.candidate_runs)
        except TypeError as error:
            raise ValueError("candidate_runs must be an iterable.") from error
        if not candidates:
            raise ValueError("candidate_runs must contain at least one run.")
        if any(not isinstance(run, EngineRunReference) for run in candidates):
            raise ValueError(
                "candidate_runs must contain only EngineRunReference values."
            )

        run_ids = (self.reference_run.run_id, *(run.run_id for run in candidates))
        if len(set(run_ids)) != len(run_ids):
            raise ValueError(
                "reference and candidate run_id values must be unique within a scope."
            )

        object.__setattr__(self, "candidate_runs", candidates)
        object.__setattr__(
            self,
            "requested_levels",
            _normalized_levels(self.requested_levels, allow_empty=False),
        )


@dataclass(frozen=True, slots=True)
class RunEvidenceProfile:
    """Levels that an adapter can substantiate for one exported run."""

    run: EngineRunReference
    available_levels: tuple[ComparisonLevel, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run, EngineRunReference):
            raise ValueError("run must be an EngineRunReference.")
        object.__setattr__(
            self,
            "available_levels",
            _normalized_levels(self.available_levels, allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class LevelEligibility:
    """Eligibility of one requested level for one run pair."""

    level: ComparisonLevel
    status: LevelEligibilityStatus

    def __post_init__(self) -> None:
        try:
            level = ComparisonLevel(self.level)
        except (TypeError, ValueError) as error:
            raise ValueError("level must be a supported ComparisonLevel.") from error
        try:
            status = LevelEligibilityStatus(self.status)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "status must be a supported LevelEligibilityStatus."
            ) from error
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "status", status)

    @property
    def eligible(self) -> bool:
        return self.status is LevelEligibilityStatus.ELIGIBLE


@dataclass(frozen=True, slots=True)
class PairScopeAssessment:
    """Independent eligibility results for one candidate against the reference."""

    candidate_run: EngineRunReference
    levels: tuple[LevelEligibility, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_run, EngineRunReference):
            raise ValueError("candidate_run must be an EngineRunReference.")
        try:
            levels = tuple(self.levels)
        except TypeError as error:
            raise ValueError("levels must be an iterable.") from error
        if not levels:
            raise ValueError("levels must contain at least one assessment.")
        if any(not isinstance(item, LevelEligibility) for item in levels):
            raise ValueError("levels must contain only LevelEligibility values.")
        level_names = tuple(item.level for item in levels)
        if len(set(level_names)) != len(level_names):
            raise ValueError("levels must not contain duplicate comparison levels.")
        object.__setattr__(
            self,
            "levels",
            tuple(sorted(levels, key=lambda item: _LEVEL_ORDER[item.level])),
        )

    @property
    def eligible_levels(self) -> tuple[ComparisonLevel, ...]:
        return tuple(item.level for item in self.levels if item.eligible)

    @property
    def unavailable_levels(self) -> tuple[ComparisonLevel, ...]:
        return tuple(item.level for item in self.levels if not item.eligible)

    @property
    def is_fully_eligible(self) -> bool:
        return bool(self.levels) and all(item.eligible for item in self.levels)


@dataclass(frozen=True, slots=True)
class ScopeAssessment:
    """Preflight result for every candidate in a reconciliation scope."""

    scope: ReconciliationScope
    pairs: tuple[PairScopeAssessment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ReconciliationScope):
            raise ValueError("scope must be a ReconciliationScope.")
        try:
            pairs = tuple(self.pairs)
        except TypeError as error:
            raise ValueError("pairs must be an iterable.") from error
        if any(not isinstance(pair, PairScopeAssessment) for pair in pairs):
            raise ValueError("pairs must contain only PairScopeAssessment values.")

        expected_candidates = self.scope.candidate_runs
        supplied_candidates = tuple(pair.candidate_run for pair in pairs)
        if supplied_candidates != expected_candidates:
            raise ValueError(
                "pairs must match every scoped candidate in declared order."
            )
        for pair in pairs:
            if tuple(item.level for item in pair.levels) != self.scope.requested_levels:
                raise ValueError(
                    "each pair must assess exactly the scope's requested levels."
                )
        object.__setattr__(self, "pairs", pairs)

    @property
    def has_any_eligible_comparison(self) -> bool:
        return any(pair.eligible_levels for pair in self.pairs)

    @property
    def is_fully_eligible(self) -> bool:
        return bool(self.pairs) and all(pair.is_fully_eligible for pair in self.pairs)


def _eligibility_status(
    *,
    reference_available: bool,
    candidate_available: bool,
) -> LevelEligibilityStatus:
    if reference_available and candidate_available:
        return LevelEligibilityStatus.ELIGIBLE
    if reference_available:
        return LevelEligibilityStatus.CANDIDATE_UNAVAILABLE
    if candidate_available:
        return LevelEligibilityStatus.REFERENCE_UNAVAILABLE
    return LevelEligibilityStatus.BOTH_UNAVAILABLE


def assess_reconciliation_scope(
    scope: ReconciliationScope,
    evidence_profiles: Iterable[RunEvidenceProfile],
) -> ScopeAssessment:
    """Assess requested levels without inferring or repairing missing evidence.

    Exactly one evidence profile is required for each scoped run.  Missing
    *levels* are valid, typed evidence gaps.  Missing, duplicated, extra, or
    identity-mismatched *profiles* are contract errors because the caller could
    otherwise assess a different set of runs than the declared scope.
    """

    if not isinstance(scope, ReconciliationScope):
        raise ValueError("scope must be a ReconciliationScope.")
    try:
        profiles = tuple(evidence_profiles)
    except TypeError as error:
        raise ValueError("evidence_profiles must be an iterable.") from error
    if any(not isinstance(profile, RunEvidenceProfile) for profile in profiles):
        raise ValueError(
            "evidence_profiles must contain only RunEvidenceProfile values."
        )

    profile_ids = tuple(profile.run.run_id for profile in profiles)
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("evidence_profiles must contain one profile per run_id.")

    expected_runs = (scope.reference_run, *scope.candidate_runs)
    expected_by_id = {run.run_id: run for run in expected_runs}
    profiles_by_id = {profile.run.run_id: profile for profile in profiles}
    expected_ids = set(expected_by_id)
    supplied_ids = set(profiles_by_id)
    if supplied_ids != expected_ids:
        missing = sorted(expected_ids - supplied_ids)
        extra = sorted(supplied_ids - expected_ids)
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"extra={','.join(extra)}")
        raise ValueError(
            "evidence profile run_ids must exactly match the scope ("
            + "; ".join(details)
            + ")."
        )

    for run_id, expected_run in expected_by_id.items():
        if profiles_by_id[run_id].run != expected_run:
            raise ValueError(
                f"evidence profile identity does not match scoped run_id {run_id!r}."
            )

    reference_levels = set(profiles_by_id[scope.reference_run.run_id].available_levels)
    pair_assessments: list[PairScopeAssessment] = []
    for candidate in scope.candidate_runs:
        candidate_levels = set(profiles_by_id[candidate.run_id].available_levels)
        level_assessments = tuple(
            LevelEligibility(
                level=level,
                status=_eligibility_status(
                    reference_available=level in reference_levels,
                    candidate_available=level in candidate_levels,
                ),
            )
            for level in scope.requested_levels
        )
        pair_assessments.append(
            PairScopeAssessment(
                candidate_run=candidate,
                levels=level_assessments,
            )
        )

    return ScopeAssessment(scope=scope, pairs=tuple(pair_assessments))
