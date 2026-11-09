"""Write the five example notebooks (sources only; outputs come from executing).

    python make_notebooks.py          # rewrite 01_...05_*.ipynb without outputs
    ruff format *.ipynb               # the committed cells are ruff-formatted
    bash run_notebooks.sh             # execute them in place with nbconvert

Every notebook follows the same path for one engine: run the toy strategy of
``toy_strategy.py`` natively, export the result with the package's exporter,
map it to canonical bundle 1.0, compare it with the independent reference, and
run the implementation-risk audit on the correct run and on a copy with an
injected one-bar look-ahead. Cells tagged ``doc:<name>`` are quoted verbatim
by the documentation (``scripts/docs_snippets.py``).
"""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).resolve().parent

COMMON_IMPORTS = """\
from pathlib import Path

import pandas as pd

import audit_kit as kit
import backtest_auditor
import toy_strategy as ts
"""

COMMON_CONFIG = """\
pd.set_option("display.width", 140)
pd.set_option("display.max_colwidth", 90)
REPO = Path.cwd().resolve().parents[1]
package_dir = Path(backtest_auditor.__file__).resolve().parent
print("backtest_auditor", backtest_auditor.__version__, "from", package_dir.relative_to(REPO))
"""


def setup(imports: str, after: str) -> str:
    """The first code cell: every import, then display options and versions."""

    return COMMON_IMPORTS + imports + "\n" + COMMON_CONFIG + after


DATA = """\
prices = ts.load_prices()
expected = ts.expected_run()
print(len(prices), "bars,", prices.index[0], "to", prices.index[-1])
prices.head(3)
"""

REFERENCE_MD = """\
## 1. The data and the independent reference

`toy_strategy.py` holds the bars and computes the expected result with pandas
and `decimal` only (no engine, no auditor): ten fills, five round trips
including one short, final equity USD 99,844.00.
"""

CLOSING_TEMPLATE = """\
## What this shows, and what it does not

- The {engine} run and the independent reference agree on every measured
  field at every level compared above (other differences are confined to
  fields the reference leaves empty, labels that differ by design, or float
  noise below the thresholds), and the audit names no defect.
- The injected one-bar look-ahead {lookahead_effect}
- The audit compares evidence against a declared reference under explicit
  thresholds. It does not prove either implementation correct, and it says
  nothing about whether the strategy is any good.
- The full JSON and Markdown reports of both runs are in `_output/` after
  executing this notebook.
"""


def code(source: str, tag: str | None = None):
    cell = new_code_cell(source.rstrip("\n"))
    if tag:
        cell.metadata["tags"] = [f"doc:{tag}"]
    return cell


def markdown(source: str):
    return new_markdown_cell(source.rstrip("\n"))


def audit_cells(
    engine: str, slug: str, levels: str, reference_call: str, lookahead_md: str
):
    return [
        markdown(
            f"""\
## 4. Implementation-risk audit of the correct run

The reference bundle is built from `toy_strategy.py` alone. Levels are aligned
on economics (time, instrument, side), not on engine-local ids. Materiality
thresholds sit far above float noise and far below the effect of a one-bar
shift (see `audit_kit.MEASURED_FIELDS`). Levels compared for {engine}:
{levels.replace("ComparisonLevel.", "").lower()}.

How to read the summary: a score near zero means every measured difference
is float noise below its threshold. No score with uncertainty `not_assessed`
means there was no numeric observation to classify, so read it with the
findings: with no `adverse` or `evidence_gap` finding it is exact agreement on
every measured field; with `evidence_gap` findings it means records could not
be paired at all (the NautilusTrader look-ahead run shows that case)."""
        ),
        code(
            f"""\
LEVELS = ({levels},)
reference_bundle = {reference_call}
correct = kit.implementation_risk(reference_bundle, bundle, LEVELS, name="{slug}-correct")
kit.summary(correct)""",
            "audit",
        ),
        code("kit.levels_table(correct)"),
        markdown(
            """\
`matched_different` counts matched records in which any field differs,
including fields that only one side fills in (the reference leaves market
values and exposures empty) and labels that differ by design (a trade's
grouping method). Which fields differ, and whether the measurement policy
measures them:"""
        ),
        code("kit.differing_fields(correct)"),
        code("print(kit.report_excerpt(correct))"),
        markdown(
            f"""\
## 5. The same strategy with a one-bar look-ahead

The defect: the position follows the signal of the same bar, so the strategy
trades on a close it could not have known. {lookahead_md}"""
        ),
    ]


def notebook(cells, path: Path) -> None:
    nb = new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3 (ipykernel)",
        "language": "python",
        "name": "python3",
    }
    nb.metadata["language_info"] = {"name": "python"}
    nbformat.write(nb, path)


# --------------------------------------------------------------------------
# 01 vectorbt
# --------------------------------------------------------------------------

VECTORBT = [
    markdown(
        """\
# vectorbt → canonical bundle → implementation-risk audit

This notebook runs one toy strategy in **vectorbt 1.1.0**, exports the result
with `backtest_auditor`, maps it to canonical bundle 1.0, checks it against an
independent pandas reference, and runs the implementation-risk audit on the
correct run and on a copy with an injected one-bar look-ahead.

Strategy and reference: [`toy_strategy.py`](toy_strategy.py) (SMA 20/50 cross,
a scheduled short, one-bar execution lag, USD 1.00 per fill). Shared steps:
[`audit_kit.py`](audit_kit.py). Outputs below come from
`jupyter nbconvert --execute --to notebook --inplace 01_vectorbt.ipynb`."""
    ),
    code(
        setup(
            """\
import vectorbt as vbt
from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    build_v1_5d2_service,
    export_vectorbt_portfolio,
)
""",
            'print("vectorbt", vbt.__version__)',
        )
    ),
    markdown(REFERENCE_MD),
    code(DATA),
    markdown(
        """\
## 2. The strategy in vectorbt

vectorbt computes both moving averages (`vbt.MA`) and simulates target
positions with `Portfolio.from_orders`: market fills at the bar close, a fixed
fee per fill."""
    ),
    code(
        """\
def run_vectorbt(lag: int) -> vbt.Portfolio:
    \"\"\"The toy strategy the vectorbt way; lag=0 is the look-ahead bug.\"\"\"
    close = prices["close"]
    fast = vbt.MA.run(close, window=ts.FAST).ma.to_numpy()
    slow = vbt.MA.run(close, window=ts.SLOW).ma.to_numpy()
    long_signal = pd.Series((fast > slow).astype(int), index=close.index)
    sessions = close.index.tz_convert(ts.EXCHANGE_TIMEZONE).normalize().tz_localize(None)
    signal = long_signal.where(~ts.in_short_window(sessions), -1)
    target = signal.shift(lag).fillna(0) * ts.QUANTITY  # shares held at each close
    return vbt.Portfolio.from_orders(
        close,
        size=target,
        size_type="targetamount",
        fixed_fees=float(ts.FEE),
        init_cash=float(ts.INITIAL_CASH),
        freq="1D",
    )


portfolio = run_vectorbt(lag=1)
print("final value:", portfolio.final_value())""",
        "strategy",
    ),
    markdown(
        """\
## 3. Export, map to canonical bundle 1.0, check against the reference

`export_vectorbt_portfolio` reads the executed portfolio (it never re-runs it)
and refuses any vectorbt other than 1.1.0. The D2 adapter maps the export to
canonical artifacts; anything vectorbt does not record is marked unavailable,
and every reconstruction is reported as a warning."""
    ),
    code(
        """\
EXPORTS = kit.OUTPUT / "vectorbt"
exported = export_vectorbt_portfolio(
    portfolio,
    EXPORTS / "export-correct",
    run_id="vectorbt-correct",
    instrument_id=ts.INSTRUMENT,
    base_currency=ts.CURRENCY,
    overwrite=True,
)
adapted = build_v1_5d2_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "vectorbt-correct.zip")
kit.bundle_summary(EXPORTS / "vectorbt-correct.zip")""",
        "export",
    ),
    code("kit.compare_fills(bundle, expected)"),
    code("kit.final_value_check(bundle, expected)"),
    *audit_cells(
        "vectorbt",
        "vectorbt",
        "ComparisonLevel.FILL, ComparisonLevel.TRADE, ComparisonLevel.POSITION, "
        "ComparisonLevel.CASH, ComparisonLevel.COST, ComparisonLevel.EQUITY, "
        "ComparisonLevel.RETURN",
        "kit.reference_artifacts()",
        "Every fill moves one bar earlier.",
    ),
    code(
        """\
exported = export_vectorbt_portfolio(
    run_vectorbt(lag=0),
    EXPORTS / "export-lookahead",
    run_id="vectorbt-lookahead",
    instrument_id=ts.INSTRUMENT,
    base_currency=ts.CURRENCY,
    overwrite=True,
)
lookahead_bundle = kit.write_bundle(
    build_v1_5d2_service().adapt(exported).artifacts, EXPORTS / "vectorbt-lookahead.zip"
)
lookahead = kit.implementation_risk(
    reference_bundle, lookahead_bundle, LEVELS, name="vectorbt-lookahead"
)
kit.summary(lookahead)"""
    ),
    code("kit.families_table(lookahead)"),
    code("print(kit.report_findings(lookahead, 4))"),
    markdown(
        """\
## 6. The same audit from the command line

The CLI reads bundle ZIPs and the four policies as JSON files. The package
serializes its own policy objects (`normalization_plan_to_json` and its three
siblings), so the policies above can be written out and the correct run
audited again by `backtest-auditor implementation-risk`:"""
    ),
    code(
        """\
import shutil

CLI_DIR = EXPORTS / "cli"
shutil.rmtree(CLI_DIR, ignore_errors=True)  # list only what this run writes
kit.write_bundle(kit.restrict(reference_bundle, LEVELS), CLI_DIR / "reference.zip")
kit.write_bundle(kit.restrict(bundle, LEVELS), CLI_DIR / "candidate.zip")
kit.policies(reference_bundle, bundle, LEVELS).write(CLI_DIR)
print(sorted(path.name for path in CLI_DIR.iterdir()))
print((CLI_DIR / "comparison-policy.json").read_text()[:240], "...")""",
        "cli-files",
    ),
    code(
        """\
import json
import subprocess
import sys

command = [
    str(Path(sys.executable).with_name("backtest-auditor")),
    "implementation-risk",
    "reference.zip",
    "candidate.zip",
    "--normalization-plan", "normalization-plan.json",
    "--comparison-policy", "comparison-policy.json",
    "--measurement-policy", "measurement-policy.json",
    "--assessment-policy", "assessment-policy.json",
    "--format", "json",
    "--output", "report.json",
    "--force",
]  # fmt: skip
completed = subprocess.run(command, cwd=CLI_DIR, capture_output=True, text=True)
print("exit code:", completed.returncode, completed.stdout, completed.stderr)
cli_report = json.loads((CLI_DIR / "report.json").read_text(encoding="utf-8"))
kit.validate_report(cli_report)
print("CLI report equals the report of the Python call above:", cli_report == correct.report)""",
        "cli-run",
    ),
    markdown(
        CLOSING_TEMPLATE.format(
            engine="vectorbt",
            lookahead_effect=(
                "produces adverse findings in the sizing, accounting and return\n"
                "  families, and the score is withheld because evidence on some\n"
                "  levels became one-sided."
            ),
        )
    ),
]

# --------------------------------------------------------------------------
# 02 bt
# --------------------------------------------------------------------------

BT = [
    markdown(
        """\
# bt → canonical bundle → implementation-risk audit

The same toy strategy in **bt 1.2.0**: export, canonical bundle 1.0, check
against the independent reference, and the implementation-risk audit on the
correct run and on a run with an injected one-bar look-ahead.

bt prepends a virtual row one calendar day before the data to hold the
initial capital. The adapter maps it as evidence, so the reference carries the
same initial-capital observation (`prestart=`); against an engine without such
a row it would show up as one-sided evidence. Outputs below come from
`jupyter nbconvert --execute --to notebook --inplace 02_bt.ipynb`."""
    ),
    code(
        setup(
            """\
import bt
from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    build_v1_5d2_service,
    export_bt_result,
)
""",
            'print("bt", bt.__version__)',
        )
    ),
    markdown(REFERENCE_MD),
    code(DATA),
    markdown(
        """\
## 2. The strategy in bt

A bt `Algo` computes both averages from the data bt has revealed so far and
transacts the share difference at bt's price for the day, the close.
Commission is bt's `commissions` callable."""
    ),
    code(
        """\
class MovingAverageCross(bt.Algo):
    \"\"\"Holds 100 x signal shares; the signal is lagged `lag` bars.\"\"\"

    def __init__(self, lag: int) -> None:
        super().__init__()
        self.lag = lag

    def __call__(self, target) -> bool:
        closes = target.universe[ts.INSTRUMENT].dropna()
        if len(closes) <= self.lag:
            return True
        seen = closes.iloc[: len(closes) - self.lag]
        fast = seen.rolling(ts.FAST).mean().iloc[-1]
        slow = seen.rolling(ts.SLOW).mean().iloc[-1]
        signal = 1 if fast > slow else 0
        session = seen.index[-1].tz_convert(ts.EXCHANGE_TIMEZONE).normalize().tz_localize(None)
        if ts.SHORT_FIRST_SIGNAL_SESSION <= session <= ts.SHORT_LAST_SIGNAL_SESSION:
            signal = -1
        wanted = ts.QUANTITY * signal
        held = target.children[ts.INSTRUMENT].position if ts.INSTRUMENT in target.children else 0.0
        if wanted != held:
            target.transact(wanted - held, child=ts.INSTRUMENT)
        return True


def run_bt(lag: int) -> bt.backtest.Result:
    data = prices[["close"]].rename(columns={"close": ts.INSTRUMENT})
    strategy = bt.Strategy("ma_cross", [MovingAverageCross(lag)], children=[ts.INSTRUMENT])
    backtest = bt.Backtest(
        strategy,
        data,
        initial_capital=float(ts.INITIAL_CASH),
        commissions=lambda quantity, price: float(ts.FEE),
        integer_positions=True,
        progress_bar=False,
    )
    return bt.run(backtest)


result = run_bt(lag=1)
print("final value:", result.backtests["ma_cross"].strategy.values.iloc[-1])""",
        "strategy",
    ),
    markdown(
        """\
## 3. Export, map to canonical bundle 1.0, check against the reference

`export_bt_result` reads the completed `bt.Result` and refuses any bt other
than 1.2.0. bt records per-day fees, not per-fill links, so costs are not
linked to fills; there is no trade level."""
    ),
    code(
        """\
EXPORTS = kit.OUTPUT / "bt"
exported = export_bt_result(
    result,
    EXPORTS / "export-correct",
    run_id="bt-correct",
    base_currency=ts.CURRENCY,
    overwrite=True,
)
adapted = build_v1_5d2_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "bt-correct.zip")
kit.bundle_summary(EXPORTS / "bt-correct.zip")""",
        "export",
    ),
    code("kit.compare_fills(bundle, expected)"),
    code("kit.final_value_check(bundle, expected)"),
    *audit_cells(
        "bt",
        "bt",
        "ComparisonLevel.FILL, ComparisonLevel.POSITION, ComparisonLevel.CASH, "
        "ComparisonLevel.COST, ComparisonLevel.EQUITY, ComparisonLevel.RETURN",
        "kit.reference_artifacts(prestart=prices.index[0] - pd.DateOffset(days=1))",
        "Every fill moves one bar earlier.",
    ),
    code(
        """\
exported = export_bt_result(
    run_bt(lag=0),
    EXPORTS / "export-lookahead",
    run_id="bt-lookahead",
    base_currency=ts.CURRENCY,
    overwrite=True,
)
lookahead_bundle = kit.write_bundle(
    build_v1_5d2_service().adapt(exported).artifacts, EXPORTS / "bt-lookahead.zip"
)
lookahead = kit.implementation_risk(reference_bundle, lookahead_bundle, LEVELS, name="bt-lookahead")
kit.summary(lookahead)"""
    ),
    code("kit.families_table(lookahead)"),
    code("print(kit.report_findings(lookahead, 4))"),
    markdown(
        CLOSING_TEMPLATE.format(
            engine="bt",
            lookahead_effect=(
                "produces adverse findings, and the score is withheld because\n"
                "  evidence on some levels became one-sided."
            ),
        )
    ),
]

# --------------------------------------------------------------------------
# 03 Backtrader
# --------------------------------------------------------------------------

BACKTRADER = [
    markdown(
        """\
# Backtrader → canonical bundle → implementation-risk audit

The same toy strategy in **Backtrader 1.9.78.123**. Backtrader has no export
of its own, so the package provides an analyzer that records orders, fills
and the portfolio during the run; the exporter then writes what it recorded.

The bars are fed as naive New York times (16:00) and the analyzer is told
`source_timezone="America/New_York"`, so the export must carry 20:00Z in
summer and 21:00Z in winter. Outputs below come from
`jupyter nbconvert --execute --to notebook --inplace 03_backtrader.ipynb`."""
    ),
    code(
        setup(
            """\
import backtrader
from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    build_v1_5d2_service,
    create_backtrader_audit_analyzer,
    export_backtrader_analysis,
)
""",
            'print("backtrader", backtrader.__version__)',
        )
    ),
    markdown(REFERENCE_MD),
    code(DATA),
    markdown(
        """\
## 2. The strategy in Backtrader

The one-bar execution lag is Backtrader's own market-on-close order: sent with
`exectype=Order.Close` in `next()` on bar t, it fills at the close of bar t+1.
The look-ahead variant reads the next bar's averages (`self.fast[1]`), which
Backtrader's default preloaded mode silently allows."""
    ),
    code(
        """\
class FixedFeePerOrder(backtrader.CommInfoBase):
    \"\"\"A flat fee per execution, whatever the size or price.\"\"\"

    params = (
        ("stocklike", True),
        ("commtype", backtrader.CommInfoBase.COMM_FIXED),
        ("commission", float(ts.FEE)),
    )

    def _getcommission(self, size, price, pseudoexec):
        return float(ts.FEE)


class MovingAverageCross(backtrader.Strategy):
    \"\"\"Long while SMA20 > SMA50, short in the scheduled window, else flat.\"\"\"

    params = (("peek", 0),)  # peek=1 is the look-ahead bug

    def __init__(self) -> None:
        self.fast = backtrader.indicators.SMA(self.data.close, period=ts.FAST)
        self.slow = backtrader.indicators.SMA(self.data.close, period=ts.SLOW)

    def _signal(self, ago: int) -> int:
        session = pd.Timestamp(self.data.datetime.date(ago))
        if ts.SHORT_FIRST_SIGNAL_SESSION <= session <= ts.SHORT_LAST_SIGNAL_SESSION:
            return -1
        return 1 if self.fast[ago] > self.slow[ago] else 0

    def prenext(self) -> None:
        self.next()

    def next(self) -> None:
        peeking = self.p.peek and len(self.data) < self.data.buflen()
        signal = self._signal(self.p.peek if peeking else 0)
        self.order_target_size(
            target=signal * ts.QUANTITY, exectype=backtrader.Order.Close
        )


def run_backtrader(peek: int = 0):
    local = prices.copy()
    local.index = local.index.tz_convert(ts.EXCHANGE_TIMEZONE).tz_localize(None)
    cerebro = backtrader.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(ts.INITIAL_CASH))
    cerebro.broker.addcommissioninfo(FixedFeePerOrder())
    cerebro.adddata(
        backtrader.feeds.PandasData(dataname=local, openinterest=None), name=ts.INSTRUMENT
    )
    cerebro.addstrategy(MovingAverageCross, peek=peek)
    cerebro.addanalyzer(
        create_backtrader_audit_analyzer(source_timezone=ts.EXCHANGE_TIMEZONE),
        _name="integrity",
    )
    return cerebro.run()[0]


strategy = run_backtrader()
print("final value:", strategy.broker.getvalue())""",
        "strategy",
    ),
    markdown(
        """\
## 3. Export, map to canonical bundle 1.0, check against the reference

`export_backtrader_analysis` writes what the analyzer recorded and refuses any
Backtrader other than 1.9.78.123. Backtrader exports no trade level."""
    ),
    code(
        """\
EXPORTS = kit.OUTPUT / "backtrader"
exported = export_backtrader_analysis(
    strategy.analyzers.integrity,
    EXPORTS / "export-correct",
    run_id="backtrader-correct",
    base_currency=ts.CURRENCY,
    overwrite=True,
)
adapted = build_v1_5d2_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "backtrader-correct.zip")
kit.bundle_summary(EXPORTS / "backtrader-correct.zip")""",
        "export",
    ),
    code("kit.compare_fills(bundle, expected)"),
    code("kit.final_value_check(bundle, expected)"),
    *audit_cells(
        "Backtrader",
        "backtrader",
        "ComparisonLevel.FILL, ComparisonLevel.POSITION, ComparisonLevel.CASH, "
        "ComparisonLevel.COST, ComparisonLevel.EQUITY, ComparisonLevel.RETURN",
        "kit.reference_artifacts()",
        "Every fill moves one bar earlier.",
    ),
    code(
        """\
exported = export_backtrader_analysis(
    run_backtrader(peek=1).analyzers.integrity,
    EXPORTS / "export-lookahead",
    run_id="backtrader-lookahead",
    base_currency=ts.CURRENCY,
    overwrite=True,
)
lookahead_bundle = kit.write_bundle(
    build_v1_5d2_service().adapt(exported).artifacts, EXPORTS / "backtrader-lookahead.zip"
)
lookahead = kit.implementation_risk(
    reference_bundle, lookahead_bundle, LEVELS, name="backtrader-lookahead"
)
kit.summary(lookahead)"""
    ),
    code("kit.families_table(lookahead)"),
    code("print(kit.report_findings(lookahead, 4))"),
    markdown(
        CLOSING_TEMPLATE.format(
            engine="Backtrader",
            lookahead_effect=(
                "produces adverse findings, and the score is withheld because\n"
                "  evidence on some levels became one-sided."
            ),
        )
    ),
]

# --------------------------------------------------------------------------
# 04 NautilusTrader
# --------------------------------------------------------------------------

NAUTILUS = [
    markdown(
        """\
# NautilusTrader → canonical bundle → implementation-risk audit

The same toy strategy in **NautilusTrader 1.231.0** (Python 3.12+): a
low-level `BacktestEngine` with Nautilus's own `SimpleMovingAverage`
indicators, a NETTING/MARGIN venue (a cash account would deny the short) and a
`FixedFeeModel` of USD 1.00 per order. A market order submitted in `on_bar`
fills at that bar's close.

The exporter reads the four reports Nautilus generates after a run. This
notebook passes them to `export_nautilustrader_reports` itself, reading them
from `engine.trader`. (In 1.5.2 the convenience call
`export_nautilustrader_engine(engine, venue, ...)` looks for the report methods
on the engine instead of `engine.trader` and fails on a real engine; the fix
is on branch `wave3/adapter-e2e`.) Outputs below come from
`jupyter nbconvert --execute --to notebook --inplace 04_nautilustrader.ipynb`."""
    ),
    code(
        setup(
            """\
import warnings

import nautilus_trader
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, FixedFeeModel
from nautilus_trader.config import LoggingConfig, StrategyConfig
from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    build_v1_5d3_service,
    export_nautilustrader_reports,
)
""",
            """\
# nautilus_trader 1.231.0 calls a pandas API that pandas 3.1 deprecates; the
# warning comes from inside the engine and does not concern this example.
warnings.filterwarnings("ignore", message="Timestamp.utcnow is deprecated")
print("nautilus_trader", nautilus_trader.__version__)""",
        )
    ),
    markdown(REFERENCE_MD),
    code(DATA),
    markdown(
        """\
## 2. The strategy in NautilusTrader"""
    ),
    code(
        """\
VENUE = Venue("SIM")
INSTRUMENT_ID = InstrumentId(Symbol(ts.INSTRUMENT), VENUE)
BAR_TYPE = BarType.from_str(f"{INSTRUMENT_ID}-1-DAY-LAST-EXTERNAL")


class MovingAverageCrossConfig(StrategyConfig, frozen=True):
    lag: int = 1  # lag=0 is the look-ahead bug


class MovingAverageCross(Strategy):
    def __init__(self, config: MovingAverageCrossConfig) -> None:
        super().__init__(config)
        self.fast = SimpleMovingAverage(ts.FAST)
        self.slow = SimpleMovingAverage(ts.SLOW)
        self.lag = config.lag
        self.previous_signal = 0

    def on_start(self) -> None:
        self.register_indicator_for_bars(BAR_TYPE, self.fast)
        self.register_indicator_for_bars(BAR_TYPE, self.slow)
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar: Bar) -> None:
        ready = self.fast.initialized and self.slow.initialized
        long_signal = 1 if ready and self.fast.value > self.slow.value else 0
        session = (
            pd.Timestamp(bar.ts_event, unit="ns", tz="UTC")
            .tz_convert(ts.EXCHANGE_TIMEZONE)
            .normalize()
            .tz_localize(None)
        )
        in_short = ts.SHORT_FIRST_SIGNAL_SESSION <= session <= ts.SHORT_LAST_SIGNAL_SESSION
        signal = -1 if in_short else long_signal
        acting = signal if self.lag == 0 else self.previous_signal
        self.previous_signal = signal
        delta = acting * ts.QUANTITY - int(self.portfolio.net_position(INSTRUMENT_ID))
        if delta:
            self.submit_order(
                self.order_factory.market(
                    INSTRUMENT_ID,
                    OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    Quantity.from_int(abs(delta)),
                    time_in_force=TimeInForce.GTC,
                )
            )


def bars() -> list[Bar]:
    return [
        Bar(
            BAR_TYPE,
            Price.from_str(f"{row.open:.2f}"),
            Price.from_str(f"{row.high:.2f}"),
            Price.from_str(f"{row.low:.2f}"),
            Price.from_str(f"{row.close:.2f}"),
            Quantity.from_int(int(row.volume)),
            timestamp.value,
            timestamp.value,
        )
        for timestamp, row in prices.iterrows()
    ]


def run_nautilus(lag: int) -> BacktestEngine:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("EXAMPLE-001"),
            logging=LoggingConfig(log_level="ERROR", bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(ts.INITIAL_CASH, USD)],
        fee_model=FixedFeeModel(Money(ts.FEE, USD)),
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=1),
    )
    engine.add_instrument(
        Equity(
            instrument_id=INSTRUMENT_ID,
            raw_symbol=Symbol(ts.INSTRUMENT),
            currency=USD,
            price_precision=2,
            price_increment=Price.from_str("0.01"),
            lot_size=Quantity.from_int(1),
            ts_event=0,
            ts_init=0,
        )
    )
    engine.add_data(bars())
    engine.add_strategy(MovingAverageCross(MovingAverageCrossConfig(lag=lag)))
    engine.run()
    return engine""",
        "strategy",
    ),
    markdown(
        """\
## 3. Export, map to canonical bundle 1.0, check against the reference

The D3 adapter maps orders, fills, trades, positions, cash (the account
balance) and costs. It has no equity or return level, and positions only at
round-trip closes, so the audit below compares fills, trades, cash and
costs. The account is a MARGIN account, whose balance does not debit the
notional of an open position; the reference cash is therefore the matching
margin balance (`kit.margin_balances()`), built from the reference trades.

NautilusTrader puts a random UUID into every position id, so the trade ids,
`trades.csv` and the bundle's hashes change from run to run; the compared
values do not."""
    ),
    code(
        """\
EXPORTS = kit.OUTPUT / "nautilustrader"


def export_run(engine: BacktestEngine, name: str):
    trader = engine.trader  # a BacktestEngine generates its reports here
    exported = export_nautilustrader_reports(
        trader.generate_orders_report(),
        trader.generate_fills_report(),
        trader.generate_positions_report(),
        trader.generate_account_report(VENUE),
        EXPORTS / f"export-{name}",
        run_id=f"nautilustrader-{name}",
        base_currency=ts.CURRENCY,
        overwrite=True,
    )
    return build_v1_5d3_service().adapt(exported)


engine = run_nautilus(lag=1)
adapted = export_run(engine, "correct")
engine.dispose()
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "nautilustrader-correct.zip")
kit.bundle_summary(EXPORTS / "nautilustrader-correct.zip")""",
        "export",
    ),
    code("kit.compare_fills(bundle, expected)"),
    code("kit.final_value_check(bundle, expected)"),
    *audit_cells(
        "NautilusTrader",
        "nautilustrader",
        "ComparisonLevel.FILL, ComparisonLevel.TRADE, ComparisonLevel.CASH, "
        "ComparisonLevel.COST",
        "kit.reference_artifacts(cash=kit.margin_balances())",
        "Without an equity or return level, almost no Nautilus record exists at "
        "the same instant in both runs once every fill moves a bar (only the "
        "opening balance does), so the shift shows up as one-sided records "
        "(evidence gaps), not as a measured divergence.",
    ),
    code(
        """\
engine = run_nautilus(lag=0)
lookahead_adapted = export_run(engine, "lookahead")
engine.dispose()
lookahead_bundle = kit.write_bundle(
    lookahead_adapted.artifacts, EXPORTS / "nautilustrader-lookahead.zip"
)
lookahead = kit.implementation_risk(
    reference_bundle, lookahead_bundle, LEVELS, name="nautilustrader-lookahead"
)
kit.summary(lookahead)"""
    ),
    code("kit.levels_table(lookahead)"),
    code("kit.findings_counts(lookahead)"),
    markdown(
        CLOSING_TEMPLATE.format(
            engine="NautilusTrader",
            lookahead_effect=(
                "is visible, but only as one-sided fills, costs, trades and\n"
                "  balances (evidence gaps): nothing can be measured, so there is\n"
                "  no score and no adverse finding. A per-bar equity record in the\n"
                "  exporter would let the same shift surface as a measured\n"
                "  divergence."
            ),
        )
    ),
]

# --------------------------------------------------------------------------
# 05 QuantConnect LEAN
# --------------------------------------------------------------------------

LEAN = [
    markdown(
        """\
# QuantConnect LEAN → canonical bundle → implementation-risk audit

The same toy strategy, written in C# for **QuantConnect LEAN**. LEAN is not a
pip package and needs .NET, so this notebook does not run LEAN. It reads the
two result files that a real local LEAN run wrote, checked in verbatim under
`data/lean/` (sample-output approach): W3-J12 built LEAN from source at commit
`278fcb3` (master when 2.5.17999 was published) with a user-local .NET 10 SDK,
without Docker, and ran `lean/SynMaCrossAlgorithm.cs` once as specified
(`lag1/`) and once with the look-ahead (`lag0/`). A source build reports
itself as 2.5.0.0, so the version passed to the exporter, 2.5.17999, is a
declaration based on that commit.

**Which code produced the outputs below.** The 1.5.2 exporter cannot read
LEAN 2.5's own serialization (it stops with
`ValueError: order time is ambiguous.`). W3-J12 fixed that on branch
`wave3/adapter-e2e` (commits 9b9b072, 9535748, 6b708c5, 3f264fc, 0a6ad5e,
afa7b80), which the 1.5.2 release candidate merges. This notebook was executed
against a temporary merge of 1.5.2 with that branch; the first code cell prints
where the package was imported from. After the merge it runs as is."""
    ),
    code(
        setup(
            """\
import json

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    build_v1_5d3_service,
    export_quantconnect_lean_results,
)
""",
            'LEAN_VERSION = "2.5.17999"  # producer-declared (see above)',
        )
    ),
    markdown(REFERENCE_MD),
    code(DATA),
    markdown(
        """\
## 2. The strategy in LEAN (C#)

Twenty minutes before the close, the algorithm acts on the last completed
bar's signal from LEAN's own SMA indicators with a market-on-close order,
which LEAN fills at that day's close. The order logic:"""
    ),
    code(
        """\
source = Path("lean/SynMaCrossAlgorithm.cs").read_text(encoding="utf-8")
start = source.index("        private void Rebalance")
print(source[start : source.index("\\n        }\\n", start) + 10])"""
    ),
    code(
        """\
def lean_files(lag: int) -> tuple[Path, Path]:
    folder = Path("data/lean") / f"lag{lag}"
    return folder / "SynMaCrossAlgorithm.json", folder / "SynMaCrossAlgorithm-order-events.json"


statistics = json.loads(lean_files(1)[0].read_text(encoding="utf-8"))["statistics"]
{key: statistics[key] for key in ("Total Orders", "End Equity", "Total Fees")}""",
        "strategy",
    ),
    markdown(
        """\
## 3. Export, map to canonical bundle 1.0, check against the reference

`export_quantconnect_lean_results` reads LEAN's result JSON and order-events
JSON. The D3 adapter derives positions from fills and returns from LEAN's
equity chart, and says so in its warnings. There is no trade level."""
    ),
    code(
        """\
EXPORTS = kit.OUTPUT / "quantconnect_lean"
result_file, events_file = lean_files(1)
exported = export_quantconnect_lean_results(
    result_file,
    events_file,
    EXPORTS / "export-correct",
    run_id="lean-correct",
    base_currency=ts.CURRENCY,
    engine_version=LEAN_VERSION,
    overwrite=True,
)
adapted = build_v1_5d3_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "lean-correct.zip")
kit.bundle_summary(EXPORTS / "lean-correct.zip")""",
        "export",
    ),
    code("kit.compare_fills(bundle, expected)"),
    code("kit.final_value_check(bundle, expected)"),
    markdown(
        """\
LEAN samples equity at its own chart instants (each New York midnight and
close), so the reference equity is sampled at the same instants, read from
LEAN's file; positions are compared after each fill."""
    ),
    code(
        """\
def lean_equity_instants(lag: int) -> list[pd.Timestamp]:
    result = json.loads(lean_files(lag)[0].read_text(encoding="utf-8"))
    candles = result["charts"]["Strategy Equity"]["series"]["Equity"]["values"]
    return [pd.Timestamp(candle[0], unit="s", tz="UTC") for candle in candles]"""
    ),
    *audit_cells(
        "LEAN",
        "lean",
        "ComparisonLevel.FILL, ComparisonLevel.POSITION, ComparisonLevel.COST, "
        "ComparisonLevel.EQUITY, ComparisonLevel.RETURN",
        'kit.reference_artifacts(positions_at="fill", equity_at=lean_equity_instants(1))',
        "In the C# algorithm the defect reads the day's close from the price "
        "file before the close and trades on it.",
    ),
    code(
        """\
result_file, events_file = lean_files(0)
exported = export_quantconnect_lean_results(
    result_file,
    events_file,
    EXPORTS / "export-lookahead",
    run_id="lean-lookahead",
    base_currency=ts.CURRENCY,
    engine_version=LEAN_VERSION,
    overwrite=True,
)
lookahead_bundle = kit.write_bundle(
    build_v1_5d3_service().adapt(exported).artifacts, EXPORTS / "lean-lookahead.zip"
)
lookahead = kit.implementation_risk(
    kit.reference_artifacts(positions_at="fill", equity_at=lean_equity_instants(0)),
    lookahead_bundle,
    LEVELS,
    name="lean-lookahead",
)
kit.summary(lookahead)"""
    ),
    code("kit.families_table(lookahead)"),
    code("print(kit.report_findings(lookahead, 4))"),
    markdown(
        CLOSING_TEMPLATE.format(
            engine="LEAN",
            lookahead_effect=(
                "produces adverse findings, and the score is withheld because\n"
                "  evidence on some levels became one-sided."
            ),
        )
        + """
- LEAN itself was not run here; the result files are a recorded run. To
  regenerate them, build LEAN and run `tests/e2e/lean/run_lean.py` from
  branch `wave3/adapter-e2e` (part of the 1.5.2 release candidate).
"""
    ),
]

NOTEBOOKS = {
    "01_vectorbt.ipynb": VECTORBT,
    "02_bt.ipynb": BT,
    "03_backtrader.ipynb": BACKTRADER,
    "04_nautilustrader.ipynb": NAUTILUS,
    "05_quantconnect_lean.ipynb": LEAN,
}


if __name__ == "__main__":
    for name, cells in NOTEBOOKS.items():
        notebook(cells, HERE / name)
        print("wrote", name)
