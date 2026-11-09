"""Concrete bt 1.2.0 export mapper for V1.5D2."""

from __future__ import annotations

from backtest_auditor.implementation_risk.adapters.engine_csv import (
    ADAPTER_METADATA_FILE,
    map_row_failure,
    mapping_error,
    optional_decimal,
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
from backtest_auditor.implementation_risk.exporters.bt import (
    BT_EXPORT_FORMAT_ID,
    BT_PORTFOLIO_FILE,
    BT_PORTFOLIO_HEADERS,
    BT_POSITIONS_FILE,
    BT_POSITIONS_HEADERS,
    BT_TESTED_VERSION,
    BT_TRANSACTIONS_FILE,
    BT_TRANSACTIONS_HEADERS,
)


BT_ADAPTER_ID = "backtest-auditor.bt"


def _capability(
    level: ComparisonLevel,
    availability: CapabilityAvailability,
    origin: EvidenceOrigin,
    explanation: str,
) -> AdapterCapability:
    return AdapterCapability(level, availability, origin, explanation)


BT_DESCRIPTOR = EngineAdapterDescriptor(
    adapter_id=BT_ADAPTER_ID,
    adapter_version="1.0.0",
    engine=SupportedEngine.BT,
    display_name="bt",
    export_format_id=BT_EXPORT_FORMAT_ID,
    supported_export_format_versions=("1.0",),
    tested_engine_versions=(BT_TESTED_VERSION,),
    allow_undisclosed_engine_version=False,
    allow_untested_engine_version=False,
    capabilities=(
        _capability(
            ComparisonLevel.STRATEGY_SPECIFICATION,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "An executed bt result does not serialize the complete Algo stack canonically.",
        ),
        _capability(
            ComparisonLevel.MARKET_DATA,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "Valuation prices in snapshots do not constitute an auditable market-data history.",
        ),
        _capability(
            ComparisonLevel.SIGNAL,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "bt Result does not expose strategy signals as a stable result table.",
        ),
        _capability(
            ComparisonLevel.ORDER,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.DETERMINISTIC_DERIVATION,
            "Each executed bt transaction produces one synthetic filled order.",
        ),
        _capability(
            ComparisonLevel.FILL,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Result.get_transactions supplies timestamp, security, quantity, and price.",
        ),
        _capability(
            ComparisonLevel.TRADE,
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.NONE,
            "bt does not freeze one universal transaction-to-trade grouping convention.",
        ),
        _capability(
            ComparisonLevel.POSITION,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Executed strategy position histories map to quantity snapshots.",
        ),
        _capability(
            ComparisonLevel.CASH,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "The executed strategy cash series maps to base-currency balances.",
        ),
        _capability(
            ComparisonLevel.COST,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Strategy fee history maps to timestamp-level commission impacts.",
        ),
        _capability(
            ComparisonLevel.EQUITY,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.ENGINE_EXPORT,
            "Strategy values, cash, positions, and prices map to equity points.",
        ),
        _capability(
            ComparisonLevel.RETURN,
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.DETERMINISTIC_DERIVATION,
            "Returns are the period changes in bt's flow-adjusted strategy price series.",
        ),
    ),
)


_PAYLOAD_CONTRACT = {
    ADAPTER_METADATA_FILE: ("adapter_metadata", "application/json"),
    BT_TRANSACTIONS_FILE: ("transactions", "text/csv"),
    BT_POSITIONS_FILE: ("positions", "text/csv"),
    BT_PORTFOLIO_FILE: ("portfolio", "text/csv"),
}


class BtArtifactMapper:
    """Normalize one verified bt D2 export without importing bt."""

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        return BT_DESCRIPTOR

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        payloads = require_payload_contract(
            export,
            _PAYLOAD_CONTRACT,
            engine=SupportedEngine.BT,
            adapter_id=BT_ADAPTER_ID,
        )
        currency = read_adapter_metadata(
            payloads[ADAPTER_METADATA_FILE],
            engine=SupportedEngine.BT,
            adapter_id=BT_ADAPTER_ID,
        )
        transaction_rows = read_csv_rows(
            payloads[BT_TRANSACTIONS_FILE],
            BT_TRANSACTIONS_HEADERS,
            engine=SupportedEngine.BT,
            adapter_id=BT_ADAPTER_ID,
        )
        position_rows = read_csv_rows(
            payloads[BT_POSITIONS_FILE],
            BT_POSITIONS_HEADERS,
            engine=SupportedEngine.BT,
            adapter_id=BT_ADAPTER_ID,
        )
        portfolio_rows = read_csv_rows(
            payloads[BT_PORTFOLIO_FILE],
            BT_PORTFOLIO_HEADERS,
            engine=SupportedEngine.BT,
            adapter_id=BT_ADAPTER_ID,
        )
        if not portfolio_rows:
            mapping_error(
                engine=SupportedEngine.BT,
                adapter_id=BT_ADAPTER_ID,
                detail="empty_portfolio",
                message="portfolio-series.csv must contain at least one row.",
                file_path=BT_PORTFOLIO_FILE,
            )

        orders: list[OrderRecord] = []
        fills: list[FillRecord] = []
        transaction_instruments: set[str] = set()
        for row_number, row in enumerate(transaction_rows, start=2):
            try:
                raw_quantity = parse_decimal(row["quantity"])
                if raw_quantity == 0:
                    raise ValueError("transaction quantity must not be zero.")
                side = OrderSide.BUY if raw_quantity > 0 else OrderSide.SELL
                quantity = raw_quantity.copy_abs()
                raw_id = row["transaction_id"]
                order_id = f"bt-order-{raw_id}"
                fill_id = f"bt-fill-{raw_id}"
                timestamp = parse_timestamp(row["timestamp"])
                instrument = row["instrument"]
                transaction_instruments.add(instrument)
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
                        price=parse_decimal(row["price"], non_negative=True),
                        currency=currency,
                        liquidity_role=LiquidityRole.UNKNOWN,
                    )
                )
            except (TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.BT,
                    adapter_id=BT_ADAPTER_ID,
                    file_path=BT_TRANSACTIONS_FILE,
                    row_number=row_number,
                )

        positions: list[PositionSnapshot] = []
        position_instruments: set[str] = set()
        for row_number, row in enumerate(position_rows, start=2):
            try:
                instrument = row["instrument"]
                position_instruments.add(instrument)
                positions.append(
                    PositionSnapshot(
                        timestamp=parse_timestamp(row["timestamp"]),
                        instrument_id=instrument,
                        quantity=parse_decimal(row["quantity"]),
                        currency=currency,
                        market_price=optional_decimal(
                            row["market_price"],
                            non_negative=True,
                        ),
                        market_value=parse_decimal(row["market_value"]),
                    )
                )
            except (TypeError, ValueError) as error:
                map_row_failure(
                    error,
                    engine=SupportedEngine.BT,
                    adapter_id=BT_ADAPTER_ID,
                    file_path=BT_POSITIONS_FILE,
                    row_number=row_number,
                )
        if not transaction_instruments.issubset(position_instruments):
            mapping_error(
                engine=SupportedEngine.BT,
                adapter_id=BT_ADAPTER_ID,
                detail="instrument_scope_mismatch",
                message="transactions reference instruments absent from position history.",
            )

        balances: list[CashBalance] = []
        costs: list[CostRecord] = []
        equity: list[EquityPoint] = []
        returns: list[ReturnPoint] = []
        previous_timestamp = None
        for row_number, row in enumerate(portfolio_rows, start=2):
            try:
                timestamp = parse_timestamp(row["timestamp"])
                cash = parse_decimal(row["cash"])
                fees = parse_decimal(row["fees"], non_negative=True)
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
                if fees != 0:
                    costs.append(
                        CostRecord(
                            cost_id=f"bt-fees-{row_number - 1:08d}",
                            timestamp=timestamp,
                            cost_type=CostType.COMMISSION,
                            pnl_impact=fees.copy_negate(),
                            currency=currency,
                        )
                    )
                if previous_timestamp is None:
                    if row["return"] != "":
                        raise ValueError("the first portfolio return must be empty.")
                else:
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
                    engine=SupportedEngine.BT,
                    adapter_id=BT_ADAPTER_ID,
                    file_path=BT_PORTFOLIO_FILE,
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
        warnings = tuple(
            sorted(
                (
                    AdapterWarning(
                        "bt.aggregate_fees_unlinked",
                        "bt fee history is timestamp-aggregated and cannot be linked to an individual transaction.",
                        BT_PORTFOLIO_FILE,
                        field="fees",
                    ),
                    AdapterWarning(
                        "bt.transactions_reconstructed_orders",
                        "bt exports executed transactions, so canonical order lifecycle, type, and time-in-force are synthetic.",
                        BT_TRANSACTIONS_FILE,
                    ),
                ),
                key=lambda item: item.sort_key,
            )
        )
        return EngineMappingOutput(artifacts, warnings)


__all__ = ["BT_ADAPTER_ID", "BT_DESCRIPTOR", "BtArtifactMapper"]
