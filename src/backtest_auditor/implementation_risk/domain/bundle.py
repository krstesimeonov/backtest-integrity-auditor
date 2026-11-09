"""Canonical run-artifact bundle and cross-record integrity rules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar

from backtest_auditor.implementation_risk.domain.artifacts import (
    CashArtifacts,
    CostRecord,
    EquityPoint,
    FillRecord,
    MarketDataObservation,
    OrderRecord,
    PositionSnapshot,
    ReturnPoint,
    SignalRecord,
    TradeRecord,
)
from backtest_auditor.implementation_risk.domain.enums import (
    ComparisonLevel,
    OrderStatus,
)
from backtest_auditor.implementation_risk.domain.scope import (
    EngineRunReference,
    RunEvidenceProfile,
)
from backtest_auditor.implementation_risk.domain.specification import (
    CanonicalRunSpecification,
)
from backtest_auditor.implementation_risk.domain.validation import exact_add


CANONICAL_ARTIFACT_SCHEMA_VERSION = "1.0"
_RecordT = TypeVar("_RecordT")


def _record_collection(
    value: Iterable[_RecordT] | None,
    item_type: type[_RecordT],
    *,
    field: str,
) -> tuple[_RecordT, ...] | None:
    if value is None:
        return None
    try:
        records = tuple(value)
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable or None.") from error
    if any(not isinstance(record, item_type) for record in records):
        raise ValueError(f"{field} contains an invalid record type.")
    return records


def _require_unique(
    records: tuple[_RecordT, ...],
    *,
    key: Callable[[_RecordT], Hashable],
    field: str,
) -> None:
    identities = tuple(key(record) for record in records)
    if len(set(identities)) != len(identities):
        raise ValueError(f"{field} values must be unique.")


def _require_canonical_order(
    records: tuple[_RecordT, ...],
    *,
    key: Callable[[_RecordT], Any],
    field: str,
) -> None:
    if records != tuple(sorted(records, key=key)):
        raise ValueError(f"{field} must be in canonical order.")


@dataclass(frozen=True, slots=True)
class CanonicalRunArtifacts:
    """All available canonical evidence for one exported run.

    ``None`` means that a level was not supplied. An empty tuple means the
    level was supplied and contains no records. That distinction is retained
    for honest eligibility reporting.
    """

    run: EngineRunReference
    specification: CanonicalRunSpecification | None = None
    market_data: tuple[MarketDataObservation, ...] | None = None
    signals: tuple[SignalRecord, ...] | None = None
    orders: tuple[OrderRecord, ...] | None = None
    fills: tuple[FillRecord, ...] | None = None
    trades: tuple[TradeRecord, ...] | None = None
    positions: tuple[PositionSnapshot, ...] | None = None
    cash: CashArtifacts | None = None
    costs: tuple[CostRecord, ...] | None = None
    equity: tuple[EquityPoint, ...] | None = None
    returns: tuple[ReturnPoint, ...] | None = None
    artifact_schema_version: str = CANONICAL_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.run, EngineRunReference):
            raise ValueError("run must be an EngineRunReference.")
        if self.specification is not None and not isinstance(
            self.specification,
            CanonicalRunSpecification,
        ):
            raise ValueError(
                "specification must be a CanonicalRunSpecification or None."
            )
        if self.cash is not None and not isinstance(self.cash, CashArtifacts):
            raise ValueError("cash must be CashArtifacts or None.")
        if self.artifact_schema_version != CANONICAL_ARTIFACT_SCHEMA_VERSION:
            raise ValueError(
                "artifact_schema_version must equal "
                f"{CANONICAL_ARTIFACT_SCHEMA_VERSION!r}."
            )

        market_data = _record_collection(
            self.market_data,
            MarketDataObservation,
            field="market_data",
        )
        signals = _record_collection(self.signals, SignalRecord, field="signals")
        orders = _record_collection(self.orders, OrderRecord, field="orders")
        fills = _record_collection(self.fills, FillRecord, field="fills")
        trades = _record_collection(self.trades, TradeRecord, field="trades")
        positions = _record_collection(
            self.positions,
            PositionSnapshot,
            field="positions",
        )
        costs = _record_collection(self.costs, CostRecord, field="costs")
        equity = _record_collection(self.equity, EquityPoint, field="equity")
        returns = _record_collection(self.returns, ReturnPoint, field="returns")

        for field, records, identity, order in (
            (
                "market_data",
                market_data,
                lambda item: item.observation_id,
                lambda item: (
                    item.event_timestamp,
                    item.available_timestamp or item.event_timestamp,
                    item.instrument_id,
                    item.field,
                    item.observation_id,
                ),
            ),
            (
                "signals",
                signals,
                lambda item: item.signal_id,
                lambda item: (item.timestamp, item.signal_id),
            ),
            (
                "orders",
                orders,
                lambda item: item.order_id,
                lambda item: (item.created_at, item.order_id),
            ),
            (
                "fills",
                fills,
                lambda item: item.fill_id,
                lambda item: (item.timestamp, item.fill_id),
            ),
            (
                "trades",
                trades,
                lambda item: item.trade_id,
                lambda item: (item.opened_at, item.trade_id),
            ),
            (
                "positions",
                positions,
                lambda item: (item.timestamp, item.instrument_id),
                lambda item: (item.timestamp, item.instrument_id),
            ),
            (
                "costs",
                costs,
                lambda item: item.cost_id,
                lambda item: (item.timestamp, item.cost_id),
            ),
            (
                "equity",
                equity,
                lambda item: item.timestamp,
                lambda item: item.timestamp,
            ),
            (
                "returns",
                returns,
                lambda item: (item.start_timestamp, item.end_timestamp),
                lambda item: (item.end_timestamp, item.start_timestamp),
            ),
        ):
            if records is not None:
                _require_unique(records, key=identity, field=f"{field} identity")
                _require_canonical_order(records, key=order, field=field)

        object.__setattr__(self, "market_data", market_data)
        object.__setattr__(self, "signals", signals)
        object.__setattr__(self, "orders", orders)
        object.__setattr__(self, "fills", fills)
        object.__setattr__(self, "trades", trades)
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "costs", costs)
        object.__setattr__(self, "equity", equity)
        object.__setattr__(self, "returns", returns)

        self._validate_instrument_references(
            market_data=market_data,
            signals=signals,
            orders=orders,
            fills=fills,
            trades=trades,
            positions=positions,
        )
        self._validate_signal_order_fill_chain(
            signals=signals,
            orders=orders,
            fills=fills,
        )
        self._validate_trade_fill_chain(trades=trades, fills=fills)
        self._validate_cost_references(
            costs=costs,
            orders=orders,
            fills=fills,
            trades=trades,
        )
        self._validate_base_currency(equity=equity)

    @property
    def available_levels(self) -> tuple[ComparisonLevel, ...]:
        availability = {
            ComparisonLevel.STRATEGY_SPECIFICATION: self.specification is not None,
            ComparisonLevel.MARKET_DATA: self.market_data is not None,
            ComparisonLevel.SIGNAL: self.signals is not None,
            ComparisonLevel.ORDER: self.orders is not None,
            ComparisonLevel.FILL: self.fills is not None,
            ComparisonLevel.TRADE: self.trades is not None,
            ComparisonLevel.POSITION: self.positions is not None,
            ComparisonLevel.CASH: self.cash is not None,
            ComparisonLevel.COST: self.costs is not None,
            ComparisonLevel.EQUITY: self.equity is not None,
            ComparisonLevel.RETURN: self.returns is not None,
        }
        return tuple(level for level in ComparisonLevel if availability[level])

    def evidence_profile(self) -> RunEvidenceProfile:
        return RunEvidenceProfile(
            run=self.run,
            available_levels=self.available_levels,
        )

    def _validate_instrument_references(
        self,
        *,
        market_data: tuple[MarketDataObservation, ...] | None,
        signals: tuple[SignalRecord, ...] | None,
        orders: tuple[OrderRecord, ...] | None,
        fills: tuple[FillRecord, ...] | None,
        trades: tuple[TradeRecord, ...] | None,
        positions: tuple[PositionSnapshot, ...] | None,
    ) -> None:
        if self.specification is None:
            return
        instruments = {
            item.instrument_id: item for item in self.specification.strategy.universe
        }
        for field, records in (
            ("market_data", market_data),
            ("signals", signals),
            ("orders", orders),
            ("fills", fills),
            ("trades", trades),
            ("positions", positions),
        ):
            if records is None:
                continue
            unknown = sorted(
                {
                    record.instrument_id
                    for record in records
                    if record.instrument_id not in instruments
                }
            )
            if unknown:
                raise ValueError(
                    f"{field} references instruments outside the strategy universe: "
                    + ", ".join(unknown)
                    + "."
                )

        for fill_record in fills or ():
            expected_currency = instruments[fill_record.instrument_id].currency
            if fill_record.currency != expected_currency:
                raise ValueError(
                    f"fill {fill_record.fill_id!r} currency does not match its instrument."
                )
        for trade_record in trades or ():
            expected_currency = instruments[trade_record.instrument_id].currency
            if trade_record.currency != expected_currency:
                raise ValueError(
                    f"trade {trade_record.trade_id!r} currency does not match its instrument."
                )
        for position_record in positions or ():
            expected_currency = instruments[position_record.instrument_id].currency
            if position_record.currency != expected_currency:
                raise ValueError(
                    "position currency does not match instrument "
                    f"{position_record.instrument_id!r}."
                )

    @staticmethod
    def _validate_signal_order_fill_chain(
        *,
        signals: tuple[SignalRecord, ...] | None,
        orders: tuple[OrderRecord, ...] | None,
        fills: tuple[FillRecord, ...] | None,
    ) -> None:
        signals_by_id = (
            None if signals is None else {item.signal_id: item for item in signals}
        )
        orders_by_id = (
            None if orders is None else {item.order_id: item for item in orders}
        )
        if orders_by_id is not None:
            for order in orders_by_id.values():
                if order.parent_order_id is not None:
                    parent = orders_by_id.get(order.parent_order_id)
                    if parent is None:
                        raise ValueError(
                            f"order {order.order_id!r} references an unknown parent order."
                        )
                    if parent.created_at > order.created_at:
                        raise ValueError(
                            "parent orders must not be created after children."
                        )
                if order.signal_id is not None and signals_by_id is not None:
                    signal = signals_by_id.get(order.signal_id)
                    if signal is None:
                        raise ValueError(
                            f"order {order.order_id!r} references an unknown signal."
                        )
                    if signal.instrument_id != order.instrument_id:
                        raise ValueError(
                            "signal and order instrument_id values must match."
                        )
                    if signal.timestamp > order.created_at:
                        raise ValueError("signals must not occur after their orders.")

        if fills is None or orders_by_id is None:
            return
        quantities_by_order: dict[str, Decimal] = defaultdict(Decimal)
        for fill in fills:
            related_order = orders_by_id.get(fill.order_id)
            if related_order is None:
                raise ValueError(f"fill {fill.fill_id!r} references an unknown order.")
            if (
                fill.instrument_id != related_order.instrument_id
                or fill.side is not related_order.side
            ):
                raise ValueError(
                    "fill instrument and side must match the related order."
                )
            earliest_fill = related_order.submitted_at or related_order.created_at
            if fill.timestamp < earliest_fill:
                raise ValueError("fills must not occur before their related orders.")
            quantities_by_order[related_order.order_id] = exact_add(
                quantities_by_order[related_order.order_id], fill.quantity
            )

        for order_id, order in orders_by_id.items():
            filled_quantity = quantities_by_order[order_id]
            if filled_quantity > order.quantity:
                raise ValueError(f"fills exceed order quantity for {order_id!r}.")
            if order.status is OrderStatus.FILLED and filled_quantity != order.quantity:
                raise ValueError(
                    f"filled order {order_id!r} must be completely filled."
                )
            if order.status is OrderStatus.PARTIALLY_FILLED and not (
                Decimal(0) < filled_quantity < order.quantity
            ):
                raise ValueError(
                    f"partially filled order {order_id!r} needs a partial quantity."
                )
            if order.status in {
                OrderStatus.CREATED,
                OrderStatus.SUBMITTED,
                OrderStatus.ACCEPTED,
                OrderStatus.REJECTED,
            } and filled_quantity != Decimal(0):
                raise ValueError(
                    f"{order.status.value} order {order_id!r} must not have fills."
                )

    @staticmethod
    def _validate_trade_fill_chain(
        *,
        trades: tuple[TradeRecord, ...] | None,
        fills: tuple[FillRecord, ...] | None,
    ) -> None:
        if trades is None or fills is None:
            return
        fills_by_id = {item.fill_id: item for item in fills}
        for trade in trades:
            for fill_id in trade.fill_ids:
                fill = fills_by_id.get(fill_id)
                if fill is None:
                    raise ValueError(
                        f"trade {trade.trade_id!r} references an unknown fill."
                    )
                if fill.instrument_id != trade.instrument_id:
                    raise ValueError("trade and fill instrument_id values must match.")

    @staticmethod
    def _validate_cost_references(
        *,
        costs: tuple[CostRecord, ...] | None,
        orders: tuple[OrderRecord, ...] | None,
        fills: tuple[FillRecord, ...] | None,
        trades: tuple[TradeRecord, ...] | None,
    ) -> None:
        if costs is None:
            return
        identifiers = {
            "order_id": None if orders is None else {item.order_id for item in orders},
            "fill_id": None if fills is None else {item.fill_id for item in fills},
            "trade_id": None if trades is None else {item.trade_id for item in trades},
        }
        for cost in costs:
            for field, known in identifiers.items():
                reference = getattr(cost, field)
                if (
                    reference is not None
                    and known is not None
                    and reference not in known
                ):
                    raise ValueError(
                        f"cost {cost.cost_id!r} references an unknown {field}."
                    )

    def _validate_base_currency(
        self,
        *,
        equity: tuple[EquityPoint, ...] | None,
    ) -> None:
        if self.specification is None or equity is None:
            return
        base_currency = self.specification.simulation.base_currency
        if any(item.currency != base_currency for item in equity):
            raise ValueError("equity currency must equal the simulation base currency.")
