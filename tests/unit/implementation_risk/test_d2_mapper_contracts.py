from __future__ import annotations

from dataclasses import replace

import pytest

from backtest_auditor.implementation_risk import (
    CapabilityAvailability,
    ComparisonLevel,
    EngineAdapterError,
    EngineArtifactMapper,
    EngineExportPayload,
    EvidenceOrigin,
    OrderStatus,
    OrderType,
    SupportedEngine,
    VerifiedEngineExport,
    build_v1_5d2_registry,
)
from backtest_auditor.implementation_risk.adapters.backtrader import (
    BACKTRADER_DESCRIPTOR,
    BacktraderArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.bt import (
    BT_DESCRIPTOR,
    BtArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.engine_csv import (
    canonical_csv_bytes,
)
from backtest_auditor.implementation_risk.adapters.vectorbt import (
    VECTORBT_DESCRIPTOR,
    VectorbtArtifactMapper,
)
from backtest_auditor.implementation_risk.exporters.backtrader import (
    BACKTRADER_EXPORT_FORMAT_ID,
    BACKTRADER_FILLS_FILE,
    BACKTRADER_FILLS_HEADERS,
    BACKTRADER_LEVELS,
    BACKTRADER_ORDERS_FILE,
    BACKTRADER_ORDERS_HEADERS,
    BACKTRADER_PORTFOLIO_FILE,
    BACKTRADER_PORTFOLIO_HEADERS,
    BACKTRADER_POSITIONS_FILE,
    BACKTRADER_POSITIONS_HEADERS,
    BACKTRADER_TESTED_VERSION,
)
from backtest_auditor.implementation_risk.exporters.bt import (
    BT_EXPORT_FORMAT_ID,
    BT_LEVELS,
    BT_PORTFOLIO_FILE,
    BT_PORTFOLIO_HEADERS,
    BT_POSITIONS_FILE,
    BT_POSITIONS_HEADERS,
    BT_TESTED_VERSION,
    BT_TRANSACTIONS_FILE,
    BT_TRANSACTIONS_HEADERS,
)
from backtest_auditor.implementation_risk.exporters.common import (
    adapter_metadata_payload,
)
from backtest_auditor.implementation_risk.exporters.vectorbt import (
    VECTORBT_EXPORT_FORMAT_ID,
    VECTORBT_LEVELS,
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


T0 = "2024-01-01T00:00:00.000000Z"
T1 = "2024-01-02T00:00:00.000000Z"


def _csv_payload(
    path: str,
    role: str,
    headers: tuple[str, ...],
    rows: tuple[dict[str, str], ...],
) -> EngineExportPayload:
    return EngineExportPayload(
        path,
        role,
        "text/csv",
        canonical_csv_bytes(headers, rows),
    )


def _export(
    engine: SupportedEngine,
    version: str,
    format_id: str,
    levels: tuple[ComparisonLevel, ...],
    payloads: tuple[EngineExportPayload, ...],
) -> VerifiedEngineExport:
    return VerifiedEngineExport.create(
        run_id=f"{engine.value}-unit",
        engine=engine,
        engine_version=version,
        export_format_id=format_id,
        export_format_version="1.0",
        declared_levels=levels,
        payloads=payloads,
    )


def _replace_payload(
    export: VerifiedEngineExport,
    replacement: EngineExportPayload,
) -> VerifiedEngineExport:
    payloads = tuple(
        replacement if item.path == replacement.path else item
        for item in export.payloads
    )
    envelope = export.envelope
    return _export(
        envelope.engine,
        envelope.engine_version or "",
        envelope.export_format_id,
        envelope.declared_levels,
        payloads,
    )


def _vectorbt_export(
    *,
    side: str = "Buy",
    position_instrument: str = "AAPL",
    portfolio_rows: tuple[dict[str, str], ...] | None = None,
) -> VerifiedEngineExport:
    return _export(
        SupportedEngine.VECTORBT,
        VECTORBT_TESTED_VERSION,
        VECTORBT_EXPORT_FORMAT_ID,
        VECTORBT_LEVELS,
        (
            adapter_metadata_payload("USD"),
            _csv_payload(
                VECTORBT_ORDERS_FILE,
                "orders",
                VECTORBT_ORDERS_HEADERS,
                (
                    {
                        "order_id": "1",
                        "instrument": "AAPL",
                        "timestamp": T0,
                        "size": "1",
                        "price": "100",
                        "fees": "1",
                        "side": side,
                    },
                ),
            ),
            _csv_payload(
                VECTORBT_TRADES_FILE,
                "trades",
                VECTORBT_TRADES_HEADERS,
                (
                    {
                        "position_id": "1",
                        "instrument": "AAPL",
                        "size": "1",
                        "entry_timestamp": T0,
                        "avg_entry_price": "100",
                        "entry_fees": "1",
                        "exit_timestamp": T1,
                        "avg_exit_price": "105",
                        "exit_fees": "0",
                        "pnl": "4",
                        "return": "0.04",
                        "direction": "Long",
                        "status": "Open",
                    },
                ),
            ),
            _csv_payload(
                VECTORBT_POSITIONS_FILE,
                "positions",
                VECTORBT_POSITIONS_HEADERS,
                (
                    {
                        "timestamp": T0,
                        "instrument": position_instrument,
                        "quantity": "1",
                        "market_price": "100",
                        "market_value": "100",
                    },
                    {
                        "timestamp": T1,
                        "instrument": position_instrument,
                        "quantity": "1",
                        "market_price": "105",
                        "market_value": "105",
                    },
                ),
            ),
            _csv_payload(
                VECTORBT_PORTFOLIO_FILE,
                "portfolio",
                VECTORBT_PORTFOLIO_HEADERS,
                portfolio_rows
                if portfolio_rows is not None
                else (
                    {
                        "timestamp": T0,
                        "total_equity": "999",
                        "cash": "899",
                        "gross_exposure": "100",
                        "net_exposure": "100",
                        "return": "-0.001",
                    },
                    {
                        "timestamp": T1,
                        "total_equity": "1004",
                        "cash": "899",
                        "gross_exposure": "105",
                        "net_exposure": "105",
                        "return": "0.005005005005005005",
                    },
                ),
            ),
        ),
    )


def _bt_export(
    *,
    quantity: str = "1",
    transaction_instrument: str = "AAPL",
    first_return: str = "",
    portfolio_rows: tuple[dict[str, str], ...] | None = None,
) -> VerifiedEngineExport:
    return _export(
        SupportedEngine.BT,
        BT_TESTED_VERSION,
        BT_EXPORT_FORMAT_ID,
        BT_LEVELS,
        (
            adapter_metadata_payload("USD"),
            _csv_payload(
                BT_TRANSACTIONS_FILE,
                "transactions",
                BT_TRANSACTIONS_HEADERS,
                (
                    {
                        "transaction_id": "00000001",
                        "timestamp": T1,
                        "instrument": transaction_instrument,
                        "quantity": quantity,
                        "price": "100",
                    },
                ),
            ),
            _csv_payload(
                BT_POSITIONS_FILE,
                "positions",
                BT_POSITIONS_HEADERS,
                (
                    {
                        "timestamp": T0,
                        "instrument": "AAPL",
                        "quantity": "0",
                        "market_price": "",
                        "market_value": "0",
                    },
                    {
                        "timestamp": T1,
                        "instrument": "AAPL",
                        "quantity": "1",
                        "market_price": "100",
                        "market_value": "100",
                    },
                ),
            ),
            _csv_payload(
                BT_PORTFOLIO_FILE,
                "portfolio",
                BT_PORTFOLIO_HEADERS,
                portfolio_rows
                if portfolio_rows is not None
                else (
                    {
                        "timestamp": T0,
                        "total_equity": "1000",
                        "cash": "1000",
                        "gross_exposure": "0",
                        "net_exposure": "0",
                        "fees": "0",
                        "return": first_return,
                    },
                    {
                        "timestamp": T1,
                        "total_equity": "1000",
                        "cash": "900",
                        "gross_exposure": "100",
                        "net_exposure": "100",
                        "fees": "1",
                        "return": "0",
                    },
                ),
            ),
        ),
    )


def _backtrader_export(
    *,
    status: str = "Completed",
    order_type: str = "Market",
    fill_instrument: str = "AAPL",
    include_fill: bool = True,
    first_equity: str = "1000",
) -> VerifiedEngineExport:
    fill_rows = (
        (
            {
                "fill_id": "1-1",
                "order_ref": "1",
                "timestamp": T1,
                "instrument": fill_instrument,
                "side": "Buy",
                "quantity": "1",
                "price": "100",
                "commission": "1",
            },
        )
        if include_fill
        else ()
    )
    return _export(
        SupportedEngine.BACKTRADER,
        BACKTRADER_TESTED_VERSION,
        BACKTRADER_EXPORT_FORMAT_ID,
        BACKTRADER_LEVELS,
        (
            adapter_metadata_payload("USD"),
            _csv_payload(
                BACKTRADER_ORDERS_FILE,
                "orders",
                BACKTRADER_ORDERS_HEADERS,
                (
                    {
                        "order_ref": "1",
                        "created_timestamp": T0,
                        "submitted_timestamp": T1,
                        "last_updated_timestamp": T1,
                        "instrument": "AAPL",
                        "side": "Buy",
                        "quantity": "1",
                        "order_type": order_type,
                        "status": status,
                        "parent_order_ref": "",
                        "valid_timestamp": "",
                        "limit_price": "",
                        "stop_price": "",
                    },
                ),
            ),
            _csv_payload(
                BACKTRADER_FILLS_FILE,
                "fills",
                BACKTRADER_FILLS_HEADERS,
                fill_rows,
            ),
            _csv_payload(
                BACKTRADER_POSITIONS_FILE,
                "positions",
                BACKTRADER_POSITIONS_HEADERS,
                (
                    {
                        "timestamp": T0,
                        "instrument": "AAPL",
                        "quantity": "0",
                        "market_price": "99",
                        "market_value": "0",
                    },
                    {
                        "timestamp": T1,
                        "instrument": "AAPL",
                        "quantity": "1" if include_fill else "0",
                        "market_price": "100",
                        "market_value": "100" if include_fill else "0",
                    },
                ),
            ),
            _csv_payload(
                BACKTRADER_PORTFOLIO_FILE,
                "portfolio",
                BACKTRADER_PORTFOLIO_HEADERS,
                (
                    {
                        "timestamp": T0,
                        "total_equity": first_equity,
                        "cash": first_equity,
                        "gross_exposure": "0",
                        "net_exposure": "0",
                    },
                    {
                        "timestamp": T1,
                        "total_equity": "1000",
                        "cash": "900" if include_fill else "1000",
                        "gross_exposure": "100" if include_fill else "0",
                        "net_exposure": "100" if include_fill else "0",
                    },
                ),
            ),
        ),
    )


def test_d2_registry_and_descriptors_are_concrete_and_ordered() -> None:
    registry = build_v1_5d2_registry()
    assert tuple(item.engine for item in registry.descriptors) == (
        SupportedEngine.VECTORBT,
        SupportedEngine.BT,
        SupportedEngine.BACKTRADER,
    )
    for mapper in (
        VectorbtArtifactMapper(),
        BtArtifactMapper(),
        BacktraderArtifactMapper(),
    ):
        assert isinstance(mapper, EngineArtifactMapper)
        assert len(mapper.descriptor.capabilities) == 11
        assert mapper.descriptor.allow_untested_engine_version is False
    assert (
        VECTORBT_DESCRIPTOR.capability_for(ComparisonLevel.ORDER).origin
        is EvidenceOrigin.DETERMINISTIC_DERIVATION
    )
    assert (
        BT_DESCRIPTOR.capability_for(ComparisonLevel.TRADE).availability
        is CapabilityAvailability.UNSUPPORTED
    )
    assert (
        BACKTRADER_DESCRIPTOR.capability_for(ComparisonLevel.ORDER).origin
        is EvidenceOrigin.ENGINE_EXPORT
    )


def test_vectorbt_mapper_preserves_open_trade_and_all_declared_levels() -> None:
    output = VectorbtArtifactMapper().map(_vectorbt_export())
    assert output.artifacts.available_levels == VECTORBT_LEVELS
    trade = (output.artifacts.trades or ())[0]
    assert trade.closed_at is None
    assert trade.exit_price is None
    assert trade.realized_pnl is None
    assert len(output.artifacts.costs or ()) == 1


@pytest.mark.parametrize(
    "export",
    [
        _vectorbt_export(side="Hold"),
        _vectorbt_export(position_instrument="MSFT"),
        _vectorbt_export(portfolio_rows=()),
    ],
)
def test_vectorbt_mapper_rejects_invalid_rows_or_scope(
    export: VerifiedEngineExport,
) -> None:
    with pytest.raises(EngineAdapterError):
        VectorbtArtifactMapper().map(export)


def test_bt_mapper_handles_sell_and_aggregate_fee() -> None:
    output = BtArtifactMapper().map(_bt_export(quantity="-1"))
    assert output.artifacts.available_levels == BT_LEVELS
    assert (output.artifacts.orders or ())[0].side.value == "sell"
    assert len(output.artifacts.costs or ()) == 1
    assert len(output.artifacts.returns or ()) == 1


@pytest.mark.parametrize(
    "export",
    [
        _bt_export(quantity="0"),
        _bt_export(transaction_instrument="MSFT"),
        _bt_export(first_return="0"),
        _bt_export(portfolio_rows=()),
    ],
)
def test_bt_mapper_rejects_invalid_transactions_or_portfolio(
    export: VerifiedEngineExport,
) -> None:
    with pytest.raises(EngineAdapterError):
        BtArtifactMapper().map(export)


def test_backtrader_mapper_maps_full_order_fill_cost_chain() -> None:
    output = BacktraderArtifactMapper().map(_backtrader_export())
    assert output.artifacts.available_levels == BACKTRADER_LEVELS
    order = (output.artifacts.orders or ())[0]
    assert order.order_type is OrderType.MARKET
    assert order.status is OrderStatus.FILLED
    assert len(output.artifacts.fills or ()) == 1
    assert len(output.artifacts.costs or ()) == 1
    assert len(output.artifacts.returns or ()) == 1
    assert output.warnings == ()


def test_backtrader_mapper_retains_lossy_status_and_type_warnings() -> None:
    output = BacktraderArtifactMapper().map(
        _backtrader_export(
            status="Margin",
            order_type="StopTrail",
            include_fill=False,
        )
    )
    order = (output.artifacts.orders or ())[0]
    assert order.status is OrderStatus.REJECTED
    assert order.order_type is OrderType.CUSTOM
    assert tuple(item.code for item in output.warnings) == (
        "backtrader.custom_order_type",
        "backtrader.margin_mapped_rejected",
    )


@pytest.mark.parametrize(
    "export",
    [
        _backtrader_export(status="Unknown"),
        _backtrader_export(fill_instrument="MSFT"),
        _backtrader_export(first_equity="0"),
    ],
)
def test_backtrader_mapper_rejects_invalid_lifecycle_or_return_derivation(
    export: VerifiedEngineExport,
) -> None:
    with pytest.raises(EngineAdapterError):
        BacktraderArtifactMapper().map(export)


def test_mapper_rejects_wrong_payload_metadata() -> None:
    export = _vectorbt_export()
    original = export.payload(VECTORBT_ORDERS_FILE)
    changed = replace(original, role="wrong")
    with pytest.raises(EngineAdapterError) as captured:
        VectorbtArtifactMapper().map(_replace_payload(export, changed))
    assert captured.value.engine_error_code == "vectorbt.payload_metadata_mismatch"
