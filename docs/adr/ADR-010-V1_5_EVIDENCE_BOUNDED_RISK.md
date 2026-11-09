# ADR-010: Make implementation-risk interpretation policy-explicit

Status: accepted for V1.5H.

## Decision

Classify exact divergence with field-specific absolute thresholds, normalize
only through those thresholds, cap each family contribution at its declared
weight, and withhold scores when evidence is incomplete by default.
Attribution is restricted to declared co-occurrence hypotheses.

## Consequences

Scores are reproducible rather than universal facts. Changing thresholds or
weights changes the policy hash. A supported hypothesis cannot be presented as
a root cause, and unavailable evidence cannot silently improve the score.
