"""Adversarial reproducers: engine runs the adapters accept but mis-state.

Every test drives a real engine in a legitimate configuration (or feeds the
exporter LEAN's own checked-in result files, at most with one value a LEAN
algorithm can really produce), exports it with the shipped exporter, maps it
with the shipped D3 service, and asserts what the canonical bundle has to say
about the strategy that actually ran.

Each of these fails today: export and mapping succeed, and the bundle states
something false. Refusing the run (the exporter raising ``ValueError`` or the
adapter raising ``EngineAdapterError``) is also an acceptable fix, so a refusal
makes a test pass; only an accepted but wrong bundle fails it.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    CanonicalRunArtifacts,
    CostType,
    EngineAdapterError,
    OrderSide,
    OrderStatus,
    build_v1_5d3_service,
    create_backtrader_audit_analyzer,
    export_backtrader_analysis,
    export_bt_result,
    export_nautilustrader_engine,
    export_quantconnect_lean_results,
)

from e2e import reference

NEW_YORK = reference.EXCHANGE_TIMEZONE
LEAN_DATA = Path(__file__).resolve().parent / "data" / "lean" / "lag1"
LEAN_ALGORITHM = "SynMaCrossAlgorithm"


def _adapt(export: Callable[[], Path]) -> CanonicalRunArtifacts | None:
    """Export and map; ``None`` when the package refuses the run."""

    try:
        exported = export()
    except ValueError:
        return None
    try:
        return build_v1_5d3_service().adapt(exported).artifacts
    except EngineAdapterError:
        return None


def _signed(fill) -> Decimal:
    return fill.quantity if fill.side is OrderSide.BUY else -fill.quantity


def _bar_instants() -> set[pd.Timestamp]:
    return set(reference.load_prices().index)


# ---------------------------------------------------------------------------
# NautilusTrader 1.231.0
# ---------------------------------------------------------------------------


def _nautilus_scripted_run(tmp: Path, *, oms: str, plan: dict[int, tuple[str, int]]):
    """A strategy that sends ``plan[bar] = (side, qty)`` market orders."""

    pytest.importorskip("nautilus_trader")
    from e2e import test_nautilustrader as nt_e2e
    from nautilus_trader.backtest.config import BacktestEngineConfig
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FillModel, FixedFeeModel
    from nautilus_trader.config import LoggingConfig, StrategyConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide as NtSide
    from nautilus_trader.model.enums import TimeInForce
    from nautilus_trader.model.identifiers import TraderId
    from nautilus_trader.model.objects import Money, Quantity
    from nautilus_trader.trading.strategy import Strategy

    class ScriptedConfig(StrategyConfig, frozen=True):
        pass

    class Scripted(Strategy):
        def __init__(self, config: ScriptedConfig) -> None:
            super().__init__(config)
            self.bars_seen = 0

        def on_start(self) -> None:
            self.subscribe_bars(nt_e2e.BAR_TYPE)

        def on_bar(self, bar) -> None:
            self.bars_seen += 1
            if self.bars_seen in plan:
                side, quantity = plan[self.bars_seen]
                self.submit_order(
                    self.order_factory.market(
                        nt_e2e.INSTRUMENT_ID,
                        NtSide.BUY if side == "BUY" else NtSide.SELL,
                        Quantity.from_int(quantity),
                        time_in_force=TimeInForce.GTC,
                    )
                )

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("ADV-001"),
            logging=LoggingConfig(log_level="ERROR", bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=nt_e2e.VENUE,
        oms_type=getattr(OmsType, oms),
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(reference.INITIAL_CASH, USD)],
        fee_model=FixedFeeModel(Money(reference.FEE, USD)),
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=1),
    )
    engine.add_instrument(nt_e2e._instrument())
    engine.add_data(nt_e2e._bars()[:30])
    engine.add_strategy(Scripted(ScriptedConfig()))
    engine.run()
    try:
        return _adapt(
            lambda: export_nautilustrader_engine(
                engine,
                nt_e2e.VENUE,
                tmp / "nautilus-export",
                run_id=f"nautilus-{oms.lower()}",
                base_currency=reference.CURRENCY,
            )
        )
    finally:
        engine.dispose()


def test_nautilustrader_hedging_position_snapshots_state_net_quantity(tmp_path):
    """HEDGING OMS: a long and a later short are two open positions.

    The account is net flat after the short (long 100 + short 100), but the
    bundle's position snapshot at the short's fill says -100: each
    positions-report row is booked as the instrument's net quantity at its own
    last update, so overlapping positions are never summed.
    """

    bundle = _nautilus_scripted_run(
        tmp_path, oms="HEDGING", plan={3: ("BUY", 100), 6: ("SELL", 100)}
    )
    if bundle is None:
        return
    fills = sorted(bundle.fills, key=lambda item: item.timestamp)
    assert [(item.side, item.quantity) for item in fills] == [
        (OrderSide.BUY, Decimal(100)),
        (OrderSide.SELL, Decimal(100)),
    ]
    stated = [(item.timestamp, item.quantity) for item in bundle.positions]
    truth = [
        (
            timestamp,
            sum(
                (_signed(fill) for fill in fills if fill.timestamp <= timestamp),
                Decimal(0),
            ),
        )
        for timestamp, _ in stated
    ]
    assert stated == truth
    assert stated[-1][1] == 0


# ---------------------------------------------------------------------------
# Backtrader 1.9.78.123
# ---------------------------------------------------------------------------


def _backtrader_run(
    tmp: Path,
    *,
    configure: Callable[[object], None] | None = None,
    feed_kwargs: dict | None = None,
    strategy: type | None = None,
    source_timezone: str = NEW_YORK,
    cerebro_tz: str | None = None,
    aware_index: bool = False,
):
    backtrader = pytest.importorskip("backtrader")
    from e2e import test_backtrader as bt_e2e

    local = reference.load_prices().copy()
    local.index = local.index.tz_convert(NEW_YORK)
    if not aware_index:
        local.index = local.index.tz_localize(None)
    cerebro = backtrader.Cerebro(stdstats=False, tz=cerebro_tz)
    cerebro.broker.setcash(float(reference.INITIAL_CASH))
    if configure is None:
        cerebro.broker.addcommissioninfo(bt_e2e.FixedFeePerOrder())
    else:
        configure(cerebro)
    cerebro.adddata(
        backtrader.feeds.PandasData(
            dataname=local, openinterest=None, **(feed_kwargs or {})
        ),
        name=reference.INSTRUMENT,
    )
    cerebro.addstrategy(strategy or bt_e2e.MovingAverageCross)
    cerebro.addanalyzer(
        create_backtrader_audit_analyzer(source_timezone=source_timezone),
        _name="integrity",
    )

    def run_and_export() -> Path:
        # The audit analyzer may refuse a broker setup while the run starts.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ran = cerebro.run()[0]
        return export_backtrader_analysis(
            ran.analyzers.integrity,
            tmp / "backtrader-export",
            run_id="backtrader-adversarial",
            base_currency=reference.CURRENCY,
        )

    return _adapt(run_and_export)


@pytest.mark.parametrize(
    ("feed_kwargs", "cerebro_tz", "aware_index"),
    [
        ({"tzinput": NEW_YORK, "tz": NEW_YORK}, None, False),
        ({}, NEW_YORK, False),
        ({}, None, True),
    ],
    ids=["feed-tz", "cerebro-tz", "tz-aware-index"],
)
def test_backtrader_timezone_settings_keep_every_row_on_the_bar_clock(
    tmp_path, feed_kwargs, cerebro_tz, aware_index
):
    """New York bars, analyzer told ``source_timezone="America/New_York"``.

    * feed ``tzinput``/``tz`` = New York: fills are read through the feed
      (``data.num2date``, New York) but position/cash/equity rows and order
      ``last_updated_at`` through the strategy clock, whose zone is Cerebro's
      (none: Backtrader's stored UTC). New York is attached to a UTC wall
      time: every snapshot lands 4-5 hours late (2024-01-03T02:00Z for the
      2024-01-02T21:00Z close), and no fill bar has a position row;
    * ``Cerebro(tz=New York)``: the strategy clock now converts the stored
      New York wall time as if it were UTC; snapshots land 4-5 hours early
      (16:00Z);
    * a tz-aware New York pandas index: Backtrader stores it in UTC, and the
      analyzer attaches New York to that, so fills, orders and snapshots are
      all 4-5 hours late (the 2024-03-25T20:00Z fill becomes 2024-03-26T00:00Z).
    """

    bundle = _backtrader_run(
        tmp_path,
        feed_kwargs=feed_kwargs,
        cerebro_tz=cerebro_tz,
        aware_index=aware_index,
    )
    # The fix maps this run; a refusal here would be a regression, not a pass
    # (W5-J1 adversarial finding 3).
    assert bundle is not None
    bars = _bar_instants()
    assert {pd.Timestamp(item.timestamp) for item in bundle.fills} <= bars
    assert {pd.Timestamp(item.timestamp) for item in bundle.equity} <= bars
    assert {pd.Timestamp(item.timestamp) for item in bundle.positions} <= bars


def test_backtrader_short_borrow_interest_is_not_booked_as_commission(tmp_path):
    """``interest=0.10``: Backtrader's standard short-borrow charge.

    BackBroker debits the interest from cash every day the short is held and,
    with the default ``int2pnl=True``, also adds the accumulated amount to the
    closing execution's ``comm``. The bundle books it as a $75.10 commission on
    the buy-to-cover fill, while the commission was $1 and the interest had
    already been paid day by day.
    """

    from e2e import test_backtrader as bt_e2e

    class FeeWithShortInterest(bt_e2e.FixedFeePerOrder):
        params = (("interest", 0.10),)

    bundle = _backtrader_run(
        tmp_path,
        configure=lambda cerebro: cerebro.broker.addcommissioninfo(
            FeeWithShortInterest()
        ),
    )
    # The fix maps this run; a refusal here would be a regression, not a pass
    # (W5-J1 adversarial finding 3).
    assert bundle is not None
    commissions = [
        item.pnl_impact
        for item in bundle.costs
        if item.cost_type is CostType.COMMISSION
    ]
    assert len(commissions) == len(bundle.fills)
    assert set(commissions) == {-reference.FEE}


def test_backtrader_shortcash_false_still_credits_short_sale_proceeds(tmp_path):
    """``broker.set_shortcash(False)``, a standard BackBroker option.

    Backtrader then debits the short's market value from ``getcash()`` instead
    of crediting the sale proceeds. The bundle reports that as cash: 90,156
    during the short, where the account holds 109,474 (reference ledger), and
    its own equity rows stop adding up (cash + net exposure != total equity).
    """

    from e2e import test_backtrader as bt_e2e

    def configure(cerebro) -> None:
        cerebro.broker.set_shortcash(False)
        cerebro.broker.addcommissioninfo(bt_e2e.FixedFeePerOrder())

    bundle = _backtrader_run(tmp_path, configure=configure)
    if bundle is None:
        return
    ledger = reference.expected_run().ledger
    short_bars = [item.timestamp for item in bundle.positions if item.quantity < 0]
    assert short_bars
    for point in bundle.equity:
        assert abs(point.cash + point.net_exposure - point.total_equity) < Decimal(
            "0.000001"
        )
    for point in bundle.equity:
        if point.timestamp in short_bars:
            assert point.cash == ledger.loc[pd.Timestamp(point.timestamp), "cash"]


def test_backtrader_futures_position_value_uses_the_contract_multiplier(tmp_path):
    """``setcommission(margin=2000, mult=50)``: a futures-style instrument.

    One contract at 91.13 is 4,556.50 of notional, but the analyzer values
    positions as ``size * close`` and reports market value and net/gross
    exposure of 91.13, ignoring the multiplier BackBroker itself uses.
    """

    backtrader = pytest.importorskip("backtrader")

    class LongThenShortOneContract(backtrader.Strategy):
        def next(self) -> None:
            if len(self) == 60:
                self.buy(size=1)
            elif len(self) == 80:
                self.sell(size=2)

    bundle = _backtrader_run(
        tmp_path,
        configure=lambda cerebro: cerebro.broker.setcommission(
            commission=1.0, margin=2000.0, mult=50.0
        ),
        strategy=LongThenShortOneContract,
    )
    # The fix maps this run; a refusal here would be a regression, not a pass
    # (W5-J1 adversarial finding 3).
    assert bundle is not None
    held = [item for item in bundle.positions if item.quantity != 0]
    assert {item.quantity for item in held} == {Decimal(1), Decimal(-1)}
    for position in held:
        notional = position.quantity * position.market_price * 50
        assert abs(position.market_value - notional) < Decimal("0.000001")


# ---------------------------------------------------------------------------
# bt 1.2.0
# ---------------------------------------------------------------------------


def test_bt_same_bar_close_and_reopen_keeps_every_fill(tmp_path):
    """``target.flatten()`` then a re-buy on the same bar: two real executions.

    bt charges both ($2 fee on the bar), but ``Result.get_transactions`` is
    the day-over-day position difference, so the sell and the re-buy net to
    nothing and the bundle has fees on bars with no fill at all (4 of 6 fills
    dropped).
    """

    bt = pytest.importorskip("bt")

    class CloseThenReopen(bt.Algo):
        def __call__(self, target) -> bool:
            bar = len(target.universe)
            if bar == 3:
                target.transact(100, child=reference.INSTRUMENT)
            elif bar in (6, 7):
                target.flatten()
                target.transact(100, child=reference.INSTRUMENT)
            elif bar == 10:
                target.transact(-200, child=reference.INSTRUMENT)
            return True

    prices = (
        reference.load_prices()[["close"]]
        .rename(columns={"close": reference.INSTRUMENT})
        .iloc[:15]
    )
    strategy = bt.Strategy(
        "close_reopen", [CloseThenReopen()], children=[reference.INSTRUMENT]
    )
    backtest = bt.Backtest(
        strategy,
        prices,
        initial_capital=float(reference.INITIAL_CASH),
        commissions=lambda quantity, price: float(reference.FEE),
        integer_positions=True,
        progress_bar=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = bt.run(backtest)
        bundle = _adapt(
            lambda: export_bt_result(
                result,
                tmp_path / "bt-export",
                run_id="bt-close-reopen",
                base_currency=reference.CURRENCY,
            )
        )
    if bundle is None:
        return
    fee_bars = {item.timestamp for item in bundle.costs}
    fill_bars = {item.timestamp for item in bundle.fills}
    assert fee_bars <= fill_bars
    assert len(bundle.fills) == 6


def test_bt_same_bar_partial_offset_keeps_every_fill(tmp_path):
    """Sell 100 then buy 150 on one bar: two executions, two $1 fees.

    ``Result.get_transactions`` reports their net, one buy of 50, so the
    bundle would state one fill where two happened (W3-J12 follow-up to the
    close-and-reopen case above; a refusal also passes).
    """

    bt = pytest.importorskip("bt")

    class PartialOffset(bt.Algo):
        def __call__(self, target) -> bool:
            bar = len(target.universe)
            if bar == 3:
                target.transact(100, child=reference.INSTRUMENT)
            elif bar == 6:
                target.transact(-100, child=reference.INSTRUMENT)
                target.transact(150, child=reference.INSTRUMENT)
            elif bar == 10:
                target.transact(-150, child=reference.INSTRUMENT)
            return True

    prices = (
        reference.load_prices()[["close"]]
        .rename(columns={"close": reference.INSTRUMENT})
        .iloc[:15]
    )
    strategy = bt.Strategy(
        "partial_offset", [PartialOffset()], children=[reference.INSTRUMENT]
    )
    backtest = bt.Backtest(
        strategy,
        prices,
        initial_capital=float(reference.INITIAL_CASH),
        commissions=lambda quantity, price: float(reference.FEE),
        integer_positions=True,
        progress_bar=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = bt.run(backtest)
        bundle = _adapt(
            lambda: export_bt_result(
                result,
                tmp_path / "bt-export",
                run_id="bt-partial-offset",
                base_currency=reference.CURRENCY,
            )
        )
    if bundle is None:
        return
    assert len(bundle.fills) == 4


def test_bt_position_value_uses_the_security_multiplier(tmp_path):
    """``bt.Security(name, multiplier=50)``: bt's futures-style security.

    bt values 2 contracts at 100.99 as 10,099 (strategy value 99,999 = cash
    89,900 + 10,099), but the exporter values positions as ``quantity *
    price``: the bundle states market value and net exposure of 201.98, and
    its own equity row no longer adds up.
    """

    bt = pytest.importorskip("bt")

    class BuyTwoContracts(bt.Algo):
        def __call__(self, target) -> bool:
            if len(target.universe) == 3:
                target.transact(2, child=reference.INSTRUMENT)
            return True

    prices = (
        reference.load_prices()[["close"]]
        .rename(columns={"close": reference.INSTRUMENT})
        .iloc[:8]
    )
    strategy = bt.Strategy(
        "contracts",
        [BuyTwoContracts()],
        children=[bt.Security(reference.INSTRUMENT, multiplier=50)],
    )
    backtest = bt.Backtest(
        strategy,
        prices,
        initial_capital=float(reference.INITIAL_CASH),
        commissions=lambda quantity, price: float(reference.FEE),
        progress_bar=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = bt.run(backtest)
        bundle = _adapt(
            lambda: export_bt_result(
                result,
                tmp_path / "bt-export",
                run_id="bt-multiplier",
                base_currency=reference.CURRENCY,
            )
        )
    # The fix maps this run; a refusal here would be a regression, not a pass
    # (W5-J1 adversarial finding 3).
    assert bundle is not None
    held = [item for item in bundle.positions if item.quantity != 0]
    assert held
    for position in held:
        notional = position.quantity * position.market_price * 50
        assert abs(position.market_value - notional) < Decimal("0.000001")
    for point in bundle.equity:
        assert abs(point.cash + point.net_exposure - point.total_equity) < Decimal(
            "0.000001"
        )


# ---------------------------------------------------------------------------
# QuantConnect LEAN 2.5.17999
# ---------------------------------------------------------------------------


def _lean_bundle(tmp: Path, *, edit_events: Callable[[list], None] | None = None):
    result = json.loads((LEAN_DATA / f"{LEAN_ALGORITHM}.json").read_text("utf-8"))
    events = json.loads(
        (LEAN_DATA / f"{LEAN_ALGORITHM}-order-events.json").read_text("utf-8")
    )
    if edit_events is not None:
        edit_events(events)
    result_path = tmp / "result.json"
    events_path = tmp / "order-events.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    events_path.write_text(json.dumps(events), encoding="utf-8")
    return _adapt(
        lambda: export_quantconnect_lean_results(
            result_path,
            events_path,
            tmp / "lean-export",
            run_id="lean-adversarial",
            base_currency=reference.CURRENCY,
            engine_version="2.5.17999",
        )
    )


def test_quantconnect_lean_fee_rebate_keeps_its_sign(tmp_path):
    """A custom fee model paying a $0.35 rebate on order 1's fill.

    LEAN serializes ``OrderFee.Value.Amount`` unchanged (SerializedOrderEvent)
    and credits the cash book with it (OrderFee.ApplyToPortfolio subtracts the
    amount). The exporter takes ``abs()`` of the amount, so the bundle books a
    $0.35 charge where the account received $0.35.
    """

    def rebate(events: list) -> None:
        fill = next(
            item for item in events if item["orderId"] == 1 and item["fillQuantity"]
        )
        fill["orderFeeAmount"] = -0.35

    bundle = _lean_bundle(tmp_path, edit_events=rebate)
    # The fix maps this run; a refusal here would be a regression, not a pass
    # (W5-J1 adversarial finding 3).
    assert bundle is not None
    fill = next(item for item in bundle.fills if item.order_id == "lean-order-1")
    costs = [item for item in bundle.costs if item.fill_id == fill.fill_id]
    assert [item.pnl_impact for item in costs] == [Decimal("0.35")]


def test_quantconnect_lean_filled_order_is_not_last_updated_before_its_fill(
    tmp_path,
):
    """LEAN's own lag=1 files, unmodified.

    A MarketOnClose order is created at 19:40Z and filled at 20:00Z. LEAN
    writes ``lastFillTime`` (and no ``lastUpdateTime`` for an order never
    updated), the exporter reads only ``lastUpdateTime``, and the mapper falls
    back to the creation time: every filled order is stated as last updated
    20 minutes before its own fill.
    """

    bundle = _lean_bundle(tmp_path)
    # The fix maps this run; a refusal here would be a regression, not a pass
    # (W5-J1 adversarial finding 3).
    assert bundle is not None
    last_fill: dict[str, object] = {}
    for fill in bundle.fills:
        last_fill[fill.order_id] = max(
            last_fill.get(fill.order_id, fill.timestamp), fill.timestamp
        )
    filled = [item for item in bundle.orders if item.status is OrderStatus.FILLED]
    assert filled
    for order in filled:
        assert order.last_updated_at >= last_fill[order.order_id]
