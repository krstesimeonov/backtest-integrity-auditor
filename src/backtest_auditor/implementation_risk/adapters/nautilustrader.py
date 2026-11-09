"""SDK-neutral mapper for NautilusTrader 1.231.0 report exports."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from backtest_auditor.implementation_risk.adapters.engine_csv import (
    ADAPTER_METADATA_FILE,
    map_row_failure,
    mapping_error,
    optional_decimal,
    optional_timestamp,
    parse_decimal,
    parse_timestamp,
    read_adapter_metadata,
    read_csv_rows,
    require_payload_contract,
)
from backtest_auditor.implementation_risk.domain import (
    AdapterCapability,
    AdapterWarning,
    CanonicalRunArtifacts,
    CashArtifacts,
    CashBalance,
    CapabilityAvailability,
    ComparisonLevel,
    CostRecord,
    CostType,
    EngineAdapterDescriptor,
    EngineMappingOutput,
    EngineRunReference,
    EvidenceOrigin,
    FillRecord,
    LiquidityRole,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    SupportedEngine,
    TimeInForce,
    TradeDirection,
    TradeRecord,
    VerifiedEngineExport,
)
from backtest_auditor.implementation_risk.exporters.nautilustrader import (
    NAUTILUSTRADER_CASH_FILE,
    NAUTILUSTRADER_CASH_HEADERS,
    NAUTILUSTRADER_EXPORT_FORMAT_ID,
    NAUTILUSTRADER_FILLS_FILE,
    NAUTILUSTRADER_FILLS_HEADERS,
    NAUTILUSTRADER_ORDERS_FILE,
    NAUTILUSTRADER_ORDERS_HEADERS,
    NAUTILUSTRADER_POSITIONS_FILE,
    NAUTILUSTRADER_POSITIONS_HEADERS,
    NAUTILUSTRADER_TESTED_VERSION,
)
from backtest_auditor.implementation_risk.domain.validation import exact_add


NAUTILUSTRADER_ADAPTER_ID = "backtest-auditor.nautilustrader"


def _capability(
    level: ComparisonLevel,
    availability: CapabilityAvailability,
    origin: EvidenceOrigin,
    explanation: str,
) -> AdapterCapability:
    return AdapterCapability(level, availability, origin, explanation)


NAUTILUSTRADER_DESCRIPTOR = EngineAdapterDescriptor(
    adapter_id=NAUTILUSTRADER_ADAPTER_ID,
    adapter_version="1.0.0",
    engine=SupportedEngine.NAUTILUSTRADER,
    display_name="NautilusTrader",
    export_format_id=NAUTILUSTRADER_EXPORT_FORMAT_ID,
    supported_export_format_versions=("1.0",),
    tested_engine_versions=(NAUTILUSTRADER_TESTED_VERSION,),
    allow_undisclosed_engine_version=False,
    allow_untested_engine_version=False,
    capabilities=(
        _capability(
            ComparisonLevel.STRATEGY_SPECIFICATION,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Post-run reports do not retain a complete canonical strategy configuration.",
        ),
        _capability(
            ComparisonLevel.MARKET_DATA,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Report tables do not contain the exact market-data event history.",
        ),
        _capability(
            ComparisonLevel.SIGNAL,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Strategy signals are not part of the documented report set.",
        ),
        _capability(
            ComparisonLevel.ORDER,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "The orders report maps final lifecycle, quantity, type, and time-in-force fields.",
        ),
        _capability(
            ComparisonLevel.FILL,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "The fills report supplies one row per OrderFilled event.",
        ),
        _capability(
            ComparisonLevel.TRADE,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Position and snapshot report rows retain engine-native position grouping and realized P&L.",
        ),
        _capability(
            ComparisonLevel.POSITION,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.DETERMINISTIC_DERIVATION,
            "Instrument net quantities are summed at each reported position update timestamp.",
        ),
        _capability(
            ComparisonLevel.CASH,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "One account report supplies timestamped balances by currency.",
        ),
        _capability(
            ComparisonLevel.COST,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Per-fill commissions map to fill-linked commission impacts.",
        ),
        _capability(
            ComparisonLevel.EQUITY,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Account balances are not promoted to portfolio equity without valuation evidence.",
        ),
        _capability(
            ComparisonLevel.RETURN,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "The documented report set does not expose a timestamped portfolio return series.",
        ),
    ),
)

_PAYLOAD_CONTRACT = {
    ADAPTER_METADATA_FILE: ("adapter_metadata", "application/json"),
    NAUTILUSTRADER_ORDERS_FILE: ("orders", "text/csv"),
    NAUTILUSTRADER_FILLS_FILE: ("fills", "text/csv"),
    NAUTILUSTRADER_POSITIONS_FILE: ("positions", "text/csv"),
    NAUTILUSTRADER_CASH_FILE: ("cash", "text/csv"),
}

_ORDER_TYPES = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP_MARKET": OrderType.STOP,
    "STOP_LIMIT": OrderType.STOP_LIMIT,
    "MARKET_ON_CLOSE": OrderType.MARKET_ON_CLOSE,
    "LIMIT_ON_CLOSE": OrderType.LIMIT_ON_CLOSE,
}
_TIME_IN_FORCE = {
    "DAY": TimeInForce.DAY,
    "GTC": TimeInForce.GTC,
    "IOC": TimeInForce.IOC,
    "FOK": TimeInForce.FOK,
    "AT_THE_OPEN": TimeInForce.AT_OPEN,
    "AT_THE_CLOSE": TimeInForce.AT_CLOSE,
}
_ORDER_STATUSES = {
    "INITIALIZED": OrderStatus.CREATED,
    "EMULATED": OrderStatus.CREATED,
    "RELEASED": OrderStatus.CREATED,
    "SUBMITTED": OrderStatus.SUBMITTED,
    "PENDING_UPDATE": OrderStatus.SUBMITTED,
    "PENDING_CANCEL": OrderStatus.SUBMITTED,
    "TRIGGERED": OrderStatus.ACCEPTED,
    "ACCEPTED": OrderStatus.ACCEPTED,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "EXPIRED": OrderStatus.EXPIRED,
    "REJECTED": OrderStatus.REJECTED,
    "DENIED": OrderStatus.REJECTED,
}


class NautilusTraderArtifactMapper:
    """Normalize verified report CSVs without importing NautilusTrader."""

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        return NAUTILUSTRADER_DESCRIPTOR

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        payloads = require_payload_contract(
            export,
            _PAYLOAD_CONTRACT,
            engine=SupportedEngine.NAUTILUSTRADER,
            adapter_id=NAUTILUSTRADER_ADAPTER_ID,
        )
        base_currency = read_adapter_metadata(
            payloads[ADAPTER_METADATA_FILE],
            engine=SupportedEngine.NAUTILUSTRADER,
            adapter_id=NAUTILUSTRADER_ADAPTER_ID,
        )
        order_rows = read_csv_rows(
            payloads[NAUTILUSTRADER_ORDERS_FILE],
            NAUTILUSTRADER_ORDERS_HEADERS,
            engine=SupportedEngine.NAUTILUSTRADER,
            adapter_id=NAUTILUSTRADER_ADAPTER_ID,
        )
        fill_rows = read_csv_rows(
            payloads[NAUTILUSTRADER_FILLS_FILE],
            NAUTILUSTRADER_FILLS_HEADERS,
            engine=SupportedEngine.NAUTILUSTRADER,
            adapter_id=NAUTILUSTRADER_ADAPTER_ID,
        )
        position_rows = read_csv_rows(
            payloads[NAUTILUSTRADER_POSITIONS_FILE],
            NAUTILUSTRADER_POSITIONS_HEADERS,
            engine=SupportedEngine.NAUTILUSTRADER,
            adapter_id=NAUTILUSTRADER_ADAPTER_ID,
        )
        cash_rows = read_csv_rows(
            payloads[NAUTILUSTRADER_CASH_FILE],
            NAUTILUSTRADER_CASH_HEADERS,
            engine=SupportedEngine.NAUTILUSTRADER,
            adapter_id=NAUTILUSTRADER_ADAPTER_ID,
        )

        orders: list[OrderRecord] = []
        custom_order_type = False
        custom_time_in_force = False
        collapsed_status = False
        for row_number, row in enumerate(order_rows, start=2):
            try:
                created = parse_timestamp(row["created_at"])
                status = _ORDER_STATUSES[row["status"]]
                order_type = _ORDER_TYPES.get(row["type"], OrderType.CUSTOM)
                custom_order_type = custom_order_type or order_type is OrderType.CUSTOM
                custom_time_in_force = (
                    custom_time_in_force or row["time_in_force"] not in _TIME_IN_FORCE
                )
                collapsed_status = collapsed_status or row["status"] in {
                    "EMULATED",
                    "RELEASED",
                    "PENDING_UPDATE",
                    "PENDING_CANCEL",
                    "TRIGGERED",
                    "DENIED",
                }
                orders.append(
                    OrderRecord(
                        order_id=f"nt-order-{row['order_id']}",
                        created_at=created,
                        instrument_id=row["instrument"],
                        side={"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}[
                            row["side"]
                        ],
                        quantity=parse_decimal(row["quantity"], non_negative=True),
                        order_type=order_type,
                        time_in_force=_TIME_IN_FORCE.get(
                            row["time_in_force"], TimeInForce.CUSTOM
                        ),
                        status=status,
                        submitted_at=(
                            None
                            if status in {OrderStatus.CREATED, OrderStatus.REJECTED}
                            else created
                        ),
                        last_updated_at=parse_timestamp(row["last_updated_at"]),
                        limit_price=optional_decimal(
                            row["limit_price"], non_negative=True
                        ),
                        stop_price=optional_decimal(
                            row["stop_price"], non_negative=True
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.NAUTILUSTRADER,
                    adapter_id=NAUTILUSTRADER_ADAPTER_ID,
                    file_path=NAUTILUSTRADER_ORDERS_FILE,
                    row_number=row_number,
                )

        fills: list[FillRecord] = []
        costs: list[CostRecord] = []
        for row_number, row in enumerate(fill_rows, start=2):
            try:
                fill_id = f"nt-fill-{row['fill_id']}"
                order_id = f"nt-order-{row['order_id']}"
                timestamp = parse_timestamp(row["timestamp"])
                fills.append(
                    FillRecord(
                        fill_id=fill_id,
                        order_id=order_id,
                        timestamp=timestamp,
                        instrument_id=row["instrument"],
                        side={"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}[
                            row["side"]
                        ],
                        quantity=parse_decimal(row["quantity"], non_negative=True),
                        price=parse_decimal(row["price"], non_negative=True),
                        currency=row["currency"],
                        liquidity_role={
                            "MAKER": LiquidityRole.MAKER,
                            "TAKER": LiquidityRole.TAKER,
                            "NO_LIQUIDITY_SIDE": LiquidityRole.UNKNOWN,
                        }[row["liquidity_role"]],
                    )
                )
                fee = parse_decimal(row["fee_amount"], non_negative=True)
                if fee != 0:
                    costs.append(
                        CostRecord(
                            cost_id=f"nt-fee-{row['fill_id']}",
                            timestamp=timestamp,
                            cost_type=CostType.COMMISSION,
                            pnl_impact=fee.copy_negate(),
                            currency=row["fee_currency"],
                            order_id=order_id,
                            fill_id=fill_id,
                        )
                    )
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.NAUTILUSTRADER,
                    adapter_id=NAUTILUSTRADER_ADAPTER_ID,
                    file_path=NAUTILUSTRADER_FILLS_FILE,
                    row_number=row_number,
                )

        trades: list[TradeRecord] = []
        grouped_positions: defaultdict[tuple[datetime, str], Decimal] = defaultdict(
            Decimal
        )
        position_currencies: dict[str, str] = {}
        position_spans: defaultdict[str, list[tuple[datetime, datetime | None]]] = (
            defaultdict(list)
        )
        for row_number, row in enumerate(position_rows, start=2):
            try:
                opened = parse_timestamp(row["opened_at"])
                updated = parse_timestamp(row["last_updated_at"])
                closed = optional_timestamp(row["closed_at"])
                direction = {
                    "BUY": TradeDirection.LONG,
                    "SELL": TradeDirection.SHORT,
                }[row["entry_side"]]
                trade_currency = row["realized_pnl_currency"] or base_currency
                peak = parse_decimal(row["peak_quantity"], non_negative=True)
                if peak == 0:
                    raise ValueError("peak_quantity must be positive.")
                trades.append(
                    TradeRecord(
                        trade_id=f"nt-position-{row['position_id']}",
                        instrument_id=row["instrument"],
                        direction=direction,
                        opened_at=opened,
                        quantity=peak,
                        entry_price=parse_decimal(
                            row["entry_price"], non_negative=True
                        ),
                        currency=trade_currency,
                        grouping_method="NautilusTrader position_id",
                        closed_at=closed,
                        exit_price=(
                            optional_decimal(row["exit_price"], non_negative=True)
                            if closed is not None
                            else None
                        ),
                        realized_pnl=(
                            optional_decimal(row["realized_pnl"])
                            if closed is not None
                            else None
                        ),
                    )
                )
                raw_quantity = parse_decimal(row["quantity"], non_negative=True)
                signed_quantity = {
                    "LONG": raw_quantity,
                    "SHORT": raw_quantity.copy_negate(),
                    "FLAT": Decimal(0),
                }[row["side"]]
                key = (updated, row["instrument"])
                grouped_positions[key] = exact_add(
                    grouped_positions[key], signed_quantity
                )
                position_spans[row["instrument"]].append((opened, closed))
                position_currencies[row["instrument"]] = trade_currency
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.NAUTILUSTRADER,
                    adapter_id=NAUTILUSTRADER_ADAPTER_ID,
                    file_path=NAUTILUSTRADER_POSITIONS_FILE,
                    row_number=row_number,
                )
        # A row's quantity is the instrument's net quantity only while no other
        # position of that instrument is open (NETTING, one strategy). Under
        # HEDGING, or with several strategies, positions overlap and a row
        # states one leg, so the derived snapshot would misstate the net.
        for spans in position_spans.values():
            spans.sort(key=lambda span: span[0])
            for (_, first_closed), (second_opened, _) in zip(spans, spans[1:]):
                if first_closed is None or second_opened < first_closed:
                    mapping_error(
                        engine=SupportedEngine.NAUTILUSTRADER,
                        adapter_id=NAUTILUSTRADER_ADAPTER_ID,
                        detail="overlapping_positions",
                        message=(
                            "positions of one instrument overlap (HEDGING or "
                            "several strategies); a report row is not the "
                            "instrument's net quantity."
                        ),
                        file_path=NAUTILUSTRADER_POSITIONS_FILE,
                    )
        positions = tuple(
            PositionSnapshot(
                timestamp=timestamp,
                instrument_id=instrument,
                quantity=quantity,
                currency=position_currencies[instrument],
            )
            for (timestamp, instrument), quantity in sorted(grouped_positions.items())
        )

        balances: list[CashBalance] = []
        for row_number, row in enumerate(cash_rows, start=2):
            try:
                balances.append(
                    CashBalance(
                        timestamp=parse_timestamp(row["timestamp"]),
                        currency=row["currency"],
                        total=parse_decimal(row["total"]),
                    )
                )
            except (TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.NAUTILUSTRADER,
                    adapter_id=NAUTILUSTRADER_ADAPTER_ID,
                    file_path=NAUTILUSTRADER_CASH_FILE,
                    row_number=row_number,
                )

        envelope = export.envelope
        artifacts = CanonicalRunArtifacts(
            run=EngineRunReference(
                run_id=envelope.run_id,
                engine_name=envelope.engine.value,
                engine_version=envelope.engine_version,
                source_sha256=envelope.source_sha256,
            ),
            orders=tuple(
                sorted(orders, key=lambda item: (item.created_at, item.order_id))
            ),
            fills=tuple(sorted(fills, key=lambda item: (item.timestamp, item.fill_id))),
            trades=tuple(
                sorted(trades, key=lambda item: (item.opened_at, item.trade_id))
            ),
            positions=positions,
            cash=CashArtifacts(
                balances=tuple(
                    sorted(balances, key=lambda item: (item.timestamp, item.currency))
                )
            ),
            costs=tuple(sorted(costs, key=lambda item: (item.timestamp, item.cost_id))),
        )
        warning_values = [
            AdapterWarning(
                "nautilustrader.position_fill_links_unavailable",
                "The positions report preserves engine-native grouping but does not list every contributing fill ID.",
                NAUTILUSTRADER_POSITIONS_FILE,
            ),
            AdapterWarning(
                "nautilustrader.position_snapshots_quantity_only",
                "Canonical position snapshots are timestamp/instrument net quantities without valuation fields.",
                NAUTILUSTRADER_POSITIONS_FILE,
            ),
        ]
        if custom_order_type:
            warning_values.append(
                AdapterWarning(
                    "nautilustrader.order_type_mapped_custom",
                    "At least one NautilusTrader order type has no exact canonical equivalent and was retained as custom.",
                    NAUTILUSTRADER_ORDERS_FILE,
                    field="type",
                )
            )
        if custom_time_in_force:
            warning_values.append(
                AdapterWarning(
                    "nautilustrader.time_in_force_mapped_custom",
                    "At least one NautilusTrader time-in-force has no exact canonical equivalent and was retained as custom.",
                    NAUTILUSTRADER_ORDERS_FILE,
                    field="time_in_force",
                )
            )
        if collapsed_status:
            warning_values.append(
                AdapterWarning(
                    "nautilustrader.transitional_status_collapsed",
                    "At least one engine-specific transitional status was mapped to the nearest canonical lifecycle state.",
                    NAUTILUSTRADER_ORDERS_FILE,
                    field="status",
                )
            )
        warnings = tuple(
            sorted(
                warning_values,
                key=lambda item: item.sort_key,
            )
        )
        return EngineMappingOutput(artifacts, warnings)


__all__ = [
    "NAUTILUSTRADER_ADAPTER_ID",
    "NAUTILUSTRADER_DESCRIPTOR",
    "NautilusTraderArtifactMapper",
]
