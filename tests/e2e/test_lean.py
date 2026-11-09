"""End to end: the toy strategy in QuantConnect LEAN through the shipped adapter.

LEAN ran locally without Docker: built from source at commit 278fcb3 (master
when NuGet 2.5.17999 was published) with a user-local .NET 10 SDK, running
``tests/e2e/lean/SynMaCrossAlgorithm.cs`` via ``tests/e2e/lean/run_lean.py``
(docs/history/w3-j12/ASSUMPTIONS.md J9). LEAN's two result files per variant are checked in
verbatim under ``tests/e2e/data/lean/lag1`` (the specification) and ``lag0``
(the look-ahead defect), so this test needs no LEAN install. It exports them
with ``export_quantconnect_lean_results``, maps them with the D3 service, and
checks the bundle against ``reference.py``.

The first tests feed the exporter one real LEAN 2.5.17999 serialization
feature at a time (taken from those files), each otherwise in the form the
exporter already accepted, so each exporter fix has its own failing test.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    OrderType,
    TimeInForce,
    build_v1_5d3_service,
    export_quantconnect_lean_results,
)

from e2e import harness, reference

ENGINE_VERSION = "2.5.17999"
LEAN_DATA = Path(__file__).resolve().parent / "data" / "lean"
ALGORITHM = "SynMaCrossAlgorithm"


def lean_files(lag: int) -> tuple[Path, Path]:
    folder = LEAN_DATA / f"lag{lag}"
    return folder / f"{ALGORITHM}.json", folder / f"{ALGORITHM}-order-events.json"


def _documents(
    *,
    order_times: str = "time",
    time_in_force: object = "GoodTilCanceledTimeInForce",
    event_id: object = 2,
    equity: str = "objects",
) -> tuple[dict, list]:
    """Order 1 and its fill from the real lag=1 run, in a chosen shape.

    The defaults are the shapes the exporter accepted before W3-J12, which are
    not what LEAN writes; each keyword switches one feature back to LEAN's own
    serialization.
    """

    result_path, events_path = lean_files(1)
    real = json.loads(result_path.read_text(encoding="utf-8"))
    events = json.loads(events_path.read_text(encoding="utf-8"))
    order = dict(real["orders"]["1"])
    fill = dict(
        next(item for item in events if item["orderId"] == 1 and item["fillQuantity"])
    )
    assert "time" in order and "createdTime" in order
    if order_times == "time":
        del order["createdTime"]
    order["properties"] = {"timeInForce": time_in_force}
    fill["id"] = event_id
    candles = real["charts"]["Strategy Equity"]["series"]["Equity"]["values"][:3]
    assert all(isinstance(item, list) and len(item) == 5 for item in candles)
    values = (
        candles
        if equity == "candles"
        else [{"x": item[0], "y": item[4]} for item in candles]
    )
    result = {
        "orders": {"1": order},
        "charts": {"Strategy Equity": {"series": {"Equity": {"values": values}}}},
    }
    return result, [fill]


def _export(tmp: Path, result: dict, events: list):
    result_path = tmp / "result.json"
    events_path = tmp / "events.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    events_path.write_text(json.dumps(events), encoding="utf-8")
    exported = export_quantconnect_lean_results(
        result_path,
        events_path,
        tmp / "export",
        run_id="lean-format",
        base_currency="USD",
        engine_version=ENGINE_VERSION,
    )
    return build_v1_5d3_service().adapt(exported).artifacts


def test_lean_order_carries_time_and_created_time(tmp_path: Path) -> None:
    """LEAN serializes Order.CreatedTime, an alias of Order.Time, as well."""

    result, events = _documents(order_times="both")
    artifacts = _export(tmp_path, result, events)
    (order,) = artifacts.orders
    assert order.created_at.isoformat() == "2024-03-25T19:40:00+00:00"


@pytest.mark.parametrize(
    ("serialized", "expected"),
    [
        # LEAN's TimeInForceJsonConverter omits $type for GoodTilCanceled,
        # which is also its reader's default; other kinds carry their type.
        ({}, TimeInForce.GTC),
        ({"$type": "QuantConnect.Orders.TimeInForces.DayTimeInForce"}, TimeInForce.DAY),
    ],
)
def test_lean_time_in_force_is_an_object(tmp_path: Path, serialized, expected) -> None:
    result, events = _documents(order_times="both", time_in_force=serialized)
    (order,) = _export(tmp_path, result, events).orders
    assert order.time_in_force is expected


def test_lean_order_event_id_is_text(tmp_path: Path) -> None:
    """SerializedOrderEvent.Id is "<algorithmId>-<orderId>-<orderEventId>"."""

    result, events = _documents(
        order_times="both", time_in_force={}, event_id="SynMaCrossAlgorithm-1-2"
    )
    artifacts = _export(tmp_path, result, events)
    (fill,) = artifacts.fills
    (cost,) = artifacts.costs
    assert fill.fill_id == "lean-fill-SynMaCrossAlgorithm-1-2"
    assert cost.fill_id == fill.fill_id


def test_lean_strategy_equity_is_candlesticks(tmp_path: Path) -> None:
    """The Equity series is a CandlestickSeries: [time, open, high, low, close]."""

    result, events = _documents(
        order_times="both",
        time_in_force={},
        event_id="SynMaCrossAlgorithm-1-2",
        equity="candles",
    )
    candles = result["charts"]["Strategy Equity"]["series"]["Equity"]["values"]
    artifacts = _export(tmp_path, result, events)
    assert [
        (int(item.timestamp.timestamp()), item.total_equity)
        for item in artifacts.equity
    ] == [(candle[0], Decimal(str(candle[4]))) for candle in candles]


# ---------------------------------------------------------------------------
# The real LEAN run, end to end
# ---------------------------------------------------------------------------

LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)


def lean_equity_instants(lag: int) -> list[pd.Timestamp]:
    """The Strategy Equity sample instants, read from LEAN's file directly."""

    result = json.loads(lean_files(lag)[0].read_text(encoding="utf-8"))
    candles = result["charts"]["Strategy Equity"]["series"]["Equity"]["values"]
    return [pd.Timestamp(candle[0], unit="s", tz="UTC") for candle in candles]


def lean_reference(*, lag: int = reference.EXECUTION_LAG_BARS):
    return harness.reference_artifacts(
        lag=lag,
        positions_at="fill",
        equity_at=lean_equity_instants(lag),
    )


def mapped_bundle(tmp: Path, *, lag: int):
    result_file, events_file = lean_files(lag)
    exported = export_quantconnect_lean_results(
        result_file,
        events_file,
        tmp / "lean-export",
        run_id=f"lean-lag{lag}",
        base_currency=reference.CURRENCY,
        engine_version=ENGINE_VERSION,
    )
    mapped = build_v1_5d3_service().adapt(exported)
    bundle = harness.write_and_validate(mapped.artifacts, tmp / "bundle", "lean")
    return mapped, bundle


@pytest.fixture(scope="module")
def correct(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("lean-correct"), lag=1)


@pytest.fixture(scope="module")
def lookahead(tmp_path_factory):
    return mapped_bundle(tmp_path_factory.mktemp("lean-lookahead"), lag=0)


@pytest.fixture(scope="module")
def expected():
    return reference.expected_run()


def test_bundle_validates_against_schema_1_0(correct) -> None:
    mapped, bundle = correct
    assert bundle.run.engine_version == ENGINE_VERSION
    assert set(LEVELS) <= set(bundle.available_levels)
    assert tuple(item.code for item in mapped.warnings) == (
        "quantconnect_lean.engine_version_producer_declared",
        "quantconnect_lean.order_submission_time_uses_creation",
        "quantconnect_lean.positions_derived_from_fills",
        "quantconnect_lean.returns_derived_from_equity",
    )


def test_orders_are_market_on_close_sent_before_the_close(correct) -> None:
    bundle = correct[1]
    fills = {item.order_id: item for item in bundle.fills or ()}
    assert len(bundle.orders or ()) == 10
    for order in bundle.orders or ():
        assert order.order_type is OrderType.MARKET_ON_CLOSE
        assert order.time_in_force is TimeInForce.GTC
        assert fills[order.order_id].timestamp - order.created_at == pd.Timedelta(
            minutes=20
        )


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
        lean_reference(),
        correct[1],
        LEVELS,
        report_path=tmp_path / "lean-correct.json",
    )
    harness.assert_no_implementation_defect(run)


def test_lookahead_defect_is_flagged(lookahead, tmp_path) -> None:
    run = harness.implementation_risk(
        lean_reference(),
        lookahead[1],
        LEVELS,
        report_path=tmp_path / "lean-lookahead.json",
    )
    harness.assert_defect_flagged(run)
    assert {"accounting", "return"} <= run.adverse_families()


def test_lookahead_run_matches_the_shifted_reference(lookahead) -> None:
    shifted = reference.expected_run(lag=0)
    harness.assert_fills_match(lookahead[1], shifted)
    harness.assert_final_equity(lookahead[1], shifted)
