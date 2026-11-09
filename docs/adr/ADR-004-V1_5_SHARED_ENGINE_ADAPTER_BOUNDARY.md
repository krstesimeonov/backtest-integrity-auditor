# ADR-004: Use a verified common envelope and explicit registry for engine adapters

- Status: accepted
- Date: 2026-08-15
- Decision owner: V1.5 Implementation Risk Engine

## Context

V1.5 will normalize exports from vectorbt, bt, Backtrader, QuantConnect LEAN,
and NautilusTrader. Their files, terminology, versioning, and evidence depth
differ substantially. Implementing the first mapper without a shared boundary
would let its assumptions leak into later adapters and make provenance or
missing evidence inconsistent.

## Decision

All concrete mappers will consume a verified versioned engine-export envelope,
enter through a runtime-checkable `EngineArtifactMapper` port, publish a full
eleven-level capability descriptor, and be resolved by an explicitly
constructed deterministic registry. A shared service will enforce exact
version policy, source identity, run identity, declared/actual level equality,
capability promises, warning references, and canonical output identity.

The auditor will not import or execute any engine SDK. Optional exporter
helpers run outside the auditor and emit the same envelope.

## Consequences

Positive:

- Raw and normalized identities are both retained.
- Engine-specific terms end at one anti-corruption boundary.
- Unsupported evidence cannot be silently represented as empty evidence.
- Version acceptance and warnings are explicit and testable.
- D2/D3 mappers can be tested against one conformance contract.

Costs:

- Export producers must create one small manifest in addition to native files.
- New adapters must declare capability and version policy before registration.
- Large exports are bounded and loaded as immutable verified bytes; streaming
  would require a later versioned extension rather than an invisible behavior
  change.

## Rejected alternatives

Import engine SDKs in the auditor
: Rejected because it couples audits to heavy, conflicting environments and
  permits accidental execution.

Dispatch by filename or inferred columns
: Rejected because ambiguous detection can select the wrong mapper and hide
  export-contract changes.

Trust adapter-returned hashes and availability
: Rejected because an adapter bug could silently change run identity or drop
  an evidence level.

Use a mutable global plugin registry
: Rejected because import order would affect behavior and make installed
  results harder to reproduce.

Treat every mapping issue as a warning
: Rejected because provenance, version, identity, and domain contradictions
  invalidate the import and must remain fatal.
