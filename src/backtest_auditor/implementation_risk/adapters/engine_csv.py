"""Strict helpers shared by the concrete D2 engine CSV mappers.

The common engine-export envelope authenticates bytes.  These helpers enforce
the second boundary: an engine-specific, versioned CSV/JSON contract whose
rows are never repaired or guessed while they are normalized.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn

from backtest_auditor.implementation_risk.adapters.errors import (
    describe_name_difference,
)
from backtest_auditor.implementation_risk.application.errors import (
    EngineAdapterError,
    EngineAdapterErrorCode,
)
from backtest_auditor.implementation_risk.domain.engine_adapters import (
    EngineExportPayload,
    SupportedEngine,
    VerifiedEngineExport,
)


ADAPTER_METADATA_FILE = "adapter-metadata.json"
ADAPTER_EXPORT_SCHEMA_VERSION = "1.0"
_METADATA_KEYS = ("adapter_export_schema_version", "base_currency")
_UTC = timezone.utc


def canonical_json_bytes(value: object) -> bytes:
    """Serialize one adapter payload using the repository's canonical JSON."""

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


def canonical_csv_bytes(
    headers: tuple[str, ...],
    rows: Iterable[Mapping[str, str]],
) -> bytes:
    """Serialize rows deterministically for an engine-specific CSV payload."""

    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=headers,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


def canonical_timestamp(value: datetime) -> str:
    """Return the one timestamp spelling accepted by D2 contracts."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamp must be a timezone-aware datetime.")
    normalized = value.astimezone(_UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    """Parse a canonical UTC timestamp without inferring a timezone."""

    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must use canonical UTC Z notation.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("timestamp is invalid.") from error
    if canonical_timestamp(parsed) != value:
        raise ValueError("timestamp must include exactly six fractional digits.")
    return parsed


def canonical_decimal(value: object) -> str:
    """Return a finite, non-exponent decimal spelling."""

    if isinstance(value, bool):
        raise ValueError("numeric values must not be booleans.")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("numeric value is invalid.") from error
    if not decimal.is_finite():
        raise ValueError("numeric value must be finite.")
    if decimal == 0:
        decimal = Decimal(0)
    return format(decimal, "f")


def parse_decimal(value: str, *, non_negative: bool = False) -> Decimal:
    """Parse the canonical decimal spelling emitted by D2 exporters."""

    if not isinstance(value, str) or not value:
        raise ValueError("numeric field must not be empty.")
    try:
        decimal = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("numeric field is invalid.") from error
    if not decimal.is_finite() or canonical_decimal(decimal) != value:
        raise ValueError("numeric field must use canonical finite decimal notation.")
    if non_negative and decimal < 0:
        raise ValueError("numeric field must be non-negative.")
    return decimal


def optional_decimal(value: str, *, non_negative: bool = False) -> Decimal | None:
    if value == "":
        return None
    return parse_decimal(value, non_negative=non_negative)


def optional_timestamp(value: str) -> datetime | None:
    if value == "":
        return None
    return parse_timestamp(value)


def _duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _nonfinite_json(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed.")


def mapping_error(
    *,
    engine: SupportedEngine,
    adapter_id: str,
    detail: str,
    message: str,
    file_path: str | None = None,
    row_number: int | None = None,
    field: str | None = None,
) -> NoReturn:
    """Raise one namespaced, stable fatal mapping error."""

    raise EngineAdapterError(
        EngineAdapterErrorCode.MAPPING_FAILED,
        message,
        engine=engine,
        adapter_id=adapter_id,
        engine_error_code=f"{engine.value}.{detail}",
        file_path=file_path,
        row_number=row_number,
        field=field,
    )


def read_adapter_metadata(
    payload: EngineExportPayload,
    *,
    engine: SupportedEngine,
    adapter_id: str,
) -> str:
    """Validate the shared D2 metadata payload and return base currency."""

    try:
        value = json.loads(
            payload.data.decode("utf-8"),
            object_pairs_hook=_duplicate_keys,
            parse_constant=_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="invalid_metadata",
            message=str(error),
            file_path=payload.path,
        )
    if canonical_json_bytes(value) != payload.data:
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="noncanonical_metadata",
            message="adapter metadata must use canonical UTF-8 JSON.",
            file_path=payload.path,
        )
    if not isinstance(value, dict):
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="invalid_metadata",
            message="adapter metadata must be a JSON object.",
            file_path=payload.path,
        )
    if set(value) != set(_METADATA_KEYS):
        difference, field = describe_name_difference(_METADATA_KEYS, value, noun="key")
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="invalid_metadata",
            message=f"adapter metadata keys do not match the 1.0 contract: {difference}.",
            file_path=payload.path,
            field=field,
        )
    if value["adapter_export_schema_version"] != ADAPTER_EXPORT_SCHEMA_VERSION:
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="unsupported_metadata_version",
            message="adapter metadata schema version is unsupported.",
            file_path=payload.path,
            field="adapter_export_schema_version",
        )
    currency = value["base_currency"]
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency.upper() != currency
    ):
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="invalid_currency",
            message="base_currency must be a three-letter uppercase ASCII code.",
            file_path=payload.path,
            field="base_currency",
        )
    return currency


def read_csv_rows(
    payload: EngineExportPayload,
    headers: tuple[str, ...],
    *,
    engine: SupportedEngine,
    adapter_id: str,
) -> tuple[dict[str, str], ...]:
    """Decode one exact, canonically serialized D2 CSV payload."""

    try:
        text = payload.data.decode("utf-8")
    except UnicodeDecodeError:
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="invalid_utf8",
            message="CSV must be valid UTF-8 without a byte-order mark.",
            file_path=payload.path,
        )
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    supplied = tuple(reader.fieldnames or ())
    if supplied != headers:
        difference, field = describe_name_difference(headers, supplied, noun="column")
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="header_mismatch",
            message=(
                "CSV header does not match the versioned engine contract: "
                f"{difference}."
            ),
            file_path=payload.path,
            field=field,
        )
    rows: list[dict[str, str]] = []
    try:
        for row in reader:
            if set(row) != set(headers) or any(value is None for value in row.values()):
                raise ValueError("row has missing or additional columns.")
            rows.append(dict(row))
    except (csv.Error, ValueError) as error:
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="invalid_row",
            message=str(error),
            file_path=payload.path,
            row_number=reader.line_num,
        )
    result = tuple(rows)
    if canonical_csv_bytes(headers, result) != payload.data:
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="noncanonical_csv",
            message="CSV must use canonical UTF-8, quoting, and newlines.",
            file_path=payload.path,
        )
    return result


def require_payload_contract(
    export: VerifiedEngineExport,
    expected: Mapping[str, tuple[str, str]],
    *,
    engine: SupportedEngine,
    adapter_id: str,
) -> dict[str, EngineExportPayload]:
    """Require exact path, role, and media-type inventory for one mapper."""

    actual = {payload.path: payload for payload in export.payloads}
    if set(actual) != set(expected):
        mapping_error(
            engine=engine,
            adapter_id=adapter_id,
            detail="payload_inventory_mismatch",
            message="payload paths do not match the versioned engine contract.",
        )
    for path, (role, media_type) in expected.items():
        payload = actual[path]
        if payload.role != role or payload.media_type != media_type:
            mapping_error(
                engine=engine,
                adapter_id=adapter_id,
                detail="payload_metadata_mismatch",
                message="payload role or media type does not match its contract.",
                file_path=path,
            )
    return actual


def map_row_failure(
    error: Exception,
    *,
    engine: SupportedEngine,
    adapter_id: str,
    file_path: str,
    row_number: int,
    field: str | None = None,
) -> NoReturn:
    mapping_error(
        engine=engine,
        adapter_id=adapter_id,
        detail="invalid_row",
        message=str(error),
        file_path=file_path,
        row_number=row_number,
        field=field,
    )
