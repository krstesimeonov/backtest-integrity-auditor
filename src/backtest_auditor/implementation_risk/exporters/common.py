"""SDK-neutral utilities for optional engine-side D2 exporters."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd

from backtest_auditor.implementation_risk.adapters.engine_csv import (
    ADAPTER_EXPORT_SCHEMA_VERSION,
    ADAPTER_METADATA_FILE,
    canonical_json_bytes,
    canonical_timestamp,
)
from backtest_auditor.implementation_risk.adapters.engine_export import (
    EngineExportFileBundleAdapter,
)
from backtest_auditor.implementation_risk.domain import (
    ComparisonLevel,
    EngineExportPayload,
    SupportedEngine,
    VerifiedEngineExport,
)


def installed_engine_version(distribution: str) -> str:
    """Return an installed engine version without importing its SDK."""

    try:
        return version(distribution)
    except PackageNotFoundError as error:
        raise ValueError(
            f"{distribution} must be installed in the exporter environment."
        ) from error


def validate_base_currency(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value.upper() != value
    ):
        raise ValueError("base_currency must be a three-letter uppercase ASCII code.")
    return value


def adapter_metadata_payload(base_currency: str) -> EngineExportPayload:
    currency = validate_base_currency(base_currency)
    return EngineExportPayload(
        path=ADAPTER_METADATA_FILE,
        role="adapter_metadata",
        media_type="application/json",
        data=canonical_json_bytes(
            {
                "adapter_export_schema_version": ADAPTER_EXPORT_SCHEMA_VERSION,
                "base_currency": currency,
            }
        ),
    )


def utc_timestamp(value: object, *, field: str) -> str:
    """Normalize pandas/Python timestamps while refusing timezone inference."""

    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} is not a valid timestamp.") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware; localize it explicitly.")
    return canonical_timestamp(timestamp.to_pydatetime())


def require_datetime_index(value: object, *, field: str) -> pd.DatetimeIndex:
    index = getattr(value, "index", None)
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(f"{field} must use a pandas DatetimeIndex.")
    if index.tz is None:
        raise ValueError(f"{field} index must be timezone-aware.")
    if index.has_duplicates:
        raise ValueError(f"{field} index must not contain duplicate timestamps.")
    if not index.is_monotonic_increasing:
        raise ValueError(f"{field} index must be increasing.")
    return index


def require_series(value: object, *, field: str) -> pd.Series:
    if not isinstance(value, pd.Series):
        raise ValueError(f"{field} must be a pandas Series.")
    require_datetime_index(value, field=field)
    return value


def require_frame(value: object, *, field: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise ValueError(f"{field} must be a pandas DataFrame.")
    require_datetime_index(value, field=field)
    if value.columns.has_duplicates:
        raise ValueError(f"{field} columns must be unique.")
    return value


def write_engine_export(
    *,
    run_id: str,
    engine: SupportedEngine,
    engine_version: str,
    export_format_id: str,
    declared_levels: tuple[ComparisonLevel, ...],
    payloads: tuple[EngineExportPayload, ...],
    destination: str | Path,
    overwrite: bool,
) -> Path:
    verified = VerifiedEngineExport.create(
        run_id=run_id,
        engine=engine,
        engine_version=engine_version,
        export_format_id=export_format_id,
        export_format_version="1.0",
        declared_levels=declared_levels,
        payloads=payloads,
    )
    return EngineExportFileBundleAdapter().write(
        verified,
        destination,
        overwrite=overwrite,
    )
