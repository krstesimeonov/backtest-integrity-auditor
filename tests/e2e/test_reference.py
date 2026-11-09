"""The reference itself: seed, data file, and the properties strategy_spec.md claims."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from e2e import reference


def test_price_file_is_the_seeded_series() -> None:
    generated = reference.generate_prices()
    loaded = reference.load_prices()
    pd.testing.assert_frame_equal(generated, loaded, check_freq=False)
    assert (loaded["high"] >= loaded[["open", "close"]].max(axis=1)).all()
    assert (loaded["low"] <= loaded[["open", "close"]].min(axis=1)).all()


def test_timestamps_are_session_closes_across_dst() -> None:
    index = reference.load_prices().index
    local = index.tz_convert(reference.EXCHANGE_TIMEZONE)
    assert (local.hour == 16).all() and (local.minute == 0).all()
    assert set(index.hour) == {20, 21}
    assert len(index) == reference.BARS and index.is_monotonic_increasing


def test_signal_properties_the_spec_relies_on() -> None:
    frame = reference.signals(reference.load_prices())
    defined = frame.dropna(subset=["sma_slow"])
    assert defined["moving_average_signal"].iloc[0] == 0
    assert (defined["sma_fast"] - defined["sma_slow"]).abs().min() > 0.065
    short = frame[frame["signal"] == -1]
    assert len(short) == 20
    margin = frame.loc[
        short.index[0] - pd.Timedelta(days=14) : short.index[-1] + pd.Timedelta(days=14)
    ]
    assert (margin["moving_average_signal"] == 0).all()
    assert frame["position"].iloc[-1] == 0


def test_expected_trade_list_matches_the_spec_table() -> None:
    run = reference.expected_run()
    assert list(run.fills["side"]) == ["buy", "sell"] * 3 + ["sell", "buy"] + [
        "buy",
        "sell",
    ]
    assert list(run.fills["price"]) == [
        Decimal(item)
        for item in (
            "89.51",
            "97.33",
            "101.88",
            "94.88",
            "97.56",
            "94.96",
            "96.59",
            "91.56",
            "102.53",
            "97.82",
        )
    ]
    assert set(run.fills["quantity"]) == {Decimal(100)}
    assert set(run.fills["fee"]) == {Decimal("1.00")}
    assert list(run.trades["direction"]) == ["long", "long", "long", "short", "long"]
    assert list(run.trades["net_pnl"]) == [
        Decimal(item) for item in ("780.00", "-702.00", "-262.00", "501.00", "-473.00")
    ]
    assert run.final_equity == Decimal("99844.00")
    assert run.final_equity == reference.INITIAL_CASH + run.trades["net_pnl"].sum()


def test_lookahead_variant_trades_one_bar_earlier() -> None:
    spec = reference.expected_run()
    defect = reference.expected_run(lag=0)
    index = reference.load_prices().index
    for right, wrong in zip(
        spec.fills["timestamp"], defect.fills["timestamp"], strict=True
    ):
        assert index.get_loc(wrong) == index.get_loc(right) - 1
    assert defect.final_equity == Decimal("99750.00")
