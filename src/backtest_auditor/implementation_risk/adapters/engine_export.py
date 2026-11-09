"""Strict directory/ZIP transport for the common engine-export envelope."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from backtest_auditor.implementation_risk.application.errors import (
    EngineAdapterError,
    EngineAdapterErrorCode,
)
from backtest_auditor.implementation_risk.domain.engine_adapters import (
    ENGINE_EXPORT_ENVELOPE_SCHEMA_VERSION,
    EngineExportEnvelope,
    EngineExportFile,
    EngineExportPayload,
    SupportedEngine,
    VerifiedEngineExport,
)
from backtest_auditor.implementation_risk.domain.enums import ComparisonLevel


ENGINE_EXPORT_ENVELOPE_FILE = "engine-export.json"
_MAX_FILES = 64
_MAX_MANIFEST_BYTES = 1_000_000
_MAX_FILE_BYTES = 512_000_000
_MAX_TOTAL_BYTES = 1_000_000_000
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def engine_export_envelope_to_json(
    envelope: EngineExportEnvelope,
) -> dict[str, object]:
    """Return the canonical JSON-compatible representation of an envelope."""

    if not isinstance(envelope, EngineExportEnvelope):
        raise ValueError("envelope must be an EngineExportEnvelope.")
    return {
        "envelope_schema_version": envelope.envelope_schema_version,
        "run_id": envelope.run_id,
        "engine": envelope.engine.value,
        "engine_version": envelope.engine_version,
        "export_format_id": envelope.export_format_id,
        "export_format_version": envelope.export_format_version,
        "declared_levels": [level.value for level in envelope.declared_levels],
        "files": [
            {
                "path": item.path,
                "role": item.role,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in envelope.files
        ],
        "source_sha256": envelope.source_sha256,
    }


def _error(
    code: EngineAdapterErrorCode,
    message: str,
    *,
    engine: SupportedEngine | None = None,
    file_path: str | None = None,
    field: str | None = None,
) -> NoReturn:
    raise EngineAdapterError(
        code=code,
        message=message,
        engine=engine,
        file_path=file_path,
        field=field,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key!r}.")
        value[key] = item
    return value


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed.")


def _parse_json(data: bytes) -> object:
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EngineAdapterError(
            EngineAdapterErrorCode.INVALID_JSON,
            str(error),
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
        ) from error
    if _json_bytes(value) != data:
        _error(
            EngineAdapterErrorCode.INVALID_JSON,
            "envelope JSON must use canonical UTF-8 serialization.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
        )
    return value


def _object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _error(
            EngineAdapterErrorCode.INVALID_ENVELOPE,
            "value must be a JSON object.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field=field,
        )
    return value


def _list(value: object, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        _error(
            EngineAdapterErrorCode.INVALID_ENVELOPE,
            "value must be a JSON array.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field=field,
        )
    return value


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        _error(
            EngineAdapterErrorCode.INVALID_ENVELOPE,
            "value must be a string.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field=field,
        )
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _error(
            EngineAdapterErrorCode.INVALID_ENVELOPE,
            "value must be a non-negative integer.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field=field,
        )
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], *, field: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        _error(
            EngineAdapterErrorCode.INVALID_ENVELOPE,
            "object keys must match exactly (" + "; ".join(details) + ").",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field=field,
        )


def engine_export_envelope_from_json(value: object) -> EngineExportEnvelope:
    """Decode one strict JSON envelope into the immutable domain contract."""

    root = _object(value, field="root")
    _exact_keys(
        root,
        {
            "envelope_schema_version",
            "run_id",
            "engine",
            "engine_version",
            "export_format_id",
            "export_format_version",
            "declared_levels",
            "files",
            "source_sha256",
        },
        field="root",
    )
    version = _string(
        root["envelope_schema_version"],
        field="envelope_schema_version",
    )
    if version != ENGINE_EXPORT_ENVELOPE_SCHEMA_VERSION:
        _error(
            EngineAdapterErrorCode.UNSUPPORTED_ENVELOPE_VERSION,
            f"engine-export envelope schema {version!r} is unsupported.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field="envelope_schema_version",
        )
    raw_files = _list(root["files"], field="files")
    if len(raw_files) > _MAX_FILES:
        _error(
            EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "envelope declares too many payload files.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field="files",
        )
    files: list[EngineExportFile] = []
    for index, raw_file in enumerate(raw_files):
        field = f"files[{index}]"
        item = _object(raw_file, field=field)
        _exact_keys(
            item,
            {"path", "role", "media_type", "size_bytes", "sha256"},
            field=field,
        )
        size_bytes = _integer(item["size_bytes"], field=f"{field}.size_bytes")
        if size_bytes > _MAX_FILE_BYTES:
            _error(
                EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "declared payload exceeds the per-file safety limit.",
                file_path=ENGINE_EXPORT_ENVELOPE_FILE,
                field=f"{field}.size_bytes",
            )
        try:
            files.append(
                EngineExportFile(
                    path=_string(item["path"], field=f"{field}.path"),
                    role=_string(item["role"], field=f"{field}.role"),
                    media_type=_string(
                        item["media_type"],
                        field=f"{field}.media_type",
                    ),
                    size_bytes=size_bytes,
                    sha256=_string(item["sha256"], field=f"{field}.sha256"),
                )
            )
        except ValueError as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.INVALID_ENVELOPE,
                str(error),
                file_path=ENGINE_EXPORT_ENVELOPE_FILE,
                field=field,
            ) from error
    if sum(item.size_bytes for item in files) > _MAX_TOTAL_BYTES:
        _error(
            EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "declared export exceeds the total safety limit.",
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
            field="files",
        )
    try:
        engine = SupportedEngine(_string(root["engine"], field="engine"))
        levels = tuple(
            ComparisonLevel(_string(item, field=f"declared_levels[{index}]"))
            for index, item in enumerate(
                _list(root["declared_levels"], field="declared_levels")
            )
        )
        return EngineExportEnvelope(
            run_id=_string(root["run_id"], field="run_id"),
            engine=engine,
            engine_version=_optional_string(
                root["engine_version"],
                field="engine_version",
            ),
            export_format_id=_string(
                root["export_format_id"],
                field="export_format_id",
            ),
            export_format_version=_string(
                root["export_format_version"],
                field="export_format_version",
            ),
            declared_levels=levels,
            files=tuple(files),
            source_sha256=_string(root["source_sha256"], field="source_sha256"),
            envelope_schema_version=version,
        )
    except (TypeError, ValueError) as error:
        raise EngineAdapterError(
            EngineAdapterErrorCode.INVALID_ENVELOPE,
            str(error),
            file_path=ENGINE_EXPORT_ENVELOPE_FILE,
        ) from error


def _safe_archive_path(value: str) -> bool:
    if "\\" in value or value.endswith("/"):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and str(path) == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _read_directory(source: Path) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    try:
        entries = tuple(sorted(source.rglob("*")))
    except OSError as error:
        raise EngineAdapterError(
            EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED,
            "engine-export directory could not be inspected.",
        ) from error
    files = tuple(item for item in entries if not item.is_dir())
    if len(files) > _MAX_FILES + 1:
        _error(
            EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "engine-export directory contains too many files.",
        )
    total_size = 0
    for path in entries:
        relative = path.relative_to(source).as_posix()
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            _error(
                EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED,
                "engine-export entries must be regular files or directories.",
                file_path=relative,
            )
        if path.is_dir():
            continue
        try:
            size = path.stat().st_size
        except OSError as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED,
                "engine-export payload could not be inspected.",
                file_path=relative,
            ) from error
        limit = (
            _MAX_MANIFEST_BYTES
            if relative == ENGINE_EXPORT_ENVELOPE_FILE
            else _MAX_FILE_BYTES
        )
        if size > limit:
            _error(
                EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "engine-export file exceeds the safety limit.",
                file_path=relative,
            )
        total_size += size
        try:
            contents[relative] = path.read_bytes()
        except OSError as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED,
                "engine-export payload could not be read.",
                file_path=relative,
            ) from error
    if total_size > _MAX_TOTAL_BYTES + _MAX_MANIFEST_BYTES:
        _error(
            EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "engine-export directory exceeds the total safety limit.",
        )
    return contents


def _read_zip(source: Path) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise EngineAdapterError(
            EngineAdapterErrorCode.UNSAFE_ARCHIVE,
            "engine-export ZIP could not be opened.",
        ) from error
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_FILES + 1:
            _error(
                EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "engine-export ZIP contains too many entries.",
            )
        names: set[str] = set()
        total_size = 0
        for info in infos:
            mode = info.external_attr >> 16
            if (
                info.is_dir()
                or not _safe_archive_path(info.filename)
                or info.filename in names
                or info.flag_bits & 0x1
                or (mode and stat.S_ISLNK(mode))
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                _error(
                    EngineAdapterErrorCode.UNSAFE_ARCHIVE,
                    "ZIP entries must be unique, safe, unencrypted regular files.",
                    file_path=info.filename,
                )
            limit = (
                _MAX_MANIFEST_BYTES
                if info.filename == ENGINE_EXPORT_ENVELOPE_FILE
                else _MAX_FILE_BYTES
            )
            if info.file_size > limit:
                _error(
                    EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
                    "ZIP entry exceeds the safety limit.",
                    file_path=info.filename,
                )
            names.add(info.filename)
            total_size += info.file_size
        if total_size > _MAX_TOTAL_BYTES + _MAX_MANIFEST_BYTES:
            _error(
                EngineAdapterErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "engine-export ZIP exceeds the total uncompressed safety limit.",
            )
        try:
            return {info.filename: archive.read(info) for info in infos}
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.UNSAFE_ARCHIVE,
                "engine-export ZIP payload could not be read safely.",
            ) from error


def _decode(contents: dict[str, bytes]) -> VerifiedEngineExport:
    manifest = contents.get(ENGINE_EXPORT_ENVELOPE_FILE)
    if manifest is None:
        _error(
            EngineAdapterErrorCode.MISSING_ENVELOPE,
            f"engine export must contain {ENGINE_EXPORT_ENVELOPE_FILE}.",
        )
    envelope = engine_export_envelope_from_json(_parse_json(manifest))
    payload_contents = {
        path: data
        for path, data in contents.items()
        if path != ENGINE_EXPORT_ENVELOPE_FILE
    }
    declared = {item.path for item in envelope.files}
    supplied = set(payload_contents)
    missing = sorted(declared - supplied)
    extra = sorted(supplied - declared)
    if missing:
        _error(
            EngineAdapterErrorCode.MISSING_FILE,
            "declared payload is absent: " + ", ".join(missing) + ".",
            engine=envelope.engine,
        )
    if extra:
        _error(
            EngineAdapterErrorCode.UNDECLARED_FILE,
            "payload is absent from the envelope: " + ", ".join(extra) + ".",
            engine=envelope.engine,
        )
    payloads = tuple(
        EngineExportPayload(
            path=item.path,
            role=item.role,
            media_type=item.media_type,
            data=payload_contents[item.path],
        )
        for item in envelope.files
    )
    for identity, payload in zip(envelope.files, payloads, strict=True):
        actual = payload.file_identity()
        if actual.size_bytes != identity.size_bytes:
            _error(
                EngineAdapterErrorCode.SIZE_MISMATCH,
                "payload size does not match the envelope.",
                engine=envelope.engine,
                file_path=identity.path,
            )
        if actual.sha256 != identity.sha256:
            _error(
                EngineAdapterErrorCode.HASH_MISMATCH,
                "payload SHA-256 does not match the envelope.",
                engine=envelope.engine,
                file_path=identity.path,
            )
    return VerifiedEngineExport(envelope=envelope, payloads=payloads)


def _payload(export: VerifiedEngineExport) -> dict[str, bytes]:
    return {
        ENGINE_EXPORT_ENVELOPE_FILE: _json_bytes(
            engine_export_envelope_to_json(export.envelope)
        ),
        **{item.path: item.data for item in export.payloads},
    }


def _write_directory(contents: dict[str, bytes], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        for name, data in contents.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_zip(contents: dict[str, bytes], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            ordered = (
                ENGINE_EXPORT_ENVELOPE_FILE,
                *sorted(set(contents) - {ENGINE_EXPORT_ENVELOPE_FILE}),
            )
            for name in ordered:
                info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, contents[name], compresslevel=9)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class EngineExportFileBundleAdapter:
    """Read and write verified common engine exports without engine SDKs."""

    def read(self, source: str | Path) -> VerifiedEngineExport:
        path = Path(source)
        if not path.exists():
            _error(
                EngineAdapterErrorCode.SOURCE_NOT_FOUND,
                "engine-export source does not exist.",
            )
        if path.is_symlink():
            _error(
                EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED,
                "engine-export source must not be a symbolic link.",
            )
        if path.is_dir():
            return _decode(_read_directory(path))
        if path.is_file() and path.suffix.lower() == ".zip":
            return _decode(_read_zip(path))
        _error(
            EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED,
            "engine-export source must be a directory or .zip file.",
        )

    def write(
        self,
        export: VerifiedEngineExport,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        if not isinstance(export, VerifiedEngineExport):
            _error(
                EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                "export must be a VerifiedEngineExport.",
            )
        path = Path(destination)
        is_zip = path.suffix.lower() == ".zip"
        if path.suffix and not is_zip:
            _error(
                EngineAdapterErrorCode.SOURCE_TYPE_UNSUPPORTED,
                "destination must be a suffix-free directory or .zip file.",
            )
        if path.exists() or path.is_symlink():
            if not overwrite:
                _error(
                    EngineAdapterErrorCode.WRITE_FAILED,
                    "destination exists; pass overwrite=True explicitly.",
                )
            if path.is_symlink():
                _error(
                    EngineAdapterErrorCode.WRITE_FAILED,
                    "symbolic-link destinations cannot be overwritten.",
                )
            if is_zip and not path.is_file():
                _error(
                    EngineAdapterErrorCode.WRITE_FAILED,
                    "ZIP destination exists but is not a regular file.",
                )
            if not is_zip and not path.is_dir():
                _error(
                    EngineAdapterErrorCode.WRITE_FAILED,
                    "directory destination exists but is not a directory.",
                )
        contents = _payload(export)
        try:
            if is_zip:
                _write_zip(contents, path)
            elif path.exists():
                backup = path.with_name(f".{path.name}.backup")
                if backup.exists():
                    _error(
                        EngineAdapterErrorCode.WRITE_FAILED,
                        "stale directory backup blocks atomic replacement.",
                    )
                os.replace(path, backup)
                try:
                    _write_directory(contents, path)
                except Exception:
                    os.replace(backup, path)
                    raise
                shutil.rmtree(backup)
            else:
                _write_directory(contents, path)
        except EngineAdapterError:
            raise
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.WRITE_FAILED,
                str(error),
                engine=export.envelope.engine,
            ) from error
        return path
