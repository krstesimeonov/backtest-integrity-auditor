# ADR-003: Use a Hybrid JSON/CSV Directory-or-ZIP Bundle

- Status: Accepted
- Date: 2026-08-15
- Decision owners: project owner and architecture implementation

## Context

V1.5B defines immutable nested specifications and flat time-ordered execution
artifacts. V1.5C needs one versioned external contract that concrete engine
adapters can produce without leaking engine terms into the domain.

Three representations were considered: one JSON document, a JSON/JSONL ZIP,
and a combined JSON/CSV directory or ZIP.

## Decision

Use a hybrid bundle:

- canonical JSON for the manifest and nested run specification;
- canonical CSV for flat artifact histories;
- a separate `trade_fills.csv` relation for trade membership;
- identical semantics in a top-level directory or deterministic ZIP;
- engine-neutral read/write protocols;
- strict hashes, sizes, counts, availability, versions, and round-trip checks;
  and
- typed fail-closed errors with file/row/field context.

An absent unavailable level has no file. An available empty level has a
header-only CSV. Cash balance and movement files remain independently optional.

## Why

- Users can inspect large histories directly with pandas, spreadsheets, SQL
  loaders, or text tools.
- JSON preserves nested configuration and typed scalar parameters without
  inventing fragile flattened columns.
- A normalized relation table avoids hiding JSON inside CSV cells.
- Directory form is convenient for authoring and debugging; ZIP form is
  convenient for transport and hashing.
- One logical contract prevents directory and ZIP behavior from diverging.
- Strict canonical serialization makes hashes and reproducibility meaningful.

## Consequences

Positive:

- Concrete adapters have one stable target.
- Flat data remain accessible without an engine SDK or proprietary format.
- Tampering, truncation, extra files, and contradictory availability fail
  before comparison.
- Exact Decimal and UTC semantics survive file exchange.
- The V1.5B domain remains independent from files and compression.

Costs:

- Canonical CSV is stricter than typical user-authored CSV: line endings,
  timestamp precision, decimals, headers, and ordering are enforced.
- Two JSON Schemas are required in addition to programmatic CSV validation.
- The reader eventually materializes immutable tuples because that is the V1.5B
  domain contract; file-size limits bound this behavior.
- A bundle is an interchange format, not a convenient place for arbitrary
  engine-specific metadata.

## Rejected alternatives

**One JSON document:** rejected because large artifact histories become hard to
inspect, stream, diff, and load into common tabular tools.

**JSONL for every artifact:** technically valid, but rejected for V1.5C because
the artifact records are flat and CSV provides better user inspectability and
tool interoperability.

**Pure CSV:** rejected because strategy, universe, model, and typed parameter
structures do not map cleanly without embedded JSON or lossy flattening.

**Parquet:** deferred because it would add a binary format and runtime
dependency before data volumes demonstrate that need. A later schema version
can add a columnar representation without changing V1.5B objects.

**Accept and normalize permissive files:** rejected because silent trimming,
sorting, decimal conversion, or timestamp repair would make provenance and
hashes ambiguous.

## Revisit conditions

Consider a new bundle schema version when concrete adapter benchmarks show that
CSV parsing or the 1 GB uncompressed limit is a real bottleneck. Any Parquet or
streaming extension must preserve exact Decimal/UTC semantics, explicit
availability, deterministic identities, and the same engine-neutral port.
