"""Concrete Backtrader 1.9.78.123 lifecycle mapper for V1.5D2."""

from __future__ import annotations

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
    CashArtifacts,
    CashBalance,
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
from backtest_auditor.implementation_risk.exporters.backtrader import (
    BACKTRADER_EXPORT_FORMAT_ID,
    BACKTRADER_FILLS_FILE,
    BACKTRADER_FILLS_HEADERS,
    BACKTRADER_ORDERS_FILE,
    BACKTRADER_ORDERS_HEADERS,
    BACKTRADER_PORTFOLIO_FILE,
    BACKTRADER_PORTFOLIO_HEADERS,
    BACKTRADER_POSITIONS_FILE,
    BACKTRADER_POSITIONS_HEADERS,
    BACKTRADER_TESTED_VERSION,
)


BACKTRADER_ADAPTER_ID = "backtest-auditor.backtrader"


def _capability(
    level: ComparisonLevel,
    availability: CapabilityAvailability,
    origin: EvidenceOrigin,
    explanation: str,
) -> AdapterCapability:
    return AdapterCapability(level, availability, origin, explanation)


BACKTRADER_DESCRIPTOR = EngineAdapterDescriptor(
    adapter_id=BACKTRADER_ADAPTER_ID,
    adapter_version="1.0.0",
    engine=SupportedEngine.BACKTRADER,
    display_name="Backtrader",
    export_format_id=BACKTRADER_EXPORT_FORMAT_ID,
    supported_export_format_versions=("1.0",),
    tested_engine_versions=(BACKTRADER_TESTED_VERSION,),
    allow_undisclosed_engine_version=False,
    allow_untested_engine_version=False,
    capabilities=(
        _capability(
            ComparisonLevel.STRATEGY_SPECIFICATION,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "The analyzer does not serialize arbitrary Strategy Python code and parameters.",
        ),
        _capability(
            ComparisonLevel.MARKET_DATA,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Snapshot close prices are valuation evidence, not a complete data-feed export.",
        ),
        _capability(
            ComparisonLevel.SIGNAL,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Backtrader strategies do not share one stable signal representation.",
        ),
        _capability(
            ComparisonLevel.ORDER,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Analyzer order notifications preserve final lifecycle state and timestamps.",
        ),
        _capability(
            ComparisonLevel.FILL,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "OrderExecutionBit values map one-to-one to canonical fills.",
        ),
        _capability(
            ComparisonLevel.TRADE,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Backtrader trade grouping may depend on tradeid and strategy conventions not frozen in D2.",
        ),
        _capability(
            ComparisonLevel.POSITION,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Analyzer snapshots preserve per-feed position quantity and close valuation.",
        ),
        _capability(
            ComparisonLevel.CASH,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Broker cash snapshots map to base-currency balances.",
        ),
        _capability(
            ComparisonLevel.COST,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Execution-bit commissions map to fill-linked P&L impacts.",
        ),
        _capability(
            ComparisonLevel.EQUITY,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Broker value, cash, and recorded position exposure map to equity points.",
        ),
        _capability(
            ComparisonLevel.RETURN,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.DETERMINISTIC_DERIVATION,
            "Simple returns are derived from consecutive broker equity snapshots.",
        ),
    ),
)


_PAYLOAD_CONTRACT = {
    ADAPTER_METADATA_FILE: ("adapter_metadata", "application/json"),
    BACKTRADER_ORDERS_FILE: ("orders", "text/csv"),
    BACKTRADER_FILLS_FILE: ("fills", "text/csv"),
    BACKTRADER_POSITIONS_FILE: ("positions", "text/csv"),
    BACKTRADER_PORTFOLIO_FILE: ("portfolio", "text/csv"),
}

_ORDER_TYPES = {
    "Market": OrderType.MARKET,
    "Limit": OrderType.LIMIT,
    "Stop": OrderType.STOP,
    "StopLimit": OrderType.STOP_LIMIT,
    "Close": OrderType.MARKET_ON_CLOSE,
}
_ORDER_STATUSES = {
    "Created": OrderStatus.CREATED,
    "Submitted": OrderStatus.SUBMITTED,
    "Accepted": OrderStatus.ACCEPTED,
    "Partial": OrderStatus.PARTIALLY_FILLED,
    "Completed": OrderStatus.FILLED,
    "Canceled": OrderStatus.CANCELED,
    "Cancelled": OrderStatus.CANCELED,
    "Expired": OrderStatus.EXPIRED,
    "Margin": OrderStatus.REJECTED,
    "Rejected": OrderStatus.REJECTED,
}


class BacktraderArtifactMapper:
    """Normalize a verified Backtrader lifecycle export without its SDK."""

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        return BACKTRADER_DESCRIPTOR

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        payloads = require_payload_contract(
            export,
            _PAYLOAD_CONTRACT,
            engine=SupportedEngine.BACKTRADER,
            adapter_id=BACKTRADER_ADAPTER_ID,
        )
        currency = read_adapter_metadata(
            payloads[ADAPTER_METADATA_FILE],
            engine=SupportedEngine.BACKTRADER,
            adapter_id=BACKTRADER_ADAPTER_ID,
        )
        order_rows = read_csv_rows(
            payloads[BACKTRADER_ORDERS_FILE],
            BACKTRADER_ORDERS_HEADERS,
            engine=SupportedEngine.BACKTRADER,
            adapter_id=BACKTRADER_ADAPTER_ID,
        )
        fill_rows = read_csv_rows(
            payloads[BACKTRADER_FILLS_FILE],
            BACKTRADER_FILLS_HEADERS,
            engine=SupportedEngine.BACKTRADER,
            adapter_id=BACKTRADER_ADAPTER_ID,
        )
        position_rows = read_csv_rows(
            payloads[BACKTRADER_POSITIONS_FILE],
            BACKTRADER_POSITIONS_HEADERS,
            engine=SupportedEngine.BACKTRADER,
            adapter_id=BACKTRADER_ADAPTER_ID,
        )
        portfolio_rows = read_csv_rows(
            payloads[BACKTRADER_PORTFOLIO_FILE],
            BACKTRADER_PORTFOLIO_HEADERS,
            engine=SupportedEngine.BACKTRADER,
            adapter_id=BACKTRADER_ADAPTER_ID,
        )
        if not portfolio_rows:
            mapping_error(
                engine=SupportedEngine.BACKTRADER,
                adapter_id=BACKTRADER_ADAPTER_ID,
                detail="empty_portfolio",
                message="portfolio-series.csv must contain at least one row.",
                file_path=BACKTRADER_PORTFOLIO_FILE,
            )

        warnings: list[AdapterWarning] = []
        orders: list[OrderRecord] = []
        order_instruments: set[str] = set()
        for row_number, row in enumerate(order_rows, start=2):
            try:
                raw_ref = row["order_ref"]
                order_type = _ORDER_TYPES.get(row["order_type"], OrderType.CUSTOM)
                if order_type is OrderType.CUSTOM:
                    warnings.append(
                        AdapterWarning(
                            "backtrader.custom_order_type",
                            f"Backtrader order type {row['order_type']!r} maps to canonical custom.",
                            BACKTRADER_ORDERS_FILE,
                            row_number,
                            "order_type",
                        )
                    )
                status = _ORDER_STATUSES[row["status"]]
                if row["status"] == "Margin":
                    warnings.append(
                        AdapterWarning(
                            "backtrader.margin_mapped_rejected",
                            "Backtrader Margin has no exact canonical status and maps to rejected.",
                            BACKTRADER_ORDERS_FILE,
                            row_number,
                            "status",
                        )
                    )
                instrument = row["instrument"]
                order_instruments.add(instrument)
                valid = optional_timestamp(row["valid_timestamp"])
                orders.append(
                    OrderRecord(
                        order_id=f"backtrader-order-{raw_ref}",
                        created_at=parse_timestamp(row["created_timestamp"]),
                        instrument_id=instrument,
                        side={
                            "Buy": OrderSide.BUY,
                            "Sell": OrderSide.SELL,
                        }[row["side"]],
                        quantity=parse_decimal(row["quantity"], non_negative=True),
                        order_type=order_type,
                        time_in_force=(
                            TimeInForce.GTD if valid is not None else TimeInForce.CUSTOM
                        ),
                        status=status,
                        parent_order_id=(
                            None
                            if row["parent_order_ref"] == ""
                            else f"backtrader-order-{row['parent_order_ref']}"
                        ),
                        submitted_at=optional_timestamp(row["submitted_timestamp"]),
                        last_updated_at=parse_timestamp(row["last_updated_timestamp"]),
                        expires_at=valid,
                        limit_price=optional_decimal(
                            row["limit_price"],
                            non_negative=True,
                        ),
                        stop_price=optional_decimal(
                            row["stop_price"],
                            non_negative=True,
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.BACKTRADER,
                    adapter_id=BACKTRADER_ADAPTER_ID,
                    file_path=BACKTRADER_ORDERS_FILE,
                    row_number=row_number,
                )

        fills: list[FillRecord] = []
        costs: list[CostRecord] = []
        fill_instruments: set[str] = set()
        for row_number, row in enumerate(fill_rows, start=2):
            try:
                raw_fill_id = row["fill_id"]
                raw_ref = row["order_ref"]
                fill_id = f"backtrader-fill-{raw_fill_id}"
                order_id = f"backtrader-order-{raw_ref}"
                timestamp = parse_timestamp(row["timestamp"])
                instrument = row["instrument"]
                fill_instruments.add(instrument)
                commission = parse_decimal(
                    row["commission"],
                    non_negative=True,
                )
                fills.append(
                    FillRecord(
                        fill_id=fill_id,
                        order_id=order_id,
                        timestamp=timestamp,
                        instrument_id=instrument,
                        side={
                            "Buy": OrderSide.BUY,
                            "Sell": OrderSide.SELL,
                        }[row["side"]],
                        quantity=parse_decimal(row["quantity"], non_negative=True),
                        price=parse_decimal(row["price"], non_negative=True),
                        currency=currency,
                        liquidity_role=LiquidityRole.UNKNOWN,
                    )
                )
                if commission != 0:
                    costs.append(
                        CostRecord(
                            cost_id=f"backtrader-commission-{raw_fill_id}",
                            timestamp=timestamp,
                            cost_type=CostType.COMMISSION,
                            pnl_impact=commission.copy_negate(),
                            currency=currency,
                            order_id=order_id,
                            fill_id=fill_id,
                        )
                    )
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.BACKTRADER,
                    adapter_id=BACKTRADER_ADAPTER_ID,
                    file_path=BACKTRADER_FILLS_FILE,
                    row_number=row_number,
                )
        if not fill_instruments.issubset(order_instruments):
            mapping_error(
                engine=SupportedEngine.BACKTRADER,
                adapter_id=BACKTRADER_ADAPTER_ID,
                detail="instrument_scope_mismatch",
                message="fills reference instruments absent from order history.",
            )

        positions: list[PositionSnapshot] = []
        for row_number, row in enumerate(position_rows, start=2):
            try:
                positions.append(
                    PositionSnapshot(
                        timestamp=parse_timestamp(row["timestamp"]),
                        instrument_id=row["instrument"],
                        quantity=parse_decimal(row["quantity"]),
                        currency=currency,
                        market_price=parse_decimal(
                            row["market_price"],
                            non_negative=True,
                        ),
                        market_value=parse_decimal(row["market_value"]),
                    )
                )
            except (TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.BACKTRADER,
                    adapter_id=BACKTRADER_ADAPTER_ID,
                    file_path=BACKTRADER_POSITIONS_FILE,
                    row_number=row_number,
                )

        balances: list[CashBalance] = []
        equity: list[EquityPoint] = []
        returns: list[ReturnPoint] = []
        previous_timestamp = None
        previous_equity: Decimal | None = None
        for row_number, row in enumerate(portfolio_rows, start=2):
            try:
                timestamp = parse_timestamp(row["timestamp"])
                cash = parse_decimal(row["cash"])
                total_equity = parse_decimal(row["total_equity"])
                balances.append(CashBalance(timestamp, currency, cash, cash))
                equity.append(
                    EquityPoint(
                        timestamp=timestamp,
                        currency=currency,
                        total_equity=total_equity,
                        cash=cash,
                        gross_exposure=parse_decimal(
                            row["gross_exposure"],
                            non_negative=True,
                        ),
                        net_exposure=parse_decimal(row["net_exposure"]),
                    )
                )
                if previous_timestamp is not None and previous_equity is not None:
                    if previous_equity == 0:
                        raise ValueError(
                            "return cannot be derived after zero total equity."
                        )
                    returns.append(
                        ReturnPoint(
                            start_timestamp=previous_timestamp,
                            end_timestamp=timestamp,
                            value=(total_equity / previous_equity) - Decimal(1),
                            convention=ArtifactReturnConvention.SIMPLE,
                        )
                    )
                previous_timestamp = timestamp
                previous_equity = total_equity
            except (TypeError, ValueError, ArithmeticError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.BACKTRADER,
                    adapter_id=BACKTRADER_ADAPTER_ID,
                    file_path=BACKTRADER_PORTFOLIO_FILE,
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
            cash=CashArtifacts(
                balances=tuple(
                    sorted(balances, key=lambda item: (item.timestamp, item.currency))
                ),
            ),
            costs=tuple(sorted(costs, key=lambda item: (item.timestamp, item.cost_id))),
            equity=tuple(sorted(equity, key=lambda item: item.timestamp)),
            returns=tuple(
                sorted(
                    returns, key=lambda item: (item.end_timestamp, item.start_timestamp)
                )
            ),
        )
        return EngineMappingOutput(
            artifacts,
            tuple(sorted(warnings, key=lambda item: item.sort_key)),
        )


__all__ = [
    "BACKTRADER_ADAPTER_ID",
    "BACKTRADER_DESCRIPTOR",
    "BacktraderArtifactMapper",
]
