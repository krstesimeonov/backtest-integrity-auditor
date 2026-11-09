from dataclasses import dataclass
from enum import StrEnum


class FindingCategory(StrEnum):
    DATA_QUALITY = "data_quality"
    SAMPLE_SUFFICIENCY = "sample_sufficiency"
    STATISTICAL_EVIDENCE = "statistical_evidence"
    SELECTION_BIAS = "selection_bias"
    ROBUSTNESS = "robustness"
    METHODOLOGICAL_RISK = "methodological_risk"


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    category: FindingCategory

    claim: str
    implication: str
    remediation: str | None = None
