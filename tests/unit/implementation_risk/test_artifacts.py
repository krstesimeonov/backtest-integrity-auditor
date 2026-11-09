from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk import (
    ArtifactReturnConvention,
    CashArtifacts,
    CashBalance,
    CashMovement,
    CashMovementType,
    CostRecord,
    CostType,
    EquityPoint,
    FillRecord,
    LiquidityRole,
    MarketDataObservation,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    ReturnPoint,
    SignalRecord,
    SignalType,
    TimeInForce,
    TradeDirection,
    TradeRecord,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T1 + timedelta(minutes=1)


def _order(**overrides) -> OrderRecord:
    values = {
        "order_id": "order-1",
        "created_at": T0,
        "instrument_id": "AAPL.XNAS",
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "status": OrderStatus.FILLED,
        "submitted_at": T0,
        "last_updated_at": T1,
    }
    values.update(overrides)
    return OrderRecord(**values)


def _fill(**overrides) -> FillRecord:
    values = {
        "fill_id": "fill-1",
        "order_id": "order-1",
        "timestamp": T1,
        "instrument_id": "AAPL.XNAS",
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "price": Decimal("100"),
        "currency": "USD",
    }
    values.update(overrides)
    return FillRecord(**values)


def test_market_data_preserves_event_and_availability_time() -> None:
    eastern = timezone(timedelta(hours=-5))
    observation = MarketDataObservation(
        observation_id=" close-1 ",
        instrument_id=" AAPL.XNAS ",
        event_timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=eastern),
        available_timestamp=T0,
        field=" close ",
        value="100.00",  # type: ignore[arg-type]
        unit=" USD ",
    )

    assert observation.event_timestamp == T0
    assert observation.available_timestamp == T0
    assert observation.value == Decimal(100)
    assert observation.field == "close"
    assert observation.unit == "USD"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"event_timestamp": datetime(2026, 1, 1)}, "timezone-aware"),
        ({"event_timestamp": "2026-01-01"}, "must be a datetime"),
        ({"available_timestamp": T0 - timedelta(seconds=1)}, "not be earlier"),
        ({"field": ""}, "market-data field"),
        ({"value": 1.5}, "floats are rejected"),
        ({"value": object()}, "Decimal, integer, or decimal string"),
        ({"value": "not-a-decimal"}, "valid decimal value"),
        ({"value": "NaN"}, "must be finite"),
        ({"unit": "\n"}, "market-data unit"),
    ],
)
def test_market_data_rejects_invalid_contract(overrides, message) -> None:
    values = {
        "observation_id": "observation-1",
        "instrument_id": "AAPL.XNAS",
        "event_timestamp": T0,
        "field": "close",
        "value": Decimal(100),
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        MarketDataObservation(**values)


@pytest.mark.parametrize(
    ("signal_type", "value"),
    [
        (SignalType.TARGET_QUANTITY, Decimal(10)),
        (SignalType.TARGET_WEIGHT, Decimal("0.5")),
        (SignalType.TARGET_NOTIONAL, Decimal(1000)),
        (SignalType.SCORE, Decimal("1.2")),
        (SignalType.ENTRY, None),
        (SignalType.EXIT, None),
        (SignalType.CUSTOM, None),
    ],
)
def test_signal_supports_explicit_signal_semantics(signal_type, value) -> None:
    signal = SignalRecord(
        "signal-1",
        T1,
        "AAPL.XNAS",
        signal_type,
        value,
        T0,
    )

    assert signal.signal_type is signal_type
    assert signal.value == value


def test_signal_normalizes_runtime_enum_and_utc() -> None:
    signal = SignalRecord(
        "signal-1",
        T1,
        "AAPL.XNAS",
        "target_quantity",  # type: ignore[arg-type]
        "10",  # type: ignore[arg-type]
    )

    assert signal.signal_type is SignalType.TARGET_QUANTITY
    assert signal.value == Decimal(10)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"signal_type": "unknown"}, "signal_type"),
        ({"value": None}, "require a value"),
        ({"source_data_timestamp": T2}, "must not be later"),
    ],
)
def test_signal_rejects_invalid_contract(overrides, message) -> None:
    values = {
        "signal_id": "signal-1",
        "timestamp": T1,
        "instrument_id": "AAPL.XNAS",
        "signal_type": SignalType.TARGET_QUANTITY,
        "value": Decimal(10),
        "source_data_timestamp": T0,
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        SignalRecord(**values)


@pytest.mark.parametrize(
    ("order_type", "limit_price", "stop_price"),
    [
        (OrderType.MARKET, None, None),
        (OrderType.MARKET_ON_CLOSE, None, None),
        (OrderType.LIMIT, Decimal(100), None),
        (OrderType.LIMIT_ON_CLOSE, Decimal(100), None),
        (OrderType.STOP, None, Decimal(99)),
        (OrderType.STOP_LIMIT, Decimal(98), Decimal(99)),
        (OrderType.CUSTOM, Decimal(98), Decimal(99)),
    ],
)
def test_order_enforces_type_specific_price_contract(
    order_type,
    limit_price,
    stop_price,
) -> None:
    order = _order(
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
    )

    assert order.order_type is order_type
    assert order.limit_price == limit_price
    assert order.stop_price == stop_price


def test_order_normalizes_runtime_enums_identifiers_and_decimals() -> None:
    order = OrderRecord(
        order_id=" order-1 ",
        created_at=T0,
        instrument_id=" AAPL.XNAS ",
        side="buy",  # type: ignore[arg-type]
        quantity="10.0",  # type: ignore[arg-type]
        order_type="market",  # type: ignore[arg-type]
        time_in_force="day",  # type: ignore[arg-type]
        status="created",  # type: ignore[arg-type]
        signal_id=" signal-1 ",
    )

    assert order.order_id == "order-1"
    assert order.signal_id == "signal-1"
    assert order.quantity == Decimal(10)
    assert order.side is OrderSide.BUY


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"parent_order_id": "order-1"}, "must not equal"),
        ({"submitted_at": T0 - timedelta(seconds=1)}, "submitted_at"),
        ({"last_updated_at": T0 - timedelta(seconds=1)}, "last_updated_at"),
        ({"last_updated_at": T0, "submitted_at": T1}, "last_updated_at"),
        ({"quantity": 0}, "greater than zero"),
        ({"side": "hold"}, "side"),
        ({"side": 1}, "side"),
        ({"order_type": "unknown"}, "order_type"),
        ({"time_in_force": "unknown"}, "time_in_force"),
        ({"status": "unknown"}, "status"),
        ({"order_type": OrderType.LIMIT}, "limit orders"),
        (
            {"order_type": OrderType.STOP, "stop_price": None},
            "stop orders",
        ),
        (
            {"order_type": OrderType.STOP_LIMIT, "limit_price": Decimal(1)},
            "stop-limit",
        ),
        ({"limit_price": Decimal(1)}, "market orders"),
        ({"time_in_force": TimeInForce.GTD}, "require expires_at"),
        ({"expires_at": T2}, "only for GTD"),
        ({"submitted_at": None}, "require submitted_at"),
    ],
)
def test_order_rejects_invalid_contract(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        _order(**overrides)


def test_order_accepts_gtd_and_unsubmitted_created_or_rejected_statuses() -> None:
    gtd = _order(time_in_force=TimeInForce.GTD, expires_at=T2)
    created = _order(status=OrderStatus.CREATED, submitted_at=None)
    rejected = _order(status=OrderStatus.REJECTED, submitted_at=None)

    assert gtd.expires_at == T2
    assert created.submitted_at is None
    assert rejected.submitted_at is None


def test_fill_normalizes_values_and_optional_provenance() -> None:
    fill = FillRecord(
        " fill-1 ",
        " order-1 ",
        T1,
        " AAPL.XNAS ",
        "buy",  # type: ignore[arg-type]
        "10",  # type: ignore[arg-type]
        "100.50",  # type: ignore[arg-type]
        "usd",
        "maker",  # type: ignore[arg-type]
        " XNAS ",
    )

    assert fill.price == Decimal("100.5")
    assert fill.currency == "USD"
    assert fill.liquidity_role is LiquidityRole.MAKER
    assert fill.venue == "XNAS"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"quantity": 0}, "greater than zero"),
        ({"price": 0}, "greater than zero"),
        ({"liquidity_role": "unknown-role"}, "liquidity_role"),
        ({"currency": "?"}, "currency"),
    ],
)
def test_fill_rejects_invalid_contract(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        _fill(**overrides)


def test_trade_distinguishes_open_and_closed_records() -> None:
    open_trade = TradeRecord(
        "trade-open",
        "AAPL.XNAS",
        TradeDirection.LONG,
        T0,
        Decimal(10),
        Decimal(100),
        "USD",
        "engine declared",
    )
    closed_trade = TradeRecord(
        "trade-closed",
        "AAPL.XNAS",
        "long",  # type: ignore[arg-type]
        T0,
        "10",  # type: ignore[arg-type]
        "100",  # type: ignore[arg-type]
        "usd",
        " engine declared ",
        T2,
        "110",  # type: ignore[arg-type]
        "100",  # type: ignore[arg-type]
        ("fill-z", "fill-a"),
    )

    assert open_trade.closed_at is None
    assert closed_trade.exit_price == Decimal(110)
    assert closed_trade.fill_ids == ("fill-a", "fill-z")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"direction": "flat"}, "direction"),
        ({"closed_at": T0 - timedelta(seconds=1)}, "closed_at"),
        ({"exit_price": Decimal(110)}, "open trades"),
        ({"realized_pnl": Decimal(1)}, "open trades"),
        ({"closed_at": T2}, "closed trades require"),
        ({"fill_ids": None}, "iterable"),
        ({"fill_ids": ("fill-1", "fill-1")}, "duplicates"),
    ],
)
def test_trade_rejects_invalid_contract(overrides, message) -> None:
    values = {
        "trade_id": "trade-1",
        "instrument_id": "AAPL.XNAS",
        "direction": TradeDirection.LONG,
        "opened_at": T0,
        "quantity": Decimal(10),
        "entry_price": Decimal(100),
        "currency": "USD",
        "grouping_method": "engine declared",
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        TradeRecord(**values)


def test_position_normalizes_signed_quantity_and_optional_valuation() -> None:
    position = PositionSnapshot(
        T1,
        "AAPL.XNAS",
        "-10",  # type: ignore[arg-type]
        "usd",
        "100",  # type: ignore[arg-type]
        "-1000",  # type: ignore[arg-type]
        "95",  # type: ignore[arg-type]
        "5",  # type: ignore[arg-type]
        "-50",  # type: ignore[arg-type]
    )

    assert position.quantity == Decimal(-10)
    assert position.market_value == Decimal(-1000)


@pytest.mark.parametrize(
    ("field", "value"),
    [("market_price", 0), ("average_cost", -1)],
)
def test_position_rejects_invalid_price_or_cost(field, value) -> None:
    values = {
        "timestamp": T1,
        "instrument_id": "AAPL.XNAS",
        "quantity": Decimal(1),
        "currency": "USD",
        field: value,
    }
    with pytest.raises(ValueError):
        PositionSnapshot(**values)


def test_cash_records_use_signed_movements_and_canonical_currency() -> None:
    balance = CashBalance(T0, "usd", "1000.00", "900")  # type: ignore[arg-type]
    movement = CashMovement(
        "movement-1",
        T1,
        "usd",
        "-10",  # type: ignore[arg-type]
        "tax",  # type: ignore[arg-type]
        "fill-1",
    )

    assert balance.total == Decimal(1000)
    assert movement.amount == Decimal(-10)
    assert movement.movement_type is CashMovementType.TAX


def test_cash_movement_rejects_zero_or_unknown_type() -> None:
    with pytest.raises(ValueError, match="must not be zero"):
        CashMovement("movement", T0, "USD", 0, CashMovementType.OTHER)
    with pytest.raises(ValueError, match="movement_type"):
        CashMovement("movement", T0, "USD", 1, "unknown")  # type: ignore[arg-type]


def test_cash_artifacts_preserve_unavailable_versus_empty() -> None:
    empty_balances = CashArtifacts(balances=(), movements=None)
    movements = CashArtifacts(
        balances=None,
        movements=(CashMovement("movement", T0, "USD", 1, CashMovementType.DEPOSIT),),
    )

    assert empty_balances.balances == ()
    assert empty_balances.movements is None
    assert movements.balances is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "require"),
        ({"balances": None, "movements": None}, "require"),
        ({"balances": 1}, "iterable"),
        ({"balances": ("balance",)}, "invalid record"),
        (
            {"balances": (CashBalance(T0, "USD", 1), CashBalance(T0, "USD", 2))},
            "unique",
        ),
        (
            {
                "movements": (
                    CashMovement("later", T1, "USD", 1, CashMovementType.DEPOSIT),
                    CashMovement("earlier", T0, "USD", 1, CashMovementType.DEPOSIT),
                )
            },
            "canonical order",
        ),
    ],
)
def test_cash_artifacts_reject_invalid_collections(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        CashArtifacts(**kwargs)


def test_cost_uses_signed_pnl_impact_and_optional_links() -> None:
    cost = CostRecord(
        " cost-1 ",
        T1,
        "commission",  # type: ignore[arg-type]
        "-1.25",  # type: ignore[arg-type]
        "usd",
        "order-1",
        "fill-1",
        None,
    )

    assert cost.cost_type is CostType.COMMISSION
    assert cost.pnl_impact == Decimal("-1.25")
    assert cost.fill_id == "fill-1"


def test_cost_rejects_invalid_type() -> None:
    with pytest.raises(ValueError, match="cost_type"):
        CostRecord("cost", T1, "unknown", -1, "USD")  # type: ignore[arg-type]


def test_equity_allows_negative_net_exposure_but_not_negative_gross() -> None:
    point = EquityPoint(T1, "usd", "1000", "100", "500", "-200")  # type: ignore[arg-type]

    assert point.net_exposure == Decimal(-200)
    with pytest.raises(ValueError, match="greater than or equal"):
        EquityPoint(T1, "USD", 1000, gross_exposure=-1)


@pytest.mark.parametrize(
    ("convention", "value"),
    [
        (ArtifactReturnConvention.SIMPLE, Decimal("-1")),
        (ArtifactReturnConvention.SIMPLE, Decimal("0.1")),
        (ArtifactReturnConvention.LOG, Decimal("-2")),
    ],
)
def test_return_point_supports_explicit_conventions(convention, value) -> None:
    point = ReturnPoint(T0, T1, value, convention)

    assert point.value == value
    assert point.convention is convention


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"end_timestamp": T0}, "later"),
        ({"convention": "unknown"}, "return convention"),
        ({"value": Decimal("-1.01")}, "greater than or equal"),
    ],
)
def test_return_point_rejects_invalid_contract(overrides, message) -> None:
    values = {
        "start_timestamp": T0,
        "end_timestamp": T1,
        "value": Decimal("0.1"),
        "convention": ArtifactReturnConvention.SIMPLE,
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        ReturnPoint(**values)
