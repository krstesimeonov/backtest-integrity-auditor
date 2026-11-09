"""Stable V1.5H risk-assessment errors."""

from dataclasses import dataclass
from enum import StrEnum


class RiskAssessmentErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    SCOPE_MISMATCH = "scope_mismatch"
    POLICY_MISMATCH = "policy_mismatch"


@dataclass(frozen=True, slots=True)
class RiskAssessmentError(Exception):
    code: RiskAssessmentErrorCode
    message: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "code", RiskAssessmentErrorCode(self.code))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "code must be a supported RiskAssessmentErrorCode."
            ) from error
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be non-empty text.")
        object.__setattr__(self, "message", self.message.strip())
        Exception.__init__(self, f"{self.code.value}: {self.message}")


__all__ = ["RiskAssessmentError", "RiskAssessmentErrorCode"]
