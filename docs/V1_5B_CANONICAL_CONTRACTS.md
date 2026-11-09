# V1.5B Canonical Strategy and Artifact Contracts

Status: implemented in package `1.5.0a2`.

V1.5B defines the engine-neutral evidence that later increments will parse,
align, compare, and attribute. It remains domain work only: no backtesting
engine is imported or executed, and no file parser, tolerance, comparison,
report, CLI, Streamlit workflow, or persistence adapter is included.

## Central separation

The contracts separate two questions that must not be conflated:

1. **What strategy was intended?** `StrategySpecification` records strategy
   identity, logic identity, universe, parameters, data frequency, signal
   timing, signal model, and sizing model.
2. **How did this engine simulate it?** `SimulationSpecification` records base
   currency, initial cash, calendar and timezone, data adjustment, execution
   timing and model, accounting model, cost models, shorting, and fractional
   quantity policy.

`CanonicalRunSpecification` contains both sections without treating a
simulation assumption as strategy logic. This is necessary for honest
attribution: two runs can implement the same intended strategy while producing
different results because of execution, cost, or accounting choices.

## Specification contracts

| Contract | Purpose |
|---|---|
| `CanonicalParameter` | Named scalar parameter with optional unit; nested configuration uses dotted names |
| `InstrumentReference` | Stable instrument ID, asset class, symbol, currency, optional venue, multiplier, and attributes |
| `ModelSpecification` | Named model with typed parameters, optional version, and optional implementation SHA-256 |
| `StrategySpecification` | Intended strategy logic and universe, independent from simulation mechanics |
| `SimulationSpecification` | Explicit run-specific execution, accounting, cost, and capital assumptions |
| `CanonicalRunSpecification` | One strategy specification paired with one simulation specification |

Parameter values may be strings, integers, `Decimal`, booleans, or `None`.
Binary floating-point values are rejected. Lists, mappings, and arbitrary
objects are also rejected; nested declarations use stable dotted parameter
names instead of an unbounded recursive object model.

## Artifact contracts

| Comparison level | Canonical record | Important semantics |
|---|---|---|
| `market_data` | `MarketDataObservation` | Long-format numeric field; economic event time is separate from first availability time |
| `signal` | `SignalRecord` | Explicit target quantity, weight, notional, score, entry, exit, or custom semantics |
| `order` | `OrderRecord` | Side, quantity, type, time-in-force, status, timestamps, optional signal and parent lineage |
| `fill` | `FillRecord` | Order link, timestamp, side, quantity, price, currency, liquidity role, and venue |
| `trade` | `TradeRecord` | Engine-declared grouping method, open/close state, prices, realized P&L, and fill links |
| `position` | `PositionSnapshot` | Signed quantity plus optional price, value, cost, and realized/unrealized P&L |
| `cash` | `CashBalance`, `CashMovement`, `CashArtifacts` | Currency balances and signed movements remain independently available |
| `cost` | `CostRecord` | Signed P&L impact: negative is a cost and positive is a rebate |
| `equity` | `EquityPoint` | Total equity plus optional cash, gross exposure, and signed net exposure |
| `return` | `ReturnPoint` | Explicit interval and simple or log convention |

The `strategy_specification` level uses `CanonicalRunSpecification`. All eleven
levels therefore have concrete engine-neutral domain contracts.

## Numeric and time rules

- Financial values use `Decimal`; Python `float` is rejected at the boundary.
  This prevents an adapter-dependent binary representation from becoming part
  of comparison evidence.
- Every timestamp must be timezone-aware and is normalized to UTC. A naive
  timestamp is invalid; the domain does not guess its timezone.
- Market data keeps both `event_timestamp` and `available_timestamp`. The
  latter cannot be earlier than the event timestamp.
- Values must be finite. Quantities and executable prices that must be positive
  are validated as such; signed quantities, P&L, cash, exposure, and return
  values retain their economic sign.
- Currency identifiers normalize to uppercase and accept ISO-style codes plus
  longer engine-neutral units such as valid digital-asset denominations.

## Canonical collections and missing evidence

`CanonicalRunArtifacts` binds one `EngineRunReference` to every artifact level
that an adapter can substantiate. Its artifact schema version is `1.0`.

The missing-data rule is strict:

- `None` means the level was not supplied and is unavailable.
- `()` means the level was supplied, validated, and contains no records.

These states are not interchangeable. For example, `fills=None` cannot refute
an order's filled status because fill evidence is unavailable. `fills=()` can:
the adapter explicitly supplied a complete empty fill collection, so a
`FILLED` order is contradictory.

Cash uses a nested `CashArtifacts` object because balance history and movement
history can be available independently. Every collection has stable identity
keys and canonical ordering. Invalid input fails; the domain never silently
sorts event series, deduplicates records, or repairs references.

## Conditional cross-record integrity

The bundle checks relationships only when the related evidence level is
available. This preserves partial evidence without inventing facts.

When the relevant levels are available, it validates:

- artifact instrument IDs against the declared strategy universe;
- fill, trade, and position currency against instrument currency;
- parent-order existence and parent-before-child timing;
- signal existence, instrument identity, and signal-before-order timing;
- fill existence, order identity, side, instrument, timing, and cumulative
  quantity;
- exact fill quantities for `FILLED` and `PARTIALLY_FILLED` status claims, and
  absence of fills for clearly unfilled statuses;
- trade-to-fill existence and instrument identity;
- cost-to-order, fill, and trade references; and
- equity currency against the simulation base currency.

An upstream level that is `None` leaves its references visible but unverified.
An available empty upstream collection makes every such reference unknown and
therefore invalid. This is deliberate evidence-bounded validation.

## SHA-256 roles

The user is not expected to type hashes manually. Adapters calculate source
and implementation identities:

- `EngineRunReference.source_sha256` identifies the exact exported source
  bytes assessed by the auditor.
- `StrategySpecification.logic_sha256` identifies the exact intended logic
  declaration used for the run.
- `ModelSpecification.implementation_sha256`, when available, identifies a
  particular model implementation.

A SHA-256 value is provenance, not a digital signature and not proof that an
engine or export is correct. It prevents different evidence from being treated
as identical merely because a filename, strategy name, or run ID matches.

## Public API example

```python
from datetime import datetime, timezone
from decimal import Decimal

from backtest_auditor.implementation_risk import (
    CanonicalRunArtifacts,
    EngineRunReference,
    FillRecord,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)

timestamp = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
run = EngineRunReference("run-1", "engine", "1.0", "a" * 64)
order = OrderRecord(
    "order-1",
    timestamp,
    "AAPL.XNAS",
    OrderSide.BUY,
    Decimal("10"),
    OrderType.MARKET,
    TimeInForce.DAY,
    OrderStatus.FILLED,
    submitted_at=timestamp,
)
fill = FillRecord(
    "fill-1",
    "order-1",
    timestamp,
    "AAPL.XNAS",
    OrderSide.BUY,
    Decimal("10"),
    Decimal("100"),
    "USD",
)
bundle = CanonicalRunArtifacts(run=run, orders=(order,), fills=(fill,))
```

## Implemented by V1.5C

- A versioned hybrid JSON/CSV contract, deterministic directory/ZIP writer,
  strict reader, engine-neutral ports, typed validation failures, schemas, and
  example bundle are implemented in `1.5.0a3`. See
  [`V1_5C_FILE_BUNDLE_CONTRACT.md`](V1_5C_FILE_BUNDLE_CONTRACT.md).

## Deliberately deferred beyond V1.5C

- Engine-specific field mappings.
- Session, symbol, currency, frequency, and timestamp alignment policy.
- Numeric tolerances and deterministic pairwise comparison.
- Canonical trade reconstruction when an engine does not export trades.
- Materiality, causal attribution, and uncertainty findings.
- Versioned V1.5 reports, CLI, Streamlit, schemas, and manifest integration.

V1 report schema `2.5`, audit-run-manifest schema `1.1`, database schema `1`,
and all V1 statistical behavior remain unchanged.

## Definition of done

- Intended strategy logic and simulation mechanics are separate immutable
  contracts.
- Every comparison level has an explicit canonical record shape.
- Numeric, time, enum, identity, ordering, and missing-evidence semantics are
  deterministic.
- Cross-record validation is strict where evidence exists and makes no claim
  where the relevant level is unavailable.
- The implementation-risk domain remains standard-library-only and independent
  of engines, files, persistence, presentation, reporting, and V1 statistics.
- Formatting, lint, focused static typing, coverage, build, clean-wheel import,
  deterministic CLI, and the complete inherited regression suite pass.
