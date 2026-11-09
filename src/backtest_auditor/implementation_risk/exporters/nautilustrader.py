"""Deterministic exporter for completed NautilusTrader report tables."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_auditor.implementation_risk.adapters.engine_csv import (
    canonical_csv_bytes,
    canonical_decimal,
)
from backtest_auditor.implementation_risk.domain import (
    ComparisonLevel,
    EngineExportPayload,
    SupportedEngine,
)
from backtest_auditor.implementation_risk.exporters.common import (
    adapter_metadata_payload,
    installed_engine_version,
    utc_timestamp,
    write_engine_export,
)


NAUTILUSTRADER_EXPORT_FORMAT_ID = "backtest-auditor.nautilustrader"
NAUTILUSTRADER_TESTED_VERSION = "1.231.0"
NAUTILUSTRADER_ORDERS_FILE = "nautilustrader-orders.csv"
NAUTILUSTRADER_FILLS_FILE = "nautilustrader-fills.csv"
NAUTILUSTRADER_POSITIONS_FILE = "nautilustrader-positions.csv"
NAUTILUSTRADER_CASH_FILE = "nautilustrader-cash.csv"

NAUTILUSTRADER_ORDERS_HEADERS = (
    "order_id",
    "instrument",
    "created_at",
    "last_updated_at",
    "side",
    "type",
    "status",
    "quantity",
    "time_in_force",
    "limit_price",
    "stop_price",
)
NAUTILUSTRADER_FILLS_HEADERS = (
    "fill_id",
    "order_id",
    "instrument",
    "timestamp",
    "side",
    "quantity",
    "price",
    "currency",
    "liquidity_role",
    "fee_amount",
    "fee_currency",
    "position_id",
)
NAUTILUSTRADER_POSITIONS_HEADERS = (
    "position_id",
    "instrument",
    "opened_at",
    "last_updated_at",
    "closed_at",
    "entry_side",
    "side",
    "peak_quantity",
    "quantity",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "realized_pnl_currency",
    "is_snapshot",
)
NAUTILUSTRADER_CASH_HEADERS = (
    "timestamp",
    "currency",
    "total",
)

NAUTILUSTRADER_LEVELS = (
    ComparisonLevel.ORDER,
    ComparisonLevel.FILL,
    ComparisonLevel.TRADE,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
)

_ORDERS_COLUMNS = (
    "instrument_id",
    "side",
    "type",
    "status",
    "quantity",
    "time_in_force",
    "ts_init",
    "ts_last",
)
_FILLS_COLUMNS = (
    "trade_id",
    "instrument_id",
    "order_side",
    "last_px",
    "last_qty",
    "currency",
    "liquidity_side",
    "commission",
    "ts_event",
)
_POSITIONS_COLUMNS = (
    "instrument_id",
    "entry",
    "side",
    "quantity",
    "peak_qty",
    "avg_px_open",
    "avg_px_close",
    "realized_pnl",
    "ts_opened",
    "ts_last",
    "ts_closed",
    "is_snapshot",
)
_ACCOUNT_COLUMNS = (
    "currency",
    "total",
)


def _frame(
    value: object,
    *,
    field: str,
    require_unique_index: bool,
) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise ValueError(f"{field} must be a pandas DataFrame.")
    if value.columns.has_duplicates:
        raise ValueError(f"{field} columns must be unique.")
    if require_unique_index and value.index.has_duplicates:
        raise ValueError(f"{field} index must be unique.")
    return value


def _require_columns(
    frame: pd.DataFrame,
    required: tuple[str, ...],
    *,
    field: str,
) -> None:
    if frame.empty:
        return
    missing = tuple(column for column in required if column not in frame.columns)
    if missing:
        raise ValueError(f"{field} is missing columns: {', '.join(missing)}.")


def _text(value: object, *, field: str) -> str:
    if pd.isna(value) or not str(value).strip():
        raise ValueError(f"{field} must be non-empty text.")
    return str(value).strip()


def _optional_text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _decimal(value: object, *, field: str) -> str:
    try:
        return canonical_decimal(value)
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error


def _optional_decimal(value: object, *, field: str) -> str:
    if pd.isna(value) or value == "":
        return ""
    return _decimal(value, field=field)


def _timestamp(value: object, *, field: str, nanoseconds: bool = False) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field} must not be a boolean.")
    try:
        if nanoseconds and isinstance(value, (int, float, Decimal)):
            parsed = pd.Timestamp(int(value), unit="ns", tz="UTC")
        else:
            parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{field} is not a valid timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must disclose its UTC offset.")
    return utc_timestamp(parsed.to_pydatetime(), field=field)


def _optional_timestamp(
    value: object,
    *,
    field: str,
    nanoseconds: bool = False,
) -> str:
    if pd.isna(value) or value == "":
        return ""
    return _timestamp(value, field=field, nanoseconds=nanoseconds)


def _money(
    value: object,
    *,
    field: str,
    allow_empty: bool,
) -> tuple[str, str]:
    if pd.isna(value) or value == "":
        if allow_empty:
            return "", ""
        raise ValueError(f"{field} must contain an amount and currency.")
    if hasattr(value, "as_decimal") and hasattr(value, "currency"):
        amount = value.as_decimal()
        currency = str(value.currency)
        return _decimal(amount, field=field), _text(currency, field=field)
    parts = str(value).strip().split()
    if len(parts) != 2:
        raise ValueError(f"{field} must use '<amount> <currency>' spelling.")
    return _decimal(parts[0], field=field), _text(parts[1], field=field)


def _column(row: pd.Series, name: str) -> object:
    return row[name] if name in row.index else pd.NA


def _export_reports(
    *,
    orders_report: pd.DataFrame,
    fills_report: pd.DataFrame,
    positions_report: pd.DataFrame,
    account_report: pd.DataFrame,
    destination: str | Path,
    run_id: str,
    base_currency: str,
    engine_version: str,
    overwrite: bool,
) -> Path:
    orders = _frame(
        orders_report,
        field="orders_report",
        require_unique_index=True,
    )
    fills = _frame(
        fills_report,
        field="fills_report",
        require_unique_index=False,
    )
    positions = _frame(
        positions_report,
        field="positions_report",
        require_unique_index=True,
    )
    account = _frame(
        account_report,
        field="account_report",
        require_unique_index=False,
    )
    _require_columns(orders, _ORDERS_COLUMNS, field="orders_report")
    _require_columns(fills, _FILLS_COLUMNS, field="fills_report")
    _require_columns(positions, _POSITIONS_COLUMNS, field="positions_report")
    _require_columns(account, _ACCOUNT_COLUMNS, field="account_report")

    order_rows: list[dict[str, str]] = []
    for raw_id, row in orders.iterrows():
        order_rows.append(
            {
                "order_id": _text(raw_id, field="client_order_id"),
                "instrument": _text(row["instrument_id"], field="instrument_id"),
                "created_at": _timestamp(
                    row["ts_init"], field="orders_report.ts_init", nanoseconds=True
                ),
                "last_updated_at": _timestamp(
                    row["ts_last"], field="orders_report.ts_last", nanoseconds=True
                ),
                "side": _text(row["side"], field="orders_report.side"),
                "type": _text(row["type"], field="orders_report.type"),
                "status": _text(row["status"], field="orders_report.status"),
                "quantity": _decimal(row["quantity"], field="orders_report.quantity"),
                "time_in_force": _text(
                    row["time_in_force"], field="orders_report.time_in_force"
                ),
                "limit_price": _optional_decimal(
                    _column(row, "price"), field="orders_report.price"
                ),
                "stop_price": _optional_decimal(
                    _column(row, "trigger_price"),
                    field="orders_report.trigger_price",
                ),
            }
        )
    order_rows.sort(key=lambda row: (row["created_at"], row["order_id"]))

    fill_rows: list[dict[str, str]] = []
    for raw_order_id, row in fills.iterrows():
        fee_amount, fee_currency = _money(
            row["commission"],
            field="fills_report.commission",
            allow_empty=True,
        )
        fill_rows.append(
            {
                "fill_id": _text(row["trade_id"], field="trade_id"),
                "order_id": _text(raw_order_id, field="client_order_id"),
                "instrument": _text(row["instrument_id"], field="instrument_id"),
                "timestamp": _timestamp(row["ts_event"], field="fills_report.ts_event"),
                "side": _text(row["order_side"], field="fills_report.order_side"),
                "quantity": _decimal(row["last_qty"], field="fills_report.last_qty"),
                "price": _decimal(row["last_px"], field="fills_report.last_px"),
                "currency": _text(row["currency"], field="fills_report.currency"),
                "liquidity_role": _text(
                    row["liquidity_side"], field="fills_report.liquidity_side"
                ),
                "fee_amount": fee_amount or "0",
                "fee_currency": fee_currency,
                "position_id": _optional_text(_column(row, "position_id")),
            }
        )
    fill_rows.sort(key=lambda row: (row["timestamp"], row["fill_id"]))

    position_rows: list[dict[str, str]] = []
    for raw_position_id, row in positions.iterrows():
        pnl_amount, pnl_currency = _money(
            row["realized_pnl"],
            field="positions_report.realized_pnl",
            allow_empty=True,
        )
        position_rows.append(
            {
                "position_id": _text(raw_position_id, field="position_id"),
                "instrument": _text(row["instrument_id"], field="instrument_id"),
                "opened_at": _timestamp(
                    row["ts_opened"], field="positions_report.ts_opened"
                ),
                "last_updated_at": _timestamp(
                    row["ts_last"],
                    field="positions_report.ts_last",
                    nanoseconds=True,
                ),
                "closed_at": _optional_timestamp(
                    row["ts_closed"], field="positions_report.ts_closed"
                ),
                "entry_side": _text(row["entry"], field="positions_report.entry"),
                "side": _text(row["side"], field="positions_report.side"),
                "peak_quantity": _decimal(
                    row["peak_qty"], field="positions_report.peak_qty"
                ),
                "quantity": _decimal(
                    row["quantity"], field="positions_report.quantity"
                ),
                "entry_price": _decimal(
                    row["avg_px_open"], field="positions_report.avg_px_open"
                ),
                "exit_price": _optional_decimal(
                    row["avg_px_close"], field="positions_report.avg_px_close"
                ),
                "realized_pnl": pnl_amount,
                "realized_pnl_currency": pnl_currency,
                "is_snapshot": "true" if bool(row["is_snapshot"]) else "false",
            }
        )
    position_rows.sort(key=lambda row: (row["opened_at"], row["position_id"]))

    cash_rows: list[dict[str, str]] = []
    for raw_timestamp, row in account.iterrows():
        cash_rows.append(
            {
                "timestamp": _timestamp(
                    raw_timestamp,
                    field="account_report.ts_event",
                    nanoseconds=True,
                ),
                "currency": _text(row["currency"], field="account_report.currency"),
                "total": _decimal(row["total"], field="account_report.total"),
            }
        )
    cash_rows.sort(key=lambda row: (row["timestamp"], row["currency"]))
    cash_keys = [(row["timestamp"], row["currency"]) for row in cash_rows]
    if len(cash_keys) != len(set(cash_keys)):
        raise ValueError(
            "account_report must contain one account scope per timestamp/currency."
        )

    payloads = (
        adapter_metadata_payload(base_currency),
        EngineExportPayload(
            NAUTILUSTRADER_ORDERS_FILE,
            "orders",
            "text/csv",
            canonical_csv_bytes(NAUTILUSTRADER_ORDERS_HEADERS, order_rows),
        ),
        EngineExportPayload(
            NAUTILUSTRADER_FILLS_FILE,
            "fills",
            "text/csv",
            canonical_csv_bytes(NAUTILUSTRADER_FILLS_HEADERS, fill_rows),
        ),
        EngineExportPayload(
            NAUTILUSTRADER_POSITIONS_FILE,
            "positions",
            "text/csv",
            canonical_csv_bytes(
                NAUTILUSTRADER_POSITIONS_HEADERS,
                position_rows,
            ),
        ),
        EngineExportPayload(
            NAUTILUSTRADER_CASH_FILE,
            "cash",
            "text/csv",
            canonical_csv_bytes(NAUTILUSTRADER_CASH_HEADERS, cash_rows),
        ),
    )
    return write_engine_export(
        run_id=run_id,
        engine=SupportedEngine.NAUTILUSTRADER,
        engine_version=engine_version,
        export_format_id=NAUTILUSTRADER_EXPORT_FORMAT_ID,
        declared_levels=NAUTILUSTRADER_LEVELS,
        payloads=payloads,
        destination=destination,
        overwrite=overwrite,
    )


def export_nautilustrader_reports(
    orders_report: pd.DataFrame,
    fills_report: pd.DataFrame,
    positions_report: pd.DataFrame,
    account_report: pd.DataFrame,
    destination: str | Path,
    *,
    run_id: str,
    base_currency: str,
    overwrite: bool = False,
) -> Path:
    """Export the four documented reports from one completed run/account."""

    engine_version = installed_engine_version("nautilus_trader")
    if engine_version != NAUTILUSTRADER_TESTED_VERSION:
        raise ValueError(
            "NautilusTrader exporter was tested only with "
            f"{NAUTILUSTRADER_TESTED_VERSION}; installed version is "
            f"{engine_version}."
        )
    return _export_reports(
        orders_report=orders_report,
        fills_report=fills_report,
        positions_report=positions_report,
        account_report=account_report,
        destination=destination,
        run_id=run_id,
        base_currency=base_currency,
        engine_version=engine_version,
        overwrite=overwrite,
    )


def export_nautilustrader_engine(
    engine: Any,
    venue: Any,
    destination: str | Path,
    *,
    run_id: str,
    base_currency: str,
    overwrite: bool = False,
) -> Path:
    """Generate documented reports from one already completed engine.

    NautilusTrader 1.231.0's ``BacktestEngine`` exposes the report methods on
    its ``trader``, not on the engine itself, so an engine without them is
    read through ``engine.trader``.
    """

    methods = (
        "generate_orders_report",
        "generate_fills_report",
        "generate_positions_report",
        "generate_account_report",
    )
    reporter = engine
    trader = getattr(engine, "trader", None)
    if not callable(getattr(engine, methods[0], None)) and trader is not None:
        reporter = trader
    for method in methods:
        if not callable(getattr(reporter, method, None)):
            raise ValueError(f"engine.{method} must be callable.")
    try:
        orders = reporter.generate_orders_report()
        fills = reporter.generate_fills_report()
        positions = reporter.generate_positions_report()
        account = reporter.generate_account_report(venue=venue)
    except Exception as error:
        raise ValueError("NautilusTrader reports could not be generated.") from error
    return export_nautilustrader_reports(
        orders,
        fills,
        positions,
        account,
        destination,
        run_id=run_id,
        base_currency=base_currency,
        overwrite=overwrite,
    )


__all__ = ["export_nautilustrader_engine", "export_nautilustrader_reports"]
