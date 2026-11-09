"""End to end: the toy strategy in NautilusTrader 1.231.0 through the shipped adapter.

A low-level ``BacktestEngine`` runs a native ``Strategy``: Nautilus's own
``SimpleMovingAverage`` indicators are registered for the daily bars, and the
strategy submits a market order for the position delta. The venue is a
NETTING/MARGIN venue (a CASH account denies the short sale) with
``FixedFeeModel`` charging $1.00 once per order and no slippage. A market order
submitted in ``on_bar`` fills at that bar's close, stamped with the bar's
timestamp, which is the specification's convention.

The completed engine is exported with ``export_nautilustrader_engine``, mapped
with the D3 service and checked against ``reference.py``.

The D3 Nautilus bundle has no equity or return level, so:

* the end value is the final account balance (the strategy ends flat);
* the cash level is a MARGIN account balance, which does not debit the
  notional of an open position. The comparable reference quantity is the
  realized balance (initial cash - fees + gross P&L of closed round trips),
  computed below from the reference trade list alone;
* the position level is not compared: the mapper derives one quantity per
  positions-report row at its last update, so a strategy whose round trips
  all close yields only zero-quantity snapshots at the exits
  (``test_position_evidence_is_round_trip_closes_only``);
* a one-bar look-ahead shifts every fill, cost, trade and balance row by one
  bar, so the semantic alignment can only report them one-sided. That is an
  evidence gap, never an adverse divergence.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    CashArtifacts,
    CashBalance,
    ComparisonLevel,
    build_v1_5d3_service,
    export_nautilustrader_engine,
)

from e2e import harness, reference

pytest.importorskip("nautilus_trader")

from nautilus_trader.backtest.config import BacktestEngineConfig  # noqa: E402
from nautilus_trader.backtest.engine import BacktestEngine  # noqa: E402
from nautilus_trader.backtest.models import FillModel, FixedFeeModel  # noqa: E402
from nautilus_trader.config import LoggingConfig, StrategyConfig  # noqa: E402
from nautilus_trader.indicators import SimpleMovingAverage  # noqa: E402
from nautilus_trader.model.currencies import USD  # noqa: E402
from nautilus_trader.model.data import Bar, BarType  # noqa: E402
from nautilus_trader.model.enums import (  # noqa: E402
    AccountType,
    OmsType,
    OrderSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import (  # noqa: E402
    InstrumentId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.instruments import Equity  # noqa: E402
from nautilus_trader.model.objects import Money, Price, Quantity  # noqa: E402
from nautilus_trader.trading.strategy import Strategy  # noqa: E402

ENGINE_VERSION = "1.231.0"
VENUE = Venue("SIM")
INSTRUMENT_ID = InstrumentId(Symbol(reference.INSTRUMENT), VENUE)
BUNDLE_INSTRUMENT = str(INSTRUMENT_ID)
BAR_TYPE = BarType.from_str(f"{INSTRUMENT_ID}-1-DAY-LAST-EXTERNAL")
LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.TRADE,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
)


def _instrument() -> Equity:
    return Equity(
        instrument_id=INSTRUMENT_ID,
        raw_symbol=Symbol(reference.INSTRUMENT),
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        lot_size=Quantity.from_int(1),
        ts_event=0,
        ts_init=0,
    )


def _bars() -> list[Bar]:
    bars = []
    for timestamp, row in reference.load_prices().iterrows():
        nanoseconds = timestamp.value
        bars.append(
            Bar(
                BAR_TYPE,
                Price.from_str(f"{row.open:.2f}"),
                Price.from_str(f"{row.high:.2f}"),
                Price.from_str(f"{row.low:.2f}"),
                Price.from_str(f"{row.close:.2f}"),
                Quantity.from_int(int(row.volume)),
                nanoseconds,
                nanoseconds,
            )
        )
    return bars


class MovingAverageCrossConfig(StrategyConfig, frozen=True):
    lag: int = reference.EXECUTION_LAG_BARS


class MovingAverageCross(Strategy):
    """The toy strategy the Nautilus way; ``lag=0`` is the look-ahead bug."""

    def __init__(self, config: MovingAverageCrossConfig) -> None:
        super().__init__(config)
        self.fast = SimpleMovingAverage(reference.FAST)
        self.slow = SimpleMovingAverage(reference.SLOW)
        self.lag = config.lag
        self.previous_signal = 0

    def on_start(self) -> None:
        self.register_indicator_for_bars(BAR_TYPE, self.fast)
        self.register_indicator_for_bars(BAR_TYPE, self.slow)
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar: Bar) -> None:
        ready = self.fast.initialized and self.slow.initialized
        long_signal = 1 if ready and self.fast.value > self.slow.value else 0
        session = (
            pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")
            .tz_convert(reference.EXCHANGE_TIMEZONE)
            .normalize()
            .tz_localize(None)
        )
        in_short = (
            reference.SHORT_FIRST_SIGNAL_SESSION
            <= session
            <= reference.SHORT_LAST_SIGNAL_SESSION
        )
        signal = -1 if in_short else long_signal
        acting = signal if self.lag == 0 else self.previous_signal
        self.previous_signal = signal
        delta = acting * reference.QUANTITY - int(
            self.portfolio.net_position(INSTRUMENT_ID)
        )
        if delta:
            self.submit_order(
                self.order_factory.market(
                    INSTRUMENT_ID,
                    OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    Quantity.from_int(abs(delta)),
                    time_in_force=TimeInForce.GTC,
                )
            )


def run_nautilus(*, lag: int) -> BacktestEngine:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("E2E-001"),
            logging=LoggingConfig(log_level="ERROR", bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(reference.INITIAL_CASH, USD)],
        fee_model=FixedFeeModel(Money(reference.FEE, USD)),
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=1),
    )
    engine.add_instrument(_instrument())
    engine.add_data(_bars())
    engine.add_strategy(MovingAverageCross(MovingAverageCrossConfig(lag=lag)))
    engine.run()
    return engine


def mapped_bundle(tmp, *, lag: int):
    import nautilus_trader

    assert nautilus_trader.__version__ == ENGINE_VERSION
    engine = run_nautilus(lag=lag)
    try:
        exported = export_nautilustrader_engine(
            engine,
            VENUE,
            tmp / "nautilus-export",
            run_id=f"nautilustrader-lag{lag}",
            base_currency=reference.CURRENCY,
        )
    finally:
        engine.dispose()
    result = build_v1_5d3_service().adapt(exported)
    bundle = harness.write_and_validate(
        result.artifacts, tmp / "bundle", "nautilustrader"
    )
    return result, bundle


def margin_reference(*, lag: int = reference.EXECUTION_LAG_BARS):
    """Reference artifacts whose cash level is a futures-style margin balance.

    The balance starts at the initial cash on the first bar and changes only at
    fills: minus the fee, plus the gross P&L of the round trip the fill closes.
    Everything comes from ``reference.expected_run``.
    """

    artifacts = harness.reference_artifacts(lag=lag)
    run = reference.expected_run(lag=lag)
    gross_by_close = dict(zip(run.trades["closed_at"], run.trades["gross_pnl"]))
    balance = reference.INITIAL_CASH
    rows = [CashBalance(_utc(run.ledger.index[0]), reference.CURRENCY, balance)]
    for fill in run.fills.itertuples(index=False):
        balance = balance - fill.fee + gross_by_close.get(fill.timestamp, Decimal(0))
        rows.append(CashBalance(_utc(fill.timestamp), reference.CURRENCY, balance))
    return dataclasses.replace(artifacts, cash=CashArtifacts(balances=tuple(rows)))


def _utc(value: pd.Timestamp) -> datetime:
    return value.tz_convert("UTC").to_pydatetime()


@pytest.fixture(scope="module")
def correct(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("nautilus-correct"), lag=1)


@pytest.fixture(scope="module")
def lookahead(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("nautilus-lookahead"), lag=0)


@pytest.fixture(scope="module")
def expected():
    return reference.expected_run()


def test_bundle_validates_against_schema_1_0(correct) -> None:
    result, bundle = correct
    assert bundle.run.engine_version == ENGINE_VERSION
    assert bundle.available_levels == (
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
        ComparisonLevel.TRADE,
        ComparisonLevel.POSITION,
        ComparisonLevel.CASH,
        ComparisonLevel.COST,
    )
    assert tuple(item.code for item in result.warnings) == (
        "nautilustrader.position_fill_links_unavailable",
        "nautilustrader.position_snapshots_quantity_only",
    )


def test_fills_match_reference(correct, expected) -> None:
    harness.assert_fills_match(correct[1], expected, instrument_id=BUNDLE_INSTRUMENT)


def test_fees_match_reference(correct, expected) -> None:
    harness.assert_costs_match(correct[1], expected)


def test_round_trips_match_reference(correct, expected) -> None:
    # Nautilus's realized P&L is net of the entry and exit commissions.
    harness.assert_trades_match(
        correct[1], expected, pnl="net_pnl", instrument_id=BUNDLE_INSTRUMENT
    )


def test_final_equity_matches_reference(correct, expected) -> None:
    harness.assert_final_cash(correct[1], expected)


def test_margin_balances_match_reference_realized_balance(correct) -> None:
    expected_rows = margin_reference().cash.balances
    actual = correct[1].cash.balances
    assert [(item.timestamp, item.total) for item in actual] == [
        (item.timestamp, item.total) for item in expected_rows
    ]


def test_position_evidence_is_round_trip_closes_only(correct, expected) -> None:
    positions = correct[1].positions
    assert [(item.timestamp, item.quantity) for item in positions] == [
        (_utc(closed), Decimal(0)) for closed in expected.trades["closed_at"]
    ]


def test_implementation_risk_names_no_defect(correct, tmp_path) -> None:
    run = harness.implementation_risk(
        margin_reference(),
        correct[1],
        LEVELS,
        report_path=tmp_path / "nautilustrader-correct.json",
    )
    harness.assert_no_implementation_defect(run)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "E01 nautilus_trader 1.231.0: the D3 bundle has no fixed-grid level (no "
        "equity or return; cash rows only at account events), so a one-bar "
        "shift makes every fill, cost, trade and balance row one-sided: "
        "evidence_gap findings, no adverse divergence"
    ),
)
def test_lookahead_defect_is_flagged(lookahead, tmp_path) -> None:
    run = harness.implementation_risk(
        margin_reference(),
        lookahead[1],
        LEVELS,
        report_path=tmp_path / "nautilustrader-lookahead.json",
    )
    harness.assert_defect_flagged(run)


def test_lookahead_defect_is_visible_as_one_sided_evidence(lookahead, expected) -> None:
    run = harness.implementation_risk(margin_reference(), lookahead[1], LEVELS)
    fills = Counter(
        item.status.value for item in run.level(ComparisonLevel.FILL).records
    )
    assert fills == Counter({"reference_only": 10, "candidate_only": 10})
    assert "IMPLEMENTATION_FAMILY_EVIDENCE_IMPAIRED" in run.codes(
        harness.ImplementationRiskFindingKind.EVIDENCE_GAP
    )
    assert run.result.assessment.candidates[0].implementation_risk_score is None
    final = harness.assert_final_cash(lookahead[1], reference.expected_run(lag=0))
    assert final != expected.final_equity
