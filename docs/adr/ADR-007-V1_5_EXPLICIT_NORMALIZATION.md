# ADR-007: Require Explicit Cross-Engine Normalization Evidence

Status: accepted for V1.5E.

## Decision

Introduce a policy-driven normalization boundary between canonical engine
adaptation and any later cross-run alignment or comparison. A reconciliation
plan contains exactly one policy for each scoped run. Mappings are exhaustive,
immutable, deterministic, and retained as evidence.

Permit only explicit strategy/instrument/currency identifier mappings, fixed
UTC timestamp offsets by comparison level, and shared fixed or calendar
frequency declarations. Preserve run provenance, all numerical values, and
unavailable-versus-available-empty semantics. Rebuild every result through the
canonical artifact contracts and calculate a deterministic bundle identity.

## Consequences

- Missing, unused, ambiguous, or contradictory rules fail closed.
- Instrument mappings cannot change asset class, contract multiplier, or
  denomination economics.
- Currency rules are identifier relabeling, never exchange-rate conversion.
- Timestamp rules cannot become tolerance windows or event matching.
- Fixed frequency validates exact return intervals; calendar frequency retains
  explicit calendar/timezone semantics without resampling.
- Later stages can cite both the plan SHA-256 and each normalized bundle
  SHA-256, while inspecting canonically ordered change evidence.

## Rejected alternatives

- Inferring equivalence from symbols, strategy names, return correlation, or
  observed timestamp proximity would hide assumptions.
- Automatically converting currencies would introduce external prices,
  valuation times, and rounding policy outside the available evidence.
- Resampling at normalization time would destroy source observations before
  alignment policy is explicit.
- Folding normalization into engine adapters would make pair-specific policy
  affect source canonicalization and weaken adapter reproducibility.
- Treating a missing timestamp rule as permission to estimate an offset would
  overstate certainty; absence means exact canonical UTC identity.
