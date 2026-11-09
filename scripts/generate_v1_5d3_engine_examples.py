"""Generate or verify the two executable V1.5D3 engine examples."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from backtest_auditor.implementation_risk import (
    build_v1_5d3_service,
    export_nautilustrader_reports,
    export_quantconnect_lean_results,
)
from backtest_auditor.implementation_risk.exporters.quantconnect_lean import (
    QUANTCONNECT_LEAN_TESTED_VERSION,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "v1_5d3_engine_exports"


def _generate_lean(destination: Path, temporary: Path) -> None:
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
        }
    ]
    result_file = temporary / "algorithm.json"
    events_file = temporary / "algorithm-order-events.json"
    result_file.write_text(
        json.dumps(result, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    events_file.write_text(
        json.dumps(order_events, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    export_quantconnect_lean_results(
        result_file,
        events_file,
        destination,
        run_id="v1-5d3-lean-example",
        base_currency="USD",
        engine_version=QUANTCONNECT_LEAN_TESTED_VERSION,
        overwrite=destination.exists(),
    )


def _generate_nautilustrader(destination: Path) -> None:
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
    export_nautilustrader_reports(
        ReportProvider.generate_orders_report([order]),
        ReportProvider.generate_fills_report([order]),
        ReportProvider.generate_positions_report([position]),
        ReportProvider.generate_account_report(account),
        destination,
        run_id="v1-5d3-nautilustrader-example",
        base_currency="USD",
        overwrite=destination.exists(),
    )


def generate_examples(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as raw_temporary:
        temporary = Path(raw_temporary)
        _generate_lean(destination / "quantconnect_lean", temporary)
    _generate_nautilustrader(destination / "nautilustrader")
    service = build_v1_5d3_service()
    service.adapt(destination / "quantconnect_lean")
    service.adapt(destination / "nautilustrader")


def _tree(directory: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(directory): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if not arguments.check:
        generate_examples(EXAMPLE_ROOT)
        return 0
    if not EXAMPLE_ROOT.is_dir():
        raise SystemExit(f"missing example directory: {EXAMPLE_ROOT}")
    with tempfile.TemporaryDirectory() as raw_temporary:
        generated = Path(raw_temporary) / "examples"
        generate_examples(generated)
        if _tree(generated) != _tree(EXAMPLE_ROOT):
            raise SystemExit("V1.5D3 examples differ from deterministic generator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
