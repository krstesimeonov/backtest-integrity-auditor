"""End to end: the toy strategy in Backtrader 1.9.78.123 through the shipped adapter.

Backtrader computes the moving averages (``bt.indicators.SMA``) inside a
``Strategy``. The specification's one-bar execution lag is Backtrader's own
market-on-close order: an order sent with ``exectype=Order.Close`` in
``next()`` on bar t fills at the close of bar t+1. The injected look-ahead
defect reads the signal one bar ahead (``self.fast[1]``), which Backtrader's
default preloaded ``runonce`` mode lets a strategy do silently.

Bars are fed as naive New York local times (16:00) and the audit analyzer is
told ``source_timezone="America/New_York"``, so the exporter's DST conversion
is exercised: the bundle must carry 20:00Z in summer and 21:00Z in winter.

A second path runs the same strategy with ``broker.set_coc(True)`` (cheat on
close: a market order fills at the close of the bar that sent it, so the
strategy acts on the previous bar's signal). That broker mode exposes two
exporter problems; see the ``cheat_on_close`` tests.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    OrderStatus,
    OrderType,
    build_v1_5d2_service,
    create_backtrader_audit_analyzer,
    export_backtrader_analysis,
)

from e2e import harness, reference

backtrader = pytest.importorskip("backtrader")

ENGINE_VERSION = "1.9.78.123"
# Backtrader exports no trade level (docs/V1_5D2_CONCRETE_ENGINE_ADAPTERS.md).
LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)


class FixedFeePerOrder(backtrader.CommInfoBase):
    """A flat fee per execution, whatever the size or price."""

    params = (
        ("stocklike", True),
        ("commtype", backtrader.CommInfoBase.COMM_FIXED),
        ("commission", float(reference.FEE)),
    )

    def _getcommission(self, size, price, pseudoexec):
        return float(reference.FEE)


class MovingAverageCross(backtrader.Strategy):
    """Long while SMA20 > SMA50, short in the scheduled window, else flat.

    ``peek=0`` is the specification. ``peek=1`` is the injected look-ahead
    defect: the target comes from the next bar's averages and session.
    ``cheat_on_close=True`` sends plain market orders for the previous bar's
    signal and relies on ``broker.set_coc(True)`` to fill them at this close.
    """

    params = (("peek", 0), ("cheat_on_close", False))

    def __init__(self) -> None:
        self.fast = backtrader.indicators.SMA(self.data.close, period=reference.FAST)
        self.slow = backtrader.indicators.SMA(self.data.close, period=reference.SLOW)
        self.signals: list[int] = []

    def _signal(self, ago: int) -> int:
        session = pd.Timestamp(self.data.datetime.date(ago))
        if (
            reference.SHORT_FIRST_SIGNAL_SESSION
            <= session
            <= reference.SHORT_LAST_SIGNAL_SESSION
        ):
            return -1
        return 1 if self.fast[ago] > self.slow[ago] else 0

    def prenext(self) -> None:
        self.next()

    def next(self) -> None:
        self.signals.append(self._signal(0))
        if self.p.cheat_on_close:
            previous = self.signals[-2] if len(self.signals) > 1 else 0
            self.order_target_size(target=previous * reference.QUANTITY)
            return
        if self.p.peek and len(self.data) < self.data.buflen():
            signal = self._signal(self.p.peek)
        else:
            signal = self.signals[-1]
        self.order_target_size(
            target=signal * reference.QUANTITY,
            exectype=backtrader.Order.Close,
        )


def run_backtrader(*, peek: int = 0, cheat_on_close: bool = False):
    prices = reference.load_prices()
    local = prices.copy()
    local.index = local.index.tz_convert(reference.EXCHANGE_TIMEZONE).tz_localize(None)
    cerebro = backtrader.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(reference.INITIAL_CASH))
    cerebro.broker.set_coc(cheat_on_close)
    cerebro.broker.addcommissioninfo(FixedFeePerOrder())
    cerebro.adddata(
        backtrader.feeds.PandasData(dataname=local, openinterest=None),
        name=reference.INSTRUMENT,
    )
    cerebro.addstrategy(MovingAverageCross, peek=peek, cheat_on_close=cheat_on_close)
    cerebro.addanalyzer(
        create_backtrader_audit_analyzer(source_timezone=reference.EXCHANGE_TIMEZONE),
        _name="integrity",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return cerebro.run()[0]


def mapped_bundle(tmp: Path, *, peek: int = 0, cheat_on_close: bool = False):
    assert backtrader.__version__ == ENGINE_VERSION
    strategy = run_backtrader(peek=peek, cheat_on_close=cheat_on_close)
    exported = export_backtrader_analysis(
        strategy.analyzers.integrity,
        tmp / "backtrader-export",
        run_id=f"backtrader-peek{peek}{'-coc' if cheat_on_close else ''}",
        base_currency=reference.CURRENCY,
    )
    result = build_v1_5d2_service().adapt(exported)
    bundle = harness.write_and_validate(result.artifacts, tmp / "bundle", "backtrader")
    return result, bundle


@pytest.fixture(scope="module")
def correct(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("backtrader-correct"))


@pytest.fixture(scope="module")
def lookahead(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("backtrader-lookahead"), peek=1)


@pytest.fixture(scope="module")
def expected():
    return reference.expected_run()


def test_bundle_validates_against_schema_1_0(correct) -> None:
    result, bundle = correct
    assert bundle.run.engine_version == ENGINE_VERSION
    assert set(LEVELS) <= set(bundle.available_levels)
    assert ComparisonLevel.TRADE not in bundle.available_levels
    assert result.warnings == ()


def test_orders_are_market_on_close_sent_one_bar_before_the_fill(
    correct, expected
) -> None:
    bundle = correct[1]
    orders = sorted(bundle.orders or (), key=lambda item: item.created_at)
    fills = {item.order_id: item for item in bundle.fills or ()}
    bars = list(expected.ledger.index)
    assert len(orders) == len(expected.fills)
    for order in orders:
        assert order.order_type is OrderType.MARKET_ON_CLOSE
        assert order.status is OrderStatus.FILLED
        fill = fills[order.order_id]
        created = bars.index(pd.Timestamp(order.created_at))
        assert pd.Timestamp(fill.timestamp) == bars[created + 1]


def test_fills_match_reference(correct, expected) -> None:
    harness.assert_fills_match(correct[1], expected)


def test_fees_match_reference(correct, expected) -> None:
    harness.assert_costs_match(correct[1], expected)


def test_round_trips_match_reference(correct, expected) -> None:
    # No trade level in this adapter (by design): pair the fills instead.
    harness.assert_fills_imply_round_trips(correct[1], expected)


def test_final_equity_matches_reference(correct, expected) -> None:
    harness.assert_final_equity(correct[1], expected)


def test_implementation_risk_names_no_defect(correct, tmp_path) -> None:
    run = harness.implementation_risk(
        harness.reference_artifacts(),
        correct[1],
        LEVELS,
        report_path=tmp_path / "backtrader-correct.json",
    )
    harness.assert_no_implementation_defect(run)


def test_lookahead_defect_is_flagged(lookahead, tmp_path) -> None:
    run = harness.implementation_risk(
        harness.reference_artifacts(),
        lookahead[1],
        LEVELS,
        report_path=tmp_path / "backtrader-lookahead.json",
    )
    harness.assert_defect_flagged(run)
    assert {"accounting", "return", "sizing"} <= run.adverse_families()


def test_lookahead_run_matches_the_shifted_reference(lookahead) -> None:
    """The defect run is exactly the reference with the signal one bar early."""

    shifted = reference.expected_run(lag=0)
    harness.assert_fills_match(lookahead[1], shifted)
    harness.assert_final_equity(lookahead[1], shifted)


# ---------------------------------------------------------------------------
# Cheat-on-close broker mode
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cheat_on_close(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("backtrader-coc"), cheat_on_close=True)


def test_cheat_on_close_run_maps_and_matches_fills(cheat_on_close, expected) -> None:
    """Backtrader books a coc fill at the close of the bar that sent the order.

    BackBroker submits an order inside the ``next()`` that creates it, but the
    analyzer only hears of it when notifications are delivered at the start of
    the next cycle. The submission time must therefore come from the order's
    creation bar, not from the notification cycle; otherwise every coc fill is
    earlier than its order's submission and the mapper rejects the export.
    """

    result, bundle = cheat_on_close
    assert result.warnings == ()
    harness.assert_fills_match(bundle, expected)
    harness.assert_costs_match(bundle, expected)
    harness.assert_final_equity(bundle, expected)
    for order in bundle.orders or ():
        assert order.submitted_at == order.created_at


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "E02 backtrader 1.9.78.123: with broker.set_coc(True) the fill is dated at "
        "bar t (the close it executes at) but BackBroker books it in the next "
        "cycle, after the audit analyzer has already recorded bar t's position, "
        "cash and value in next(); the bundle's position/cash/equity at every "
        "fill bar are therefore the pre-fill state (position off by 100 shares, "
        "cash by price*100+fee, equity by the $1 fee). Fixing it needs the "
        "exporter to re-date coc executions into the previous snapshot or to "
        "refuse coc runs; see tests/e2e/MATRIX.md"
    ),
)
def test_cheat_on_close_snapshots_include_same_bar_fills(
    cheat_on_close, tmp_path
) -> None:
    run = harness.implementation_risk(
        harness.reference_artifacts(),
        cheat_on_close[1],
        LEVELS,
        report_path=tmp_path / "backtrader-coc.json",
    )
    harness.assert_no_implementation_defect(run)
