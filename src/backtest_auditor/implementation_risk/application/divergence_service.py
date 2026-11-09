"""Measure V1.5G divergence without thresholds, scoring, or attribution."""

from backtest_auditor.implementation_risk.application.divergence_errors import (
    DivergenceError,
    DivergenceErrorCode,
)
from backtest_auditor.implementation_risk.domain import (
    CandidateDivergence,
    ComparisonLevel,
    DivergenceFamily,
    DivergenceMeasurementPolicy,
    DivergenceObservation,
    DivergenceStatus,
    FamilyDivergence,
    LevelComparison,
    LevelComparisonStatus,
    ReconciliationComparison,
    ReconciliationDivergence,
    RecordComparisonStatus,
    divergence_policy_sha256,
)


class DivergenceMeasurementService:
    """Project exact numeric differences into implementation-risk families."""

    def measure(
        self,
        comparison: ReconciliationComparison,
        policy: DivergenceMeasurementPolicy,
    ) -> ReconciliationDivergence:
        if not isinstance(comparison, ReconciliationComparison):
            raise DivergenceError(
                DivergenceErrorCode.INVALID_INPUT,
                "comparison must be a ReconciliationComparison.",
            )
        if not isinstance(policy, DivergenceMeasurementPolicy):
            raise DivergenceError(
                DivergenceErrorCode.INVALID_INPUT,
                "policy must be a DivergenceMeasurementPolicy.",
            )
        if policy.reconciliation_id != comparison.scope.reconciliation_id:
            raise DivergenceError(
                DivergenceErrorCode.SCOPE_MISMATCH,
                "policy reconciliation_id must match the comparison scope.",
            )
        requested = set(comparison.scope.requested_levels)
        if any(rule.level not in requested for rule in policy.rules):
            raise DivergenceError(
                DivergenceErrorCode.POLICY_MISMATCH,
                "every measurement rule level must be requested by the comparison scope.",
            )
        candidates = tuple(
            CandidateDivergence(
                candidate.candidate_run,
                tuple(
                    self._family(candidate.levels, policy, family)
                    for family in DivergenceFamily
                ),
            )
            for candidate in comparison.candidates
        )
        return ReconciliationDivergence(
            comparison.scope,
            comparison.normalization_plan_sha256,
            comparison.comparison_policy_sha256,
            divergence_policy_sha256(policy),
            candidates,
        )

    @staticmethod
    def _family(
        levels: tuple[LevelComparison, ...],
        policy: DivergenceMeasurementPolicy,
        family: DivergenceFamily,
    ) -> FamilyDivergence:
        rules = tuple(item for item in policy.rules if item.family is family)
        if not rules:
            return FamilyDivergence(
                family, DivergenceStatus.NOT_REQUESTED, (), 0, 0, 0, 0, 0
            )
        level_by_name = {item.level: item for item in levels}
        fields_by_level: dict[ComparisonLevel, set[str]] = {}
        for rule in rules:
            fields_by_level.setdefault(rule.level, set()).add(rule.field)
        observations: list[DivergenceObservation] = []
        equal = non_numeric = one_sided = ambiguous = unavailable = 0
        for level_name, selected_fields in fields_by_level.items():
            level = level_by_name[level_name]
            if level.status is not LevelComparisonStatus.COMPARED:
                unavailable += 1
                continue
            for record in level.records:
                if record.status is RecordComparisonStatus.MATCHED_EQUAL:
                    equal += 1
                elif record.status in {
                    RecordComparisonStatus.REFERENCE_ONLY,
                    RecordComparisonStatus.CANDIDATE_ONLY,
                }:
                    one_sided += 1
                elif record.status is RecordComparisonStatus.AMBIGUOUS:
                    ambiguous += 1
                else:
                    for difference in record.differences:
                        if difference.field not in selected_fields:
                            continue
                        if difference.decimal_delta is None:
                            non_numeric += 1
                        else:
                            observations.append(
                                DivergenceObservation(
                                    family,
                                    level.level,
                                    record.alignment_key,
                                    difference.field,
                                    difference.reference_value,
                                    difference.candidate_value,
                                    difference.decimal_delta,
                                )
                            )
        impaired = non_numeric + one_sided + ambiguous + unavailable
        status = DivergenceStatus.PARTIAL if impaired else DivergenceStatus.MEASURED
        if unavailable == len(fields_by_level):
            status = DivergenceStatus.UNAVAILABLE
        return FamilyDivergence(
            family,
            status,
            tuple(sorted(observations, key=lambda item: item.sort_key)),
            equal,
            non_numeric,
            one_sided,
            ambiguous,
            unavailable,
        )


__all__ = ["DivergenceMeasurementService"]
