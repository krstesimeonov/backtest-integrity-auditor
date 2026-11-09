"""Stable errors for V1.5G divergence measurement."""

from dataclasses import dataclass
from enum import StrEnum


class DivergenceErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    SCOPE_MISMATCH = "scope_mismatch"
    POLICY_MISMATCH = "policy_mismatch"


@dataclass(frozen=True, slots=True)
class DivergenceError(Exception):
    code: DivergenceErrorCode
    message: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "code", DivergenceErrorCode(self.code))
        except (TypeError, ValueError) as error:
            raise ValueError("code must be a supported DivergenceErrorCode.") from error
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be non-empty text.")
        object.__setattr__(self, "message", self.message.strip())
        Exception.__init__(self, f"{self.code.value}: {self.message}")


__all__ = ["DivergenceError", "DivergenceErrorCode"]
