# V1.5G Divergence Measurement

Status: implemented in package `1.5.0a9`.

V1.5G projects V1.5F exact comparison evidence into four explicit families:
transaction cost, sizing, accounting, and returns. A versioned measurement
policy selects the exact canonical level and field for every observation.

Measurements preserve reference and candidate typed values and define every
Decimal delta as `candidate - reference`. They are intentionally not summed
across currencies, instruments, timestamps, or economic units.

`measured` means all selected levels were comparable. `partial` retains
one-sided, ambiguous, or non-numeric evidence. `unavailable` means every
selected level for that family lacked bilateral evidence. `not_requested`
means the policy selected no field in that family. Available-empty levels stay
measured rather than becoming unavailable.

The result remains linked to the V1.5E normalization-plan SHA-256, V1.5F
comparison-policy SHA-256, and its own canonical measurement-policy SHA-256.

V1.5G does not assign root causes, materiality, severity, scores, confidence,
pass/fail verdicts, findings, or reports. Root-cause attribution and
implementation-risk scoring belong to V1.5H; presentation belongs to V1.5I.
