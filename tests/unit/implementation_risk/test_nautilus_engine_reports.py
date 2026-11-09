"""export_nautilustrader_engine reads a real engine's reports through engine.trader.

nautilus_trader 1.231.0's BacktestEngine has no generate_*_report methods of
its own; its trader has them. This runs without nautilus_trader installed;
tests/e2e/test_nautilustrader.py covers the real engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import backtest_auditor.implementation_risk.exporters.nautilustrader as exporter


class _Trader:
    def generate_orders_report(self) -> str:
        return "orders"

    def generate_fills_report(self) -> str:
        return "fills"

    def generate_positions_report(self) -> str:
        return "positions"

    def generate_account_report(self, *, venue: object) -> str:
        return f"account@{venue}"


class _BacktestEngineLike:
    trader = _Trader()


def test_reports_come_from_the_trader_when_the_engine_lacks_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[tuple[object, ...]] = []

    def capture(orders, fills, positions, account, destination, **_options):
        received.append((orders, fills, positions, account))
        return Path(destination)

    monkeypatch.setattr(exporter, "export_nautilustrader_reports", capture)
    exporter.export_nautilustrader_engine(
        _BacktestEngineLike(), "SIM", tmp_path / "out", run_id="r", base_currency="USD"
    )
    assert received == [("orders", "fills", "positions", "account@SIM")]


def test_an_object_without_reports_is_still_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match="engine.generate_orders_report must be callable"
    ):
        exporter.export_nautilustrader_engine(
            object(), "SIM", tmp_path / "out", run_id="r", base_currency="USD"
        )
