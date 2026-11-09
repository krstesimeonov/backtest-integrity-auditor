"""Strict IBKR Activity Flex Change-in-NAV ingestion.

The adapter deliberately recognizes one narrow contract: period-level TWR from
the ``ChangeInNAV`` section.  It does not infer trades, cash flows, daily NAV,
or returns at a finer frequency than the source statement supplies.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from backtest_auditor.domain.enums import IssueSeverity, ReturnConvention
from backtest_auditor.domain.issues import InputValidationError, ValidationIssue
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.normalization import (
    ReturnSeriesNormalizationResult,
    normalize_return_series,
)


MAX_FLEX_PAYLOAD_BYTES = 20 * 1024 * 1024
MAX_FLEX_PERIODS = 10_000
IBKR_FLEX_DATE_FORMATS: dict[str, str] = {
    "yyyyMMdd": "%Y%m%d",
    "yyyy-MM-dd": "%Y-%m-%d",
    "MM/dd/yyyy": "%m/%d/%Y",
    "MM/dd/yy": "%m/%d/%y",
    "dd/MM/yyyy": "%d/%m/%Y",
    "dd/MM/yy": "%d/%m/%y",
    "dd-MMM-yy": "%d-%b-%y",
}

_CONTROL_XML_PATTERN = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IbkrFlexPayload:
    """One immutable exported statement or Web Service response body."""

    name: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        name = _safe_name(self.name)
        if not isinstance(self.content, bytes):
            raise ValueError("IBKR Flex payload content must be bytes.")
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class IbkrFlexSelection:
    """Optional account/model selector for multi-scope Flex statements."""

    account_id: str | None = field(default=None, repr=False)
    model: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_id",
            _optional_selector(self.account_id, "account_id"),
        )
        object.__setattr__(self, "model", _optional_selector(self.model, "model"))
        if self.model is not None and self.account_id is None:
            raise ValueError("model selection requires an account_id selection.")


@dataclass(frozen=True, slots=True)
class IbkrFlexPeriod:
    """One source-defined TWR interval from ChangeInNAV."""

    account_id: str = field(repr=False)
    account_alias: str | None = field(repr=False)
    model: str | None = field(repr=False)
    from_date: date
    to_date: date
    twr_percent: float

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("IBKR Flex account_id must not be empty.")
        if self.from_date > self.to_date:
            raise ValueError("IBKR Flex period from_date must not follow to_date.")


@dataclass(frozen=True, slots=True)
class IbkrFlexNormalizationResult:
    """Canonical return series plus non-secret source interval metadata."""

    normalized: ReturnSeriesNormalizationResult
    periods: tuple[IbkrFlexPeriod, ...]
    account_id_sha256: str
    model_sha256: str | None
    source_formats: tuple[str, ...]


def read_ibkr_flex_files(
    paths: Sequence[str | Path],
    *,
    selection: IbkrFlexSelection | None = None,
    date_format: str = "yyyyMMdd",
    sampling: SamplingSpec | None = None,
    name: str | None = None,
) -> IbkrFlexNormalizationResult:
    """Read exported XML/CSV Activity Flex statements from disk."""

    payloads = load_ibkr_flex_files(paths)
    return normalize_ibkr_flex_payloads(
        payloads,
        selection=selection,
        date_format=date_format,
        sampling=sampling,
        name=name,
    )


def load_ibkr_flex_files(
    paths: Sequence[str | Path],
) -> tuple[IbkrFlexPayload, ...]:
    """Load statement bytes with stable, public input-validation failures."""

    if not paths:
        raise _error(
            "IBKR_FLEX_NO_PAYLOADS",
            "At least one IBKR Flex statement file is required.",
        )
    payloads: list[IbkrFlexPayload] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            content = path.read_bytes()
        except FileNotFoundError as error:
            raise _error(
                "IBKR_FLEX_FILE_NOT_FOUND",
                "An IBKR Flex statement file does not exist.",
                str(path),
            ) from error
        except OSError as error:
            raise _error(
                "IBKR_FLEX_FILE_READ_ERROR",
                "An IBKR Flex statement file could not be read.",
                str(path),
            ) from error
        payloads.append(IbkrFlexPayload(path.name, content))
    return tuple(payloads)


def normalize_ibkr_flex_payloads(
    payloads: Sequence[IbkrFlexPayload],
    *,
    selection: IbkrFlexSelection | None = None,
    date_format: str = "yyyyMMdd",
    sampling: SamplingSpec | None = None,
    name: str | None = None,
) -> IbkrFlexNormalizationResult:
    """Parse Flex payloads and map one unambiguous scope to simple returns."""

    if not payloads:
        raise _error(
            "IBKR_FLEX_NO_PAYLOADS",
            "At least one IBKR Flex statement payload is required.",
        )
    if date_format not in IBKR_FLEX_DATE_FORMATS:
        raise ValueError(
            "date_format must be one of: " + ", ".join(IBKR_FLEX_DATE_FORMATS) + "."
        )

    periods: list[IbkrFlexPeriod] = []
    source_formats: list[str] = []
    for payload in payloads:
        source_format, parsed = _parse_payload(payload, date_format)
        source_formats.append(source_format)
        periods.extend(parsed)
        if len(periods) > MAX_FLEX_PERIODS:
            raise _error(
                "IBKR_FLEX_TOO_MANY_PERIODS",
                f"IBKR Flex import exceeds the {MAX_FLEX_PERIODS} period limit.",
            )

    chosen = _select_scope(periods, selection or IbkrFlexSelection())
    ordered = tuple(sorted(chosen, key=lambda item: (item.from_date, item.to_date)))
    _validate_period_intervals(ordered)
    values = [period.twr_percent / 100.0 for period in ordered]
    normalized = normalize_return_series(
        [period.to_date.isoformat() for period in ordered],
        values,
        convention=ReturnConvention.SIMPLE,
        sampling=sampling or SamplingSpec(),
        name=name,
    )
    account_id = ordered[0].account_id
    model = ordered[0].model
    return IbkrFlexNormalizationResult(
        normalized=normalized,
        periods=ordered,
        account_id_sha256=_sha256_text(account_id),
        model_sha256=None if model is None else _sha256_text(model),
        source_formats=tuple(sorted(set(source_formats))),
    )


def payload_sha256(payload: IbkrFlexPayload) -> str:
    return hashlib.sha256(payload.content).hexdigest()


def _parse_payload(
    payload: IbkrFlexPayload,
    date_format: str,
) -> tuple[str, tuple[IbkrFlexPeriod, ...]]:
    size = len(payload.content)
    if size == 0:
        raise _error(
            "IBKR_FLEX_EMPTY_PAYLOAD",
            "An IBKR Flex statement payload is empty.",
            payload.name,
        )
    if size > MAX_FLEX_PAYLOAD_BYTES:
        raise _error(
            "IBKR_FLEX_PAYLOAD_TOO_LARGE",
            f"An IBKR Flex payload exceeds {MAX_FLEX_PAYLOAD_BYTES} bytes.",
            payload.name,
        )
    if payload.content.lstrip().startswith(b"<"):
        return "xml", _parse_xml(payload, date_format)
    return "csv", _parse_csv(payload, date_format)


def _parse_xml(
    payload: IbkrFlexPayload,
    date_format: str,
) -> tuple[IbkrFlexPeriod, ...]:
    if _CONTROL_XML_PATTERN.search(payload.content):
        raise _error(
            "IBKR_FLEX_UNSAFE_XML",
            "IBKR Flex XML must not contain DTD or entity declarations.",
            payload.name,
        )
    try:
        root = ET.fromstring(payload.content)
    except ET.ParseError as error:
        raise _error(
            "IBKR_FLEX_XML_PARSE_ERROR",
            "IBKR Flex XML is not well formed.",
            payload.name,
        ) from error

    if _local_name(root.tag) == "flexstatementresponse":
        raise _error(
            "IBKR_FLEX_CONTROL_RESPONSE",
            "The payload is a Flex Web Service control response, not a statement.",
            payload.name,
        )

    periods: list[IbkrFlexPeriod] = []
    statements = [
        element
        for element in root.iter()
        if _local_name(element.tag) == "flexstatement"
    ]
    if not statements:
        statements = [root]
    for statement in statements:
        defaults = _normalized_mapping(statement.attrib)
        for element in statement.iter():
            if _local_name(element.tag) != "changeinnav":
                continue
            values = dict(defaults)
            values.update(_normalized_mapping(element.attrib))
            periods.append(_period_from_mapping(values, date_format, payload.name))
    if not periods:
        raise _missing_section(payload.name)
    return tuple(periods)


def _parse_csv(
    payload: IbkrFlexPayload,
    date_format: str,
) -> tuple[IbkrFlexPeriod, ...]:
    try:
        text = payload.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _error(
            "IBKR_FLEX_CSV_ENCODING_ERROR",
            "IBKR Flex CSV must be UTF-8 encoded.",
            payload.name,
        ) from error
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header: list[str] | None = None
        periods: list[IbkrFlexPeriod] = []
        for raw_row in rows:
            if not raw_row or all(not cell.strip() for cell in raw_row):
                continue
            normalized_row = [_field_key(cell) for cell in raw_row]
            if _required_fields_present(normalized_row):
                header = normalized_row
                continue
            descriptors = set(normalized_row[:2])
            if "header" in descriptors:
                header = None
                continue
            if header is None or descriptors & {"bof", "eof", "bos", "eos"}:
                continue
            mapping = {
                key: raw_row[index].strip()
                for index, key in enumerate(header)
                if key and index < len(raw_row)
            }
            periods.append(_period_from_mapping(mapping, date_format, payload.name))
    except csv.Error as error:
        raise _error(
            "IBKR_FLEX_CSV_PARSE_ERROR",
            "IBKR Flex CSV is malformed.",
            payload.name,
        ) from error
    if not periods:
        raise _missing_section(payload.name)
    return tuple(periods)


def _period_from_mapping(
    values: dict[str, str],
    date_format: str,
    location: str,
) -> IbkrFlexPeriod:
    missing = [
        display
        for key, display in (
            ("accountid", "AccountId"),
            ("fromdate", "FromDate"),
            ("todate", "ToDate"),
            ("twr", "TWR"),
        )
        if not values.get(key, "").strip()
    ]
    if missing:
        raise _error(
            "IBKR_FLEX_MISSING_FIELD",
            "ChangeInNAV is missing required field(s): " + ", ".join(missing) + ".",
            location,
        )
    try:
        from_date = datetime.strptime(
            values["fromdate"].strip(), IBKR_FLEX_DATE_FORMATS[date_format]
        ).date()
        to_date = datetime.strptime(
            values["todate"].strip(), IBKR_FLEX_DATE_FORMATS[date_format]
        ).date()
    except ValueError as error:
        raise _error(
            "IBKR_FLEX_INVALID_DATE",
            f"ChangeInNAV dates do not match configured format {date_format}.",
            location,
        ) from error
    twr_text = values["twr"].strip()
    if twr_text.endswith("%"):
        twr_text = twr_text[:-1].strip()
    try:
        twr_percent = float(twr_text)
    except ValueError as error:
        raise _error(
            "IBKR_FLEX_INVALID_TWR",
            "ChangeInNAV TWR must be a finite percentage.",
            location,
        ) from error
    if not (-100.0 <= twr_percent < float("inf")):
        raise _error(
            "IBKR_FLEX_INVALID_TWR",
            "ChangeInNAV TWR must be finite and cannot be below -100 percent.",
            location,
        )
    try:
        return IbkrFlexPeriod(
            account_id=values["accountid"].strip(),
            account_alias=_optional_text(values.get("accountalias")),
            model=_optional_text(values.get("model") or values.get("modelcode")),
            from_date=from_date,
            to_date=to_date,
            twr_percent=twr_percent,
        )
    except ValueError as error:
        raise _error(
            "IBKR_FLEX_INVALID_PERIOD",
            str(error),
            location,
        ) from error


def _select_scope(
    periods: Sequence[IbkrFlexPeriod],
    selection: IbkrFlexSelection,
) -> tuple[IbkrFlexPeriod, ...]:
    selected = tuple(
        period
        for period in periods
        if (selection.account_id is None or period.account_id == selection.account_id)
        and (selection.model is None or period.model == selection.model)
    )
    if not selected:
        raise _error(
            "IBKR_FLEX_SCOPE_NOT_FOUND",
            "No ChangeInNAV records matched the requested account/model scope.",
        )
    scopes = {(period.account_id, period.model) for period in selected}
    if len(scopes) != 1:
        raise _error(
            "IBKR_FLEX_AMBIGUOUS_SCOPE",
            "The statement contains multiple account/model scopes; select exactly one.",
        )
    return selected


def _validate_period_intervals(periods: Sequence[IbkrFlexPeriod]) -> None:
    for previous, current in zip(periods, periods[1:], strict=False):
        if current.from_date <= previous.to_date:
            raise _error(
                "IBKR_FLEX_OVERLAPPING_PERIODS",
                "ChangeInNAV periods must not overlap or duplicate one another.",
            )


def _missing_section(location: str) -> InputValidationError:
    return _error(
        "IBKR_FLEX_CHANGE_IN_NAV_MISSING",
        "No ChangeInNAV records with column headers were found.",
        location,
    )


def _required_fields_present(values: Iterable[str]) -> bool:
    return {"accountid", "fromdate", "todate", "twr"}.issubset(set(values))


def _normalized_mapping(values: dict[str, str]) -> dict[str, str]:
    return {_field_key(key): value for key, value in values.items()}


def _field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _optional_selector(value: str | None, field_name: str) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} must not contain control characters.")
    if len(normalized) > 128:
        raise ValueError(f"{field_name} must not exceed 128 characters.")
    return normalized


def _safe_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("IBKR Flex payload name must be a string.")
    name = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if name in {"", ".", ".."}:
        raise ValueError("IBKR Flex payload name must identify a file.")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("IBKR Flex payload name must not contain control characters.")
    if len(name.encode("utf-8")) > 255:
        raise ValueError("IBKR Flex payload name must not exceed 255 UTF-8 bytes.")
    return name


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _error(
    code: str, message: str, location: str | None = None
) -> InputValidationError:
    return InputValidationError(
        (
            ValidationIssue(
                code=code,
                message=message,
                severity=IssueSeverity.ERROR,
                blocking=True,
                location=location,
            ),
        )
    )
