"""Strict hybrid JSON/CSV adapter for canonical implementation-risk bundles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, NoReturn

from backtest_auditor.implementation_risk.adapters.csv_contracts import (
    CASH_BALANCES,
    CASH_MOVEMENTS,
    COSTS,
    EQUITY,
    FILLS,
    MARKET_DATA,
    ORDERS,
    POSITIONS,
    RETURNS,
    SIGNALS,
    TRADES,
    TRADE_FILLS_FILE,
    CsvRecordContract,
    decode_csv,
    decode_trade_fills,
    encode_csv,
    encode_trade_fills,
)
from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
)
from backtest_auditor.implementation_risk.adapters.specification_json import (
    SPECIFICATION_FILE,
    specification_from_json,
    specification_to_json,
)
from backtest_auditor.implementation_risk.domain import (
    CANONICAL_ARTIFACT_SCHEMA_VERSION,
    CanonicalRunArtifacts,
    CashArtifacts,
    ComparisonLevel,
    EngineRunReference,
)


BUNDLE_SCHEMA_VERSION = "1.0"
MANIFEST_FILE = "manifest.json"
_MANIFEST_MEDIA_TYPE = "application/json"
_CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
_MAX_FILES = 20
_MAX_MANIFEST_BYTES = 1_000_000
_MAX_FILE_BYTES = 512_000_000
_MAX_TOTAL_BYTES = 1_000_000_000
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

_LEVEL_FILES: dict[ComparisonLevel, tuple[str, ...]] = {
    ComparisonLevel.STRATEGY_SPECIFICATION: (SPECIFICATION_FILE,),
    ComparisonLevel.MARKET_DATA: (MARKET_DATA.file_name,),
    ComparisonLevel.SIGNAL: (SIGNALS.file_name,),
    ComparisonLevel.ORDER: (ORDERS.file_name,),
    ComparisonLevel.FILL: (FILLS.file_name,),
    ComparisonLevel.TRADE: (TRADE_FILLS_FILE, TRADES.file_name),
    ComparisonLevel.POSITION: (POSITIONS.file_name,),
    ComparisonLevel.CASH: (CASH_BALANCES.file_name, CASH_MOVEMENTS.file_name),
    ComparisonLevel.COST: (COSTS.file_name,),
    ComparisonLevel.EQUITY: (EQUITY.file_name,),
    ComparisonLevel.RETURN: (RETURNS.file_name,),
}
_KNOWN_PAYLOAD_FILES = frozenset(
    file_name for names in _LEVEL_FILES.values() for file_name in names
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed.")


def _parse_json(data: bytes, *, file_name: str) -> object:
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise BundleContractError(
            BundleErrorCode.INVALID_JSON,
            str(error),
            file_path=file_name,
        ) from error
    if _json_bytes(value) != data:
        raise BundleContractError(
            BundleErrorCode.INVALID_JSON,
            "JSON must use the canonical UTF-8 serialization.",
            file_path=file_name,
        )
    return value


def _file_entry(
    path: str,
    data: bytes,
    *,
    record_count: int,
) -> dict[str, Any]:
    return {
        "path": path,
        "media_type": (
            _MANIFEST_MEDIA_TYPE if path.endswith(".json") else _CSV_MEDIA_TYPE
        ),
        "size_bytes": len(data),
        "sha256": _sha256(data),
        "record_count": record_count,
    }


def _level_json(available: bool, files: tuple[str, ...]) -> dict[str, Any]:
    return {
        "status": "available" if available else "unavailable",
        "files": list(files if available else ()),
    }


def _build_payload(bundle: CanonicalRunArtifacts) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    record_counts: dict[str, int] = {}

    if bundle.specification is not None:
        payload[SPECIFICATION_FILE] = _json_bytes(
            specification_to_json(bundle.specification)
        )
        record_counts[SPECIFICATION_FILE] = 1
    csv_series: tuple[tuple[tuple[Any, ...] | None, CsvRecordContract[Any]], ...] = (
        (bundle.market_data, MARKET_DATA),
        (bundle.signals, SIGNALS),
        (bundle.orders, ORDERS),
        (bundle.fills, FILLS),
        (bundle.positions, POSITIONS),
        (bundle.costs, COSTS),
        (bundle.equity, EQUITY),
        (bundle.returns, RETURNS),
    )
    for records, contract in csv_series:
        if records is not None:
            payload[contract.file_name] = encode_csv(contract, records)
            record_counts[contract.file_name] = len(records)

    if bundle.trades is not None:
        payload[TRADES.file_name] = encode_csv(TRADES, bundle.trades)
        payload[TRADE_FILLS_FILE] = encode_trade_fills(bundle.trades)
        record_counts[TRADES.file_name] = len(bundle.trades)
        record_counts[TRADE_FILLS_FILE] = sum(
            len(trade.fill_ids) for trade in bundle.trades
        )
    if bundle.cash is not None:
        if bundle.cash.balances is not None:
            payload[CASH_BALANCES.file_name] = encode_csv(
                CASH_BALANCES,
                bundle.cash.balances,
            )
            record_counts[CASH_BALANCES.file_name] = len(bundle.cash.balances)
        if bundle.cash.movements is not None:
            payload[CASH_MOVEMENTS.file_name] = encode_csv(
                CASH_MOVEMENTS,
                bundle.cash.movements,
            )
            record_counts[CASH_MOVEMENTS.file_name] = len(bundle.cash.movements)

    available = set(bundle.available_levels)
    levels: dict[str, Any] = {}
    for level in ComparisonLevel:
        level_files = tuple(
            sorted(name for name in _LEVEL_FILES[level] if name in payload)
        )
        levels[level.value] = _level_json(level in available, level_files)

    file_entries = [
        _file_entry(
            path,
            payload[path],
            record_count=record_counts[path],
        )
        for path in sorted(payload)
    ]
    manifest_without_identity: dict[str, Any] = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "artifact_schema_version": bundle.artifact_schema_version,
        "run": {
            "run_id": bundle.run.run_id,
            "engine_name": bundle.run.engine_name,
            "engine_version": bundle.run.engine_version,
            "source_sha256": bundle.run.source_sha256,
        },
        "levels": levels,
        "files": file_entries,
    }
    manifest = {
        **manifest_without_identity,
        "bundle_content_sha256": _sha256(
            _canonical_json_bytes(manifest_without_identity)
        ),
    }
    return {MANIFEST_FILE: _json_bytes(manifest), **payload}


def canonical_artifact_bundle_sha256(bundle: CanonicalRunArtifacts) -> str:
    """Return the deterministic V1.5C bundle identity without filesystem I/O."""

    if not isinstance(bundle, CanonicalRunArtifacts):
        raise BundleContractError(
            BundleErrorCode.DOMAIN_VALIDATION_FAILED,
            "bundle must be CanonicalRunArtifacts.",
        )
    manifest = _parse_json(
        _build_payload(bundle)[MANIFEST_FILE], file_name=MANIFEST_FILE
    )
    if not isinstance(manifest, dict):  # pragma: no cover - internal invariant
        raise AssertionError("canonical bundle manifest must be an object")
    identity = manifest["bundle_content_sha256"]
    if not isinstance(identity, str):  # pragma: no cover - internal invariant
        raise AssertionError("canonical bundle identity must be a string")
    return identity


def _contract_error(
    code: BundleErrorCode,
    message: str,
    *,
    file_path: str | None = None,
    field: str | None = None,
) -> NoReturn:
    raise BundleContractError(
        code,
        message,
        file_path=file_path,
        field=field,
    )


def _object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "value must be a JSON object.",
            file_path=MANIFEST_FILE,
            field=field,
        )
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], *, field: str) -> None:
    if set(value) != expected:
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "object keys must match the versioned contract exactly.",
            file_path=MANIFEST_FILE,
            field=field,
        )


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "value must be a string.",
            file_path=MANIFEST_FILE,
            field=field,
        )
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "value must be a non-negative integer.",
            file_path=MANIFEST_FILE,
            field=field,
        )
    return value


def _list(value: object, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "value must be a JSON array.",
            file_path=MANIFEST_FILE,
            field=field,
        )
    return value


def _validate_manifest(
    value: object,
) -> tuple[EngineRunReference, dict[str, dict[str, Any]]]:
    root = _object(value, field="root")
    _exact_keys(
        root,
        {
            "bundle_schema_version",
            "artifact_schema_version",
            "bundle_content_sha256",
            "run",
            "levels",
            "files",
        },
        field="root",
    )
    bundle_version = _string(
        root["bundle_schema_version"], field="bundle_schema_version"
    )
    artifact_version = _string(
        root["artifact_schema_version"], field="artifact_schema_version"
    )
    if bundle_version != BUNDLE_SCHEMA_VERSION:
        _contract_error(
            BundleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            f"bundle schema {bundle_version!r} is unsupported.",
            file_path=MANIFEST_FILE,
            field="bundle_schema_version",
        )
    if artifact_version != CANONICAL_ARTIFACT_SCHEMA_VERSION:
        _contract_error(
            BundleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            f"artifact schema {artifact_version!r} is unsupported.",
            file_path=MANIFEST_FILE,
            field="artifact_schema_version",
        )
    declared_identity = _string(
        root["bundle_content_sha256"], field="bundle_content_sha256"
    )
    identity_body = dict(root)
    del identity_body["bundle_content_sha256"]
    if declared_identity != _sha256(_canonical_json_bytes(identity_body)):
        _contract_error(
            BundleErrorCode.HASH_MISMATCH,
            "bundle_content_sha256 does not match the canonical manifest body.",
            file_path=MANIFEST_FILE,
            field="bundle_content_sha256",
        )

    run_json = _object(root["run"], field="run")
    _exact_keys(
        run_json,
        {"run_id", "engine_name", "engine_version", "source_sha256"},
        field="run",
    )
    try:
        run = EngineRunReference(
            run_id=_string(run_json["run_id"], field="run.run_id"),
            engine_name=_string(run_json["engine_name"], field="run.engine_name"),
            engine_version=_optional_string(
                run_json["engine_version"], field="run.engine_version"
            ),
            source_sha256=_string(run_json["source_sha256"], field="run.source_sha256"),
        )
    except ValueError as error:
        raise BundleContractError(
            BundleErrorCode.INVALID_MANIFEST,
            str(error),
            file_path=MANIFEST_FILE,
            field="run",
        ) from error

    levels_json = _object(root["levels"], field="levels")
    if set(levels_json) != {level.value for level in ComparisonLevel}:
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "levels must declare every canonical comparison level exactly once.",
            file_path=MANIFEST_FILE,
            field="levels",
        )
    declared_paths: set[str] = set()
    for level in ComparisonLevel:
        field = f"levels.{level.value}"
        level_json = _object(levels_json[level.value], field=field)
        _exact_keys(level_json, {"status", "files"}, field=field)
        status_value = _string(level_json["status"], field=f"{field}.status")
        if status_value not in {"available", "unavailable"}:
            _contract_error(
                BundleErrorCode.INVALID_MANIFEST,
                "status must be 'available' or 'unavailable'.",
                file_path=MANIFEST_FILE,
                field=f"{field}.status",
            )
        raw_files = _list(level_json["files"], field=f"{field}.files")
        files = tuple(
            _string(item, field=f"{field}.files[{index}]")
            for index, item in enumerate(raw_files)
        )
        if files != tuple(sorted(files)) or len(set(files)) != len(files):
            _contract_error(
                BundleErrorCode.INVALID_MANIFEST,
                "level files must be unique and canonically ordered.",
                file_path=MANIFEST_FILE,
                field=f"{field}.files",
            )
        allowed = set(_LEVEL_FILES[level])
        supplied = set(files)
        if not supplied.issubset(allowed):
            _contract_error(
                BundleErrorCode.INVALID_MANIFEST,
                "level references an unsupported file.",
                file_path=MANIFEST_FILE,
                field=f"{field}.files",
            )
        if status_value == "unavailable" and files:
            _contract_error(
                BundleErrorCode.INVALID_MANIFEST,
                "unavailable levels must not reference files.",
                file_path=MANIFEST_FILE,
                field=field,
            )
        if status_value == "available":
            if level is ComparisonLevel.CASH:
                if not files:
                    _contract_error(
                        BundleErrorCode.INVALID_MANIFEST,
                        "available cash requires balances, movements, or both.",
                        file_path=MANIFEST_FILE,
                        field=field,
                    )
            elif supplied != allowed:
                _contract_error(
                    BundleErrorCode.INVALID_MANIFEST,
                    "available level must reference its complete file set.",
                    file_path=MANIFEST_FILE,
                    field=field,
                )
        declared_paths.update(files)

    files_json = _list(root["files"], field="files")
    if len(files_json) > _MAX_FILES:
        _contract_error(
            BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "manifest declares too many files.",
            file_path=MANIFEST_FILE,
            field="files",
        )
    entries: dict[str, dict[str, Any]] = {}
    ordered_paths: list[str] = []
    for index, raw_entry in enumerate(files_json):
        field = f"files[{index}]"
        entry = _object(raw_entry, field=field)
        _exact_keys(
            entry,
            {"path", "media_type", "size_bytes", "sha256", "record_count"},
            field=field,
        )
        path = _string(entry["path"], field=f"{field}.path")
        if path not in _KNOWN_PAYLOAD_FILES or path in entries:
            _contract_error(
                BundleErrorCode.INVALID_MANIFEST,
                "file path is unsupported or duplicated.",
                file_path=MANIFEST_FILE,
                field=f"{field}.path",
            )
        media_type = _string(entry["media_type"], field=f"{field}.media_type")
        expected_media_type = (
            _MANIFEST_MEDIA_TYPE if path.endswith(".json") else _CSV_MEDIA_TYPE
        )
        if media_type != expected_media_type:
            _contract_error(
                BundleErrorCode.INVALID_MANIFEST,
                "media_type does not match the file contract.",
                file_path=MANIFEST_FILE,
                field=f"{field}.media_type",
            )
        size_bytes = _integer(entry["size_bytes"], field=f"{field}.size_bytes")
        if size_bytes > _MAX_FILE_BYTES:
            _contract_error(
                BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "declared file size exceeds the safety limit.",
                file_path=MANIFEST_FILE,
                field=f"{field}.size_bytes",
            )
        _integer(entry["record_count"], field=f"{field}.record_count")
        digest = _string(entry["sha256"], field=f"{field}.sha256")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            _contract_error(
                BundleErrorCode.INVALID_MANIFEST,
                "sha256 must use 64 lowercase hexadecimal characters.",
                file_path=MANIFEST_FILE,
                field=f"{field}.sha256",
            )
        ordered_paths.append(path)
        entries[path] = entry
    if ordered_paths != sorted(ordered_paths):
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "file inventory must be in canonical path order.",
            file_path=MANIFEST_FILE,
            field="files",
        )
    if set(entries) != declared_paths:
        _contract_error(
            BundleErrorCode.INVALID_MANIFEST,
            "file inventory must exactly match files declared by levels.",
            file_path=MANIFEST_FILE,
            field="files",
        )
    return run, entries


def _records_count(path: str, parsed: object) -> int:
    if path == SPECIFICATION_FILE:
        return 1
    return len(parsed)  # type: ignore[arg-type]


def _decode_payload(contents: dict[str, bytes]) -> CanonicalRunArtifacts:
    manifest_data = contents.get(MANIFEST_FILE)
    if manifest_data is None:
        _contract_error(
            BundleErrorCode.MISSING_MANIFEST,
            "bundle must contain manifest.json.",
        )
    if len(manifest_data) > _MAX_MANIFEST_BYTES:
        _contract_error(
            BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "manifest exceeds the safety limit.",
            file_path=MANIFEST_FILE,
        )
    manifest_value = _parse_json(manifest_data, file_name=MANIFEST_FILE)
    run, entries = _validate_manifest(manifest_value)
    actual_paths = set(contents) - {MANIFEST_FILE}
    declared_paths = set(entries)
    if actual_paths - declared_paths:
        _contract_error(
            BundleErrorCode.UNDECLARED_FILE,
            "bundle contains files absent from the manifest inventory.",
        )
    if declared_paths - actual_paths:
        _contract_error(
            BundleErrorCode.MISSING_FILE,
            "manifest inventory references files absent from the bundle.",
        )
    if sum(len(contents[path]) for path in contents) > _MAX_TOTAL_BYTES:
        _contract_error(
            BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "bundle exceeds the total uncompressed safety limit.",
        )
    for path, entry in entries.items():
        data = contents[path]
        if len(data) != entry["size_bytes"]:
            _contract_error(
                BundleErrorCode.SIZE_MISMATCH,
                "file size does not match the manifest.",
                file_path=path,
            )
        if _sha256(data) != entry["sha256"]:
            _contract_error(
                BundleErrorCode.HASH_MISMATCH,
                "file SHA-256 does not match the manifest.",
                file_path=path,
            )

    manifest = _object(manifest_value, field="root")
    levels = _object(manifest["levels"], field="levels")

    def is_available(level: ComparisonLevel) -> bool:
        item = _object(levels[level.value], field=f"levels.{level.value}")
        return item["status"] == "available"

    parsed_by_path: dict[str, object] = {}
    specification = None
    if is_available(ComparisonLevel.STRATEGY_SPECIFICATION):
        specification_json = _parse_json(
            contents[SPECIFICATION_FILE],
            file_name=SPECIFICATION_FILE,
        )
        specification = specification_from_json(specification_json)
        parsed_by_path[SPECIFICATION_FILE] = specification

    contract_levels: tuple[tuple[ComparisonLevel, CsvRecordContract[Any], str], ...] = (
        (ComparisonLevel.MARKET_DATA, MARKET_DATA, "market_data"),
        (ComparisonLevel.SIGNAL, SIGNALS, "signals"),
        (ComparisonLevel.ORDER, ORDERS, "orders"),
        (ComparisonLevel.FILL, FILLS, "fills"),
        (ComparisonLevel.POSITION, POSITIONS, "positions"),
        (ComparisonLevel.COST, COSTS, "costs"),
        (ComparisonLevel.EQUITY, EQUITY, "equity"),
        (ComparisonLevel.RETURN, RETURNS, "returns"),
    )
    bundle_values: dict[str, Any] = {
        "run": run,
        "specification": specification,
    }
    for level, contract, field in contract_levels:
        records = None
        if is_available(level):
            records = decode_csv(contract, contents[contract.file_name])
            parsed_by_path[contract.file_name] = records
        bundle_values[field] = records

    trades = None
    if is_available(ComparisonLevel.TRADE):
        base_trades = decode_csv(TRADES, contents[TRADES.file_name])
        links = decode_trade_fills(contents[TRADE_FILLS_FILE])
        trade_ids = {trade.trade_id for trade in base_trades}
        links_by_trade: dict[str, list[str]] = {}
        for trade_id, fill_id in links:
            if trade_id not in trade_ids:
                raise BundleContractError(
                    BundleErrorCode.INVALID_ROW,
                    f"trade-fill link references unknown trade {trade_id!r}.",
                    file_path=TRADE_FILLS_FILE,
                )
            links_by_trade.setdefault(trade_id, []).append(fill_id)
        trades = tuple(
            replace(trade, fill_ids=tuple(links_by_trade.get(trade.trade_id, ())))
            for trade in base_trades
        )
        parsed_by_path[TRADES.file_name] = trades
        parsed_by_path[TRADE_FILLS_FILE] = links
    bundle_values["trades"] = trades

    cash = None
    if is_available(ComparisonLevel.CASH):
        level_item = _object(levels[ComparisonLevel.CASH.value], field="levels.cash")
        cash_files = set(_list(level_item["files"], field="levels.cash.files"))
        balances = None
        movements = None
        if CASH_BALANCES.file_name in cash_files:
            balances = decode_csv(
                CASH_BALANCES,
                contents[CASH_BALANCES.file_name],
            )
            parsed_by_path[CASH_BALANCES.file_name] = balances
        if CASH_MOVEMENTS.file_name in cash_files:
            movements = decode_csv(
                CASH_MOVEMENTS,
                contents[CASH_MOVEMENTS.file_name],
            )
            parsed_by_path[CASH_MOVEMENTS.file_name] = movements
        try:
            cash = CashArtifacts(balances=balances, movements=movements)
        except ValueError as error:
            raise BundleContractError(
                BundleErrorCode.DOMAIN_VALIDATION_FAILED,
                str(error),
            ) from error
    bundle_values["cash"] = cash

    for path, parsed in parsed_by_path.items():
        actual_count = _records_count(path, parsed)
        if actual_count != entries[path]["record_count"]:
            _contract_error(
                BundleErrorCode.RECORD_COUNT_MISMATCH,
                "parsed record count does not match the manifest.",
                file_path=path,
            )
    try:
        bundle = CanonicalRunArtifacts(
            **bundle_values,
            artifact_schema_version=CANONICAL_ARTIFACT_SCHEMA_VERSION,
        )
    except ValueError as error:
        raise BundleContractError(
            BundleErrorCode.DOMAIN_VALIDATION_FAILED,
            str(error),
        ) from error
    if _build_payload(bundle) != contents:
        _contract_error(
            BundleErrorCode.DOMAIN_VALIDATION_FAILED,
            "bundle does not round-trip to the canonical representation.",
        )
    return bundle


def _read_directory(source: Path) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    entries = tuple(source.iterdir())
    if len(entries) > _MAX_FILES + 1:
        _contract_error(
            BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
            "bundle directory contains too many entries.",
        )
    for path in entries:
        if path.is_symlink() or not path.is_file():
            _contract_error(
                BundleErrorCode.UNDECLARED_FILE,
                "bundle directories may contain only regular top-level files.",
                file_path=path.name,
            )
        size = path.stat().st_size
        limit = _MAX_MANIFEST_BYTES if path.name == MANIFEST_FILE else _MAX_FILE_BYTES
        if size > limit:
            _contract_error(
                BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "file exceeds the safety limit.",
                file_path=path.name,
            )
        contents[path.name] = path.read_bytes()
    return contents


def _read_zip(source: Path) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise BundleContractError(
            BundleErrorCode.UNSAFE_ARCHIVE,
            "source is not a valid ZIP archive.",
        ) from error
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_FILES + 1:
            _contract_error(
                BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "ZIP contains too many entries.",
            )
        names: set[str] = set()
        total_size = 0
        for info in infos:
            mode = info.external_attr >> 16
            if (
                info.is_dir()
                or info.filename != Path(info.filename).name
                or info.filename in names
                or info.flag_bits & 0x1
                or (mode and stat.S_ISLNK(mode))
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                _contract_error(
                    BundleErrorCode.UNSAFE_ARCHIVE,
                    "ZIP entries must be unique, unencrypted, regular top-level files.",
                    file_path=info.filename,
                )
            limit = (
                _MAX_MANIFEST_BYTES
                if info.filename == MANIFEST_FILE
                else _MAX_FILE_BYTES
            )
            if info.file_size > limit:
                _contract_error(
                    BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
                    "ZIP entry exceeds the safety limit.",
                    file_path=info.filename,
                )
            total_size += info.file_size
            names.add(info.filename)
        if total_size > _MAX_TOTAL_BYTES:
            _contract_error(
                BundleErrorCode.RESOURCE_LIMIT_EXCEEDED,
                "ZIP exceeds the total uncompressed safety limit.",
            )
        try:
            return {info.filename: archive.read(info) for info in infos}
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            raise BundleContractError(
                BundleErrorCode.UNSAFE_ARCHIVE,
                "ZIP payload could not be read safely.",
            ) from error


def _write_zip(payload: dict[str, bytes], destination: Path) -> None:
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
            for name in (MANIFEST_FILE, *sorted(set(payload) - {MANIFEST_FILE})):
                info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, payload[name], compresslevel=9)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_directory(payload: dict[str, bytes], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            dir=destination.parent,
        )
    )
    try:
        for name, data in payload.items():
            (temporary / name).write_bytes(data)
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


class CanonicalArtifactFileBundleAdapter:
    """Read and write V1.5C directories or deterministic ZIP bundles."""

    def read(self, source: str | Path) -> CanonicalRunArtifacts:
        path = Path(source)
        if not path.exists():
            raise BundleContractError(
                BundleErrorCode.SOURCE_NOT_FOUND,
                "bundle source does not exist.",
            )
        if path.is_symlink():
            raise BundleContractError(
                BundleErrorCode.SOURCE_TYPE_UNSUPPORTED,
                "bundle source must not be a symbolic link.",
            )
        if path.is_dir():
            return _decode_payload(_read_directory(path))
        if path.is_file() and path.suffix.lower() == ".zip":
            return _decode_payload(_read_zip(path))
        raise BundleContractError(
            BundleErrorCode.SOURCE_TYPE_UNSUPPORTED,
            "bundle source must be a directory or .zip file.",
        )

    def content_sha256(self, bundle: CanonicalRunArtifacts) -> str:
        """Calculate the same identity that the writer stores in manifest.json."""

        return canonical_artifact_bundle_sha256(bundle)

    def write(
        self,
        bundle: CanonicalRunArtifacts,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        if not isinstance(bundle, CanonicalRunArtifacts):
            raise BundleContractError(
                BundleErrorCode.DOMAIN_VALIDATION_FAILED,
                "bundle must be CanonicalRunArtifacts.",
            )
        path = Path(destination)
        is_zip = path.suffix.lower() == ".zip"
        if path.suffix and not is_zip:
            raise BundleContractError(
                BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED,
                "destination must be a suffix-free directory or .zip file.",
            )
        if path.exists() or path.is_symlink():
            if not overwrite:
                raise BundleContractError(
                    BundleErrorCode.DESTINATION_EXISTS,
                    "destination already exists; pass overwrite=True explicitly.",
                )
            if path.is_symlink():
                raise BundleContractError(
                    BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED,
                    "symbolic-link destinations cannot be overwritten.",
                )
            if is_zip and not path.is_file():
                raise BundleContractError(
                    BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED,
                    "ZIP destination exists but is not a regular file.",
                )
            if not is_zip and not path.is_dir():
                raise BundleContractError(
                    BundleErrorCode.DESTINATION_TYPE_UNSUPPORTED,
                    "directory destination exists but is not a directory.",
                )

        payload = _build_payload(bundle)
        try:
            if is_zip:
                _write_zip(payload, path)
            elif path.exists():
                backup = path.with_name(f".{path.name}.backup")
                if backup.exists():
                    raise BundleContractError(
                        BundleErrorCode.WRITE_FAILED,
                        "stale directory backup blocks atomic replacement.",
                    )
                os.replace(path, backup)
                try:
                    _write_directory(payload, path)
                except Exception:
                    os.replace(backup, path)
                    raise
                shutil.rmtree(backup)
            else:
                _write_directory(payload, path)
        except BundleContractError:
            raise
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            raise BundleContractError(
                BundleErrorCode.WRITE_FAILED,
                str(error),
            ) from error
        return path
