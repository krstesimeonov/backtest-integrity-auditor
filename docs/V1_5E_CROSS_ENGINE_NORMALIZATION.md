# V1.5E Cross-Engine Normalization

Status: implemented in package `1.5.0a7`.

V1.5E adds the explicit normalization boundary required before two canonical
engine bundles can be aligned or compared. It resolves declared differences in
strategy identity, instrument identity and symbol, denomination identifiers,
timestamp clocks, and frequency labels. It does not compare runs and does not
make unlike evidence equivalent by assumption.

## Safety invariant

Every change is declared in one immutable `ReconciliationNormalizationPlan`.
The service fails closed when a plan is missing a source identity, contains an
unused mapping, disagrees with the reconciliation scope, contradicts canonical
instrument metadata, or produces a bundle that violates the V1.5B contracts.

Normalization is deliberately narrower than transformation:

| Dimension | V1.5E permits | V1.5E does not permit |
|---|---|---|
| Strategy | Explicit source ID to one shared canonical ID | Inferring strategy equivalence from names or returns |
| Instrument | Explicit source ID to one canonical instrument and symbol | Changing asset class, contract multiplier, or denomination economics |
| Currency | Relabeling an attested three-letter denomination ID | FX conversion, scaling, or changing any numerical value |
| Timestamp | A declared fixed UTC microsecond offset per available level | Timezone guessing, event matching, tolerance windows, or clock-drift models |
| Frequency | A shared fixed-duration or calendar-semantic declaration | Resampling, aggregation, interpolation, or filling observations |

Run identity and source SHA-256 are immutable. `None` remains unavailable and
an empty tuple remains available-but-empty. Rebuilt normalized bundles pass the
same cross-record validation as adapter outputs.

## Policy contract

One `RunNormalizationPolicy` is required for every run in the scope and no
other run. Instrument and currency rules are exhaustive over the evidence
actually present in that run. Within a policy, source and canonical instrument
IDs are one-to-one, as are source and canonical currency identifiers.

Instrument metadata is globally consistent: one canonical instrument ID must
carry identical metadata across every run policy. Where a strategy
specification is available, the source and target must have the same asset
class and contract multiplier, and the mapped currency must equal the target
instrument currency. This prevents an identity rule from disguising an
economic contract change.

Timestamp rules target only available timestamped levels. Missing timestamp
rules mean exact canonical UTC identity, not an inferred offset. Explicit
offsets are bounded to seven days in either direction and all timestamps in a
level move together, including optional availability or lifecycle timestamps.

Frequency declarations have two forms:

- `fixed` requires a positive integer duration in microseconds. Every available
  return interval must equal that duration exactly.
- `calendar` requires an explicit calendar and IANA timezone. V1.5E records the
  semantics but does not manufacture elapsed-duration equality.

If a strategy specification is available, `source_frequency` must exactly
match its source `data_frequency`. Return-only evidence cannot attest a source
frequency label. The canonical frequency ID replaces the strategy label only;
observations are never resampled.

## Application workflow

```python
from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    ReconciliationNormalizationService,
)

bundle_adapter = CanonicalArtifactFileBundleAdapter()
reference = bundle_adapter.read("reference-bundle.zip")
candidate = bundle_adapter.read("candidate-bundle.zip")

result = ReconciliationNormalizationService(bundle_adapter).normalize(
    scope,
    (reference, candidate),
    plan,
)
```

The output follows reference-then-candidate scope order. Each
`NormalizedRunArtifacts` retains:

- the untouched source-run identity;
- the revalidated canonical bundle;
- its deterministic canonical bundle SHA-256;
- the canonical frequency, when frequency-bearing evidence exists; and
- canonically ordered `NormalizationChange` records with source value,
  normalized value, rationale, dimension, and optional comparison level.

The plan itself has canonical JSON and a deterministic SHA-256. This lets a
later alignment or comparison result cite the exact normalization assertions
that shaped its inputs.

## Typed failures

`NormalizationError` exposes stable codes for invalid input, scope and policy
mismatch, missing or unused instrument/currency rules, strategy mismatch,
instrument metadata contradiction, frequency mismatch, timestamp overflow,
normalized canonical-contract violation, and deterministic-identity failure.
The error retains run, level, and field context when available.

## Executable example

`examples/v1_5e_normalization` contains a canonical plan and normalized result
summary for two runs. The candidate declares a 30-second producer-clock offset,
an instrument/vendor alias, a denomination alias, and a different one-minute
frequency label. Both runs normalize to the same identities and timestamps;
the equity value remains exactly `100500` in both, demonstrating that currency
normalization performs no conversion.

Regenerate and verify it with:

```bash
python scripts/generate_v1_5e_normalization_example.py --check
```

## Verification and exclusions

V1.5E tests deterministic policy serialization, every rule and output
contract, all available artifact layers, fixed and calendar frequency
semantics, timestamp shifting, `None` versus empty preservation, numerical
immutability, scope ordering, stable identities, and every typed failure path.

V1.5E changes neither V1 report schema `2.5`, audit-run-manifest schema `1.1`,
database schema `1`, nor canonical artifact/bundle/export schemas `1.0`. It
adds no cross-run join or alignment, tolerance policy, record comparison,
divergence measurement, root-cause attribution, report, CLI, Streamlit screen,
persistence, broker connection, order placement, live reconciliation, or
assertion that a reference engine is ground truth. Those remain later
increments.
