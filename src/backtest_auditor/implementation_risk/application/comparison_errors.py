"""Typed fail-closed errors for V1.5F alignment and comparison."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest_auditor.implementation_risk.domain.enums import ComparisonLevel


class ComparisonErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    SCOPE_MISMATCH = "scope_mismatch"
    POLICY_MISMATCH = "policy_mismatch"
    NORMALIZED_INPUT_MISMATCH = "normalized_input_mismatch"
    ALIGNMENT_FAILED = "alignment_failed"


@dataclass(frozen=True, slots=True)
class ComparisonError(ValueError):
    code: ComparisonErrorCode
    message: str
    candidate_run_id: str | None = None
    level: ComparisonLevel | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "code", ComparisonErrorCode(self.code))
        except (TypeError, ValueError) as error:
            raise ValueError("code must be a supported ComparisonErrorCode.") from error
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be non-empty text.")
        object.__setattr__(self, "message", self.message.strip())
        if self.candidate_run_id is not None:
            if (
                not isinstance(self.candidate_run_id, str)
                or not self.candidate_run_id.strip()
            ):
                raise ValueError("candidate_run_id must be non-empty text or None.")
            object.__setattr__(
                self,
                "candidate_run_id",
                self.candidate_run_id.strip(),
            )
        if self.level is not None:
            try:
                object.__setattr__(self, "level", ComparisonLevel(self.level))
            except (TypeError, ValueError) as error:
                raise ValueError("level must be a ComparisonLevel or None.") from error

    def __str__(self) -> str:
        context = []
        if self.candidate_run_id is not None:
            context.append(f"candidate={self.candidate_run_id}")
        if self.level is not None:
            context.append(f"level={self.level.value}")
        suffix = f" ({', '.join(context)})" if context else ""
        return f"{self.code.value}: {self.message}{suffix}"


__all__ = ["ComparisonError", "ComparisonErrorCode"]
