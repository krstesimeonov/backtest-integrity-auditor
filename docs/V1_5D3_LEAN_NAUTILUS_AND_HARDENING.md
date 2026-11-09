# V1.5D3 LEAN, NautilusTrader, and Adapter Hardening

Status: implemented in package `1.5.0a6`.

V1.5D3 completes the accepted five-engine roadmap. It adds exporters and
SDK-neutral mappers for QuantConnect LEAN and NautilusTrader, then makes a
complete, fail-closed registry an executable invariant. Like D1/D2, this
increment consumes completed evidence and never starts a backtest.

## Frozen compatibility matrix

| Engine | Exact tested version | Export format ID | Adapter version |
|---|---:|---|---:|
| vectorbt | `1.1.0` | `backtest-auditor.vectorbt` | `1.0.0` |
| bt | `1.2.0` | `backtest-auditor.bt` | `1.0.0` |
| Backtrader | `1.9.78.123` | `backtest-auditor.backtrader` | `1.0.0` |
| QuantConnect LEAN | `2.5.17999` | `backtest-auditor.quantconnect-lean` | `1.0.0` |
| NautilusTrader | `1.231.0` | `backtest-auditor.nautilustrader` | `1.0.0` |

All formats use the verified D1 envelope and adapter-metadata version `1.0`.
The complete D3 registry requires exactly one adapter for each roadmap engine,
one exact tested engine version, no undisclosed/untested-version opt-in, and
project-namespaced adapter and format IDs.

LEAN's standard result JSON does not disclose the NuGet package version. Its
export call therefore requires an explicit producer declaration and retains
`quantconnect_lean.engine_version_producer_declared`. This is provenance, not
independent attestation. A mismatched declaration is fatal.

NautilusTrader `1.231.0` supports Python 3.12–3.14. The optional dependency is
installed on Python 3.12+; the SDK-neutral base mapper remains usable on every
project-supported Python version.

## D3 evidence matrix

`export` means direct engine evidence, `derived` means a documented
deterministic transformation, and `—` means unavailable.

| Comparison level | QuantConnect LEAN | NautilusTrader |
|---|---|---|
| Strategy specification | — | — |
| Market data | — | — |
| Signal | — | — |
| Order | export | export |
| Fill | export | export |
| Trade | — | export |
| Position | derived | derived |
| Cash | — | export |
| Cost | export | export |
| Equity | export | — |
| Return | derived | — |

The difference is deliberate. LEAN's built-in Strategy Equity chart is valid
equity evidence but its standard local result does not contain a full cash
history. Nautilus account reports are cash balances; they are not promoted to
portfolio equity without valuation evidence. No return series is invented from
cash. Neither adapter promotes charts or position marks to exact market data.

## QuantConnect LEAN workflow and semantics

Local LEAN writes `<algorithmId>.json` and
`<algorithmId>-order-events.json`. Export the completed pair:

```python
from backtest_auditor.implementation_risk import (
    build_v1_5d3_service,
    export_quantconnect_lean_results,
)

source = export_quantconnect_lean_results(
    "backtests/run/algorithm.json",
    "backtests/run/algorithm-order-events.json",
    "lean-audit-export.zip",
    run_id="lean-run-001",
    base_currency="USD",
    engine_version="2.5.17999",
)
mapped = build_v1_5d3_service().adapt(source)
```

- Final `Orders` records map IDs, symbols, quantities, sides, supported types,
  final statuses, timestamps, and price constraints.
- LEAN does not retain a separate submission timestamp in final orders. For
  submitted lifecycle states the mapper uses creation time and retains a
  warning.
- Each non-zero order event fill becomes one canonical fill. Its fee becomes a
  fill-linked commission cost in the fee's disclosed currency, keeping its
  sign (a negative fee is a rebate). An order's last update is the latest of
  `lastUpdateTime`, `lastFillTime` and `canceledTime`.
- Net quantity snapshots are accumulated by `(timestamp, instrument)` from the
  sorted fill stream. They intentionally contain no invented average cost,
  market price, value, or P&L.
- Built-in `Strategy Equity / Equity` points map directly to total equity.
  Consecutive values produce simple returns; a zero predecessor is fatal rather
  than silently divided or skipped.
- Closed-trade grouping is not mapped in D3 because the result-level grouping
  is not treated as a universal execution-to-trade convention.

The exporter accepts LEAN's numeric enum values and canonical enum names, both
root result objects and `Results` wrappers, and order-event arrays or the
timestamp-bucket representation. Ambiguous duplicate forms, naive timestamps,
non-finite values, unknown enum values, missing orders, duplicate IDs, and
unknown fill-to-order links are fatal.

LEAN 2.5's own serialization (checked against a local LEAN run, commit
`278fcb3`, in `tests/e2e/test_lean.py`) is read as LEAN writes it:

- orders carry `time` and its alias `createdTime`; equal instants are one
  fact, different ones stay ambiguous;
- `properties.timeInForce` is an object: `{"$type": "...DayTimeInForce"}`,
  or `{}` for GoodTilCanceled, the converter's default;
- order-event `id` is the text `<algorithmId>-<orderId>-<orderEventId>`;
- Strategy Equity is a candlestick series of `[time, open, high, low, close]`
  points, each one sample; the close is the equity at that time. `[time,
  value]` and `{"x", "y"}` points are also accepted.

## NautilusTrader workflow and semantics

The direct convenience function calls the four documented report methods on an
already completed engine (on a 1.231.0 `BacktestEngine` they live on
`engine.trader`, which the exporter uses when the engine lacks them):

```python
from backtest_auditor.implementation_risk import (
    build_v1_5d3_service,
    export_nautilustrader_engine,
)

source = export_nautilustrader_engine(
    engine,
    venue,
    "nautilus-audit-export",
    run_id="nautilus-run-001",
    base_currency="USD",
)
mapped = build_v1_5d3_service().adapt(source)
```

`export_nautilustrader_reports` accepts the same completed orders, individual
fills, positions-with-snapshots, and single-account report DataFrames when the
caller has already generated them.

- Orders map final lifecycle, quantity, type, time-in-force, and price fields.
- `generate_fills_report()` supplies one row per individual `OrderFilled`
  event. Fill commission and liquidity side remain linked to that event.
- Position and snapshot rows map to canonical trades using the native
  `position_id` grouping. The report does not list every contributing fill ID,
  so the mapper does not fabricate those links.
- At each reported position update timestamp, quantities are summed by
  instrument into quantity-only canonical snapshots. This remains different
  from a simultaneous market-valued portfolio snapshot. A row states the
  instrument's net quantity only while no other position of it is open, so
  overlapping positions (HEDGING, or several strategies) are refused.
- The account report maps timestamp/currency totals. The exporter requires one
  account/venue scope; duplicate timestamp/currency balances are fatal.
- The documented no-data result is an empty DataFrame. D3 preserves it as an
  available-but-empty level instead of marking the report unavailable.

## Files and deterministic examples

LEAN exports contain `adapter-metadata.json`, `lean-orders.csv`,
`lean-fills.csv`, and `portfolio-series.csv`. NautilusTrader exports contain
`adapter-metadata.json`, `nautilustrader-orders.csv`,
`nautilustrader-fills.csv`, `nautilustrader-positions.csv`, and
`nautilustrader-cash.csv`. Both also contain `engine-export.json`.

CSV columns, order, UTF-8 bytes, decimal spelling, and UTC timestamps are exact.
Directory and ZIP transports normalize to identical verified content, while
repeated ZIP exports are byte-for-byte deterministic.

Inspectable examples live under `examples/v1_5d3_engine_exports`. Reproduce
and map them with the exact engine extra installed:

```bash
python scripts/generate_v1_5d3_engine_examples.py --check
```

## Cross-adapter hardening and verification

D3 verifies the five descriptors in frozen roadmap order and exercises:

- directory/ZIP equivalence and repeatable ZIP bytes;
- exact engine and export-format versions;
- source payload hashes, sizes, roles, and media types before mapping;
- all eleven static capability declarations per engine;
- exact declared-versus-emitted evidence levels;
- available-empty versus unavailable semantics;
- order/fill/cost and trade reference integrity;
- deterministic canonical bundle identity;
- mapping of committed examples from a base installation with no engine SDK;
- real NautilusTrader `1.231.0` `ReportProvider` output;
- clean wheel and source-archive installation gates.

## References and exclusions

The source contracts are grounded in the official
[LEAN local result documentation](https://www.quantconnect.com/docs/v2/local-platform/backtesting/results),
[LEAN source](https://github.com/QuantConnect/Lean), and
[NautilusTrader report documentation](https://nautilustrader.io/docs/latest/concepts/reports/).
Exact versions are frozen from the official
[QuantConnect.Lean.Engine NuGet package](https://www.nuget.org/packages/QuantConnect.Lean.Engine/)
and [NautilusTrader releases](https://github.com/nautechsystems/nautilus_trader/releases).

V1.5D3 changes neither V1 report schema `2.5`, audit-run-manifest schema `1.1`,
database schema `1`, nor canonical artifact/bundle schema `1.0`. It adds no
cross-run alignment, tolerance policy, comparison, root-cause attribution,
implementation-risk report, CLI, Streamlit workflow, persistence, broker
connection, order placement, live reconciliation, or claim that one engine is
ground truth. Those remain later increments.
