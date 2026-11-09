from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk import (
    AdapterCapability,
    ArtifactReturnConvention,
    AssetClass,
    CanonicalParameter,
    CanonicalRunArtifacts,
    CanonicalRunSpecification,
    CashArtifacts,
    CashBalance,
    CashMovement,
    CashMovementType,
    CapabilityAvailability,
    ComparisonLevel,
    CostRecord,
    CostType,
    EngineRunReference,
    EngineAdapterDescriptor,
    EngineExportPayload,
    EquityPoint,
    EvidenceOrigin,
    FillRecord,
    InstrumentReference,
    LiquidityRole,
    MarketDataObservation,
    ModelSpecification,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    ReturnPoint,
    SignalRecord,
    SignalType,
    SimulationSpecification,
    StrategySpecification,
    SupportedEngine,
    TimeInForce,
    TradeDirection,
    TradeRecord,
    VerifiedEngineExport,
)


@pytest.fixture
def canonical_file_bundle() -> CanonicalRunArtifacts:
    t0 = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=1)
    t2 = t1 + timedelta(minutes=1)
    model_parameters = (
        CanonicalParameter("boolean", True),
        CanonicalParameter("decimal", Decimal("1.25"), "ratio"),
        CanonicalParameter("integer", 10, "bars"),
        CanonicalParameter("null", None),
        CanonicalParameter("string", "close"),
    )
    specification = CanonicalRunSpecification(
        strategy=StrategySpecification(
            strategy_id="strategy-1",
            name="Momentum",
            logic_sha256="b" * 64,
            universe=(
                InstrumentReference(
                    instrument_id="AAPL.XNAS",
                    asset_class=AssetClass.EQUITY,
                    symbol="AAPL",
                    currency="USD",
                    venue="XNAS",
                    attributes=(CanonicalParameter("vendor_id", "AAPL"),),
                ),
            ),
            parameters=(CanonicalParameter("lookback", 20, "bars"),),
            data_frequency="one minute",
            signal_timing="after bar availability",
            signal_model=ModelSpecification(
                "momentum",
                model_parameters,
                "1",
                "c" * 64,
            ),
            sizing_model=ModelSpecification("equal weight"),
            version="1",
        ),
        simulation=SimulationSpecification(
            base_currency="USD",
            initial_cash=Decimal(100_000),
            calendar="XNYS",
            calendar_timezone="America/New_York",
            data_adjustment_policy="split adjusted",
            execution_timing="next bar",
            execution_model=ModelSpecification("next bar"),
            accounting_model=ModelSpecification("average cost"),
            cost_models=(ModelSpecification("commission"),),
            shorting_allowed=False,
            fractional_quantity_allowed=False,
        ),
    )
    signal = SignalRecord(
        "signal-1",
        t0,
        "AAPL.XNAS",
        SignalType.TARGET_QUANTITY,
        Decimal(10),
        t0,
    )
    order = OrderRecord(
        order_id="order-1",
        created_at=t1,
        instrument_id="AAPL.XNAS",
        side=OrderSide.BUY,
        quantity=Decimal(10),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        status=OrderStatus.FILLED,
        signal_id="signal-1",
        submitted_at=t1,
        last_updated_at=t2,
    )
    fill = FillRecord(
        "fill-1",
        "order-1",
        t2,
        "AAPL.XNAS",
        OrderSide.BUY,
        Decimal(10),
        Decimal("100.25"),
        "USD",
        LiquidityRole.TAKER,
        "XNAS",
    )
    trade = TradeRecord(
        trade_id="trade-1",
        instrument_id="AAPL.XNAS",
        direction=TradeDirection.LONG,
        opened_at=t2,
        quantity=Decimal(10),
        entry_price=Decimal("100.25"),
        currency="USD",
        grouping_method="engine declared",
        fill_ids=("fill-1",),
    )
    return CanonicalRunArtifacts(
        run=EngineRunReference("run-1", "engine", "1.0", "a" * 64),
        specification=specification,
        market_data=(
            MarketDataObservation(
                "observation-1",
                "AAPL.XNAS",
                t0,
                "close",
                Decimal("100.25"),
                t0,
                "USD",
            ),
        ),
        signals=(signal,),
        orders=(order,),
        fills=(fill,),
        trades=(trade,),
        positions=(
            PositionSnapshot(
                t2,
                "AAPL.XNAS",
                Decimal(10),
                "USD",
                Decimal("100.25"),
                Decimal("1002.5"),
                Decimal("100.25"),
                Decimal(0),
                Decimal(0),
            ),
        ),
        cash=CashArtifacts(
            balances=(CashBalance(t2, "USD", Decimal("98997.5")),),
            movements=(
                CashMovement(
                    "cash-1",
                    t2,
                    "USD",
                    Decimal("-1002.5"),
                    CashMovementType.SETTLEMENT,
                    "fill-1",
                ),
            ),
        ),
        costs=(
            CostRecord(
                "cost-1",
                t2,
                CostType.COMMISSION,
                Decimal("-1"),
                "USD",
                "order-1",
                "fill-1",
                "trade-1",
            ),
        ),
        equity=(
            EquityPoint(
                t2,
                "USD",
                Decimal(100_000),
                Decimal("98997.5"),
                Decimal("1002.5"),
                Decimal("1002.5"),
            ),
        ),
        returns=(ReturnPoint(t0, t2, Decimal(0), ArtifactReturnConvention.SIMPLE),),
    )


@pytest.fixture
def verified_engine_export() -> VerifiedEngineExport:
    return VerifiedEngineExport.create(
        run_id="vectorbt-run",
        engine=SupportedEngine.VECTORBT,
        engine_version="0.28.1",
        export_format_id="backtest-auditor.vectorbt",
        export_format_version="1.0",
        declared_levels=(ComparisonLevel.RETURN,),
        payloads=(
            EngineExportPayload(
                path="returns.csv",
                role="returns",
                media_type="text/csv; charset=utf-8",
                data=(
                    b"start_timestamp,end_timestamp,return,return_convention\n"
                    b"2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,0.01,simple\n"
                ),
            ),
        ),
    )


@pytest.fixture
def vectorbt_adapter_descriptor() -> EngineAdapterDescriptor:
    return EngineAdapterDescriptor(
        adapter_id="backtest-auditor.vectorbt",
        adapter_version="1.5.0a4",
        engine=SupportedEngine.VECTORBT,
        display_name="vectorbt",
        export_format_id="backtest-auditor.vectorbt",
        supported_export_format_versions=("1.0",),
        tested_engine_versions=("0.28.1",),
        allow_undisclosed_engine_version=False,
        allow_untested_engine_version=False,
        capabilities=tuple(
            AdapterCapability(
                level=level,
                availability=(
                    CapabilityAvailability.CONDITIONAL
                    if level is ComparisonLevel.RETURN
                    else CapabilityAvailability.UNSUPPORTED
                ),
                origin=(
                    EvidenceOrigin.ENGINE_EXPORT
                    if level is ComparisonLevel.RETURN
                    else EvidenceOrigin.NONE
                ),
                explanation=(
                    "Mapped from an exported return history."
                    if level is ComparisonLevel.RETURN
                    else "This focused test adapter does not emit this level."
                ),
            )
            for level in ComparisonLevel
        ),
    )


@pytest.fixture
def vectorbt_return_artifacts(
    verified_engine_export: VerifiedEngineExport,
) -> CanonicalRunArtifacts:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    envelope = verified_engine_export.envelope
    return CanonicalRunArtifacts(
        run=EngineRunReference(
            run_id=envelope.run_id,
            engine_name=envelope.engine.value,
            engine_version=envelope.engine_version,
            source_sha256=envelope.source_sha256,
        ),
        returns=(
            ReturnPoint(
                start_timestamp=start,
                end_timestamp=end,
                value=Decimal("0.01"),
                convention=ArtifactReturnConvention.SIMPLE,
            ),
        ),
    )
