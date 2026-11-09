"""Engine-adapter contracts shared by every concrete V1.5 mapper.

The objects in this module describe evidence and capabilities; they do not
import, execute, or otherwise depend on a backtesting engine.  A concrete
adapter introduced in a later increment must enter through these contracts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from backtest_auditor.implementation_risk.domain.bundle import CanonicalRunArtifacts
from backtest_auditor.implementation_risk.domain.enums import ComparisonLevel
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_optional_text,
    normalize_sha256,
    normalize_text,
)


ENGINE_EXPORT_ENVELOPE_SCHEMA_VERSION = "1.0"
ENGINE_ADAPTER_ROADMAP: tuple["SupportedEngine", ...]
_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_LEVEL_ORDER = {level: index for index, level in enumerate(ComparisonLevel)}
_MAX_IDENTIFIER_LENGTH = 128
_MAX_TEXT_LENGTH = 512


class SupportedEngine(StrEnum):
    """The accepted V1.5 adapter roadmap, in implementation order."""

    VECTORBT = "vectorbt"
    BT = "bt"
    BACKTRADER = "backtrader"
    QUANTCONNECT_LEAN = "quantconnect_lean"
    NAUTILUSTRADER = "nautilustrader"


ENGINE_ADAPTER_ROADMAP = tuple(SupportedEngine)


class CapabilityAvailability(StrEnum):
    """Static availability promised by an adapter implementation."""

    ALWAYS = "always"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"


class EvidenceOrigin(StrEnum):
    """How an adapter can obtain one canonical evidence layer."""

    ENGINE_EXPORT = "engine_export"
    DETERMINISTIC_DERIVATION = "deterministic_derivation"
    NONE = "none"


def _code(value: object, *, field: str) -> str:
    normalized = normalize_text(
        value,
        field=field,
        maximum_length=_MAX_IDENTIFIER_LENGTH,
    )
    if _CODE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            f"{field} must start with a lowercase letter and contain only "
            "lowercase letters, digits, '.', '_' or '-'."
        )
    return normalized


def _portable_path(value: object, *, field: str) -> str:
    normalized = normalize_text(value, field=field, maximum_length=512)
    if "\\" in normalized:
        raise ValueError(f"{field} must use '/' separators.")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or normalized.endswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
        or str(path) != normalized
    ):
        raise ValueError(f"{field} must be a canonical relative POSIX file path.")
    return normalized


def _normalized_levels(
    values: object,
    *,
    field: str,
    require_complete: bool = False,
) -> tuple[ComparisonLevel, ...]:
    try:
        raw_values: tuple[object, ...] = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable.") from error
    try:
        levels = tuple(
            ComparisonLevel(value)  # type: ignore[arg-type]
            for value in raw_values
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{field} contains an unsupported comparison level."
        ) from error
    if len(levels) != len(set(levels)):
        raise ValueError(f"{field} must not contain duplicates.")
    expected = tuple(sorted(levels, key=_LEVEL_ORDER.__getitem__))
    if levels != expected:
        raise ValueError(f"{field} must use canonical comparison-level order.")
    if require_complete and levels != tuple(ComparisonLevel):
        raise ValueError(f"{field} must declare every comparison level exactly once.")
    return levels


@dataclass(frozen=True, slots=True)
class AdapterCapability:
    """One adapter's static promise for one canonical evidence level."""

    level: ComparisonLevel
    availability: CapabilityAvailability
    origin: EvidenceOrigin
    explanation: str

    def __post_init__(self) -> None:
        try:
            level = ComparisonLevel(self.level)
            availability = CapabilityAvailability(self.availability)
            origin = EvidenceOrigin(self.origin)
        except (TypeError, ValueError) as error:
            raise ValueError("adapter capability enum value is unsupported.") from error
        if availability is CapabilityAvailability.UNSUPPORTED:
            if origin is not EvidenceOrigin.NONE:
                raise ValueError("unsupported capabilities must use origin='none'.")
        elif origin is EvidenceOrigin.NONE:
            raise ValueError("supported capabilities must declare an evidence origin.")
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "availability", availability)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(
            self,
            "explanation",
            normalize_text(
                self.explanation,
                field="explanation",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class EngineAdapterDescriptor:
    """Version and capability declaration for one mapper implementation."""

    adapter_id: str
    adapter_version: str
    engine: SupportedEngine
    display_name: str
    export_format_id: str
    supported_export_format_versions: tuple[str, ...]
    tested_engine_versions: tuple[str, ...]
    allow_undisclosed_engine_version: bool
    allow_untested_engine_version: bool
    capabilities: tuple[AdapterCapability, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.allow_undisclosed_engine_version, bool):
            raise ValueError("allow_undisclosed_engine_version must be a boolean.")
        if not isinstance(self.allow_untested_engine_version, bool):
            raise ValueError("allow_untested_engine_version must be a boolean.")
        object.__setattr__(
            self, "adapter_id", _code(self.adapter_id, field="adapter_id")
        )
        object.__setattr__(
            self,
            "adapter_version",
            normalize_text(
                self.adapter_version,
                field="adapter_version",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        try:
            engine = SupportedEngine(self.engine)
        except (TypeError, ValueError) as error:
            raise ValueError("engine must be a supported V1.5 engine.") from error
        object.__setattr__(self, "engine", engine)
        object.__setattr__(
            self,
            "display_name",
            normalize_text(
                self.display_name,
                field="display_name",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "export_format_id",
            _code(self.export_format_id, field="export_format_id"),
        )
        object.__setattr__(
            self,
            "supported_export_format_versions",
            _normalized_versions(
                self.supported_export_format_versions,
                field="supported_export_format_versions",
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "tested_engine_versions",
            _normalized_versions(
                self.tested_engine_versions,
                field="tested_engine_versions",
                allow_empty=self.allow_untested_engine_version,
            ),
        )
        try:
            capabilities = tuple(self.capabilities)
        except TypeError as error:
            raise ValueError("capabilities must be an iterable.") from error
        if any(not isinstance(item, AdapterCapability) for item in capabilities):
            raise ValueError("capabilities must contain only AdapterCapability values.")
        levels = _normalized_levels(
            (item.level for item in capabilities),
            field="capabilities",
            require_complete=True,
        )
        if levels != tuple(item.level for item in capabilities):
            raise ValueError("capabilities must use canonical comparison-level order.")
        object.__setattr__(self, "capabilities", capabilities)

    def capability_for(self, level: ComparisonLevel) -> AdapterCapability:
        normalized = ComparisonLevel(level)
        return self.capabilities[_LEVEL_ORDER[normalized]]


def _normalized_versions(
    values: object,
    *,
    field: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    try:
        raw_values: tuple[object, ...] = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable.") from error
    normalized = tuple(
        normalize_text(value, field=field, maximum_length=_MAX_IDENTIFIER_LENGTH)
        for value in raw_values
    )
    if not allow_empty and not normalized:
        raise ValueError(f"{field} must contain at least one version.")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must not contain duplicates.")
    if normalized != tuple(sorted(normalized)):
        raise ValueError(f"{field} must use lexical canonical order.")
    return normalized


@dataclass(frozen=True, slots=True)
class EngineExportFile:
    """Content identity and semantic role of one raw export payload."""

    path: str
    role: str
    media_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _portable_path(self.path, field="path"))
        object.__setattr__(self, "role", _code(self.role, field="role"))
        object.__setattr__(
            self,
            "media_type",
            normalize_text(
                self.media_type,
                field="media_type",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative integer.")
        object.__setattr__(
            self,
            "sha256",
            normalize_sha256(self.sha256, field="sha256"),
        )


def _envelope_identity_body(
    *,
    run_id: str,
    engine: SupportedEngine,
    engine_version: str | None,
    export_format_id: str,
    export_format_version: str,
    declared_levels: tuple[ComparisonLevel, ...],
    files: tuple[EngineExportFile, ...],
) -> dict[str, object]:
    return {
        "envelope_schema_version": ENGINE_EXPORT_ENVELOPE_SCHEMA_VERSION,
        "run_id": run_id,
        "engine": engine.value,
        "engine_version": engine_version,
        "export_format_id": export_format_id,
        "export_format_version": export_format_version,
        "declared_levels": [level.value for level in declared_levels],
        "files": [
            {
                "path": item.path,
                "role": item.role,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in files
        ],
    }


def _identity_sha256(value: object) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class EngineExportEnvelope:
    """Strict metadata envelope around one engine-native export."""

    run_id: str
    engine: SupportedEngine
    engine_version: str | None
    export_format_id: str
    export_format_version: str
    declared_levels: tuple[ComparisonLevel, ...]
    files: tuple[EngineExportFile, ...]
    source_sha256: str
    envelope_schema_version: str = ENGINE_EXPORT_ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.envelope_schema_version != ENGINE_EXPORT_ENVELOPE_SCHEMA_VERSION:
            raise ValueError(
                "envelope_schema_version must equal "
                f"{ENGINE_EXPORT_ENVELOPE_SCHEMA_VERSION!r}."
            )
        run_id = normalize_text(
            self.run_id,
            field="run_id",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        try:
            engine = SupportedEngine(self.engine)
        except (TypeError, ValueError) as error:
            raise ValueError("engine must be a supported V1.5 engine.") from error
        engine_version = normalize_optional_text(
            self.engine_version,
            field="engine_version",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        export_format_id = _code(self.export_format_id, field="export_format_id")
        export_format_version = normalize_text(
            self.export_format_version,
            field="export_format_version",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        declared_levels = _normalized_levels(
            self.declared_levels,
            field="declared_levels",
        )
        try:
            files = tuple(self.files)
        except TypeError as error:
            raise ValueError("files must be an iterable.") from error
        if not files:
            raise ValueError("files must contain at least one export payload.")
        if any(not isinstance(item, EngineExportFile) for item in files):
            raise ValueError("files must contain only EngineExportFile values.")
        paths = tuple(item.path for item in files)
        if paths != tuple(sorted(paths)):
            raise ValueError("files must use canonical path order.")
        if len(paths) != len(set(paths)):
            raise ValueError("files must not contain duplicate paths.")
        source_sha256 = normalize_sha256(
            self.source_sha256,
            field="source_sha256",
        )
        expected_sha256 = _identity_sha256(
            _envelope_identity_body(
                run_id=run_id,
                engine=engine,
                engine_version=engine_version,
                export_format_id=export_format_id,
                export_format_version=export_format_version,
                declared_levels=declared_levels,
                files=files,
            )
        )
        if source_sha256 != expected_sha256:
            raise ValueError(
                "source_sha256 must match the canonical envelope and file inventory."
            )
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "engine", engine)
        object.__setattr__(self, "engine_version", engine_version)
        object.__setattr__(self, "export_format_id", export_format_id)
        object.__setattr__(self, "export_format_version", export_format_version)
        object.__setattr__(self, "declared_levels", declared_levels)
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "source_sha256", source_sha256)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        engine: SupportedEngine,
        engine_version: str | None,
        export_format_id: str,
        export_format_version: str,
        declared_levels: tuple[ComparisonLevel, ...],
        files: tuple[EngineExportFile, ...],
    ) -> "EngineExportEnvelope":
        """Create an envelope while calculating provenance automatically."""

        normalized_engine = SupportedEngine(engine)
        normalized_run_id = normalize_text(
            run_id,
            field="run_id",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        normalized_engine_version = normalize_optional_text(
            engine_version,
            field="engine_version",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        normalized_format_id = _code(export_format_id, field="export_format_id")
        normalized_format_version = normalize_text(
            export_format_version,
            field="export_format_version",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        raw_levels = tuple(ComparisonLevel(level) for level in declared_levels)
        normalized_levels = tuple(sorted(raw_levels, key=_LEVEL_ORDER.__getitem__))
        if len(normalized_levels) != len(set(normalized_levels)):
            raise ValueError("declared_levels must not contain duplicates.")
        normalized_files = tuple(sorted(tuple(files), key=lambda item: item.path))
        body = _envelope_identity_body(
            run_id=normalized_run_id,
            engine=normalized_engine,
            engine_version=normalized_engine_version,
            export_format_id=normalized_format_id,
            export_format_version=normalized_format_version,
            declared_levels=normalized_levels,
            files=normalized_files,
        )
        return cls(
            run_id=normalized_run_id,
            engine=normalized_engine,
            engine_version=normalized_engine_version,
            export_format_id=normalized_format_id,
            export_format_version=normalized_format_version,
            declared_levels=normalized_levels,
            files=normalized_files,
            source_sha256=_identity_sha256(body),
        )


@dataclass(frozen=True, slots=True)
class EngineExportPayload:
    """Immutable bytes for one verified engine-export file."""

    path: str
    role: str
    media_type: str
    data: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _portable_path(self.path, field="path"))
        object.__setattr__(self, "role", _code(self.role, field="role"))
        object.__setattr__(
            self,
            "media_type",
            normalize_text(
                self.media_type,
                field="media_type",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        if not isinstance(self.data, bytes):
            raise ValueError("data must be immutable bytes.")

    def file_identity(self) -> EngineExportFile:
        return EngineExportFile(
            path=self.path,
            role=self.role,
            media_type=self.media_type,
            size_bytes=len(self.data),
            sha256=hashlib.sha256(self.data).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class VerifiedEngineExport:
    """A source export whose payload bytes match its provenance envelope."""

    envelope: EngineExportEnvelope
    payloads: tuple[EngineExportPayload, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EngineExportEnvelope):
            raise ValueError("envelope must be an EngineExportEnvelope.")
        try:
            payloads = tuple(self.payloads)
        except TypeError as error:
            raise ValueError("payloads must be an iterable.") from error
        if any(not isinstance(item, EngineExportPayload) for item in payloads):
            raise ValueError("payloads must contain only EngineExportPayload values.")
        paths = tuple(item.path for item in payloads)
        if paths != tuple(sorted(paths)):
            raise ValueError("payloads must use canonical path order.")
        if len(paths) != len(set(paths)):
            raise ValueError("payloads must not contain duplicate paths.")
        identities = tuple(item.file_identity() for item in payloads)
        if identities != self.envelope.files:
            raise ValueError(
                "payload bytes and metadata must exactly match envelope files."
            )
        object.__setattr__(self, "payloads", payloads)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        engine: SupportedEngine,
        engine_version: str | None,
        export_format_id: str,
        export_format_version: str,
        declared_levels: tuple[ComparisonLevel, ...],
        payloads: tuple[EngineExportPayload, ...],
    ) -> "VerifiedEngineExport":
        """Build a verified export while calculating every SHA-256 value."""

        ordered = tuple(sorted(tuple(payloads), key=lambda item: item.path))
        envelope = EngineExportEnvelope.create(
            run_id=run_id,
            engine=engine,
            engine_version=engine_version,
            export_format_id=export_format_id,
            export_format_version=export_format_version,
            declared_levels=declared_levels,
            files=tuple(item.file_identity() for item in ordered),
        )
        return cls(envelope=envelope, payloads=ordered)

    def payload(self, path: str) -> EngineExportPayload:
        normalized = _portable_path(path, field="path")
        for item in self.payloads:
            if item.path == normalized:
                return item
        raise KeyError(f"engine export contains no payload {normalized!r}.")

    def payloads_for_role(self, role: str) -> tuple[EngineExportPayload, ...]:
        normalized = _code(role, field="role")
        return tuple(item for item in self.payloads if item.role == normalized)


@dataclass(frozen=True, slots=True)
class AdapterWarning:
    """Non-fatal, machine-readable limitation retained in a successful import."""

    code: str
    message: str
    file_path: str | None = None
    row_number: int | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _code(self.code, field="code"))
        object.__setattr__(
            self,
            "message",
            normalize_text(
                self.message,
                field="message",
                maximum_length=2_000,
            ),
        )
        if self.file_path is not None:
            object.__setattr__(
                self,
                "file_path",
                _portable_path(self.file_path, field="file_path"),
            )
        if self.row_number is not None and (
            isinstance(self.row_number, bool)
            or not isinstance(self.row_number, int)
            or self.row_number < 1
        ):
            raise ValueError("row_number must be a positive integer or None.")
        if self.field is not None:
            object.__setattr__(
                self,
                "field",
                normalize_text(
                    self.field,
                    field="field",
                    maximum_length=_MAX_IDENTIFIER_LENGTH,
                ),
            )

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            self.code,
            self.file_path or "",
            self.row_number or 0,
            self.field or "",
            self.message,
        )


@dataclass(frozen=True, slots=True)
class EngineMappingOutput:
    """Untrusted normalized output returned by a concrete engine mapper."""

    artifacts: CanonicalRunArtifacts
    warnings: tuple[AdapterWarning, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, CanonicalRunArtifacts):
            raise ValueError("artifacts must be CanonicalRunArtifacts.")
        try:
            warnings = tuple(self.warnings)
        except TypeError as error:
            raise ValueError("warnings must be an iterable.") from error
        if any(not isinstance(item, AdapterWarning) for item in warnings):
            raise ValueError("warnings must contain only AdapterWarning values.")
        if warnings != tuple(sorted(warnings, key=lambda item: item.sort_key)):
            raise ValueError("warnings must use canonical order.")
        if len(warnings) != len(set(warnings)):
            raise ValueError("warnings must not contain duplicates.")
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True, slots=True)
class EngineAdapterResult:
    """Fully validated adapter result returned by the D1 orchestration service."""

    descriptor: EngineAdapterDescriptor
    export: EngineExportEnvelope
    artifacts: CanonicalRunArtifacts
    canonical_bundle_sha256: str
    warnings: tuple[AdapterWarning, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, EngineAdapterDescriptor):
            raise ValueError("descriptor must be an EngineAdapterDescriptor.")
        if not isinstance(self.export, EngineExportEnvelope):
            raise ValueError("export must be an EngineExportEnvelope.")
        if not isinstance(self.artifacts, CanonicalRunArtifacts):
            raise ValueError("artifacts must be CanonicalRunArtifacts.")
        object.__setattr__(
            self,
            "canonical_bundle_sha256",
            normalize_sha256(
                self.canonical_bundle_sha256,
                field="canonical_bundle_sha256",
            ),
        )
        try:
            warnings = tuple(self.warnings)
        except TypeError as error:
            raise ValueError("warnings must be an iterable.") from error
        if any(not isinstance(item, AdapterWarning) for item in warnings):
            raise ValueError("warnings must contain only AdapterWarning values.")
        if warnings != tuple(sorted(warnings, key=lambda item: item.sort_key)):
            raise ValueError("warnings must use canonical order.")
        if len(warnings) != len(set(warnings)):
            raise ValueError("warnings must not contain duplicates.")
        object.__setattr__(self, "warnings", warnings)
