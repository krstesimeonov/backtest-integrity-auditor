"""Generate or verify the deterministic V1.5C hybrid-bundle example."""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from backtest_auditor.implementation_risk import (
    ArtifactReturnConvention,
    AssetClass,
    CanonicalArtifactFileBundleAdapter,
    CanonicalRunArtifacts,
    CanonicalRunSpecification,
    EngineRunReference,
    EquityPoint,
    FillRecord,
    InstrumentReference,
    ModelSpecification,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    ReturnPoint,
    SignalRecord,
    SignalType,
    SimulationSpecification,
    StrategySpecification,
    TimeInForce,
)


DEFAULT_DESTINATION = Path("examples/v1_5c_canonical_bundle")


def build_example_bundle() -> CanonicalRunArtifacts:
    signal_time = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    fill_time = signal_time + timedelta(minutes=1)
    specification = CanonicalRunSpecification(
        strategy=StrategySpecification(
            strategy_id="momentum-example",
            name="One-asset momentum example",
            logic_sha256="b" * 64,
            universe=(
                InstrumentReference(
                    "AAPL.XNAS",
                    AssetClass.EQUITY,
                    "AAPL",
                    "USD",
                    "XNAS",
                ),
            ),
            parameters=(),
            data_frequency="one minute",
            signal_timing="after bar availability",
            signal_model=ModelSpecification("positive score enters"),
            sizing_model=ModelSpecification("fixed quantity"),
            version="1",
        ),
        simulation=SimulationSpecification(
            base_currency="USD",
            initial_cash=Decimal(100_000),
            calendar="XNYS",
            calendar_timezone="America/New_York",
            data_adjustment_policy="split adjusted",
            execution_timing="next bar",
            execution_model=ModelSpecification("next-bar market fill"),
            accounting_model=ModelSpecification("average cost"),
            cost_models=(),
            shorting_allowed=False,
            fractional_quantity_allowed=False,
        ),
    )
    signal = SignalRecord(
        "signal-1",
        signal_time,
        "AAPL.XNAS",
        SignalType.TARGET_QUANTITY,
        Decimal(10),
        signal_time,
    )
    order = OrderRecord(
        "order-1",
        fill_time,
        "AAPL.XNAS",
        OrderSide.BUY,
        Decimal(10),
        OrderType.MARKET,
        TimeInForce.DAY,
        OrderStatus.FILLED,
        signal_id="signal-1",
        submitted_at=fill_time,
        last_updated_at=fill_time,
    )
    fill = FillRecord(
        "fill-1",
        "order-1",
        fill_time,
        "AAPL.XNAS",
        OrderSide.BUY,
        Decimal(10),
        Decimal("100.25"),
        "USD",
        venue="XNAS",
    )
    return CanonicalRunArtifacts(
        run=EngineRunReference(
            "example-run",
            "example-engine",
            "1.0",
            "a" * 64,
        ),
        specification=specification,
        signals=(signal,),
        orders=(order,),
        fills=(fill,),
        equity=(EquityPoint(fill_time, "USD", Decimal(100_000)),),
        returns=(
            ReturnPoint(
                signal_time,
                fill_time,
                Decimal(0),
                ArtifactReturnConvention.SIMPLE,
            ),
        ),
    )


def _files(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    adapter = CanonicalArtifactFileBundleAdapter()
    bundle = build_example_bundle()
    if not arguments.check:
        adapter.write(bundle, arguments.destination, overwrite=True)
        return 0
    if not arguments.destination.is_dir():
        raise SystemExit(f"missing example directory: {arguments.destination}")
    with tempfile.TemporaryDirectory() as temporary:
        expected = Path(temporary) / "bundle"
        adapter.write(bundle, expected)
        if _files(expected) != _files(arguments.destination):
            raise SystemExit("V1.5C example differs from deterministic generator")
    adapter.read(arguments.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
