"""Versioned input schemas for the V4 Edge Audit and their validation.

Two inputs, both CSV with a header row:

``edge-audit-trades/1.0`` (required): one row per *closed* trade.
``edge-audit-prices/1.0`` (optional): instrument prices, needed only for the
timing decomposition and the volatility-regime split.

Every problem found is collected with its CSV line number, then raised
together as one :class:`~backtest_auditor.domain.issues.InputValidationError`,
so a user fixes a file in one pass instead of one error per run.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from backtest_auditor.domain.enums import IssueSeverity
from backtest_auditor.domain.issues import InputValidationError, ValidationIssue

TRADES_SCHEMA = "edge-audit-trades/1.0"
PRICES_SCHEMA = "edge-audit-prices/1.0"

#: Columns every trade row must carry, in documentation order.
TRADE_REQUIRED_COLUMNS = (
    "instrument",
    "side",
    "quantity",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "fees",
)
#: Optional trade columns. Anything else is rejected (a typo such as
#: ``fee`` must not silently become "fees are zero").
TRADE_OPTIONAL_COLUMNS = ("trade_id", "multiplier", "currency", "entry_volatility")
PRICE_REQUIRED_COLUMNS = ("instrument", "timestamp", "price")

_SIDES = {"long": 1, "short": -1}
_SCHEMA_LINE = re.compile(r"^#\s*schema\s*:\s*(\S+)\s*$", re.IGNORECASE)
#: Calendar date, time to the minute (seconds and up to 9 decimals optional),
#: then Z or a +hh:mm / +hhmm offset. Anything else is refused: a parser that
#: guesses would read 03/04/2025 as 4 March.
_ISO_8601 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?"
    r"(?P<offset>[Zz]|[+-]\d{2}:?\d{2})?$"
)
_MAX_REPORTED_ISSUES = 50


@dataclass(frozen=True, slots=True)
class TradeLog:
    """Closed trades sorted by (exit_time, entry_time, trade_id).

    Exit order is the order in which P&L was realised, so it is the time axis
    of every sequential method (decay detectors, rolling expectancy).
    """

    trade_id: tuple[str, ...]
    instrument: tuple[str, ...]
    side: NDArray[np.int64]
    quantity: NDArray[np.float64]
    multiplier: NDArray[np.float64]
    entry_time: pd.DatetimeIndex
    entry_price: NDArray[np.float64]
    exit_time: pd.DatetimeIndex
    exit_price: NDArray[np.float64]
    fees: NDArray[np.float64]
    entry_volatility: NDArray[np.float64] | None
    currency: str | None
    source_lines: NDArray[np.int64]
    schema: str = TRADES_SCHEMA
    schema_declared: bool = False

    def __len__(self) -> int:
        return len(self.trade_id)

    @property
    def gross_pnl(self) -> NDArray[np.float64]:
        """side x quantity x multiplier x (exit - entry), account currency."""

        return (
            self.side
            * self.quantity
            * self.multiplier
            * (self.exit_price - self.entry_price)
        )

    @property
    def net_pnl(self) -> NDArray[np.float64]:
        return self.gross_pnl - self.fees

    @property
    def notional(self) -> NDArray[np.float64]:
        """Absolute entry notional: quantity x multiplier x entry price."""

        return self.quantity * self.multiplier * self.entry_price

    @property
    def net_return(self) -> NDArray[np.float64]:
        """Net P&L per unit of entry notional (0.001 = 10 bps)."""

        return self.net_pnl / self.notional

    @property
    def holding_seconds(self) -> NDArray[np.float64]:
        return np.asarray(
            (self.exit_time - self.entry_time).total_seconds(), dtype=np.float64
        )

    @property
    def span_years(self) -> float:
        """First entry to last exit, in years of 365.25 days."""

        seconds = (self.exit_time.max() - self.entry_time.min()).total_seconds()
        return seconds / (365.25 * 86400.0)


@dataclass(frozen=True, slots=True)
class PriceTable:
    """Per-instrument price paths, timestamps strictly increasing (UTC)."""

    timestamps: dict[str, NDArray[np.int64]]  # ns since epoch, UTC
    prices: dict[str, NDArray[np.float64]]
    schema: str = PRICES_SCHEMA

    def instruments(self) -> tuple[str, ...]:
        return tuple(sorted(self.timestamps))


def load_trade_log(path: str | Path) -> TradeLog:
    """Read and validate an ``edge-audit-trades/1.0`` CSV file."""

    declared, frame, lines, problems = _read_csv(Path(path), TRADES_SCHEMA)
    return _with_read_problems(
        problems,
        lambda: parse_trade_log(frame, schema_declared=declared, source_lines=lines),
    )


def load_price_table(path: str | Path) -> PriceTable:
    """Read and validate an ``edge-audit-prices/1.0`` CSV file."""

    _, frame, lines, problems = _read_csv(Path(path), PRICES_SCHEMA)
    return _with_read_problems(
        problems, lambda: parse_price_table(frame, source_lines=lines)
    )


_Parsed = TypeVar("_Parsed")


def _with_read_problems(
    problems: list[ValidationIssue], parse: Callable[[], _Parsed]
) -> _Parsed:
    """Report row-shape problems together with every problem in the good rows."""

    try:
        parsed = parse()
    except InputValidationError as error:
        raise InputValidationError(_capped(problems + list(error.issues))) from None
    if problems:
        raise InputValidationError(_capped(problems))
    return parsed


def parse_trade_log(
    frame: pd.DataFrame,
    *,
    schema_declared: bool = False,
    source_lines: Sequence[int] | NDArray[np.int64] | None = None,
) -> TradeLog:
    """Validate a trade frame (all columns as strings) and build a TradeLog.

    ``source_lines`` are the physical CSV line numbers of the rows, so issues
    point at the line a user sees in an editor; without them row i is taken
    to be line i + 2 (header on line 1).
    """

    issues: list[ValidationIssue] = []
    columns = [str(column).strip() for column in frame.columns]
    frame = frame.copy()
    frame.columns = columns
    missing = [name for name in TRADE_REQUIRED_COLUMNS if name not in columns]
    unknown = [
        name
        for name in columns
        if name not in TRADE_REQUIRED_COLUMNS and name not in TRADE_OPTIONAL_COLUMNS
    ]
    duplicated = sorted({name for name in columns if columns.count(name) > 1})
    for name in missing:
        issues.append(_issue("missing_column", f"required column '{name}' is missing"))
    for name in unknown:
        issues.append(
            _issue(
                "unknown_column",
                f"column '{name}' is not part of {TRADES_SCHEMA}",
            )
        )
    for name in duplicated:
        issues.append(_issue("duplicate_column", f"column '{name}' appears twice"))
    if issues:
        raise InputValidationError(tuple(issues))
    if len(frame) == 0:
        raise InputValidationError(
            (_issue("empty_trade_log", "the trade log has no data rows"),)
        )

    lines = _line_numbers(frame, source_lines)
    text = {name: _text_column(frame, name) for name in columns}

    instrument = text["instrument"]
    for line, value in zip(lines, instrument):
        if not value:
            issues.append(_row_issue("empty_instrument", line, "instrument is empty"))

    side = np.zeros(len(frame), dtype=np.int64)
    for index, (line, value) in enumerate(zip(lines, text["side"])):
        sign = _SIDES.get(value.lower())
        if sign is None:
            issues.append(
                _row_issue(
                    "invalid_side",
                    line,
                    f"side must be 'long' or 'short', got '{value}'",
                )
            )
        else:
            side[index] = sign

    quantity = _positive_numbers(text["quantity"], "quantity", lines, issues)
    entry_price = _positive_numbers(text["entry_price"], "entry_price", lines, issues)
    exit_price = _positive_numbers(text["exit_price"], "exit_price", lines, issues)
    fees = _numbers(text["fees"], "fees", lines, issues, minimum=0.0)
    if "multiplier" in text:
        multiplier = _positive_numbers(
            text["multiplier"], "multiplier", lines, issues, default=1.0
        )
    else:
        multiplier = np.ones(len(frame), dtype=np.float64)
    entry_volatility: NDArray[np.float64] | None = None
    if "entry_volatility" in text:
        entry_volatility = _numbers(
            text["entry_volatility"],
            "entry_volatility",
            lines,
            issues,
            minimum=0.0,
        )

    entry_time = _timestamps(text["entry_time"], "entry_time", lines, issues)
    exit_time = _timestamps(text["exit_time"], "exit_time", lines, issues)
    both_valid = ~(pd.isna(entry_time) | pd.isna(exit_time))
    reversed_rows = both_valid & (exit_time < entry_time)
    for line in lines[np.asarray(reversed_rows)]:
        issues.append(
            _row_issue(
                "exit_before_entry",
                line,
                "exit_time is earlier than entry_time",
            )
        )

    if "trade_id" in text:
        trade_id = text["trade_id"]
        for line, value in zip(lines, trade_id):
            if not value:
                issues.append(_row_issue("empty_trade_id", line, "trade_id is empty"))
        seen: dict[str, int] = {}
        for line, value in zip(lines, trade_id):
            if value and value in seen:
                issues.append(
                    _row_issue(
                        "duplicate_trade_id",
                        line,
                        f"trade_id '{value}' already used on line {seen[value]}",
                    )
                )
            seen.setdefault(value, int(line))
    else:
        trade_id = [f"L{line}" for line in lines]

    currency: str | None = None
    if "currency" in text:
        currencies = sorted({value.upper() for value in text["currency"]})
        if len(currencies) != 1 or not currencies[0]:
            issues.append(
                _issue(
                    "mixed_currency",
                    "all trades must share one non-empty account currency; found "
                    + ", ".join(repr(value) for value in currencies),
                )
            )
        else:
            currency = currencies[0]

    if issues:
        raise InputValidationError(_capped(issues))

    order = np.lexsort(
        (
            np.asarray(trade_id, dtype=object).astype(str),
            entry_time.asi8,
            exit_time.asi8,
        )
    )
    return TradeLog(
        trade_id=tuple(trade_id[index] for index in order),
        instrument=tuple(instrument[index] for index in order),
        side=side[order],
        quantity=quantity[order],
        multiplier=multiplier[order],
        entry_time=entry_time[order],
        entry_price=entry_price[order],
        exit_time=exit_time[order],
        exit_price=exit_price[order],
        fees=fees[order],
        entry_volatility=(
            None if entry_volatility is None else entry_volatility[order]
        ),
        currency=currency,
        source_lines=lines[order],
        schema_declared=schema_declared,
    )


def parse_price_table(
    frame: pd.DataFrame,
    *,
    source_lines: Sequence[int] | NDArray[np.int64] | None = None,
) -> PriceTable:
    """Validate a price frame (all columns as strings) and build a PriceTable."""

    issues: list[ValidationIssue] = []
    columns = [str(column).strip() for column in frame.columns]
    frame = frame.copy()
    frame.columns = columns
    for name in PRICE_REQUIRED_COLUMNS:
        if name not in columns:
            issues.append(
                _issue("missing_column", f"required column '{name}' is missing")
            )
    for name in columns:
        if name not in PRICE_REQUIRED_COLUMNS:
            issues.append(
                _issue(
                    "unknown_column",
                    f"column '{name}' is not part of {PRICES_SCHEMA}",
                )
            )
    for name in sorted({name for name in columns if columns.count(name) > 1}):
        issues.append(_issue("duplicate_column", f"column '{name}' appears twice"))
    if issues:
        raise InputValidationError(tuple(issues))
    if len(frame) == 0:
        raise InputValidationError(
            (_issue("empty_price_table", "the price file has no data rows"),)
        )

    lines = _line_numbers(frame, source_lines)
    instrument = _text_column(frame, "instrument")
    for line, value in zip(lines, instrument):
        if not value:
            issues.append(_row_issue("empty_instrument", line, "instrument is empty"))
    timestamp = _timestamps(
        _text_column(frame, "timestamp"), "timestamp", lines, issues
    )
    price = _positive_numbers(_text_column(frame, "price"), "price", lines, issues)
    if issues:
        raise InputValidationError(_capped(issues))

    timestamps: dict[str, NDArray[np.int64]] = {}
    prices: dict[str, NDArray[np.float64]] = {}
    names = np.asarray(instrument, dtype=object)
    for name in sorted(set(instrument)):
        mask = names == name
        stamps = timestamp[mask].asi8
        order = np.argsort(stamps, kind="stable")
        stamps = stamps[order]
        duplicates = np.flatnonzero(np.diff(stamps) == 0)
        for position in duplicates[:_MAX_REPORTED_ISSUES]:
            line = lines[mask][order][position + 1]
            issues.append(
                _row_issue(
                    "duplicate_price_timestamp",
                    line,
                    f"second price for '{name}' at the same timestamp",
                )
            )
        timestamps[name] = stamps
        prices[name] = price[mask][order]
    if issues:
        raise InputValidationError(_capped(issues))
    return PriceTable(timestamps=timestamps, prices=prices)


def _read_csv(
    path: Path, expected_schema: str
) -> tuple[bool, pd.DataFrame, NDArray[np.int64], list[ValidationIssue]]:
    """Read a CSV as strings with the physical line number of every record.

    The csv module, not pandas, so that a blank line or a quoted line break
    cannot shift the line numbers in error messages, and so that a repeated
    column name is seen as such (pandas renames it ``name.1``). Parsing is
    strict: an unclosed quote is an error naming the line where its record
    starts, never a field that silently swallows the rest of the file, and no
    field may hold a line break (no column of either schema can). Rows with no
    content are skipped. An optional first line ``# schema: <id>`` (cells
    after it empty, as a spreadsheet pads it) must name the expected schema.

    Returns the well-formed rows and, separately, the problems of the others,
    so that the caller can report both in one pass.
    """

    if not path.is_file():
        raise InputValidationError(
            (_issue("file_not_found", f"{path} does not exist or is not a file"),)
        )
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise InputValidationError(
            (_issue("unreadable_csv", f"{path.name}: {error}"),)
        ) from error
    reader = csv.reader(
        io.StringIO(text, newline=""), skipinitialspace=True, strict=True
    )
    declared = False
    header: list[str] | None = None
    records: list[list[str]] = []
    lines: list[int] = []
    problems: list[ValidationIssue] = []
    last_end = 0
    try:
        for row in reader:
            start, last_end = last_end + 1, reader.line_num
            if not any(cell.strip() for cell in row):
                continue
            padded = all(not cell.strip() for cell in row[1:])
            match = _SCHEMA_LINE.match(row[0].strip()) if padded else None
            if header is None and start == 1 and match:
                declared = True
                if match.group(1) != expected_schema:
                    raise InputValidationError(
                        (
                            _issue(
                                "unsupported_schema",
                                f"{path.name} declares schema '{match.group(1)}'; "
                                f"this version reads '{expected_schema}' only",
                            ),
                        )
                    )
                continue
            if any("\n" in cell or "\r" in cell for cell in row):
                problems.append(
                    _row_issue(
                        "line_break_in_field",
                        start,
                        "a field holds a line break (an unclosed quote?)",
                    )
                )
                continue
            if header is None:
                header = [cell.strip() for cell in row]
                continue
            if len(row) != len(header):
                problems.append(
                    _row_issue(
                        "wrong_field_count",
                        start,
                        f"{len(row)} fields, the header has {len(header)}",
                    )
                )
                continue
            records.append(row)
            lines.append(start)
    except csv.Error as error:
        raise InputValidationError(
            (
                _row_issue(
                    "unreadable_csv",
                    last_end + 1,
                    f"{error} in the record starting here (an unclosed quote?)",
                ),
            )
        ) from error
    if header is None:
        raise InputValidationError(
            (_issue("empty_file", f"{path.name} has no header row"),)
        )
    frame = pd.DataFrame(records, columns=header, dtype=str)
    return declared, frame, np.asarray(lines, dtype=np.int64), problems


def _line_numbers(
    frame: pd.DataFrame, source_lines: Sequence[int] | NDArray[np.int64] | None
) -> NDArray[np.int64]:
    if source_lines is None:
        return np.arange(len(frame), dtype=np.int64) + 2
    lines = np.asarray(source_lines, dtype=np.int64)
    if lines.size != len(frame):
        raise ValueError("source_lines must have one entry per row.")
    return lines


def _text_column(frame: pd.DataFrame, name: str) -> list[str]:
    return [str(value).strip() for value in frame[name].tolist()]


def _numbers(
    values: list[str],
    column: str,
    lines: NDArray[np.int64],
    issues: list[ValidationIssue],
    *,
    minimum: float | None = None,
    default: float | None = None,
) -> NDArray[np.float64]:
    result = np.zeros(len(values), dtype=np.float64)
    for index, (line, value) in enumerate(zip(lines, values)):
        if not value and default is not None:
            result[index] = default
            continue
        try:
            number = float(value)
        except ValueError:
            issues.append(
                _row_issue(
                    f"invalid_{column}",
                    line,
                    f"{column} must be a number, got '{value}'",
                )
            )
            continue
        if not math.isfinite(number):
            issues.append(
                _row_issue(f"invalid_{column}", line, f"{column} must be finite")
            )
        elif minimum is not None and number < minimum:
            issues.append(
                _row_issue(
                    f"invalid_{column}",
                    line,
                    f"{column} must be >= {minimum:g}, got {number:g}",
                )
            )
        else:
            result[index] = number
    return result


def _positive_numbers(
    values: list[str],
    column: str,
    lines: NDArray[np.int64],
    issues: list[ValidationIssue],
    *,
    default: float | None = None,
) -> NDArray[np.float64]:
    before = len(issues)
    result = _numbers(values, column, lines, issues, default=default)
    flagged = {issue.location for issue in issues[before:]}
    for line, number in zip(lines, result):
        location = f"line {line}"
        if location not in flagged and number <= 0.0:
            issues.append(
                _row_issue(
                    f"invalid_{column}",
                    line,
                    f"{column} must be > 0, got {number:g}",
                )
            )
    return result


def _timestamps(
    values: list[str],
    column: str,
    lines: NDArray[np.int64],
    issues: list[ValidationIssue],
) -> pd.DatetimeIndex:
    """Parse ISO 8601 timestamps that carry an explicit UTC offset.

    Only ``YYYY-MM-DD[T ]HH:MM[:SS[.fffffffff]]`` followed by ``Z`` or
    ``+hh:mm`` is accepted. A naive timestamp is rejected rather than assumed
    to be UTC (an exchange log in local time would shift every trade by
    hours), and so is any other layout (03/04/2025 is 3 April in one country
    and 4 March in another).
    """

    parsed: list[pd.Timestamp | None] = []
    for line, value in zip(lines, values):
        match = _ISO_8601.match(value)
        stamp: pd.Timestamp | None = None
        if match and match.group("offset"):
            try:
                stamp = pd.Timestamp(value)
            except (ValueError, TypeError):
                stamp = None
        if match and not match.group("offset"):
            issues.append(
                _row_issue(
                    f"naive_{column}",
                    line,
                    f"{column} '{value}' has no UTC offset (use Z or +hh:mm)",
                )
            )
            parsed.append(None)
        elif stamp is None or pd.isna(stamp):
            issues.append(
                _row_issue(
                    f"invalid_{column}",
                    line,
                    f"{column} must be ISO 8601 with an offset "
                    f"(2025-01-02T14:30:00Z), got '{value}'",
                )
            )
            parsed.append(None)
        else:
            parsed.append(stamp.tz_convert("UTC"))
    return pd.DatetimeIndex(
        [pd.NaT if stamp is None else stamp for stamp in parsed], tz="UTC"
    ).as_unit("ns")


def _issue(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        severity=IssueSeverity.ERROR,
        blocking=True,
    )


def _row_issue(code: str, line: int | np.integer, message: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=f"line {line}: {message}",
        severity=IssueSeverity.ERROR,
        blocking=True,
        location=f"line {line}",
    )


def _capped(issues: list[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    if len(issues) <= _MAX_REPORTED_ISSUES:
        return tuple(issues)
    extra = len(issues) - _MAX_REPORTED_ISSUES
    return tuple(issues[:_MAX_REPORTED_ISSUES]) + (
        _issue("more_issues", f"{extra} further issues not shown"),
    )
