# ADR-002: Use Immutable Decimal/UTC Canonical Contracts

- Status: Accepted
- Date: 2026-08-15
- Decision owners: project owner and architecture implementation

## Context

V1.5A established an export-only implementation-risk boundary and eleven
independent comparison levels. Part B must define engine-neutral evidence for
those levels without letting the first supported engine determine the domain
model.

Engine exports vary in numeric representation, timestamps, order state,
instrument identity, trade grouping, cost sign, and missing-data behavior. A
weak dictionary or DataFrame contract would move those ambiguities into every
comparison service.

## Decision

Use frozen, slotted dataclasses as the canonical domain API. Separate intended
strategy logic from simulation assumptions. Represent financial values with
`Decimal`, require timezone-aware timestamps and normalize them to UTC, use
explicit enums for artifact semantics, and retain stable record identities.

Bind the available records in a `CanonicalRunArtifacts` aggregate. `None`
means unavailable; an empty tuple means available but empty. Validate identity,
canonical ordering, and cross-record relationships when both related levels
are available. Do not infer or repair unavailable relationships.

## Why

- Strategy intent and engine mechanics can differ independently and must be
  compared or attributed separately.
- `Decimal` prevents binary floating-point artifacts from changing equality at
  the adapter boundary.
- UTC normalization creates one time basis without guessing naive timestamps.
- Explicit missing-versus-empty semantics prevent omitted evidence from being
  misreported as zero activity.
- Immutable records make downstream comparison deterministic and prevent an
  adapter from changing already-validated evidence.
- Conditional referential validation preserves legitimate partial exports
  while detecting contradictions in evidence that was actually supplied.

## Consequences

Positive:

- Comparison code receives typed, normalized, deterministic evidence.
- Engine-specific terminology terminates at future adapter boundaries.
- Order/fill lineage and other contradictions fail before attribution.
- Evidence profiles can be derived directly from bundle availability.

Costs:

- Adapters must convert numeric strings and floats into exact decimal values.
- Naive timestamps require an explicit timezone declaration before entering
  the domain.
- Event collections must already be in canonical order; invalid ordering is
  rejected instead of repaired.
- Recursive arbitrary configuration is not accepted; nested model parameters
  use stable dotted names.

## Rejected alternatives

**Pandas DataFrames as the domain model:** rejected because column names,
dtypes, index semantics, mutation, and missing-value behavior would leak
adapter choices into comparison logic.

**Free-form dictionaries:** rejected because misspelled fields, ambiguous
enums, and implicit optionality would be discovered too late.

**Python floats:** rejected because binary representation is not a stable
financial interchange contract.

**Treat unavailable as empty:** rejected because absence of evidence is not
evidence of no orders, fills, costs, positions, or returns.

**Require every artifact level:** rejected because engines export different
evidence layers and Part A explicitly preserves independent eligibility.

**Silently sort or deduplicate:** rejected because canonicalization must be an
observable adapter action, not an invisible domain repair.

## Revisit conditions

Add a new artifact schema version when a concrete adapter demonstrates a
missing engine-neutral concept that cannot be represented without ambiguity.
Do not weaken Decimal, timezone, or missing-versus-empty semantics for adapter
convenience. A file representation belongs to V1.5C and must map exactly to
these domain decisions.
