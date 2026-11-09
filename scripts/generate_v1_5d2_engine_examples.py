"""Generate or verify the three executable V1.5D2 engine examples."""

from __future__ import annotations

import argparse
import tempfile
import warnings
from pathlib import Path

import pandas as pd

from backtest_auditor.implementation_risk import (
    build_v1_5d2_service,
    create_backtrader_audit_analyzer,
    export_backtrader_analysis,
    export_bt_result,
    export_vectorbt_portfolio,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "v1_5d2_engine_exports"


def _price_index() -> pd.DatetimeIndex:
    return pd.date_range("2026-01-02", periods=6, tz="UTC")


def _generate_vectorbt(destination: Path) -> None:
    import vectorbt as vbt

    index = _price_index()
    close = pd.Series([100.0, 102.0, 101.0, 105.0, 104.0, 106.0], index=index)
    size = pd.Series([1.0, 0.0, 0.0, -1.0, 0.0, 0.0], index=index)
    portfolio = vbt.Portfolio.from_orders(
        close,
        size=size,
        fees=0.001,
        init_cash=1_000,
        freq="D",
    )
    export_vectorbt_portfolio(
        portfolio,
        destination,
        run_id="v1-5d2-vectorbt-example",
        instrument_id="AAPL",
        base_currency="USD",
        overwrite=destination.exists(),
    )


def _generate_bt(destination: Path) -> None:
    import bt

    prices = pd.DataFrame(
        {"AAPL": [100.0, 102.0, 101.0, 105.0, 104.0, 106.0]},
        index=_price_index(),
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
        result = bt.run(backtest)
        export_bt_result(
            result,
            destination,
            run_id="v1-5d2-bt-example",
            base_currency="USD",
            overwrite=destination.exists(),
        )


def _generate_backtrader(destination: Path) -> None:
    import backtrader

    prices = pd.DataFrame(
        {
            "open": [100, 102, 101, 105, 104, 106],
            "high": [101, 103, 102, 106, 105, 107],
            "low": [99, 101, 100, 104, 103, 105],
            "close": [100, 102, 101, 105, 104, 106],
            "volume": [1_000] * 6,
        },
        index=_price_index(),
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
    analyzer = create_backtrader_audit_analyzer(source_timezone="UTC")
    cerebro.addanalyzer(analyzer, _name="integrity")
    strategy = cerebro.run()[0]
    export_backtrader_analysis(
        strategy.analyzers.integrity,
        destination,
        run_id="v1-5d2-backtrader-example",
        base_currency="USD",
        overwrite=destination.exists(),
    )


def generate_examples(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    _generate_vectorbt(destination / "vectorbt")
    _generate_bt(destination / "bt")
    _generate_backtrader(destination / "backtrader")
    service = build_v1_5d2_service()
    for engine in ("vectorbt", "bt", "backtrader"):
        service.adapt(destination / engine)


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
    with tempfile.TemporaryDirectory() as temporary:
        generated = Path(temporary) / "examples"
        generate_examples(generated)
        if _tree(generated) != _tree(EXAMPLE_ROOT):
            raise SystemExit("V1.5D2 examples differ from deterministic generator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
