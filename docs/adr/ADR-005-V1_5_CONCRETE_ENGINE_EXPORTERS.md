# ADR-005: Keep engine execution outside the auditor and preserve asymmetric evidence

- Status: accepted
- Date: 2026-08-16
- Decision owner: V1.5 Implementation Risk Engine

## Context

vectorbt, bt, and Backtrader expose different executed-result structures.
Their notions of order, transaction, position, trade, fee, and return are not
interchangeable. Importing all SDKs into the auditor would also couple evidence
review to engine dependencies and could make accidental execution possible.

## Decision

Provide optional engine-side exporters for exact tested versions and keep the
auditor-side mappers SDK-neutral. Exporters accept only already executed
objects, emit the verified D1 file envelope, and never start a run. The base
auditor resolves those files through an explicit D2 composition root.

Capabilities remain asymmetric. Evidence is mapped only when the engine
exposes a stable meaning or when one deterministic reconstruction is explicitly
declared. Snapshot prices are not market-data history; filled transactions may
support fills without preserving pre-fill order intent; absent universal trade
grouping remains unavailable.

## Consequences

Positive:

- Audit environments remain engine-free and file-first.
- Exact version and export-format provenance fails closed.
- Derived evidence is distinguishable from engine-exported evidence.
- Each engine can retain its strongest evidence without inventing parity.
- Deterministic examples exercise the same exporter-to-mapper boundary.

Costs:

- Backtests must attach or call a small exporter in their engine environment.
- Exact engine upgrades require new compatibility evidence.
- Some comparison levels remain unavailable even when approximate inference
  would be technically possible.

## Rejected alternatives

Run backtests inside the auditor
: Rejected because auditing must not execute strategies and engine dependency
  conflicts would enter the application boundary.

Declare identical capabilities for every engine
: Rejected because it would misrepresent missing order intent, signal history,
  or trade grouping as comparable evidence.

Infer market data from position snapshots
: Rejected because sparse valuation observations are not the original input
  data history.

Accept arbitrary engine versions with warnings
: Rejected because silent structure or semantic drift can corrupt normalized
  evidence before a warning is meaningful.

Reconstruct all trades from fills
: Rejected because grouping, netting, pyramiding, and trade-ID policies are
  deferred decisions and differ by engine and strategy.
