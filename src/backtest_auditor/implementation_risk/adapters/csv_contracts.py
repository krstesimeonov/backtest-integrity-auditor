"""Deterministic CSV mappings for flat canonical artifact histories."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Generic, TypeVar

from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
    describe_name_difference,
)
from backtest_auditor.implementation_risk.domain import (
    ArtifactReturnConvention,
    CashBalance,
    CashMovement,
    CashMovementType,
    CostRecord,
    CostType,
    EquityPoint,
    FillRecord,
    LiquidityRole,
    MarketDataObservation,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    ReturnPoint,
    SignalRecord,
    SignalType,
    TimeInForce,
    TradeDirection,
    TradeRecord,
)


_RecordT = TypeVar("_RecordT")
_UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class CsvRecordContract(Generic[_RecordT]):
    file_name: str
    headers: tuple[str, ...]
    encode: Callable[[_RecordT], dict[str, str]]
    decode: Callable[[dict[str, str]], _RecordT]


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal(value: Decimal | None) -> str:
    return "" if value is None else _decimal(value)


def _parse_optional_decimal(value: str) -> Decimal | None:
    return None if value == "" else Decimal(value)


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(_UTC)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _optional_timestamp(value: datetime | None) -> str:
    return "" if value is None else _timestamp(value)


def _parse_timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("timestamp must use canonical UTC Z notation.")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if _timestamp(parsed) != value:
        raise ValueError("timestamp must include six fractional digits.")
    return parsed


def _parse_optional_timestamp(value: str) -> datetime | None:
    return None if value == "" else _parse_timestamp(value)


def _optional_text(value: str | None) -> str:
    return "" if value is None else value


def _parse_optional_text(value: str) -> str | None:
    return None if value == "" else value


MARKET_DATA = CsvRecordContract(
    "market_data.csv",
    (
        "observation_id",
        "instrument_id",
        "event_timestamp",
        "available_timestamp",
        "field",
        "value",
        "unit",
    ),
    lambda item: {
        "observation_id": item.observation_id,
        "instrument_id": item.instrument_id,
        "event_timestamp": _timestamp(item.event_timestamp),
        "available_timestamp": _optional_timestamp(item.available_timestamp),
        "field": item.field,
        "value": _decimal(item.value),
        "unit": _optional_text(item.unit),
    },
    lambda row: MarketDataObservation(
        observation_id=row["observation_id"],
        instrument_id=row["instrument_id"],
        event_timestamp=_parse_timestamp(row["event_timestamp"]),
        available_timestamp=_parse_optional_timestamp(row["available_timestamp"]),
        field=row["field"],
        value=Decimal(row["value"]),
        unit=_parse_optional_text(row["unit"]),
    ),
)

SIGNALS = CsvRecordContract(
    "signals.csv",
    (
        "signal_id",
        "timestamp",
        "instrument_id",
        "signal_type",
        "value",
        "source_data_timestamp",
    ),
    lambda item: {
        "signal_id": item.signal_id,
        "timestamp": _timestamp(item.timestamp),
        "instrument_id": item.instrument_id,
        "signal_type": item.signal_type.value,
        "value": _optional_decimal(item.value),
        "source_data_timestamp": _optional_timestamp(item.source_data_timestamp),
    },
    lambda row: SignalRecord(
        signal_id=row["signal_id"],
        timestamp=_parse_timestamp(row["timestamp"]),
        instrument_id=row["instrument_id"],
        signal_type=SignalType(row["signal_type"]),
        value=_parse_optional_decimal(row["value"]),
        source_data_timestamp=_parse_optional_timestamp(row["source_data_timestamp"]),
    ),
)

ORDERS = CsvRecordContract(
    "orders.csv",
    (
        "order_id",
        "created_at",
        "instrument_id",
        "side",
        "quantity",
        "order_type",
        "time_in_force",
        "status",
        "signal_id",
        "parent_order_id",
        "submitted_at",
        "last_updated_at",
        "expires_at",
        "limit_price",
        "stop_price",
    ),
    lambda item: {
        "order_id": item.order_id,
        "created_at": _timestamp(item.created_at),
        "instrument_id": item.instrument_id,
        "side": item.side.value,
        "quantity": _decimal(item.quantity),
        "order_type": item.order_type.value,
        "time_in_force": item.time_in_force.value,
        "status": item.status.value,
        "signal_id": _optional_text(item.signal_id),
        "parent_order_id": _optional_text(item.parent_order_id),
        "submitted_at": _optional_timestamp(item.submitted_at),
        "last_updated_at": _optional_timestamp(item.last_updated_at),
        "expires_at": _optional_timestamp(item.expires_at),
        "limit_price": _optional_decimal(item.limit_price),
        "stop_price": _optional_decimal(item.stop_price),
    },
    lambda row: OrderRecord(
        order_id=row["order_id"],
        created_at=_parse_timestamp(row["created_at"]),
        instrument_id=row["instrument_id"],
        side=OrderSide(row["side"]),
        quantity=Decimal(row["quantity"]),
        order_type=OrderType(row["order_type"]),
        time_in_force=TimeInForce(row["time_in_force"]),
        status=OrderStatus(row["status"]),
        signal_id=_parse_optional_text(row["signal_id"]),
        parent_order_id=_parse_optional_text(row["parent_order_id"]),
        submitted_at=_parse_optional_timestamp(row["submitted_at"]),
        last_updated_at=_parse_optional_timestamp(row["last_updated_at"]),
        expires_at=_parse_optional_timestamp(row["expires_at"]),
        limit_price=_parse_optional_decimal(row["limit_price"]),
        stop_price=_parse_optional_decimal(row["stop_price"]),
    ),
)

FILLS = CsvRecordContract(
    "fills.csv",
    (
        "fill_id",
        "order_id",
        "timestamp",
        "instrument_id",
        "side",
        "quantity",
        "price",
        "currency",
        "liquidity_role",
        "venue",
    ),
    lambda item: {
        "fill_id": item.fill_id,
        "order_id": item.order_id,
        "timestamp": _timestamp(item.timestamp),
        "instrument_id": item.instrument_id,
        "side": item.side.value,
        "quantity": _decimal(item.quantity),
        "price": _decimal(item.price),
        "currency": item.currency,
        "liquidity_role": item.liquidity_role.value,
        "venue": _optional_text(item.venue),
    },
    lambda row: FillRecord(
        fill_id=row["fill_id"],
        order_id=row["order_id"],
        timestamp=_parse_timestamp(row["timestamp"]),
        instrument_id=row["instrument_id"],
        side=OrderSide(row["side"]),
        quantity=Decimal(row["quantity"]),
        price=Decimal(row["price"]),
        currency=row["currency"],
        liquidity_role=LiquidityRole(row["liquidity_role"]),
        venue=_parse_optional_text(row["venue"]),
    ),
)

TRADES = CsvRecordContract(
    "trades.csv",
    (
        "trade_id",
        "instrument_id",
        "direction",
        "opened_at",
        "quantity",
        "entry_price",
        "currency",
        "grouping_method",
        "closed_at",
        "exit_price",
        "realized_pnl",
    ),
    lambda item: {
        "trade_id": item.trade_id,
        "instrument_id": item.instrument_id,
        "direction": item.direction.value,
        "opened_at": _timestamp(item.opened_at),
        "quantity": _decimal(item.quantity),
        "entry_price": _decimal(item.entry_price),
        "currency": item.currency,
        "grouping_method": item.grouping_method,
        "closed_at": _optional_timestamp(item.closed_at),
        "exit_price": _optional_decimal(item.exit_price),
        "realized_pnl": _optional_decimal(item.realized_pnl),
    },
    lambda row: TradeRecord(
        trade_id=row["trade_id"],
        instrument_id=row["instrument_id"],
        direction=TradeDirection(row["direction"]),
        opened_at=_parse_timestamp(row["opened_at"]),
        quantity=Decimal(row["quantity"]),
        entry_price=Decimal(row["entry_price"]),
        currency=row["currency"],
        grouping_method=row["grouping_method"],
        closed_at=_parse_optional_timestamp(row["closed_at"]),
        exit_price=_parse_optional_decimal(row["exit_price"]),
        realized_pnl=_parse_optional_decimal(row["realized_pnl"]),
    ),
)

POSITIONS = CsvRecordContract(
    "positions.csv",
    (
        "timestamp",
        "instrument_id",
        "quantity",
        "currency",
        "market_price",
        "market_value",
        "average_cost",
        "realized_pnl",
        "unrealized_pnl",
    ),
    lambda item: {
        "timestamp": _timestamp(item.timestamp),
        "instrument_id": item.instrument_id,
        "quantity": _decimal(item.quantity),
        "currency": item.currency,
        "market_price": _optional_decimal(item.market_price),
        "market_value": _optional_decimal(item.market_value),
        "average_cost": _optional_decimal(item.average_cost),
        "realized_pnl": _optional_decimal(item.realized_pnl),
        "unrealized_pnl": _optional_decimal(item.unrealized_pnl),
    },
    lambda row: PositionSnapshot(
        timestamp=_parse_timestamp(row["timestamp"]),
        instrument_id=row["instrument_id"],
        quantity=Decimal(row["quantity"]),
        currency=row["currency"],
        market_price=_parse_optional_decimal(row["market_price"]),
        market_value=_parse_optional_decimal(row["market_value"]),
        average_cost=_parse_optional_decimal(row["average_cost"]),
        realized_pnl=_parse_optional_decimal(row["realized_pnl"]),
        unrealized_pnl=_parse_optional_decimal(row["unrealized_pnl"]),
    ),
)

CASH_BALANCES = CsvRecordContract(
    "cash_balances.csv",
    ("timestamp", "currency", "total", "settled"),
    lambda item: {
        "timestamp": _timestamp(item.timestamp),
        "currency": item.currency,
        "total": _decimal(item.total),
        "settled": _optional_decimal(item.settled),
    },
    lambda row: CashBalance(
        timestamp=_parse_timestamp(row["timestamp"]),
        currency=row["currency"],
        total=Decimal(row["total"]),
        settled=_parse_optional_decimal(row["settled"]),
    ),
)

CASH_MOVEMENTS = CsvRecordContract(
    "cash_movements.csv",
    (
        "movement_id",
        "timestamp",
        "currency",
        "amount",
        "movement_type",
        "related_artifact_id",
    ),
    lambda item: {
        "movement_id": item.movement_id,
        "timestamp": _timestamp(item.timestamp),
        "currency": item.currency,
        "amount": _decimal(item.amount),
        "movement_type": item.movement_type.value,
        "related_artifact_id": _optional_text(item.related_artifact_id),
    },
    lambda row: CashMovement(
        movement_id=row["movement_id"],
        timestamp=_parse_timestamp(row["timestamp"]),
        currency=row["currency"],
        amount=Decimal(row["amount"]),
        movement_type=CashMovementType(row["movement_type"]),
        related_artifact_id=_parse_optional_text(row["related_artifact_id"]),
    ),
)

COSTS = CsvRecordContract(
    "costs.csv",
    (
        "cost_id",
        "timestamp",
        "cost_type",
        "pnl_impact",
        "currency",
        "order_id",
        "fill_id",
        "trade_id",
    ),
    lambda item: {
        "cost_id": item.cost_id,
        "timestamp": _timestamp(item.timestamp),
        "cost_type": item.cost_type.value,
        "pnl_impact": _decimal(item.pnl_impact),
        "currency": item.currency,
        "order_id": _optional_text(item.order_id),
        "fill_id": _optional_text(item.fill_id),
        "trade_id": _optional_text(item.trade_id),
    },
    lambda row: CostRecord(
        cost_id=row["cost_id"],
        timestamp=_parse_timestamp(row["timestamp"]),
        cost_type=CostType(row["cost_type"]),
        pnl_impact=Decimal(row["pnl_impact"]),
        currency=row["currency"],
        order_id=_parse_optional_text(row["order_id"]),
        fill_id=_parse_optional_text(row["fill_id"]),
        trade_id=_parse_optional_text(row["trade_id"]),
    ),
)

EQUITY = CsvRecordContract(
    "equity.csv",
    (
        "timestamp",
        "currency",
        "total_equity",
        "cash",
        "gross_exposure",
        "net_exposure",
    ),
    lambda item: {
        "timestamp": _timestamp(item.timestamp),
        "currency": item.currency,
        "total_equity": _decimal(item.total_equity),
        "cash": _optional_decimal(item.cash),
        "gross_exposure": _optional_decimal(item.gross_exposure),
        "net_exposure": _optional_decimal(item.net_exposure),
    },
    lambda row: EquityPoint(
        timestamp=_parse_timestamp(row["timestamp"]),
        currency=row["currency"],
        total_equity=Decimal(row["total_equity"]),
        cash=_parse_optional_decimal(row["cash"]),
        gross_exposure=_parse_optional_decimal(row["gross_exposure"]),
        net_exposure=_parse_optional_decimal(row["net_exposure"]),
    ),
)

RETURNS = CsvRecordContract(
    "returns.csv",
    ("start_timestamp", "end_timestamp", "value", "convention"),
    lambda item: {
        "start_timestamp": _timestamp(item.start_timestamp),
        "end_timestamp": _timestamp(item.end_timestamp),
        "value": _decimal(item.value),
        "convention": item.convention.value,
    },
    lambda row: ReturnPoint(
        start_timestamp=_parse_timestamp(row["start_timestamp"]),
        end_timestamp=_parse_timestamp(row["end_timestamp"]),
        value=Decimal(row["value"]),
        convention=ArtifactReturnConvention(row["convention"]),
    ),
)


def encode_csv(
    contract: CsvRecordContract[_RecordT],
    records: Iterable[_RecordT],
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=contract.headers,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for record in records:
        writer.writerow(contract.encode(record))
    return output.getvalue().encode("utf-8")


def decode_csv(
    contract: CsvRecordContract[_RecordT],
    data: bytes,
) -> tuple[_RecordT, ...]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            "CSV must be valid UTF-8 without a byte-order mark.",
            file_path=contract.file_name,
        ) from error
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    supplied = tuple(reader.fieldnames or ())
    if supplied != contract.headers:
        difference, field = describe_name_difference(
            contract.headers, supplied, noun="column"
        )
        raise BundleContractError(
            BundleErrorCode.HEADER_MISMATCH,
            f"CSV header does not match the versioned contract: {difference}.",
            file_path=contract.file_name,
            field=field,
        )
    records: list[_RecordT] = []
    try:
        for row in reader:
            if set(row) != set(contract.headers) or any(
                value is None for value in row.values()
            ):
                raise ValueError("row has missing or additional columns.")
            records.append(contract.decode(row))
    except (csv.Error, ArithmeticError, TypeError, ValueError) as error:
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            str(error),
            file_path=contract.file_name,
            row_number=reader.line_num,
        ) from error
    result = tuple(records)
    if encode_csv(contract, result) != data:
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            "CSV must use canonical UTF-8, quoting, newlines, and scalar encoding.",
            file_path=contract.file_name,
        )
    return result


TRADE_FILLS_FILE = "trade_fills.csv"
TRADE_FILLS_HEADERS = ("trade_id", "fill_id")


def encode_trade_fills(trades: Iterable[TradeRecord]) -> bytes:
    links = sorted(
        (trade.trade_id, fill_id) for trade in trades for fill_id in trade.fill_ids
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(TRADE_FILLS_HEADERS)
    writer.writerows(links)
    return output.getvalue().encode("utf-8")


def decode_trade_fills(data: bytes) -> tuple[tuple[str, str], ...]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            "CSV must be valid UTF-8 without a byte-order mark.",
            file_path=TRADE_FILLS_FILE,
        ) from error
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = tuple(next(reader))
    except (StopIteration, csv.Error) as error:
        raise BundleContractError(
            BundleErrorCode.HEADER_MISMATCH,
            "trade-fill CSV header is missing or invalid.",
            file_path=TRADE_FILLS_FILE,
        ) from error
    if header != TRADE_FILLS_HEADERS:
        difference, field = describe_name_difference(
            TRADE_FILLS_HEADERS, header, noun="column"
        )
        raise BundleContractError(
            BundleErrorCode.HEADER_MISMATCH,
            f"CSV header does not match the versioned contract: {difference}.",
            file_path=TRADE_FILLS_FILE,
            field=field,
        )
    links: list[tuple[str, str]] = []
    try:
        for row in reader:
            if len(row) != 2 or not row[0] or not row[1]:
                raise ValueError("trade-fill rows require trade_id and fill_id.")
            links.append((row[0], row[1]))
    except (csv.Error, ValueError) as error:
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            str(error),
            file_path=TRADE_FILLS_FILE,
            row_number=reader.line_num,
        ) from error
    result = tuple(links)
    if len(set(result)) != len(result):
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            "trade-fill relationships must be unique.",
            file_path=TRADE_FILLS_FILE,
        )
    if result != tuple(sorted(result)):
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            "trade-fill relationships must be in canonical order.",
            file_path=TRADE_FILLS_FILE,
        )
    empty_trades = tuple(
        TradeRecord(
            trade_id=trade_id,
            instrument_id="placeholder",
            direction=TradeDirection.LONG,
            opened_at=datetime(1970, 1, 1, tzinfo=_UTC),
            quantity=Decimal(1),
            entry_price=Decimal(1),
            currency="USD",
            grouping_method="link serialization",
            fill_ids=(fill_id,),
        )
        for trade_id, fill_id in result
    )
    if encode_trade_fills(empty_trades) != data:
        raise BundleContractError(
            BundleErrorCode.INVALID_ROW,
            "CSV must use canonical UTF-8, quoting, newlines, and ordering.",
            file_path=TRADE_FILLS_FILE,
        )
    return result


ALL_PRIMARY_CONTRACTS: tuple[CsvRecordContract[Any], ...] = (
    MARKET_DATA,
    SIGNALS,
    ORDERS,
    FILLS,
    TRADES,
    POSITIONS,
    CASH_BALANCES,
    CASH_MOVEMENTS,
    COSTS,
    EQUITY,
    RETURNS,
)
