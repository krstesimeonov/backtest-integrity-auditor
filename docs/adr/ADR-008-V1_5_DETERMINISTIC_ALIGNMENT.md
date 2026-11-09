# ADR-008: Deterministic alignment before interpretation

Status: accepted for V1.5F.

## Decision

Compare only normalized, requested evidence using an explicit per-level
semantic or source-ID policy. Treat duplicate alignment keys as ambiguous and
retain exact field-level deltas and one-sided records as typed evidence.

## Rationale

Ordinal pairing silently invents correspondence. Tolerances and attribution
also answer different questions from whether two canonical records differ.
Keeping alignment and exact comparison separate makes later interpretation
auditable and prevents missing or ambiguous evidence from becoming a verdict.

## Consequences

Policies and results are deterministic and hash-linked to the V1.5E plan.
Consumers must explicitly handle unavailable, empty, one-sided, ambiguous, and
different states. Materiality, scoring, and causal claims are intentionally
outside this decision.
