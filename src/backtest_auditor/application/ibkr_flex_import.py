"""Application service for deterministic, credential-free IBKR Flex imports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date
from typing import Literal, Sequence

from backtest_auditor import PACKAGE_VERSION
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.ibkr_flex import (
    IbkrFlexNormalizationResult,
    IbkrFlexPayload,
    IbkrFlexSelection,
    normalize_ibkr_flex_payloads,
    payload_sha256,
)


IBKR_FLEX_IMPORT_SCHEMA_VERSION = "1.0"
IBKR_FLEX_ADAPTER_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class IbkrFlexImportContext:
    """Non-secret source facts recorded in the import manifest."""

    source_mode: Literal["files", "api"]
    query_id: str | None = None
    requested_from_date: date | None = None
    requested_to_date: date | None = None

    def __post_init__(self) -> None:
        if self.source_mode not in {"files", "api"}:
            raise ValueError("source_mode must be files or api.")
        if self.source_mode == "files" and self.query_id is not None:
            raise ValueError("file imports must not declare an API query_id.")
        if self.source_mode == "api" and not _optional_text(self.query_id):
            raise ValueError("API imports require a query_id.")
        date_pair = (self.requested_from_date, self.requested_to_date)
        if (date_pair[0] is None) != (date_pair[1] is None):
            raise ValueError("requested date overrides must be supplied together.")
        if self.requested_from_date is not None:
            assert self.requested_to_date is not None
            if self.requested_from_date > self.requested_to_date:
                raise ValueError(
                    "requested_from_date must not follow requested_to_date."
                )
        object.__setattr__(self, "query_id", _optional_text(self.query_id))


@dataclass(frozen=True, slots=True)
class IbkrFlexImportResult:
    normalized: IbkrFlexNormalizationResult
    canonical_csv: str
    manifest_json: str
    import_sha256: str


def import_ibkr_flex_payloads(
    payloads: Sequence[IbkrFlexPayload],
    *,
    context: IbkrFlexImportContext,
    selection: IbkrFlexSelection | None = None,
    date_format: str = "yyyyMMdd",
    sampling: SamplingSpec | None = None,
    name: str | None = None,
) -> IbkrFlexImportResult:
    """Canonicalize source payloads and build their import evidence manifest."""

    normalized = normalize_ibkr_flex_payloads(
        payloads,
        selection=selection,
        date_format=date_format,
        sampling=sampling,
        name=name,
    )
    canonical_csv = _canonical_csv(normalized)
    raw_artifacts = sorted(
        (
            {
                "file_name_sha256": _sha256_text(payload.name),
                "size_bytes": len(payload.content),
                "sha256": payload_sha256(payload),
            }
            for payload in payloads
        ),
        key=lambda item: (item["sha256"], item["file_name_sha256"]),
    )
    artifacts = [
        {"source_ordinal": index, **artifact}
        for index, artifact in enumerate(raw_artifacts, start=1)
    ]
    periods = normalized.periods
    body: dict[str, object] = {
        "schema_version": IBKR_FLEX_IMPORT_SCHEMA_VERSION,
        "adapter": "ibkr_activity_flex_change_in_nav",
        "adapter_version": IBKR_FLEX_ADAPTER_VERSION,
        "package_version": PACKAGE_VERSION,
        "source_mode": context.source_mode,
        "source_formats": list(normalized.source_formats),
        "source_artifacts": artifacts,
        "source_scope": {
            "account_id_sha256": normalized.account_id_sha256,
            "model_sha256": normalized.model_sha256,
        },
        "api_request": (
            None
            if context.source_mode == "files"
            else {
                "flex_web_service_version": 3,
                "query_id_sha256": _sha256_text(context.query_id or ""),
                "requested_from_date": _iso_date(context.requested_from_date),
                "requested_to_date": _iso_date(context.requested_to_date),
            }
        ),
        "canonicalization": {
            "source_field": "ChangeInNAV.TWR",
            "source_unit": "percent",
            "return_convention": "simple",
            "conversion": "simple_return = TWR_percent / 100",
            "timestamp_semantics": "statement_interval_end_date",
            "interval_policy": "source intervals preserved; overlaps rejected",
            "date_format": date_format,
        },
        "period_count": len(periods),
        "first_period_start": periods[0].from_date.isoformat(),
        "last_period_end": periods[-1].to_date.isoformat(),
        "canonical_csv_sha256": _sha256_text(canonical_csv),
        "warnings": [issue.code for issue in normalized.normalized.issues],
    }
    import_sha256 = _sha256_text(_canonical_json(body))
    body["import_sha256"] = import_sha256
    manifest_json = (
        json.dumps(
            body,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return IbkrFlexImportResult(
        normalized=normalized,
        canonical_csv=canonical_csv,
        manifest_json=manifest_json,
        import_sha256=import_sha256,
    )


def _canonical_csv(result: IbkrFlexNormalizationResult) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("timestamp", "return", "period_start", "period_end"))
    for period in result.periods:
        writer.writerow(
            (
                period.to_date.isoformat(),
                format(period.twr_percent / 100.0, ".17g"),
                period.from_date.isoformat(),
                period.to_date.isoformat(),
            )
        )
    return output.getvalue()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
