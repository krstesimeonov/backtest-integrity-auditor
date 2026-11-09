# ADR-011: Separate V1.5 Report and Manifest Contracts

Status: accepted on 2026-08-21.

## Context

V1 Single-Run and Experiment-Family report schema `2.5` and audit-run-manifest
schema `1.1` are frozen. V1.5 implementation-risk evidence has a different
subject, pipeline, interpretation boundary, and provenance model. Adding V1.5
fields to either V1 report would silently change a completed public contract.

## Decision

V1.5I introduces implementation-risk report schema `1.0` and
implementation-risk run-manifest schema `1.0` as separate public objects.
Reporting consumes the completed normalization, comparison, divergence, and
assessment results. The report carries no aggregate verdict: `overall_status`
is required to be `null`.

The optional manifest binds exported-source identities, normalized canonical
bundle identities, all four policy hashes, the exact findings hash, explicit
audit identity, method versions, package/report versions, and environment
metadata. It does not reuse V1's normalized-return or statistical-method
manifest semantics.

CLI and Streamlit both invoke one application orchestration service. Neither
entry point invokes the other, and neither performs audit calculations.

## Consequences

- Existing V1 consumers remain compatible without learning V1.5 fields.
- V1.5 consumers receive a strict, purpose-specific machine contract.
- A reference remains a baseline, co-occurrence remains non-causal, and no
  global pass/fail can be inferred from the serialized shape.
- V1.5 persistence requires a later explicit schema decision.
- V1.5J can harden these frozen 1.0 objects with independent golden/reference,
  property, performance, build, and installed-resource evidence.
