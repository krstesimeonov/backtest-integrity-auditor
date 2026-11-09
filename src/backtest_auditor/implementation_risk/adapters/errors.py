"""Typed failures for the canonical file-bundle boundary."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class BundleErrorCode(StrEnum):
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_TYPE_UNSUPPORTED = "source_type_unsupported"
    DESTINATION_EXISTS = "destination_exists"
    DESTINATION_TYPE_UNSUPPORTED = "destination_type_unsupported"
    UNSAFE_ARCHIVE = "unsafe_archive"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    MISSING_MANIFEST = "missing_manifest"
    INVALID_JSON = "invalid_json"
    INVALID_MANIFEST = "invalid_manifest"
    INVALID_SPECIFICATION = "invalid_specification"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    UNDECLARED_FILE = "undeclared_file"
    MISSING_FILE = "missing_file"
    SIZE_MISMATCH = "size_mismatch"
    HASH_MISMATCH = "hash_mismatch"
    HEADER_MISMATCH = "header_mismatch"
    INVALID_ROW = "invalid_row"
    RECORD_COUNT_MISMATCH = "record_count_mismatch"
    DOMAIN_VALIDATION_FAILED = "domain_validation_failed"
    WRITE_FAILED = "write_failed"


@dataclass(frozen=True, slots=True)
class BundleContractError(ValueError):
    """One fail-closed bundle error with stable machine-readable context."""

    code: BundleErrorCode
    message: str
    file_path: str | None = None
    row_number: int | None = None
    field: str | None = None

    def __str__(self) -> str:
        context: list[str] = []
        if self.file_path is not None:
            context.append(f"file={self.file_path}")
        if self.row_number is not None:
            context.append(f"row={self.row_number}")
        if self.field is not None:
            context.append(f"field={self.field}")
        suffix = f" ({', '.join(context)})" if context else ""
        return f"{self.code.value}: {self.message}{suffix}"


def describe_name_difference(
    expected: Iterable[str],
    actual: Iterable[str],
    *,
    noun: str,
) -> tuple[str, str | None]:
    """Name what differs between a contract's names and the supplied ones.

    Returns a description for the error message and the name to report as the
    error's field: the first missing name, else the first unexpected one.
    """

    expected_names = tuple(expected)
    actual_names = tuple(actual)
    missing = [name for name in expected_names if name not in actual_names]
    unexpected = [name for name in actual_names if name not in expected_names]
    parts: list[str] = []
    for label, names in (("missing", missing), ("unexpected", unexpected)):
        if names:
            plural = noun if len(names) == 1 else f"{noun}s"
            quoted = ", ".join(repr(name) for name in names)
            parts.append(f"{label} {plural} {quoted}")
    if not parts:
        parts.append(f"{noun}s are duplicated or out of order")
    field = missing[0] if missing else (unexpected[0] if unexpected else None)
    return "; ".join(parts), field
