"""End to end: the toy strategy in bt 1.2.0 through the shipped adapter.

A bt ``Algo`` computes both moving averages from ``target.universe`` (the data
bt has revealed up to ``target.now``) and transacts the share difference at
bt's price for the day, the close. Commission is bt's ``commissions``
callable. The result is exported with ``export_bt_result``, mapped with the D2
service, and checked against ``reference.py``.

bt prepends a virtual row one calendar day before the first bar to hold the
initial capital (``bt.backtest.Backtest``), and the adapter maps it to a
position, cash and equity observation. The reference bundle carries the same
initial-capital observation (``reference_artifacts(prestart=...)``) so that row
is compared, not ignored.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    build_v1_5d2_service,
    export_bt_result,
)

from e2e import harness, reference

bt = pytest.importorskip("bt")

ENGINE_VERSION = "1.2.0"
LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)
PRESTART = reference.load_prices().index[0] - pd.DateOffset(days=1)


class MovingAverageCrossWithShortWindow(bt.Algo):
    """Holds 100 × signal shares, the signal lagged ``lag`` bars."""

    def __init__(self, lag: int) -> None:
        super().__init__()
        self.lag = lag

    def __call__(self, target) -> bool:
        closes = target.universe[reference.INSTRUMENT].dropna()
        if len(closes) <= self.lag:
            return True
        seen = closes.iloc[: len(closes) - self.lag]
        fast = seen.rolling(reference.FAST).mean().iloc[-1]
        slow = seen.rolling(reference.SLOW).mean().iloc[-1]
        signal = 1 if fast > slow else 0
        session = seen.index[-1].tz_convert(reference.EXCHANGE_TIMEZONE)
        session = session.normalize().tz_localize(None)
        if (
            reference.SHORT_FIRST_SIGNAL_SESSION
            <= session
            <= reference.SHORT_LAST_SIGNAL_SESSION
        ):
            signal = -1
        wanted = reference.QUANTITY * signal
        held = 0.0
        if reference.INSTRUMENT in target.children:
            held = target.children[reference.INSTRUMENT].position
        if wanted != held:
            target.transact(wanted - held, child=reference.INSTRUMENT)
        return True


def run_bt(*, lag: int):
    prices = reference.load_prices()[["close"]].rename(
        columns={"close": reference.INSTRUMENT}
    )
    strategy = bt.Strategy(
        "ma_cross",
        [MovingAverageCrossWithShortWindow(lag)],
        children=[reference.INSTRUMENT],
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
        return bt.run(backtest)


def mapped_bundle(tmp: Path, *, lag: int):
    assert bt.__version__ == ENGINE_VERSION
    result = run_bt(lag=lag)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        exported = export_bt_result(
            result,
            tmp / "bt-export",
            run_id=f"bt-lag{lag}",
            base_currency=reference.CURRENCY,
        )
    mapped = build_v1_5d2_service().adapt(exported)
    bundle = harness.write_and_validate(mapped.artifacts, tmp / "bundle", "bt")
    return mapped, bundle


@pytest.fixture(scope="module")
def correct(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("bt-correct"), lag=1)


@pytest.fixture(scope="module")
def lookahead(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("bt-lookahead"), lag=0)


@pytest.fixture(scope="module")
def expected():
    return reference.expected_run()


def test_bundle_validates_against_schema_1_0(correct) -> None:
    mapped, bundle = correct
    assert bundle.run.engine_version == ENGINE_VERSION
    assert set(LEVELS) <= set(bundle.available_levels)
    assert bundle.trades is None
    assert tuple(item.code for item in mapped.warnings) == (
        "bt.aggregate_fees_unlinked",
        "bt.transactions_reconstructed_orders",
    )


def test_fills_match_reference(correct, expected) -> None:
    harness.assert_fills_match(correct[1], expected)


def test_fees_match_reference(correct, expected) -> None:
    harness.assert_costs_match(correct[1], expected, linked_to_fills=False)


def test_round_trips_match_reference(correct, expected) -> None:
    # No trade level in this adapter (by design): pair the fills instead.
    harness.assert_fills_imply_round_trips(correct[1], expected)


def test_final_equity_matches_reference(correct, expected) -> None:
    harness.assert_final_equity(correct[1], expected)


def test_prestart_row_is_the_initial_capital(correct) -> None:
    bundle = correct[1]
    first = min(bundle.equity or (), key=lambda item: item.timestamp)
    assert first.timestamp == PRESTART.to_pydatetime()
    assert first.total_equity == reference.INITIAL_CASH


def test_implementation_risk_names_no_defect(correct, tmp_path) -> None:
    run = harness.implementation_risk(
        harness.reference_artifacts(prestart=PRESTART),
        correct[1],
        LEVELS,
        report_path=tmp_path / "bt-correct.json",
    )
    harness.assert_no_implementation_defect(run)


def test_lookahead_defect_is_flagged(lookahead, tmp_path) -> None:
    run = harness.implementation_risk(
        harness.reference_artifacts(prestart=PRESTART),
        lookahead[1],
        LEVELS,
        report_path=tmp_path / "bt-lookahead.json",
    )
    harness.assert_defect_flagged(run)
    assert {"accounting", "return", "sizing"} <= run.adverse_families()
