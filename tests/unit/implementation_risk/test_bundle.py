from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk import (
    CANONICAL_ARTIFACT_SCHEMA_VERSION,
    ArtifactReturnConvention,
    AssetClass,
    CanonicalRunArtifacts,
    CanonicalRunSpecification,
    CashArtifacts,
    CashBalance,
    ComparisonLevel,
    CostRecord,
    CostType,
    EngineRunReference,
    EquityPoint,
    FillRecord,
    InstrumentReference,
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
    TimeInForce,
    TradeDirection,
    TradeRecord,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T1 + timedelta(minutes=1)


def _run() -> EngineRunReference:
    return EngineRunReference("run-1", "engine", "1.0", "a" * 64)


def _model(name: str) -> ModelSpecification:
    return ModelSpecification(name)


def _specification() -> CanonicalRunSpecification:
    strategy = StrategySpecification(
        strategy_id="strategy-1",
        name="Strategy",
        logic_sha256="b" * 64,
        universe=(
            InstrumentReference(
                instrument_id="AAPL.XNAS",
                asset_class=AssetClass.EQUITY,
                symbol="AAPL",
                currency="USD",
                venue="XNAS",
            ),
        ),
        parameters=(),
        data_frequency="one minute",
        signal_timing="after bar availability",
        signal_model=_model("signal"),
        sizing_model=_model("sizing"),
    )
    simulation = SimulationSpecification(
        base_currency="USD",
        initial_cash=Decimal(100_000),
        calendar="XNYS",
        calendar_timezone="America/New_York",
        data_adjustment_policy="split adjusted",
        execution_timing="next bar",
        execution_model=_model("execution"),
        accounting_model=_model("accounting"),
        cost_models=(_model("commission"),),
        shorting_allowed=False,
        fractional_quantity_allowed=False,
    )
    return CanonicalRunSpecification(strategy, simulation)


def _signal(**overrides) -> SignalRecord:
    values = {
        "signal_id": "signal-1",
        "timestamp": T0,
        "instrument_id": "AAPL.XNAS",
        "signal_type": SignalType.TARGET_QUANTITY,
        "value": Decimal(10),
        "source_data_timestamp": T0,
    }
    values.update(overrides)
    return SignalRecord(**values)


def _order(**overrides) -> OrderRecord:
    values = {
        "order_id": "order-1",
        "created_at": T1,
        "instrument_id": "AAPL.XNAS",
        "side": OrderSide.BUY,
        "quantity": Decimal(10),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "status": OrderStatus.FILLED,
        "signal_id": "signal-1",
        "submitted_at": T1,
        "last_updated_at": T2,
    }
    values.update(overrides)
    return OrderRecord(**values)


def _fill(**overrides) -> FillRecord:
    values = {
        "fill_id": "fill-1",
        "order_id": "order-1",
        "timestamp": T2,
        "instrument_id": "AAPL.XNAS",
        "side": OrderSide.BUY,
        "quantity": Decimal(10),
        "price": Decimal(100),
        "currency": "USD",
    }
    values.update(overrides)
    return FillRecord(**values)


def _trade(**overrides) -> TradeRecord:
    values = {
        "trade_id": "trade-1",
        "instrument_id": "AAPL.XNAS",
        "direction": TradeDirection.LONG,
        "opened_at": T2,
        "quantity": Decimal(10),
        "entry_price": Decimal(100),
        "currency": "USD",
        "grouping_method": "engine declared",
        "fill_ids": ("fill-1",),
    }
    values.update(overrides)
    return TradeRecord(**values)


def _full_bundle(**overrides) -> CanonicalRunArtifacts:
    values = {
        "run": _run(),
        "specification": _specification(),
        "market_data": (
            MarketDataObservation(
                "observation-1",
                "AAPL.XNAS",
                T0,
                "close",
                Decimal(100),
                T0,
                "USD",
            ),
        ),
        "signals": (_signal(),),
        "orders": (_order(),),
        "fills": (_fill(),),
        "trades": (_trade(),),
        "positions": (PositionSnapshot(T2, "AAPL.XNAS", 10, "USD"),),
        "cash": CashArtifacts(balances=(CashBalance(T2, "USD", 99_000),)),
        "costs": (
            CostRecord(
                "cost-1",
                T2,
                CostType.COMMISSION,
                Decimal("-1"),
                "USD",
                "order-1",
                "fill-1",
                "trade-1",
            ),
        ),
        "equity": (EquityPoint(T2, "USD", 100_000),),
        "returns": (ReturnPoint(T0, T2, Decimal(0), ArtifactReturnConvention.SIMPLE),),
    }
    values.update(overrides)
    return CanonicalRunArtifacts(**values)


def test_full_bundle_exposes_every_independent_level() -> None:
    bundle = _full_bundle()

    assert bundle.artifact_schema_version == CANONICAL_ARTIFACT_SCHEMA_VERSION
    assert bundle.available_levels == tuple(ComparisonLevel)
    assert bundle.evidence_profile().run == bundle.run
    assert bundle.evidence_profile().available_levels == tuple(ComparisonLevel)


def test_none_and_empty_collection_have_distinct_availability_semantics() -> None:
    bundle = CanonicalRunArtifacts(
        run=_run(),
        signals=(),
        orders=None,
        cash=CashArtifacts(balances=()),
    )

    assert ComparisonLevel.SIGNAL in bundle.available_levels
    assert ComparisonLevel.CASH in bundle.available_levels
    assert ComparisonLevel.ORDER not in bundle.available_levels
    assert bundle.signals == ()
    assert bundle.orders is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"run": "run"}, "EngineRunReference"),
        ({"specification": "specification"}, "CanonicalRunSpecification"),
        ({"cash": "cash"}, "CashArtifacts"),
        ({"artifact_schema_version": "2.0"}, "must equal"),
        ({"signals": 1}, "iterable"),
        ({"signals": ("signal",)}, "invalid record"),
    ],
)
def test_bundle_rejects_invalid_top_level_contract(overrides, message) -> None:
    values = {"run": _run()}
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        CanonicalRunArtifacts(**values)


def test_bundle_rejects_duplicate_identity_and_noncanonical_order() -> None:
    duplicate = (_signal(), _signal())
    with pytest.raises(ValueError, match="signals identity.*unique"):
        CanonicalRunArtifacts(run=_run(), signals=duplicate)

    later = _signal(signal_id="later", timestamp=T1)
    earlier = _signal(signal_id="earlier", timestamp=T0)
    with pytest.raises(ValueError, match="signals.*canonical order"):
        CanonicalRunArtifacts(run=_run(), signals=(later, earlier))


@pytest.mark.parametrize(
    ("field", "records"),
    [
        (
            "market_data",
            (
                MarketDataObservation("b", "AAPL.XNAS", T1, "close", 1),
                MarketDataObservation("a", "AAPL.XNAS", T0, "close", 1),
            ),
        ),
        (
            "orders",
            (
                _order(order_id="b", created_at=T2, submitted_at=T2),
                _order(order_id="a"),
            ),
        ),
        (
            "fills",
            (
                _fill(fill_id="b", timestamp=T2),
                _fill(fill_id="a", timestamp=T1),
            ),
        ),
        (
            "trades",
            (
                _trade(trade_id="b", opened_at=T2),
                _trade(trade_id="a", opened_at=T1),
            ),
        ),
        (
            "positions",
            (
                PositionSnapshot(T2, "AAPL.XNAS", 1, "USD"),
                PositionSnapshot(T1, "AAPL.XNAS", 1, "USD"),
            ),
        ),
        (
            "costs",
            (
                CostRecord("b", T2, CostType.OTHER, -1, "USD"),
                CostRecord("a", T1, CostType.OTHER, -1, "USD"),
            ),
        ),
        (
            "equity",
            (EquityPoint(T2, "USD", 1), EquityPoint(T1, "USD", 1)),
        ),
        (
            "returns",
            (
                ReturnPoint(T1, T2, 0, ArtifactReturnConvention.SIMPLE),
                ReturnPoint(T0, T1, 0, ArtifactReturnConvention.SIMPLE),
            ),
        ),
    ],
)
def test_bundle_rejects_noncanonical_order_for_each_series(field, records) -> None:
    with pytest.raises(ValueError, match=f"{field}.*canonical order"):
        CanonicalRunArtifacts(run=_run(), **{field: records})


@pytest.mark.parametrize(
    ("field", "records"),
    [
        (
            "market_data",
            (
                MarketDataObservation("same", "AAPL.XNAS", T0, "close", 1),
                MarketDataObservation("same", "AAPL.XNAS", T1, "close", 2),
            ),
        ),
        ("orders", (_order(), _order())),
        ("fills", (_fill(), _fill())),
        ("trades", (_trade(), _trade())),
        (
            "positions",
            (
                PositionSnapshot(T0, "AAPL.XNAS", 1, "USD"),
                PositionSnapshot(T0, "AAPL.XNAS", 2, "USD"),
            ),
        ),
        (
            "costs",
            (
                CostRecord("same", T0, CostType.OTHER, -1, "USD"),
                CostRecord("same", T1, CostType.OTHER, -1, "USD"),
            ),
        ),
        (
            "equity",
            (EquityPoint(T0, "USD", 1), EquityPoint(T0, "USD", 2)),
        ),
        (
            "returns",
            (
                ReturnPoint(T0, T1, 0, ArtifactReturnConvention.SIMPLE),
                ReturnPoint(T0, T1, 1, ArtifactReturnConvention.SIMPLE),
            ),
        ),
    ],
)
def test_bundle_rejects_duplicate_identity_for_each_series(field, records) -> None:
    with pytest.raises(ValueError, match="identity.*unique"):
        CanonicalRunArtifacts(run=_run(), **{field: records})


@pytest.mark.parametrize(
    ("field", "record"),
    [
        (
            "market_data",
            MarketDataObservation("x", "MSFT.XNAS", T0, "close", 1),
        ),
        ("signals", _signal(instrument_id="MSFT.XNAS")),
        ("orders", _order(instrument_id="MSFT.XNAS")),
        ("fills", _fill(instrument_id="MSFT.XNAS")),
        ("trades", _trade(instrument_id="MSFT.XNAS")),
        ("positions", PositionSnapshot(T0, "MSFT.XNAS", 1, "USD")),
    ],
)
def test_specified_bundle_rejects_unknown_instruments(field, record) -> None:
    with pytest.raises(ValueError, match="outside the strategy universe"):
        CanonicalRunArtifacts(
            run=_run(),
            specification=_specification(),
            **{field: (record,)},
        )


@pytest.mark.parametrize(
    ("field", "record", "message"),
    [
        ("fills", _fill(currency="EUR"), "fill.*currency"),
        ("trades", _trade(currency="EUR"), "trade.*currency"),
        (
            "positions",
            PositionSnapshot(T0, "AAPL.XNAS", 1, "EUR"),
            "position currency",
        ),
    ],
)
def test_specified_bundle_rejects_instrument_currency_mismatch(
    field,
    record,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        CanonicalRunArtifacts(
            run=_run(),
            specification=_specification(),
            **{field: (record,)},
        )


def test_order_chain_accepts_unavailable_upstream_evidence() -> None:
    bundle = CanonicalRunArtifacts(
        run=_run(),
        signals=None,
        orders=(_order(),),
        fills=None,
    )

    assert bundle.orders == (_order(),)


def test_order_chain_rejects_unknown_or_later_parent() -> None:
    child = _order(order_id="child", parent_order_id="parent")
    with pytest.raises(ValueError, match="unknown parent"):
        CanonicalRunArtifacts(run=_run(), orders=(child,))

    parent = _order(
        order_id="parent",
        created_at=T2,
        submitted_at=T2,
        last_updated_at=T2,
    )
    with pytest.raises(ValueError, match="must not be created after"):
        CanonicalRunArtifacts(run=_run(), orders=(child, parent))


@pytest.mark.parametrize(
    ("signals", "order", "message"),
    [
        ((), _order(), "unknown signal"),
        (
            (_signal(instrument_id="MSFT.XNAS"),),
            _order(),
            "instrument_id values must match",
        ),
        (
            (_signal(timestamp=T2, source_data_timestamp=T2),),
            _order(),
            "must not occur after",
        ),
    ],
)
def test_order_chain_rejects_invalid_signal_reference(signals, order, message) -> None:
    with pytest.raises(ValueError, match=message):
        CanonicalRunArtifacts(run=_run(), signals=signals, orders=(order,))


@pytest.mark.parametrize(
    ("orders", "fill", "message"),
    [
        ((), _fill(), "unknown order"),
        (
            (_order(side=OrderSide.SELL),),
            _fill(),
            "instrument and side",
        ),
        (
            (_order(created_at=T2, submitted_at=T2),),
            _fill(timestamp=T1),
            "must not occur before",
        ),
        (
            (_order(quantity=5),),
            _fill(quantity=10),
            "exceed order quantity",
        ),
        (
            (_order(quantity=10),),
            _fill(quantity=5),
            "must be completely filled",
        ),
        (
            (_order(status=OrderStatus.PARTIALLY_FILLED),),
            _fill(quantity=10),
            "needs a partial quantity",
        ),
        (
            (_order(status=OrderStatus.REJECTED, submitted_at=None),),
            _fill(),
            "must not have fills",
        ),
    ],
)
def test_fill_chain_rejects_cross_record_contradictions(orders, fill, message) -> None:
    with pytest.raises(ValueError, match=message):
        CanonicalRunArtifacts(run=_run(), orders=orders, fills=(fill,))


@pytest.mark.parametrize(
    ("order", "message"),
    [
        (_order(), "must be completely filled"),
        (
            _order(status=OrderStatus.PARTIALLY_FILLED),
            "needs a partial quantity",
        ),
    ],
)
def test_available_empty_fills_validate_status_claims(order, message) -> None:
    with pytest.raises(ValueError, match=message):
        CanonicalRunArtifacts(run=_run(), orders=(order,), fills=())


def test_valid_partial_and_canceled_partial_fills_are_accepted() -> None:
    partial_fill = _fill(quantity=4)
    partial = CanonicalRunArtifacts(
        run=_run(),
        orders=(_order(status=OrderStatus.PARTIALLY_FILLED),),
        fills=(partial_fill,),
    )
    canceled = CanonicalRunArtifacts(
        run=_run(),
        orders=(_order(status=OrderStatus.CANCELED),),
        fills=(partial_fill,),
    )

    assert partial.fills == (partial_fill,)
    assert canceled.fills == (partial_fill,)


@pytest.mark.parametrize(
    ("trade", "fills", "message"),
    [
        (_trade(fill_ids=("missing",)), (), "unknown fill"),
        (
            _trade(instrument_id="MSFT.XNAS"),
            (_fill(),),
            "instrument_id values must match",
        ),
    ],
)
def test_trade_chain_rejects_invalid_fill_reference(trade, fills, message) -> None:
    with pytest.raises(ValueError, match=message):
        CanonicalRunArtifacts(run=_run(), trades=(trade,), fills=fills)


@pytest.mark.parametrize("field", ["order_id", "fill_id", "trade_id"])
def test_cost_chain_rejects_unknown_available_reference(field) -> None:
    values = {
        "cost_id": "cost-1",
        "timestamp": T2,
        "cost_type": CostType.OTHER,
        "pnl_impact": Decimal(-1),
        "currency": "USD",
        field: "missing",
    }
    cost = CostRecord(**values)

    with pytest.raises(ValueError, match=f"unknown {field}"):
        CanonicalRunArtifacts(
            run=_run(),
            orders=(),
            fills=(),
            trades=(),
            costs=(cost,),
        )


def test_cost_reference_is_not_guessed_when_related_level_is_unavailable() -> None:
    cost = CostRecord(
        "cost-1",
        T2,
        CostType.OTHER,
        -1,
        "USD",
        order_id="unavailable-order",
    )

    bundle = CanonicalRunArtifacts(run=_run(), orders=None, costs=(cost,))

    assert bundle.costs == (cost,)


def test_equity_must_use_declared_simulation_base_currency() -> None:
    with pytest.raises(ValueError, match="simulation base currency"):
        CanonicalRunArtifacts(
            run=_run(),
            specification=_specification(),
            equity=(EquityPoint(T2, "EUR", 100),),
        )
