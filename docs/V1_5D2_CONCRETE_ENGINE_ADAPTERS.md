# V1.5D2 Concrete Engine Adapters

Status: implemented in package `1.5.0a5`.

V1.5D2 adds executable exporters and file-only canonical mappers for vectorbt,
bt, and Backtrader. Engine code runs only in the optional exporter environment.
The auditor verifies and maps the resulting files without importing or executing
an engine SDK.

## Frozen compatibility matrix

| Engine | Exact tested version | Export format ID | Adapter version |
|---|---:|---|---:|
| vectorbt | `1.1.0` | `backtest-auditor.vectorbt` | `1.0.0` |
| bt | `1.2.0` | `backtest-auditor.bt` | `1.0.0` |
| Backtrader | `1.9.78.123` | `backtest-auditor.backtrader` | `1.0.0` |

All three use common envelope version `1.0` and adapter-metadata version `1.0`.
An absent, different, or untested engine version is fatal. Supporting another
engine version requires explicit conformance evidence and a release change.

Install the optional SDKs only where backtests are executed:

```bash
python -m pip install -e ".[engine-exporters]"
```

The base installation deliberately excludes all three SDKs and can still map
any valid committed export.

## Evidence capability matrix

`export` means direct engine evidence, `derived` means deterministic
reconstruction from exported evidence, and `—` means unavailable rather than
available-empty.

| Comparison level | vectorbt | bt | Backtrader |
|---|---|---|---|
| Strategy specification | — | — | — |
| Market data | — | — | — |
| Signal | — | — | — |
| Order | derived | derived | export |
| Fill | export | export | export |
| Trade | export | — | — |
| Position | export | export | export |
| Cash | export | export | export |
| Cost | export | export | export |
| Equity | export | export | export |
| Return | export | derived | derived |

Snapshot valuation prices are not promoted to market-data history. Arbitrary
strategy code, Algo stacks, and signals are not inferred. bt and Backtrader
transactions are not grouped into trades because neither engine freezes one
universal grouping policy at this boundary.

## Export and map workflow

An exporter consumes an already executed engine result and writes a verified
directory or deterministic ZIP. Mapping is a separate, SDK-neutral action:

```python
from backtest_auditor.implementation_risk import (
    build_v1_5d2_service,
    export_vectorbt_portfolio,
)

exported = export_vectorbt_portfolio(
    portfolio,
    "run-export",
    run_id="run-001",
    instrument_id="AAPL",
    base_currency="USD",
)
mapped = build_v1_5d2_service().adapt(exported)
```

The equivalent exporter entry points are `export_bt_result` and
`export_backtrader_analysis`. The Backtrader workflow first attaches the class
returned by `create_backtrader_audit_analyzer(source_timezone="UTC")` to
`Cerebro`; this captures order notifications and execution bits while the
engine runs.

Exporters never start a backtest. They accept executed objects, validate the
documented structures, canonicalize records, and write the D1 envelope. The
auditor then verifies all payload hashes and sizes, selects the mapper from an
explicit registry, validates exact versions and declared levels, and computes
the normalized canonical-bundle identity.

## Engine semantics

### vectorbt

- One single-column `Portfolio` is exported with an explicit canonical
  `instrument_id`.
- `portfolio.orders.records_readable` contains filled-order records. Each row
  maps to one fill and one synthetic canonical order with final status
  `filled`.
- `portfolio.positions.records_readable` supplies vectorbt's position grouping
  and maps to canonical trades.
- Assets, close, and asset value produce position snapshots; cash and value
  produce cash/equity histories; order fees produce fill-linked costs.
- The undefined first period return is omitted from canonical return evidence.

The mapper retains `vectorbt.filled_orders_reconstructed` and
`vectorbt.initial_return_omitted` warnings.

### bt

- The result must identify exactly one executed backtest unless
  `strategy_name` is supplied.
- `Result.get_transactions()` must use the documented `Date`/`Security`
  MultiIndex and quantity/price columns. Each transaction maps to a fill and a
  synthetic filled order.
- Strategy position, cash, value, fee, and flow-adjusted price histories must
  share the exact increasing timezone-aware index.
- Returns are deterministic period changes in the flow-adjusted strategy price
  series. Timestamp-level fees become commission costs but are not linked to a
  specific order or fill.

The mapper retains `bt.aggregate_fees_unlinked` and
`bt.transactions_reconstructed_orders` warnings.

`Result.get_transactions()` is the change in position between bars, so
several executions on one bar would collapse into their net. The exporter
therefore refuses a run whose recorded fees on a bar differ from the
strategy's `commission_fn` applied to that bar's net transactions (a
zero-fee strategy cannot be checked this way). Position values include the
security's `multiplier`.

### Backtrader

- Every data feed must have a non-empty unique name used as the canonical
  instrument ID.
- The audit analyzer records final order lifecycle fields from notifications
  and maps each previously unseen `OrderExecutionBit` to one canonical fill.
- Per-bar positions use feed close prices; broker cash and value supply the
  portfolio series; execution-bit commission produces fill-linked cost.
- Simple returns are derived from consecutive broker-equity observations.
- Backtrader datetimes may be naive, so the caller must explicitly name the
  source IANA timezone. The exporter never guesses one. It reads the bar time
  Backtrader stored: UTC when Backtrader converted the input itself (a
  tz-aware pandas index or `tzinput`), otherwise the naive wall time in
  `source_timezone`; a feed's or Cerebro's display `tz` does not move rows.
- `broker.set_shortcash(False)` is refused: `getcash()` then debits short
  sales and is not the account's cash. Fill commission excludes the short
  interest that `int2pnl` folds into a closing execution (that interest is in
  cash and equity). Position values include the commission-info multiplier.

Unknown order types remain custom with a warning. Backtrader `Margin` status
maps to canonical rejected status with a retained warning because the terms
are not identical.

## File contracts

Every engine directory contains canonical `engine-export.json` and
`adapter-metadata.json`. Metadata contains only
`adapter_export_schema_version` and the three-letter uppercase base currency.
The remaining exact payloads are:

| Engine | Payloads |
|---|---|
| vectorbt | `vectorbt-orders.csv`, `vectorbt-positions.csv`, `position-snapshots.csv`, `portfolio-series.csv` |
| bt | `bt-transactions.csv`, `position-snapshots.csv`, `portfolio-series.csv` |
| Backtrader | `backtrader-orders.csv`, `backtrader-fills.csv`, `position-snapshots.csv`, `portfolio-series.csv` |

CSV columns, order, UTF-8 representation, decimal spelling, and UTC timestamp
spelling are strict. Timestamps use `YYYY-MM-DDTHH:MM:SS.ffffffZ`; non-finite
numbers, duplicate rows/keys, unexpected payloads, index mismatches, and
instrument-scope contradictions fail instead of being repaired.

Generated inspectable examples live under
`examples/v1_5d2_engine_exports`. Reproduce and verify them with:

```bash
python scripts/generate_v1_5d2_engine_examples.py --check
```

## Compatibility and exclusions

V1.5D2 changes neither V1 report schema `2.5`, audit-run-manifest schema `1.1`,
database schema `1`, nor canonical artifact/bundle schema `1.0`. It adds no
cross-run alignment, tolerances, comparison, root-cause attribution, CLI,
Streamlit, persistence, broker connection, or order execution.

QuantConnect LEAN and NautilusTrader remain V1.5D3 together with shared
cross-adapter hardening.
