from dataclasses import dataclass
from enum import StrEnum


class EvidenceStatus(StrEnum):
    """Categorical interpretation for one independent evidence dimension."""

    INELIGIBLE = "ineligible"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    FRAGILE = "fragile"
    SUPPORTED_UNDER_STATED_ASSUMPTIONS = "supported_under_stated_assumptions"


class EvidenceDimensionName(StrEnum):
    INPUT_INTEGRITY = "input_integrity"
    RETURN_METHODOLOGY = "return_methodology"
    SAMPLING_ELIGIBILITY = "sampling_eligibility"
    STATISTICAL_EVIDENCE = "statistical_evidence"
    SERIAL_ROBUSTNESS = "serial_robustness"
    RESAMPLING_ROBUSTNESS = "resampling_robustness"
    BENCHMARK_EVIDENCE = "benchmark_evidence"
    EXPERIMENT_COMPLETENESS = "experiment_completeness"
    MULTIPLE_TESTING_EVIDENCE = "multiple_testing_evidence"
    PARAMETER_ROBUSTNESS = "parameter_robustness"
    TEMPORAL_ROBUSTNESS = "temporal_robustness"
    REPRODUCIBILITY = "reproducibility"


@dataclass(frozen=True, slots=True)
class EvidenceDimensionResult:
    dimension: EvidenceDimensionName
    status: EvidenceStatus
    summary: str
    supporting_evidence_codes: tuple[str, ...] = ()
    adverse_evidence_codes: tuple[str, ...] = ()
    unavailable_evidence_codes: tuple[str, ...] = ()
    assumption_codes: tuple[str, ...] = ()
    next_evidence_required: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceProfileResult:
    method: str
    audit_type: str
    dimensions: tuple[EvidenceDimensionResult, ...]
    interpretation_boundary: str


EVIDENCE_PROFILE_METHOD = "dimensioned_evidence_profile_v1"
EVIDENCE_PROFILE_BOUNDARY = (
    "Each dimension is independent. No numeric score or global pass/fail is "
    "calculated, and no status certifies skill, profit, or future performance."
)
