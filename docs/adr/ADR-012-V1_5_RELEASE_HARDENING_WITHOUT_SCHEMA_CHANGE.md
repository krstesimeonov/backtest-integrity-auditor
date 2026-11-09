# ADR-012: Harden V1.5 Without Changing Public Audit Semantics

Status: accepted for package `1.5.0`.

## Context

V1.5A–I complete the implementation-risk feature path and introduce separate
implementation-risk report and manifest schemas `1.0`. The remaining risk is
release drift: self-confirming examples, unbounded inputs, partial writes,
source-tree-only packaging success, performance regressions, and dirty source
archives. Adding fields or recalculating evidence in a release layer would
weaken rather than harden the existing contracts.

## Decision

V1.5J freezes the V1.5I report shape and interpretation. It adds independent
golden/reference data, deterministic invariant tests, explicit performance
budgets, clean-wheel verification, fail-closed source-archive verification,
bounded policy/candidate upload boundaries, and atomic opt-in overwrite for the
implementation-risk CLI.

The golden reports omit manifests because manifest environment identity is
supposed to differ across environments. Manifest shape, hashing, and identity
linkage remain covered separately. No environment value is forged merely to
make a cross-platform golden file stable.

## Consequences

- Package `1.5.0` can be reproduced and checked without altering any public
  report, manifest, database, or canonical evidence schema.
- Exact agreement remains `not_assessed` when no divergence observations exist;
  it is not converted into a zero-risk certificate.
- Release checks are stricter and slower than a unit-only workflow, but their
  failures identify contract, performance, packaging, or archive drift.
- Public publication still waits for explicit owner decisions about licensing,
  ownership, tagging, repository metadata, and destination.
