"""Concrete vectorbt 1.1.0 export mapper for V1.5D2."""

from __future__ import annotations

from backtest_auditor.implementation_risk.adapters.engine_csv import (
    ADAPTER_METADATA_FILE,
    map_row_failure,
    mapping_error,
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
    TradeDirection,
    TradeRecord,
    VerifiedEngineExport,
)
from backtest_auditor.implementation_risk.exporters.vectorbt import (
    VECTORBT_EXPORT_FORMAT_ID,
    VECTORBT_ORDERS_FILE,
    VECTORBT_ORDERS_HEADERS,
    VECTORBT_PORTFOLIO_FILE,
    VECTORBT_PORTFOLIO_HEADERS,
    VECTORBT_POSITIONS_FILE,
    VECTORBT_POSITIONS_HEADERS,
    VECTORBT_TESTED_VERSION,
    VECTORBT_TRADES_FILE,
    VECTORBT_TRADES_HEADERS,
)


VECTORBT_ADAPTER_ID = "backtest-auditor.vectorbt"


def _capability(
    level: ComparisonLevel,
    availability: CapabilityAvailability,
    origin: EvidenceOrigin,
    explanation: str,
) -> AdapterCapability:
    return AdapterCapability(level, availability, origin, explanation)


VECTORBT_DESCRIPTOR = EngineAdapterDescriptor(
    adapter_id=VECTORBT_ADAPTER_ID,
    adapter_version="1.0.0",
    engine=SupportedEngine.VECTORBT,
    display_name="vectorbt",
    export_format_id=VECTORBT_EXPORT_FORMAT_ID,
    supported_export_format_versions=("1.0",),
    tested_engine_versions=(VECTORBT_TESTED_VERSION,),
    allow_undisclosed_engine_version=False,
    allow_untested_engine_version=False,
    capabilities=(
        _capability(
            ComparisonLevel.STRATEGY_SPECIFICATION,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Portfolio exports do not retain a complete canonical strategy specification.",
        ),
        _capability(
            ComparisonLevel.MARKET_DATA,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "D2 exports the valuation close only inside position snapshots, not a market-data history.",
        ),
        _capability(
            ComparisonLevel.SIGNAL,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Portfolio objects do not reliably retain the original signal arrays and semantics.",
        ),
        _capability(
            ComparisonLevel.ORDER,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.DETERMINISTIC_DERIVATION,
            "vectorbt order records are filled orders; canonical filled orders are reconstructed one-to-one.",
        ),
        _capability(
            ComparisonLevel.FILL,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Each vectorbt filled-order record maps to one canonical fill.",
        ),
        _capability(
            ComparisonLevel.TRADE,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "vectorbt position records map to canonical trades using vectorbt position grouping.",
        ),
        _capability(
            ComparisonLevel.POSITION,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Portfolio assets, close, and asset value form quantity snapshots.",
        ),
        _capability(
            ComparisonLevel.CASH,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Portfolio cash series maps to base-currency balances.",
        ),
        _capability(
            ComparisonLevel.COST,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Filled-order fee values map to commission P&L impacts.",
        ),
        _capability(
            ComparisonLevel.EQUITY,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Portfolio value, cash, and asset value map to equity points.",
        ),
        _capability(
            ComparisonLevel.RETURN,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Portfolio returns map from the second timestamp onward.",
        ),
    ),
)


_PAYLOAD_CONTRACT = {
    ADAPTER_METADATA_FILE: ("adapter_metadata", "application/json"),
    VECTORBT_ORDERS_FILE: ("orders", "text/csv"),
    VECTORBT_TRADES_FILE: ("trades", "text/csv"),
    VECTORBT_POSITIONS_FILE: ("positions", "text/csv"),
    VECTORBT_PORTFOLIO_FILE: ("portfolio", "text/csv"),
}


class VectorbtArtifactMapper:
    """Normalize a verified vectorbt D2 export without importing vectorbt."""

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        return VECTORBT_DESCRIPTOR

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        payloads = require_payload_contract(
            export,
            _PAYLOAD_CONTRACT,
            engine=SupportedEngine.VECTORBT,
            adapter_id=VECTORBT_ADAPTER_ID,
        )
        currency = read_adapter_metadata(
            payloads[ADAPTER_METADATA_FILE],
            engine=SupportedEngine.VECTORBT,
            adapter_id=VECTORBT_ADAPTER_ID,
        )
        order_rows = read_csv_rows(
            payloads[VECTORBT_ORDERS_FILE],
            VECTORBT_ORDERS_HEADERS,
            engine=SupportedEngine.VECTORBT,
            adapter_id=VECTORBT_ADAPTER_ID,
        )
        trade_rows = read_csv_rows(
            payloads[VECTORBT_TRADES_FILE],
            VECTORBT_TRADES_HEADERS,
            engine=SupportedEngine.VECTORBT,
            adapter_id=VECTORBT_ADAPTER_ID,
        )
        position_rows = read_csv_rows(
            payloads[VECTORBT_POSITIONS_FILE],
            VECTORBT_POSITIONS_HEADERS,
            engine=SupportedEngine.VECTORBT,
            adapter_id=VECTORBT_ADAPTER_ID,
        )
        portfolio_rows = read_csv_rows(
            payloads[VECTORBT_PORTFOLIO_FILE],
            VECTORBT_PORTFOLIO_HEADERS,
            engine=SupportedEngine.VECTORBT,
            adapter_id=VECTORBT_ADAPTER_ID,
        )
        if not portfolio_rows:
            mapping_error(
                engine=SupportedEngine.VECTORBT,
                adapter_id=VECTORBT_ADAPTER_ID,
                detail="empty_portfolio",
                message="portfolio-series.csv must contain at least one row.",
                file_path=VECTORBT_PORTFOLIO_FILE,
            )

        orders: list[OrderRecord] = []
        fills: list[FillRecord] = []
        costs: list[CostRecord] = []
        instruments: set[str] = set()
        for row_number, row in enumerate(order_rows, start=2):
            try:
                raw_id = row["order_id"]
                order_id = f"vbt-order-{raw_id}"
                fill_id = f"vbt-fill-{raw_id}"
                timestamp = parse_timestamp(row["timestamp"])
                quantity = parse_decimal(row["size"], non_negative=True)
                price = parse_decimal(row["price"], non_negative=True)
                fees = parse_decimal(row["fees"], non_negative=True)
                side = {
                    "Buy": OrderSide.BUY,
                    "Sell": OrderSide.SELL,
                }[row["side"]]
                instrument = row["instrument"]
                instruments.add(instrument)
                orders.append(
                    OrderRecord(
                        order_id=order_id,
                        created_at=timestamp,
                        instrument_id=instrument,
                        side=side,
                        quantity=quantity,
                        order_type=OrderType.CUSTOM,
                        time_in_force=TimeInForce.CUSTOM,
                        status=OrderStatus.FILLED,
                        submitted_at=timestamp,
                        last_updated_at=timestamp,
                    )
                )
                fills.append(
                    FillRecord(
                        fill_id=fill_id,
                        order_id=order_id,
                        timestamp=timestamp,
                        instrument_id=instrument,
                        side=side,
                        quantity=quantity,
                        price=price,
                        currency=currency,
                        liquidity_role=LiquidityRole.UNKNOWN,
                    )
                )
                if fees != 0:
                    costs.append(
                        CostRecord(
                            cost_id=f"vbt-fee-{raw_id}",
                            timestamp=timestamp,
                            cost_type=CostType.COMMISSION,
                            pnl_impact=fees.copy_negate(),
                            currency=currency,
                            order_id=order_id,
                            fill_id=fill_id,
                        )
                    )
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.VECTORBT,
                    adapter_id=VECTORBT_ADAPTER_ID,
                    file_path=VECTORBT_ORDERS_FILE,
                    row_number=row_number,
                )

        trades: list[TradeRecord] = []
        for row_number, row in enumerate(trade_rows, start=2):
            try:
                instrument = row["instrument"]
                instruments.add(instrument)
                status = row["status"]
                closed = status == "Closed"
                if status not in {"Open", "Closed"}:
                    raise ValueError("status must be 'Open' or 'Closed'.")
                trades.append(
                    TradeRecord(
                        trade_id=f"vbt-position-{row['position_id']}",
                        instrument_id=instrument,
                        direction={
                            "Long": TradeDirection.LONG,
                            "Short": TradeDirection.SHORT,
                        }[row["direction"]],
                        opened_at=parse_timestamp(row["entry_timestamp"]),
                        quantity=parse_decimal(row["size"], non_negative=True),
                        entry_price=parse_decimal(
                            row["avg_entry_price"],
                            non_negative=True,
                        ),
                        currency=currency,
                        grouping_method="vectorbt positions",
                        closed_at=(
                            parse_timestamp(row["exit_timestamp"]) if closed else None
                        ),
                        exit_price=(
                            parse_decimal(
                                row["avg_exit_price"],
                                non_negative=True,
                            )
                            if closed
                            else None
                        ),
                        realized_pnl=(parse_decimal(row["pnl"]) if closed else None),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.VECTORBT,
                    adapter_id=VECTORBT_ADAPTER_ID,
                    file_path=VECTORBT_TRADES_FILE,
                    row_number=row_number,
                )

        positions: list[PositionSnapshot] = []
        for row_number, row in enumerate(position_rows, start=2):
            try:
                instrument = row["instrument"]
                instruments.add(instrument)
                positions.append(
                    PositionSnapshot(
                        timestamp=parse_timestamp(row["timestamp"]),
                        instrument_id=instrument,
                        quantity=parse_decimal(row["quantity"]),
                        currency=currency,
                        market_price=parse_decimal(
                            row["market_price"],
                            non_negative=True,
                        ),
                        market_value=parse_decimal(row["market_value"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.VECTORBT,
                    adapter_id=VECTORBT_ADAPTER_ID,
                    file_path=VECTORBT_POSITIONS_FILE,
                    row_number=row_number,
                )
        if len(instruments) != 1:
            mapping_error(
                engine=SupportedEngine.VECTORBT,
                adapter_id=VECTORBT_ADAPTER_ID,
                detail="instrument_scope_mismatch",
                message="the D2 vectorbt contract requires exactly one instrument.",
            )

        balances: list[CashBalance] = []
        equity: list[EquityPoint] = []
        returns: list[ReturnPoint] = []
        previous_timestamp = None
        for row_number, row in enumerate(portfolio_rows, start=2):
            try:
                timestamp = parse_timestamp(row["timestamp"])
                cash = parse_decimal(row["cash"])
                balances.append(CashBalance(timestamp, currency, cash, cash))
                equity.append(
                    EquityPoint(
                        timestamp=timestamp,
                        currency=currency,
                        total_equity=parse_decimal(row["total_equity"]),
                        cash=cash,
                        gross_exposure=parse_decimal(
                            row["gross_exposure"],
                            non_negative=True,
                        ),
                        net_exposure=parse_decimal(row["net_exposure"]),
                    )
                )
                if previous_timestamp is not None:
                    returns.append(
                        ReturnPoint(
                            start_timestamp=previous_timestamp,
                            end_timestamp=timestamp,
                            value=parse_decimal(row["return"]),
                            convention=ArtifactReturnConvention.SIMPLE,
                        )
                    )
                previous_timestamp = timestamp
            except (TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.VECTORBT,
                    adapter_id=VECTORBT_ADAPTER_ID,
                    file_path=VECTORBT_PORTFOLIO_FILE,
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
        warnings = tuple(
            sorted(
                (
                    AdapterWarning(
                        "vectorbt.filled_orders_reconstructed",
                        "vectorbt exposes filled orders, so canonical order creation, type, and time-in-force are synthetic.",
                        VECTORBT_ORDERS_FILE,
                    ),
                    AdapterWarning(
                        "vectorbt.initial_return_omitted",
                        "The first vectorbt return has no exported interval start and was omitted.",
                        VECTORBT_PORTFOLIO_FILE,
                        2,
                        "return",
                    ),
                ),
                key=lambda item: item.sort_key,
            )
        )
        return EngineMappingOutput(artifacts, warnings)


__all__ = [
    "VECTORBT_ADAPTER_ID",
    "VECTORBT_DESCRIPTOR",
    "VectorbtArtifactMapper",
]
