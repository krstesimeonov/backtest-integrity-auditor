"""Immutable canonical records exported from a backtesting engine."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, TypeVar

from backtest_auditor.implementation_risk.domain.enums import (
    ArtifactReturnConvention,
    CashMovementType,
    CostType,
    LiquidityRole,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalType,
    TimeInForce,
    TradeDirection,
)
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_currency,
    normalize_decimal,
    normalize_optional_decimal,
    normalize_optional_text,
    normalize_optional_timestamp,
    normalize_text,
    normalize_timestamp,
)


_MAX_IDENTIFIER_LENGTH = 128
_MAX_TEXT_LENGTH = 256
_EnumT = TypeVar("_EnumT", bound=StrEnum)
_RecordT = TypeVar("_RecordT")


def _identifier(value: object, *, field: str) -> str:
    return normalize_text(value, field=field, maximum_length=_MAX_IDENTIFIER_LENGTH)


def _optional_identifier(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field=field)


def _enum_value(
    value: object,
    enum_type: type[_EnumT],
    *,
    field: str,
) -> _EnumT:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} has an unsupported value.")
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} has an unsupported value.") from error


@dataclass(frozen=True, slots=True)
class MarketDataObservation:
    """One numeric field in canonical long format.

    ``event_timestamp`` is the economic timestamp of the observation;
    ``available_timestamp`` is when the strategy could first use it.
    """

    observation_id: str
    instrument_id: str
    event_timestamp: datetime
    field: str
    value: Decimal
    available_timestamp: datetime | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _identifier(self.observation_id, field="observation_id"),
        )
        object.__setattr__(
            self,
            "instrument_id",
            _identifier(self.instrument_id, field="instrument_id"),
        )
        event_timestamp = normalize_timestamp(
            self.event_timestamp, field="event_timestamp"
        )
        available_timestamp = normalize_optional_timestamp(
            self.available_timestamp,
            field="available_timestamp",
        )
        if available_timestamp is not None and available_timestamp < event_timestamp:
            raise ValueError(
                "available_timestamp must not be earlier than event_timestamp."
            )
        object.__setattr__(self, "event_timestamp", event_timestamp)
        object.__setattr__(self, "available_timestamp", available_timestamp)
        object.__setattr__(
            self,
            "field",
            normalize_text(
                self.field,
                field="market-data field",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "value",
            normalize_decimal(self.value, field="market-data value"),
        )
        object.__setattr__(
            self,
            "unit",
            normalize_optional_text(
                self.unit,
                field="market-data unit",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class SignalRecord:
    signal_id: str
    timestamp: datetime
    instrument_id: str
    signal_type: SignalType
    value: Decimal | None = None
    source_data_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "signal_id", _identifier(self.signal_id, field="signal_id")
        )
        object.__setattr__(
            self,
            "instrument_id",
            _identifier(self.instrument_id, field="instrument_id"),
        )
        timestamp = normalize_timestamp(self.timestamp, field="signal timestamp")
        source_timestamp = normalize_optional_timestamp(
            self.source_data_timestamp,
            field="source_data_timestamp",
        )
        if source_timestamp is not None and source_timestamp > timestamp:
            raise ValueError(
                "source_data_timestamp must not be later than the signal timestamp."
            )
        signal_type = _enum_value(
            self.signal_type,
            SignalType,
            field="signal_type",
        )
        value = normalize_optional_decimal(self.value, field="signal value")
        value_required = {
            SignalType.TARGET_QUANTITY,
            SignalType.TARGET_WEIGHT,
            SignalType.TARGET_NOTIONAL,
            SignalType.SCORE,
        }
        if signal_type in value_required and value is None:
            raise ValueError(f"{signal_type.value} signals require a value.")
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "source_data_timestamp", source_timestamp)
        object.__setattr__(self, "signal_type", signal_type)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class OrderRecord:
    order_id: str
    created_at: datetime
    instrument_id: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    status: OrderStatus
    signal_id: str | None = None
    parent_order_id: str | None = None
    submitted_at: datetime | None = None
    last_updated_at: datetime | None = None
    expires_at: datetime | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None

    def __post_init__(self) -> None:
        order_id = _identifier(self.order_id, field="order_id")
        object.__setattr__(self, "order_id", order_id)
        object.__setattr__(
            self,
            "instrument_id",
            _identifier(self.instrument_id, field="instrument_id"),
        )
        signal_id = _optional_identifier(self.signal_id, field="signal_id")
        parent_order_id = _optional_identifier(
            self.parent_order_id,
            field="parent_order_id",
        )
        if parent_order_id == order_id:
            raise ValueError("parent_order_id must not equal order_id.")
        object.__setattr__(self, "signal_id", signal_id)
        object.__setattr__(self, "parent_order_id", parent_order_id)

        created_at = normalize_timestamp(self.created_at, field="created_at")
        submitted_at = normalize_optional_timestamp(
            self.submitted_at,
            field="submitted_at",
        )
        last_updated_at = normalize_optional_timestamp(
            self.last_updated_at,
            field="last_updated_at",
        )
        expires_at = normalize_optional_timestamp(self.expires_at, field="expires_at")
        for field, timestamp in (
            ("submitted_at", submitted_at),
            ("last_updated_at", last_updated_at),
            ("expires_at", expires_at),
        ):
            if timestamp is not None and timestamp < created_at:
                raise ValueError(f"{field} must not be earlier than created_at.")
        if (
            submitted_at is not None
            and last_updated_at is not None
            and last_updated_at < submitted_at
        ):
            raise ValueError("last_updated_at must not be earlier than submitted_at.")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "submitted_at", submitted_at)
        object.__setattr__(self, "last_updated_at", last_updated_at)
        object.__setattr__(self, "expires_at", expires_at)

        side = _enum_value(self.side, OrderSide, field="side")
        order_type = _enum_value(self.order_type, OrderType, field="order_type")
        time_in_force = _enum_value(
            self.time_in_force,
            TimeInForce,
            field="time_in_force",
        )
        status = _enum_value(self.status, OrderStatus, field="status")
        quantity = normalize_decimal(self.quantity, field="quantity", positive=True)
        limit_price = normalize_optional_decimal(
            self.limit_price,
            field="limit_price",
            positive=True,
        )
        stop_price = normalize_optional_decimal(
            self.stop_price,
            field="stop_price",
            positive=True,
        )

        if order_type in {OrderType.LIMIT, OrderType.LIMIT_ON_CLOSE}:
            if limit_price is None or stop_price is not None:
                raise ValueError("limit orders require only limit_price.")
        elif order_type is OrderType.STOP:
            if stop_price is None or limit_price is not None:
                raise ValueError("stop orders require only stop_price.")
        elif order_type is OrderType.STOP_LIMIT:
            if limit_price is None or stop_price is None:
                raise ValueError(
                    "stop-limit orders require limit_price and stop_price."
                )
        elif order_type in {OrderType.MARKET, OrderType.MARKET_ON_CLOSE}:
            if limit_price is not None or stop_price is not None:
                raise ValueError("market orders must not declare limit or stop prices.")

        if time_in_force is TimeInForce.GTD and expires_at is None:
            raise ValueError("GTD orders require expires_at.")
        if time_in_force is not TimeInForce.GTD and expires_at is not None:
            raise ValueError("expires_at is allowed only for GTD orders.")
        submitted_statuses = {
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.EXPIRED,
        }
        if status in submitted_statuses and submitted_at is None:
            raise ValueError(f"{status.value} orders require submitted_at.")

        object.__setattr__(self, "side", side)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "time_in_force", time_in_force)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "limit_price", limit_price)
        object.__setattr__(self, "stop_price", stop_price)


@dataclass(frozen=True, slots=True)
class FillRecord:
    fill_id: str
    order_id: str
    timestamp: datetime
    instrument_id: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    currency: str
    liquidity_role: LiquidityRole = LiquidityRole.UNKNOWN
    venue: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fill_id", _identifier(self.fill_id, field="fill_id"))
        object.__setattr__(
            self, "order_id", _identifier(self.order_id, field="order_id")
        )
        object.__setattr__(
            self,
            "instrument_id",
            _identifier(self.instrument_id, field="instrument_id"),
        )
        object.__setattr__(
            self,
            "timestamp",
            normalize_timestamp(self.timestamp, field="fill timestamp"),
        )
        object.__setattr__(
            self, "side", _enum_value(self.side, OrderSide, field="side")
        )
        object.__setattr__(
            self,
            "quantity",
            normalize_decimal(self.quantity, field="quantity", positive=True),
        )
        object.__setattr__(
            self,
            "price",
            normalize_decimal(self.price, field="price", positive=True),
        )
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(
            self,
            "liquidity_role",
            _enum_value(
                self.liquidity_role,
                LiquidityRole,
                field="liquidity_role",
            ),
        )
        object.__setattr__(
            self,
            "venue",
            normalize_optional_text(
                self.venue,
                field="venue",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class TradeRecord:
    trade_id: str
    instrument_id: str
    direction: TradeDirection
    opened_at: datetime
    quantity: Decimal
    entry_price: Decimal
    currency: str
    grouping_method: str
    closed_at: datetime | None = None
    exit_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    fill_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "trade_id", _identifier(self.trade_id, field="trade_id")
        )
        object.__setattr__(
            self,
            "instrument_id",
            _identifier(self.instrument_id, field="instrument_id"),
        )
        object.__setattr__(
            self,
            "direction",
            _enum_value(self.direction, TradeDirection, field="direction"),
        )
        opened_at = normalize_timestamp(self.opened_at, field="opened_at")
        closed_at = normalize_optional_timestamp(self.closed_at, field="closed_at")
        if closed_at is not None and closed_at < opened_at:
            raise ValueError("closed_at must not be earlier than opened_at.")
        exit_price = normalize_optional_decimal(
            self.exit_price,
            field="exit_price",
            positive=True,
        )
        realized_pnl = normalize_optional_decimal(
            self.realized_pnl,
            field="realized_pnl",
        )
        if closed_at is None and (exit_price is not None or realized_pnl is not None):
            raise ValueError("open trades must not declare exit_price or realized_pnl.")
        if closed_at is not None and exit_price is None:
            raise ValueError("closed trades require exit_price.")
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "closed_at", closed_at)
        object.__setattr__(
            self,
            "quantity",
            normalize_decimal(self.quantity, field="quantity", positive=True),
        )
        object.__setattr__(
            self,
            "entry_price",
            normalize_decimal(self.entry_price, field="entry_price", positive=True),
        )
        object.__setattr__(self, "exit_price", exit_price)
        object.__setattr__(self, "realized_pnl", realized_pnl)
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(
            self,
            "grouping_method",
            normalize_text(
                self.grouping_method,
                field="grouping_method",
                maximum_length=_MAX_TEXT_LENGTH,
            ),
        )
        try:
            fill_ids = tuple(
                _identifier(value, field="fill_id") for value in self.fill_ids
            )
        except TypeError as error:
            raise ValueError("fill_ids must be an iterable.") from error
        if len(set(fill_ids)) != len(fill_ids):
            raise ValueError("fill_ids must not contain duplicates.")
        object.__setattr__(self, "fill_ids", tuple(sorted(fill_ids)))


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    timestamp: datetime
    instrument_id: str
    quantity: Decimal
    currency: str
    market_price: Decimal | None = None
    market_value: Decimal | None = None
    average_cost: Decimal | None = None
    realized_pnl: Decimal | None = None
    unrealized_pnl: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp",
            normalize_timestamp(self.timestamp, field="position timestamp"),
        )
        object.__setattr__(
            self,
            "instrument_id",
            _identifier(self.instrument_id, field="instrument_id"),
        )
        object.__setattr__(
            self,
            "quantity",
            normalize_decimal(self.quantity, field="quantity"),
        )
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(
            self,
            "market_price",
            normalize_optional_decimal(
                self.market_price,
                field="market_price",
                positive=True,
            ),
        )
        object.__setattr__(
            self,
            "market_value",
            normalize_optional_decimal(self.market_value, field="market_value"),
        )
        object.__setattr__(
            self,
            "average_cost",
            normalize_optional_decimal(
                self.average_cost,
                field="average_cost",
                non_negative=True,
            ),
        )
        object.__setattr__(
            self,
            "realized_pnl",
            normalize_optional_decimal(self.realized_pnl, field="realized_pnl"),
        )
        object.__setattr__(
            self,
            "unrealized_pnl",
            normalize_optional_decimal(self.unrealized_pnl, field="unrealized_pnl"),
        )


@dataclass(frozen=True, slots=True)
class CashBalance:
    timestamp: datetime
    currency: str
    total: Decimal
    settled: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp",
            normalize_timestamp(self.timestamp, field="cash-balance timestamp"),
        )
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(self, "total", normalize_decimal(self.total, field="total"))
        object.__setattr__(
            self,
            "settled",
            normalize_optional_decimal(self.settled, field="settled"),
        )


@dataclass(frozen=True, slots=True)
class CashMovement:
    movement_id: str
    timestamp: datetime
    currency: str
    amount: Decimal
    movement_type: CashMovementType
    related_artifact_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "movement_id", _identifier(self.movement_id, field="movement_id")
        )
        object.__setattr__(
            self,
            "timestamp",
            normalize_timestamp(self.timestamp, field="cash-movement timestamp"),
        )
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        amount = normalize_decimal(self.amount, field="amount")
        if amount == 0:
            raise ValueError("cash movement amount must not be zero.")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(
            self,
            "movement_type",
            _enum_value(
                self.movement_type,
                CashMovementType,
                field="movement_type",
            ),
        )
        object.__setattr__(
            self,
            "related_artifact_id",
            _optional_identifier(
                self.related_artifact_id,
                field="related_artifact_id",
            ),
        )


@dataclass(frozen=True, slots=True)
class CashArtifacts:
    """Cash evidence distinguishes unavailable from available-but-empty series."""

    balances: tuple[CashBalance, ...] | None = None
    movements: tuple[CashMovement, ...] | None = None

    def __post_init__(self) -> None:
        if self.balances is None and self.movements is None:
            raise ValueError("cash artifacts require balances, movements, or both.")
        balances = self._collection(self.balances, CashBalance, field="balances")
        movements = self._collection(self.movements, CashMovement, field="movements")
        if balances is not None:
            self._require_unique(
                balances,
                key=lambda item: (item.timestamp, item.currency),
                field="cash balance timestamp/currency",
            )
            self._require_ordered(
                balances,
                key=lambda item: (item.timestamp, item.currency),
                field="balances",
            )
        if movements is not None:
            self._require_unique(
                movements,
                key=lambda item: item.movement_id,
                field="movement_id",
            )
            self._require_ordered(
                movements,
                key=lambda item: (item.timestamp, item.movement_id),
                field="movements",
            )
        object.__setattr__(self, "balances", balances)
        object.__setattr__(self, "movements", movements)

    @staticmethod
    def _collection(
        value: Iterable[_RecordT] | None,
        item_type: type[_RecordT],
        *,
        field: str,
    ) -> tuple[_RecordT, ...] | None:
        if value is None:
            return None
        try:
            values = tuple(value)
        except TypeError as error:
            raise ValueError(f"{field} must be an iterable or None.") from error
        if any(not isinstance(item, item_type) for item in values):
            raise ValueError(f"{field} contains an invalid record type.")
        return values

    @staticmethod
    def _require_unique(
        values: tuple[_RecordT, ...],
        *,
        key: Callable[[_RecordT], Any],
        field: str,
    ) -> None:
        identities = tuple(key(item) for item in values)
        if len(set(identities)) != len(identities):
            raise ValueError(f"{field} values must be unique.")

    @staticmethod
    def _require_ordered(
        values: tuple[_RecordT, ...],
        *,
        key: Callable[[_RecordT], Any],
        field: str,
    ) -> None:
        if values != tuple(sorted(values, key=key)):
            raise ValueError(f"{field} must be in canonical order.")


@dataclass(frozen=True, slots=True)
class CostRecord:
    """Signed P&L impact: negative is a cost; positive is a rebate."""

    cost_id: str
    timestamp: datetime
    cost_type: CostType
    pnl_impact: Decimal
    currency: str
    order_id: str | None = None
    fill_id: str | None = None
    trade_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost_id", _identifier(self.cost_id, field="cost_id"))
        object.__setattr__(
            self,
            "timestamp",
            normalize_timestamp(self.timestamp, field="cost timestamp"),
        )
        object.__setattr__(
            self,
            "cost_type",
            _enum_value(self.cost_type, CostType, field="cost_type"),
        )
        object.__setattr__(
            self,
            "pnl_impact",
            normalize_decimal(self.pnl_impact, field="pnl_impact"),
        )
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        for field in ("order_id", "fill_id", "trade_id"):
            object.__setattr__(
                self,
                field,
                _optional_identifier(getattr(self, field), field=field),
            )


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    currency: str
    total_equity: Decimal
    cash: Decimal | None = None
    gross_exposure: Decimal | None = None
    net_exposure: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp",
            normalize_timestamp(self.timestamp, field="equity timestamp"),
        )
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(
            self,
            "total_equity",
            normalize_decimal(self.total_equity, field="total_equity"),
        )
        object.__setattr__(
            self,
            "cash",
            normalize_optional_decimal(self.cash, field="cash"),
        )
        object.__setattr__(
            self,
            "gross_exposure",
            normalize_optional_decimal(
                self.gross_exposure,
                field="gross_exposure",
                non_negative=True,
            ),
        )
        object.__setattr__(
            self,
            "net_exposure",
            normalize_optional_decimal(self.net_exposure, field="net_exposure"),
        )


@dataclass(frozen=True, slots=True)
class ReturnPoint:
    start_timestamp: datetime
    end_timestamp: datetime
    value: Decimal
    convention: ArtifactReturnConvention

    def __post_init__(self) -> None:
        start = normalize_timestamp(self.start_timestamp, field="start_timestamp")
        end = normalize_timestamp(self.end_timestamp, field="end_timestamp")
        if end <= start:
            raise ValueError("end_timestamp must be later than start_timestamp.")
        convention = _enum_value(
            self.convention,
            ArtifactReturnConvention,
            field="return convention",
        )
        value = normalize_decimal(self.value, field="return value")
        if convention is ArtifactReturnConvention.SIMPLE and value < -1:
            raise ValueError("simple returns must be greater than or equal to -1.")
        object.__setattr__(self, "start_timestamp", start)
        object.__setattr__(self, "end_timestamp", end)
        object.__setattr__(self, "convention", convention)
        object.__setattr__(self, "value", value)
