from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import backtest_auditor.implementation_risk.exporters.nautilustrader as nt_exporter
from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    EngineExportFileBundleAdapter,
    OrderStatus,
    SupportedEngine,
    build_v1_5d3_registry,
    build_v1_5d3_service,
    export_nautilustrader_engine,
    export_nautilustrader_reports,
    export_quantconnect_lean_results,
)
from backtest_auditor.implementation_risk.application.errors import (
    EngineAdapterError,
    EngineAdapterErrorCode,
)
from backtest_auditor.implementation_risk.exporters.quantconnect_lean import (
    QUANTCONNECT_LEAN_TESTED_VERSION,
)


def _write_lean_sources(directory: Path) -> tuple[Path, Path]:
    result = {
        "Orders": {
            "1": {
                "id": 1,
                "symbol": {"value": "AAPL"},
                "time": "2026-01-02T14:30:00Z",
                "lastUpdateTime": "2026-01-02T14:31:00Z",
                "quantity": 2,
                "direction": 0,
                "type": 0,
                "status": 3,
                "properties": {"timeInForce": "DayTimeInForce"},
            }
        },
        "Charts": {
            "Strategy Equity": {
                "Series": {
                    "Equity": {
                        "Values": [
                            {"x": 1767364200, "y": 1000},
                            {"x": 1767450600, "y": 1020},
                        ]
                    }
                }
            }
        },
    }
    order_events = [
        {
            "id": 10,
            "orderId": 1,
            "utcTime": "2026-01-02T14:30:00Z",
            "status": 1,
            "direction": 0,
            "fillPrice": 0,
            "fillPriceCurrency": "USD",
            "fillQuantity": 0,
        },
        {
            "id": 11,
            "orderId": 1,
            "utcTime": "2026-01-02T14:31:00Z",
            "status": 3,
            "direction": 0,
            "fillPrice": 100,
            "fillPriceCurrency": "USD",
            "fillQuantity": 2,
            "orderFeeAmount": 0.2,
            "orderFeeCurrency": "USD",
        },
    ]
    result_path = directory / "algorithm.json"
    events_path = directory / "algorithm-order-events.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    events_path.write_text(json.dumps(order_events), encoding="utf-8")
    return result_path, events_path


def _nautilus_reports() -> tuple[pd.DataFrame, ...]:
    orders = pd.DataFrame(
        [
            {
                "instrument_id": "AAPL.XNAS",
                "side": "BUY",
                "type": "MARKET",
                "status": "FILLED",
                "quantity": "2",
                "filled_qty": "2",
                "price": pd.NA,
                "avg_px": "100",
                "time_in_force": "DAY",
                "ts_init": 1767364200000000000,
                "ts_last": 1767364260000000000,
            }
        ],
        index=pd.Index(["O-001"], name="client_order_id"),
    )
    fills = pd.DataFrame(
        [
            {
                "trade_id": "T-001",
                "instrument_id": "AAPL.XNAS",
                "order_side": "BUY",
                "order_type": "MARKET",
                "last_px": "100",
                "last_qty": "2",
                "currency": "USD",
                "liquidity_side": "TAKER",
                "commission": "0.20 USD",
                "position_id": "P-001",
                "ts_event": pd.Timestamp("2026-01-02T14:31:00Z"),
                "ts_init": pd.Timestamp("2026-01-02T14:31:00Z"),
            }
        ],
        index=pd.Index(["O-001"], name="client_order_id"),
    )
    positions = pd.DataFrame(
        [
            {
                "instrument_id": "AAPL.XNAS",
                "entry": "BUY",
                "side": "FLAT",
                "quantity": "0",
                "peak_qty": "2",
                "avg_px_open": "100",
                "avg_px_close": "110",
                "realized_pnl": "19.80 USD",
                "ts_init": 1767364200000000000,
                "ts_opened": pd.Timestamp("2026-01-02T14:31:00Z"),
                "ts_last": 1767450600000000000,
                "ts_closed": pd.Timestamp("2026-01-03T14:30:00Z"),
                "is_snapshot": True,
            }
        ],
        index=pd.Index(["P-001-1"], name="position_id"),
    )
    account = pd.DataFrame(
        [
            {
                "account_id": "SIM-001",
                "account_type": "CASH",
                "base_currency": "USD",
                "total": "1019.80",
                "free": "1019.80",
                "locked": "0",
                "currency": "USD",
            }
        ],
        index=pd.Index([1767450600000000000], name="ts_event"),
    )
    return orders, fills, positions, account


def test_quantconnect_lean_local_results_export_and_map_deterministically(
    tmp_path: Path,
) -> None:
    result_file, events_file = _write_lean_sources(tmp_path)
    directory = export_quantconnect_lean_results(
        result_file,
        events_file,
        tmp_path / "lean-export",
        run_id="lean-integration",
        base_currency="USD",
        engine_version=QUANTCONNECT_LEAN_TESTED_VERSION,
    )
    first = export_quantconnect_lean_results(
        result_file,
        events_file,
        tmp_path / "first.zip",
        run_id="lean-integration",
        base_currency="USD",
        engine_version=QUANTCONNECT_LEAN_TESTED_VERSION,
    )
    second = export_quantconnect_lean_results(
        result_file,
        events_file,
        tmp_path / "second.zip",
        run_id="lean-integration",
        base_currency="USD",
        engine_version=QUANTCONNECT_LEAN_TESTED_VERSION,
    )
    assert first.read_bytes() == second.read_bytes()
    assert EngineExportFileBundleAdapter().read(directory) == (
        EngineExportFileBundleAdapter().read(first)
    )

    mapped = build_v1_5d3_service().adapt(directory)
    assert mapped.artifacts.available_levels == (
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
        ComparisonLevel.POSITION,
        ComparisonLevel.COST,
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    assert len(mapped.artifacts.orders or ()) == 1
    assert len(mapped.artifacts.fills or ()) == 1
    assert len(mapped.artifacts.positions or ()) == 1
    assert len(mapped.artifacts.costs or ()) == 1
    assert len(mapped.artifacts.equity or ()) == 2
    assert len(mapped.artifacts.returns or ()) == 1
    assert (mapped.artifacts.orders or ())[0].status is OrderStatus.FILLED
    assert tuple(item.code for item in mapped.warnings) == (
        "quantconnect_lean.engine_version_producer_declared",
        "quantconnect_lean.order_submission_time_uses_creation",
        "quantconnect_lean.positions_derived_from_fills",
        "quantconnect_lean.returns_derived_from_equity",
    )


def test_nautilustrader_reports_and_engine_convenience_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        nt_exporter,
        "installed_engine_version",
        lambda _distribution: "1.231.0",
    )
    reports = _nautilus_reports()
    exported = export_nautilustrader_reports(
        *reports,
        tmp_path / "nautilus-export",
        run_id="nautilus-integration",
        base_currency="USD",
    )

    class CompletedEngine:
        def generate_orders_report(self) -> pd.DataFrame:
            return reports[0]

        def generate_fills_report(self) -> pd.DataFrame:
            return reports[1]

        def generate_positions_report(self) -> pd.DataFrame:
            return reports[2]

        def generate_account_report(self, *, venue: object) -> pd.DataFrame:
            assert venue == "SIM"
            return reports[3]

    convenience = export_nautilustrader_engine(
        CompletedEngine(),
        "SIM",
        tmp_path / "nautilus-convenience",
        run_id="nautilus-integration",
        base_currency="USD",
    )
    assert EngineExportFileBundleAdapter().read(exported) == (
        EngineExportFileBundleAdapter().read(convenience)
    )
    mapped = build_v1_5d3_service().adapt(exported)
    assert mapped.artifacts.available_levels == (
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
        ComparisonLevel.TRADE,
        ComparisonLevel.POSITION,
        ComparisonLevel.CASH,
        ComparisonLevel.COST,
    )
    assert len(mapped.artifacts.trades or ()) == 1
    assert len(mapped.artifacts.positions or ()) == 1
    assert len((mapped.artifacts.cash and mapped.artifacts.cash.balances) or ()) == 1
    assert tuple(item.code for item in mapped.warnings) == (
        "nautilustrader.position_fill_links_unavailable",
        "nautilustrader.position_snapshots_quantity_only",
    )


def test_d3_registry_is_complete_and_versions_fail_closed(tmp_path: Path) -> None:
    registry = build_v1_5d3_registry()
    registry.assert_complete_roadmap()
    assert tuple(item.engine for item in registry.descriptors) == tuple(SupportedEngine)
    result_file, events_file = _write_lean_sources(tmp_path)
    with pytest.raises(ValueError, match="tested only"):
        export_quantconnect_lean_results(
            result_file,
            events_file,
            tmp_path / "wrong",
            run_id="wrong-version",
            base_currency="USD",
            engine_version="2.5.0",
        )

    exported = export_quantconnect_lean_results(
        result_file,
        events_file,
        tmp_path / "valid",
        run_id="valid",
        base_currency="USD",
        engine_version=QUANTCONNECT_LEAN_TESTED_VERSION,
    )
    verified = EngineExportFileBundleAdapter().read(exported)
    wrong = verified.create(
        run_id=verified.envelope.run_id,
        engine=verified.envelope.engine,
        engine_version="2.5.0",
        export_format_id=verified.envelope.export_format_id,
        export_format_version=verified.envelope.export_format_version,
        declared_levels=verified.envelope.declared_levels,
        payloads=verified.payloads,
    )
    source = EngineExportFileBundleAdapter().write(wrong, tmp_path / "wrong.zip")
    with pytest.raises(EngineAdapterError) as captured:
        build_v1_5d3_service().adapt(source)
    assert captured.value.code is EngineAdapterErrorCode.UNTESTED_ENGINE_VERSION


def test_nautilustrader_documented_empty_reports_remain_available_empty(
    tmp_path: Path,
) -> None:
    pytest.importorskip("nautilus_trader")
    from nautilus_trader.analysis import ReportProvider

    empty = ReportProvider.generate_orders_report([])
    exported = export_nautilustrader_reports(
        empty,
        ReportProvider.generate_fills_report([]),
        ReportProvider.generate_positions_report([]),
        empty,
        tmp_path / "empty-nautilus",
        run_id="nautilus-empty",
        base_currency="USD",
    )
    mapped = build_v1_5d3_service().adapt(exported)
    assert mapped.artifacts.orders == ()
    assert mapped.artifacts.fills == ()
    assert mapped.artifacts.trades == ()
    assert mapped.artifacts.positions == ()
    assert mapped.artifacts.cash is not None
    assert mapped.artifacts.cash.balances == ()
    assert mapped.artifacts.costs == ()


def test_nautilustrader_1_231_0_real_report_provider_output(tmp_path: Path) -> None:
    pytest.importorskip("nautilus_trader")
    from nautilus_trader.analysis import ReportProvider
    from nautilus_trader.model.position import Position
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from nautilus_trader.test_kit.stubs.events import TestEventStubs
    from nautilus_trader.test_kit.stubs.execution import TestExecStubs
    from nautilus_trader.test_kit.stubs.identifiers import TestIdStubs

    instrument = TestInstrumentProvider.default_fx_ccy("AUD/USD")
    order = TestExecStubs.make_accepted_order(instrument=instrument)
    fill = TestEventStubs.order_filled(
        order=order,
        instrument=instrument,
        position_id=TestIdStubs.position_id(),
    )
    order.apply(fill)
    position = Position(instrument, fill)
    account = TestExecStubs.cash_account()

    exported = export_nautilustrader_reports(
        ReportProvider.generate_orders_report([order]),
        ReportProvider.generate_fills_report([order]),
        ReportProvider.generate_positions_report([position]),
        ReportProvider.generate_account_report(account),
        tmp_path / "real-nautilus",
        run_id="nautilus-real-reports",
        base_currency="USD",
    )
    mapped = build_v1_5d3_service().adapt(exported)
    assert len(mapped.artifacts.orders or ()) == 1
    assert len(mapped.artifacts.fills or ()) == 1
    assert len(mapped.artifacts.trades or ()) == 1
    assert len(mapped.artifacts.positions or ()) == 1
    assert len((mapped.artifacts.cash and mapped.artifacts.cash.balances) or ()) == 1
