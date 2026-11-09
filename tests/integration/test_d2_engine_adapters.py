from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    EngineExportFileBundleAdapter,
    OrderStatus,
    OrderType,
    build_v1_5d2_service,
    create_backtrader_audit_analyzer,
    export_backtrader_analysis,
    export_bt_result,
    export_vectorbt_portfolio,
)


def test_vectorbt_1_1_0_export_maps_real_portfolio_deterministically(
    tmp_path: Path,
) -> None:
    vbt = pytest.importorskip("vectorbt")
    index = pd.date_range("2024-01-01", periods=5, tz="UTC")
    close = pd.Series([100.0, 102.0, 101.0, 105.0, 104.0], index=index)
    size = pd.Series([1.0, 0.0, 0.0, -1.0, 0.0], index=index)
    portfolio = vbt.Portfolio.from_orders(
        close,
        size=size,
        fees=0.001,
        init_cash=1_000,
        freq="D",
    )

    directory = export_vectorbt_portfolio(
        portfolio,
        tmp_path / "vectorbt-export",
        run_id="vectorbt-integration",
        instrument_id="AAPL",
        base_currency="USD",
    )
    first_zip = export_vectorbt_portfolio(
        portfolio,
        tmp_path / "first.zip",
        run_id="vectorbt-integration",
        instrument_id="AAPL",
        base_currency="USD",
    )
    second_zip = export_vectorbt_portfolio(
        portfolio,
        tmp_path / "second.zip",
        run_id="vectorbt-integration",
        instrument_id="AAPL",
        base_currency="USD",
    )
    assert first_zip.read_bytes() == second_zip.read_bytes()
    assert EngineExportFileBundleAdapter().read(directory) == (
        EngineExportFileBundleAdapter().read(first_zip)
    )

    result = build_v1_5d2_service().adapt(directory)
    assert result.artifacts.available_levels == (
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
        ComparisonLevel.TRADE,
        ComparisonLevel.POSITION,
        ComparisonLevel.CASH,
        ComparisonLevel.COST,
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    assert len(result.artifacts.orders or ()) == 2
    assert len(result.artifacts.fills or ()) == 2
    assert len(result.artifacts.trades or ()) == 1
    assert len(result.artifacts.positions or ()) == 5
    assert len(result.artifacts.returns or ()) == 4
    assert tuple(item.code for item in result.warnings) == (
        "vectorbt.filled_orders_reconstructed",
        "vectorbt.initial_return_omitted",
    )


def test_bt_1_2_0_export_maps_real_result(tmp_path: Path) -> None:
    bt = pytest.importorskip("bt")
    index = pd.date_range("2024-01-01", periods=5, tz="UTC")
    prices = pd.DataFrame(
        {"AAPL": [100.0, 102.0, 101.0, 105.0, 104.0]},
        index=index,
    )
    strategy = bt.Strategy(
        "strategy",
        [
            bt.algos.RunOnce(),
            bt.algos.SelectAll(),
            bt.algos.WeighEqually(),
            bt.algos.Rebalance(),
        ],
    )
    backtest = bt.Backtest(
        strategy,
        prices,
        initial_capital=1_000,
        commissions=lambda quantity, _price: abs(quantity) * 0.1,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        engine_result = bt.run(backtest)
        exported = export_bt_result(
            engine_result,
            tmp_path / "bt-export",
            run_id="bt-integration",
            base_currency="USD",
        )

    result = build_v1_5d2_service().adapt(exported)
    assert result.artifacts.available_levels == (
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
        ComparisonLevel.POSITION,
        ComparisonLevel.CASH,
        ComparisonLevel.COST,
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    assert len(result.artifacts.orders or ()) == 1
    assert len(result.artifacts.fills or ()) == 1
    assert len(result.artifacts.positions or ()) == 6
    assert len(result.artifacts.costs or ()) == 1
    assert len(result.artifacts.returns or ()) == 5
    assert tuple(item.code for item in result.warnings) == (
        "bt.aggregate_fees_unlinked",
        "bt.transactions_reconstructed_orders",
    )


def test_backtrader_analyzer_maps_real_order_lifecycle(tmp_path: Path) -> None:
    backtrader = pytest.importorskip("backtrader")
    index = pd.date_range("2024-01-01", periods=6, tz="UTC")
    prices = pd.DataFrame(
        {
            "open": [100, 102, 101, 105, 104, 106],
            "high": [101, 103, 102, 106, 105, 107],
            "low": [99, 101, 100, 104, 103, 105],
            "close": [100, 102, 101, 105, 104, 106],
            "volume": [1_000] * 6,
        },
        index=index,
    )

    class BuyOnce(backtrader.Strategy):
        def __init__(self) -> None:
            self.ordered = False

        def next(self) -> None:
            if not self.ordered:
                self.buy(size=2)
                self.ordered = True

    cerebro = backtrader.Cerebro()
    cerebro.broker.setcash(1_000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.adddata(backtrader.feeds.PandasData(dataname=prices), name="AAPL")
    cerebro.addstrategy(BuyOnce)
    analyzer_class = create_backtrader_audit_analyzer(source_timezone="UTC")
    cerebro.addanalyzer(analyzer_class, _name="integrity")
    strategy = cerebro.run()[0]
    exported = export_backtrader_analysis(
        strategy.analyzers.integrity,
        tmp_path / "backtrader-export",
        run_id="backtrader-integration",
        base_currency="USD",
    )

    result = build_v1_5d2_service().adapt(exported)
    assert result.artifacts.available_levels == (
        ComparisonLevel.ORDER,
        ComparisonLevel.FILL,
        ComparisonLevel.POSITION,
        ComparisonLevel.CASH,
        ComparisonLevel.COST,
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    assert len(result.artifacts.orders or ()) == 1
    assert len(result.artifacts.fills or ()) == 1
    assert len(result.artifacts.positions or ()) == 6
    assert len(result.artifacts.costs or ()) == 1
    assert len(result.artifacts.returns or ()) == 5
    order = (result.artifacts.orders or ())[0]
    assert order.order_type is OrderType.MARKET
    assert order.status is OrderStatus.FILLED
    assert result.warnings == ()
