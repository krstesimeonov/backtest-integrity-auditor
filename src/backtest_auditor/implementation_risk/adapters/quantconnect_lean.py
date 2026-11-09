"""SDK-neutral mapper for QuantConnect LEAN 2.5.17999 result exports."""

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
    ArtifactReturnConvention,
    CanonicalRunArtifacts,
    CapabilityAvailability,
    ComparisonLevel,
    CostRecord,
    CostType,
    EngineAdapterDescriptor,
    EngineMappingOutput,
    EngineRunReference,
    EquityPoint,
    EvidenceOrigin,
    FillRecord,
    LiquidityRole,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    ReturnPoint,
    SupportedEngine,
    TimeInForce,
    VerifiedEngineExport,
)
from backtest_auditor.implementation_risk.exporters.quantconnect_lean import (
    QUANTCONNECT_LEAN_EXPORT_FORMAT_ID,
    QUANTCONNECT_LEAN_FILLS_FILE,
    QUANTCONNECT_LEAN_FILLS_HEADERS,
    QUANTCONNECT_LEAN_ORDERS_FILE,
    QUANTCONNECT_LEAN_ORDERS_HEADERS,
    QUANTCONNECT_LEAN_PORTFOLIO_FILE,
    QUANTCONNECT_LEAN_PORTFOLIO_HEADERS,
    QUANTCONNECT_LEAN_TESTED_VERSION,
)
from backtest_auditor.implementation_risk.domain.validation import exact_add


QUANTCONNECT_LEAN_ADAPTER_ID = "backtest-auditor.quantconnect-lean"


def _capability(
    level: ComparisonLevel,
    availability: CapabilityAvailability,
    origin: EvidenceOrigin,
    explanation: str,
) -> AdapterCapability:
    return AdapterCapability(level, availability, origin, explanation)


QUANTCONNECT_LEAN_DESCRIPTOR = EngineAdapterDescriptor(
    adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
    adapter_version="1.0.0",
    engine=SupportedEngine.QUANTCONNECT_LEAN,
    display_name="QuantConnect LEAN",
    export_format_id=QUANTCONNECT_LEAN_EXPORT_FORMAT_ID,
    supported_export_format_versions=("1.0",),
    tested_engine_versions=(QUANTCONNECT_LEAN_TESTED_VERSION,),
    allow_undisclosed_engine_version=False,
    allow_untested_engine_version=False,
    capabilities=(
        _capability(
            ComparisonLevel.STRATEGY_SPECIFICATION,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Local result files do not retain a complete canonical algorithm specification.",
        ),
        _capability(
            ComparisonLevel.MARKET_DATA,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Result charts are not the exact market-data stream consumed by the algorithm.",
        ),
        _capability(
            ComparisonLevel.SIGNAL,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Insights and custom charts do not establish canonical signal semantics.",
        ),
        _capability(
            ComparisonLevel.ORDER,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "The official local result Orders collection supplies final order records.",
        ),
        _capability(
            ComparisonLevel.FILL,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Non-zero fill quantities in the official order-events file map one-to-one.",
        ),
        _capability(
            ComparisonLevel.TRADE,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "D3 does not promote LEAN closed-trade grouping to a universal canonical grouping.",
        ),
        _capability(
            ComparisonLevel.POSITION,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.DETERMINISTIC_DERIVATION,
            "Net instrument quantities are accumulated from the ordered fill stream.",
        ),
        _capability(
            ComparisonLevel.CASH,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "The standard local result does not provide a complete cash-balance history.",
        ),
        _capability(
            ComparisonLevel.COST,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Order-event fees map to fill-linked commission impacts.",
        ),
        _capability(
            ComparisonLevel.EQUITY,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "The built-in Strategy Equity chart supplies total portfolio value.",
        ),
        _capability(
            ComparisonLevel.RETURN,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.DETERMINISTIC_DERIVATION,
            "Simple returns are calculated from consecutive Strategy Equity points.",
        ),
    ),
)

_PAYLOAD_CONTRACT = {
    ADAPTER_METADATA_FILE: ("adapter_metadata", "application/json"),
    QUANTCONNECT_LEAN_ORDERS_FILE: ("orders", "text/csv"),
    QUANTCONNECT_LEAN_FILLS_FILE: ("fills", "text/csv"),
    QUANTCONNECT_LEAN_PORTFOLIO_FILE: ("portfolio", "text/csv"),
}

_ORDER_TYPES = {
    "Market": OrderType.MARKET,
    "Limit": OrderType.LIMIT,
    "StopMarket": OrderType.STOP,
    "StopLimit": OrderType.STOP_LIMIT,
    "MarketOnClose": OrderType.MARKET_ON_CLOSE,
}
_TIME_IN_FORCE = {
    "Day": TimeInForce.DAY,
    "GTC": TimeInForce.GTC,
    "IOC": TimeInForce.IOC,
    "Custom": TimeInForce.CUSTOM,
}
_ORDER_STATUSES = {
    "New": OrderStatus.CREATED,
    "None": OrderStatus.CREATED,
    "Submitted": OrderStatus.SUBMITTED,
    "CancelPending": OrderStatus.SUBMITTED,
    "UpdateSubmitted": OrderStatus.SUBMITTED,
    "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
    "Filled": OrderStatus.FILLED,
    "Canceled": OrderStatus.CANCELED,
    "Invalid": OrderStatus.REJECTED,
}


class QuantConnectLeanArtifactMapper:
    """Normalize one verified LEAN file export without importing LEAN."""

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        return QUANTCONNECT_LEAN_DESCRIPTOR

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        payloads = require_payload_contract(
            export,
            _PAYLOAD_CONTRACT,
            engine=SupportedEngine.QUANTCONNECT_LEAN,
            adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
        )
        base_currency = read_adapter_metadata(
            payloads[ADAPTER_METADATA_FILE],
            engine=SupportedEngine.QUANTCONNECT_LEAN,
            adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
        )
        order_rows = read_csv_rows(
            payloads[QUANTCONNECT_LEAN_ORDERS_FILE],
            QUANTCONNECT_LEAN_ORDERS_HEADERS,
            engine=SupportedEngine.QUANTCONNECT_LEAN,
            adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
        )
        fill_rows = read_csv_rows(
            payloads[QUANTCONNECT_LEAN_FILLS_FILE],
            QUANTCONNECT_LEAN_FILLS_HEADERS,
            engine=SupportedEngine.QUANTCONNECT_LEAN,
            adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
        )
        portfolio_rows = read_csv_rows(
            payloads[QUANTCONNECT_LEAN_PORTFOLIO_FILE],
            QUANTCONNECT_LEAN_PORTFOLIO_HEADERS,
            engine=SupportedEngine.QUANTCONNECT_LEAN,
            adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
        )
        if not portfolio_rows:
            mapping_error(
                engine=SupportedEngine.QUANTCONNECT_LEAN,
                adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
                detail="empty_equity",
                message="portfolio-series.csv must contain at least one row.",
                file_path=QUANTCONNECT_LEAN_PORTFOLIO_FILE,
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
                    custom_time_in_force or row["time_in_force"] == "Custom"
                )
                collapsed_status = collapsed_status or row["status"] in {
                    "None",
                    "CancelPending",
                    "UpdateSubmitted",
                }
                submitted = (
                    None
                    if status in {OrderStatus.CREATED, OrderStatus.REJECTED}
                    else created
                )
                orders.append(
                    OrderRecord(
                        order_id=f"lean-order-{row['order_id']}",
                        created_at=created,
                        instrument_id=row["instrument"],
                        side={"Buy": OrderSide.BUY, "Sell": OrderSide.SELL}[
                            row["side"]
                        ],
                        quantity=parse_decimal(row["quantity"], non_negative=True),
                        order_type=order_type,
                        time_in_force=_TIME_IN_FORCE[row["time_in_force"]],
                        status=status,
                        submitted_at=submitted,
                        last_updated_at=(
                            optional_timestamp(row["last_updated_at"]) or created
                        ),
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
                    engine=SupportedEngine.QUANTCONNECT_LEAN,
                    adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
                    file_path=QUANTCONNECT_LEAN_ORDERS_FILE,
                    row_number=row_number,
                )

        fills: list[FillRecord] = []
        costs: list[CostRecord] = []
        for row_number, row in enumerate(fill_rows, start=2):
            try:
                fill_id = f"lean-fill-{row['fill_id']}"
                order_id = f"lean-order-{row['order_id']}"
                timestamp = parse_timestamp(row["timestamp"])
                side = {"Buy": OrderSide.BUY, "Sell": OrderSide.SELL}[row["side"]]
                fills.append(
                    FillRecord(
                        fill_id=fill_id,
                        order_id=order_id,
                        timestamp=timestamp,
                        instrument_id=row["instrument"],
                        side=side,
                        quantity=parse_decimal(row["quantity"], non_negative=True),
                        price=parse_decimal(row["price"], non_negative=True),
                        currency=row["currency"],
                        liquidity_role=LiquidityRole.UNKNOWN,
                    )
                )
                fee = parse_decimal(row["fee_amount"])
                if fee != 0:
                    costs.append(
                        CostRecord(
                            cost_id=f"lean-fee-{row['fill_id']}",
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
                    engine=SupportedEngine.QUANTCONNECT_LEAN,
                    adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
                    file_path=QUANTCONNECT_LEAN_FILLS_FILE,
                    row_number=row_number,
                )

        running: defaultdict[str, Decimal] = defaultdict(Decimal)
        currencies: dict[str, str] = {}
        grouped: defaultdict[tuple[datetime, str], Decimal] = defaultdict(Decimal)
        for fill in sorted(fills, key=lambda item: (item.timestamp, item.fill_id)):
            if (
                fill.instrument_id in currencies
                and currencies[fill.instrument_id] != fill.currency
            ):
                mapping_error(
                    engine=SupportedEngine.QUANTCONNECT_LEAN,
                    adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
                    detail="instrument_currency_mismatch",
                    message="one instrument's fills use multiple currencies.",
                    file_path=QUANTCONNECT_LEAN_FILLS_FILE,
                )
            currencies[fill.instrument_id] = fill.currency
            signed = (
                fill.quantity
                if fill.side is OrderSide.BUY
                else fill.quantity.copy_negate()
            )
            key = (fill.timestamp, fill.instrument_id)
            grouped[key] = exact_add(grouped[key], signed)
        positions: list[PositionSnapshot] = []
        for (timestamp, instrument), delta in sorted(grouped.items()):
            running[instrument] = exact_add(running[instrument], delta)
            positions.append(
                PositionSnapshot(
                    timestamp=timestamp,
                    instrument_id=instrument,
                    quantity=running[instrument],
                    currency=currencies[instrument],
                )
            )

        equity: list[EquityPoint] = []
        returns: list[ReturnPoint] = []
        previous_timestamp: datetime | None = None
        previous_equity: Decimal | None = None
        for row_number, row in enumerate(portfolio_rows, start=2):
            try:
                timestamp = parse_timestamp(row["timestamp"])
                value = parse_decimal(row["total_equity"])
                equity.append(EquityPoint(timestamp, base_currency, value))
                if previous_timestamp is not None:
                    assert previous_equity is not None
                    if previous_equity == 0:
                        raise ValueError(
                            "simple return is undefined after zero total equity."
                        )
                    returns.append(
                        ReturnPoint(
                            previous_timestamp,
                            timestamp,
                            value / previous_equity - 1,
                            ArtifactReturnConvention.SIMPLE,
                        )
                    )
                previous_timestamp = timestamp
                previous_equity = value
            except (TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.QUANTCONNECT_LEAN,
                    adapter_id=QUANTCONNECT_LEAN_ADAPTER_ID,
                    file_path=QUANTCONNECT_LEAN_PORTFOLIO_FILE,
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
            positions=tuple(
                sorted(positions, key=lambda item: (item.timestamp, item.instrument_id))
            ),
            costs=tuple(sorted(costs, key=lambda item: (item.timestamp, item.cost_id))),
            equity=tuple(sorted(equity, key=lambda item: item.timestamp)),
            returns=tuple(
                sorted(
                    returns, key=lambda item: (item.end_timestamp, item.start_timestamp)
                )
            ),
        )
        warning_values = [
            AdapterWarning(
                "quantconnect_lean.engine_version_producer_declared",
                "LEAN result JSON omits the NuGet version; the export producer explicitly declared the exact tested version.",
            ),
            AdapterWarning(
                "quantconnect_lean.order_submission_time_uses_creation",
                "LEAN final order records do not retain a distinct submission timestamp; creation time is used for submitted lifecycle states.",
                QUANTCONNECT_LEAN_ORDERS_FILE,
            ),
            AdapterWarning(
                "quantconnect_lean.positions_derived_from_fills",
                "Position snapshots are net instrument quantities accumulated from ordered fill events and contain no valuation fields.",
                QUANTCONNECT_LEAN_FILLS_FILE,
            ),
            AdapterWarning(
                "quantconnect_lean.returns_derived_from_equity",
                "Simple returns are derived from consecutive built-in Strategy Equity points.",
                QUANTCONNECT_LEAN_PORTFOLIO_FILE,
            ),
        ]
        if custom_order_type:
            warning_values.append(
                AdapterWarning(
                    "quantconnect_lean.order_type_mapped_custom",
                    "At least one LEAN order type has no exact canonical equivalent and was retained as custom.",
                    QUANTCONNECT_LEAN_ORDERS_FILE,
                    field="type",
                )
            )
        if custom_time_in_force:
            warning_values.append(
                AdapterWarning(
                    "quantconnect_lean.time_in_force_mapped_custom",
                    "At least one LEAN time-in-force representation has no exact canonical equivalent and was retained as custom.",
                    QUANTCONNECT_LEAN_ORDERS_FILE,
                    field="time_in_force",
                )
            )
        if collapsed_status:
            warning_values.append(
                AdapterWarning(
                    "quantconnect_lean.transitional_status_collapsed",
                    "At least one LEAN transitional status was mapped to the nearest canonical lifecycle state.",
                    QUANTCONNECT_LEAN_ORDERS_FILE,
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
    "QUANTCONNECT_LEAN_ADAPTER_ID",
    "QUANTCONNECT_LEAN_DESCRIPTOR",
    "QuantConnectLeanArtifactMapper",
]
