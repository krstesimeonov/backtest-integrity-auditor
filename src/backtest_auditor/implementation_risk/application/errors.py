"""Typed fatal failures shared by engine adapters and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backtest_auditor.implementation_risk.domain.engine_adapters import (
    SupportedEngine,
)


class EngineAdapterErrorCode(StrEnum):
    """Stable fatal categories for every concrete engine adapter."""

    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_TYPE_UNSUPPORTED = "source_type_unsupported"
    UNSAFE_ARCHIVE = "unsafe_archive"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    MISSING_ENVELOPE = "missing_envelope"
    INVALID_JSON = "invalid_json"
    INVALID_ENVELOPE = "invalid_envelope"
    UNSUPPORTED_ENVELOPE_VERSION = "unsupported_envelope_version"
    MISSING_FILE = "missing_file"
    UNDECLARED_FILE = "undeclared_file"
    SIZE_MISMATCH = "size_mismatch"
    HASH_MISMATCH = "hash_mismatch"
    ENGINE_MISMATCH = "engine_mismatch"
    EXPORT_FORMAT_MISMATCH = "export_format_mismatch"
    UNSUPPORTED_EXPORT_FORMAT_VERSION = "unsupported_export_format_version"
    ENGINE_VERSION_UNDISCLOSED = "engine_version_undisclosed"
    UNTESTED_ENGINE_VERSION = "untested_engine_version"
    CAPABILITY_CONTRACT_VIOLATION = "capability_contract_violation"
    ADAPTER_NOT_FOUND = "adapter_not_found"
    DUPLICATE_ADAPTER = "duplicate_adapter"
    MAPPING_FAILED = "mapping_failed"
    OUTPUT_CONTRACT_VIOLATION = "output_contract_violation"
    WRITE_FAILED = "write_failed"


@dataclass(frozen=True, slots=True)
class EngineAdapterError(ValueError):
    """A fatal adapter failure distinct from retained non-fatal warnings."""

    code: EngineAdapterErrorCode
    message: str
    engine: SupportedEngine | None = None
    adapter_id: str | None = None
    engine_error_code: str | None = None
    file_path: str | None = None
    row_number: int | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        try:
            code = EngineAdapterErrorCode(self.code)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "code must be a supported EngineAdapterErrorCode."
            ) from error
        object.__setattr__(self, "code", code)
        if self.engine is not None:
            try:
                object.__setattr__(self, "engine", SupportedEngine(self.engine))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "engine must be a supported engine or None."
                ) from error
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string.")
        object.__setattr__(self, "message", self.message.strip())
        for name in ("adapter_id", "engine_error_code", "file_path", "field"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string or None.")
            if isinstance(value, str):
                object.__setattr__(self, name, value.strip())
        if self.row_number is not None and (
            isinstance(self.row_number, bool)
            or not isinstance(self.row_number, int)
            or self.row_number < 1
        ):
            raise ValueError("row_number must be a positive integer or None.")

    def __str__(self) -> str:
        context: list[str] = []
        if self.engine is not None:
            context.append(f"engine={self.engine.value}")
        if self.adapter_id is not None:
            context.append(f"adapter={self.adapter_id}")
        if self.engine_error_code is not None:
            context.append(f"engine_error={self.engine_error_code}")
        if self.file_path is not None:
            context.append(f"file={self.file_path}")
        if self.row_number is not None:
            context.append(f"row={self.row_number}")
        if self.field is not None:
            context.append(f"field={self.field}")
        suffix = f" ({', '.join(context)})" if context else ""
        return f"{self.code.value}: {self.message}{suffix}"
