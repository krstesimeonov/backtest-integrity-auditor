"""End to end: the toy strategy in vectorbt 1.1.0 through the shipped adapter.

vectorbt computes the moving averages (``vbt.MA``) and simulates the orders
(``Portfolio.from_orders`` with target amounts, fixed fees, market fills at the
bar close). The portfolio is exported with ``export_vectorbt_portfolio``,
mapped with the D2 service, and checked against ``reference.py``.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    build_v1_5d2_service,
    export_vectorbt_portfolio,
)

from e2e import harness, reference

vbt = pytest.importorskip("vectorbt")

ENGINE_VERSION = "1.1.0"
LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.TRADE,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)


def run_vectorbt(*, lag: int):
    """The strategy written the vectorbt way; ``lag=0`` is the look-ahead bug."""

    close = reference.load_prices()["close"]
    fast = vbt.MA.run(close, window=reference.FAST).ma
    slow = vbt.MA.run(close, window=reference.SLOW).ma
    long_signal = (fast.to_numpy() > slow.to_numpy()).astype(int)
    sessions = close.index.tz_convert(reference.EXCHANGE_TIMEZONE).normalize()
    sessions = sessions.tz_localize(None)
    short_window = (sessions >= reference.SHORT_FIRST_SIGNAL_SESSION) & (
        sessions <= reference.SHORT_LAST_SIGNAL_SESSION
    )
    signal = pd.Series(long_signal, index=close.index).where(~short_window, -1)
    target = signal.shift(lag).fillna(0) * reference.QUANTITY
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return vbt.Portfolio.from_orders(
            close,
            size=target,
            size_type="targetamount",
            fixed_fees=float(reference.FEE),
            init_cash=float(reference.INITIAL_CASH),
            freq="1D",
        )


def mapped_bundle(tmp: Path, *, lag: int):
    assert vbt.__version__ == ENGINE_VERSION
    portfolio = run_vectorbt(lag=lag)
    exported = export_vectorbt_portfolio(
        portfolio,
        tmp / "vectorbt-export",
        run_id=f"vectorbt-lag{lag}",
        instrument_id=reference.INSTRUMENT,
        base_currency=reference.CURRENCY,
    )
    result = build_v1_5d2_service().adapt(exported)
    bundle = harness.write_and_validate(result.artifacts, tmp / "bundle", "vectorbt")
    return result, bundle


@pytest.fixture(scope="module")
def correct(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("vectorbt-correct"), lag=1)


@pytest.fixture(scope="module")
def lookahead(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("vectorbt-lookahead"), lag=0)


@pytest.fixture(scope="module")
def expected():
    return reference.expected_run()


def test_bundle_validates_against_schema_1_0(correct) -> None:
    result, bundle = correct
    assert bundle.run.engine_version == ENGINE_VERSION
    assert set(LEVELS) <= set(bundle.available_levels)
    assert tuple(item.code for item in result.warnings) == (
        "vectorbt.filled_orders_reconstructed",
        "vectorbt.initial_return_omitted",
    )


def test_fills_match_reference(correct, expected) -> None:
    harness.assert_fills_match(correct[1], expected)


def test_fees_match_reference(correct, expected) -> None:
    harness.assert_costs_match(correct[1], expected)


def test_round_trips_match_reference(correct, expected) -> None:
    harness.assert_trades_match(correct[1], expected, pnl="net_pnl")


def test_final_equity_matches_reference(correct, expected) -> None:
    harness.assert_final_equity(correct[1], expected)


def test_implementation_risk_names_no_defect(correct, tmp_path) -> None:
    run = harness.implementation_risk(
        harness.reference_artifacts(),
        correct[1],
        LEVELS,
        report_path=tmp_path / "vectorbt-correct.json",
    )
    harness.assert_no_implementation_defect(run)


def test_lookahead_defect_is_flagged(lookahead, tmp_path) -> None:
    run = harness.implementation_risk(
        harness.reference_artifacts(),
        lookahead[1],
        LEVELS,
        report_path=tmp_path / "vectorbt-lookahead.json",
    )
    harness.assert_defect_flagged(run)
    assert {"accounting", "return"} <= run.adverse_families()
