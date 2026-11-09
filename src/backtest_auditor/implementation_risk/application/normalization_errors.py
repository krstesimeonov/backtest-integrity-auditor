"""Typed fail-closed errors for V1.5E reconciliation normalization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest_auditor.implementation_risk.domain.enums import ComparisonLevel


class NormalizationErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    SCOPE_MISMATCH = "scope_mismatch"
    POLICY_MISMATCH = "policy_mismatch"
    MISSING_INSTRUMENT_RULE = "missing_instrument_rule"
    UNEXPECTED_INSTRUMENT_RULE = "unexpected_instrument_rule"
    MISSING_CURRENCY_RULE = "missing_currency_rule"
    UNEXPECTED_CURRENCY_RULE = "unexpected_currency_rule"
    STRATEGY_IDENTITY_MISMATCH = "strategy_identity_mismatch"
    INSTRUMENT_METADATA_MISMATCH = "instrument_metadata_mismatch"
    FREQUENCY_MISMATCH = "frequency_mismatch"
    TIMESTAMP_OVERFLOW = "timestamp_overflow"
    NORMALIZED_CONTRACT_VIOLATION = "normalized_contract_violation"
    IDENTITY_FAILED = "identity_failed"


@dataclass(frozen=True, slots=True)
class NormalizationError(ValueError):
    code: NormalizationErrorCode
    message: str
    run_id: str | None = None
    level: ComparisonLevel | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "code", NormalizationErrorCode(self.code))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "code must be a supported NormalizationErrorCode."
            ) from error
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be non-empty text.")
        object.__setattr__(self, "message", self.message.strip())
        if self.level is not None:
            try:
                object.__setattr__(self, "level", ComparisonLevel(self.level))
            except (TypeError, ValueError) as error:
                raise ValueError("level must be a ComparisonLevel or None.") from error
        for field_name in ("run_id", "field"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be non-empty text or None.")
            if isinstance(value, str):
                object.__setattr__(self, field_name, value.strip())

    def __str__(self) -> str:
        context = []
        if self.run_id is not None:
            context.append(f"run={self.run_id}")
        if self.level is not None:
            context.append(f"level={self.level.value}")
        if self.field is not None:
            context.append(f"field={self.field}")
        suffix = f" ({', '.join(context)})" if context else ""
        return f"{self.code.value}: {self.message}{suffix}"


__all__ = ["NormalizationError", "NormalizationErrorCode"]
