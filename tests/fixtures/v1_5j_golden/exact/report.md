# Backtest Implementation-Risk Report

- Report schema: `1.0`
- Reconciliation: `v1-5j-golden-exact`
- Reference: `reference-run` (Engine A)
- Candidates: 1
- Overall status: not produced

> The report identifies implementation divergence against a declared reference baseline. It does not establish that any engine is correct, prove causation, certify strategy skill, or predict future performance.

## Policy identity

| Policy | SHA-256 |
|---|---|
| Normalization | `d3afda8bab5604e0e396933419c43e4148cbc2ea2fdce316e319d178a07683a6` |
| Comparison | `b0e91d04ed875cc3f9867a36582ebca375f69564251d95abaa2856df27136efa` |
| Measurement | `c71221f9b00ee535a49154202d8a3c53b8e9ec3c392dcf266dd2ef2009574af3` |
| Assessment | `2f8058173d469c862cdc649ed5d32c85e171b022320a574d3a66e4bbf8f50451` |

## Candidate `candidate-run`

- Engine: Engine B
- Implementation-risk score: withheld
- Uncertainty: not_assessed

### Comparison levels

| Level | Status | Alignment | Exact match | Records |
|---|---|---|---:|---:|
| order | compared | semantic | true | 1 |
| cost | compared | semantic | true | 1 |
| equity | compared | semantic | true | 1 |
| return | compared | semantic | true | 1 |

### Divergence families

| Family | Status | Maximum threshold ratio | Score contribution |
|---|---|---:|---:|
| transaction_cost | measured | unavailable | unavailable |
| sizing | measured | unavailable | unavailable |
| accounting | measured | unavailable | unavailable |
| return | measured | unavailable | unavailable |

### Attribution hypotheses

| Hypothesis | Source | Target | Status |
|---|---|---|---|
| cost_may_explain_return | transaction_cost | return | not_supported |

## Independent findings

| Code | Kind | Candidate | Family | Summary | Limitation | Action |
|---|---|---|---|---|---|---|
| IMPLEMENTATION_ATTRIBUTION_NOT_SUPPORTED | supporting | candidate-run |  | Attribution hypothesis cost_may_explain_return is not_supported. | Co-occurrence is not causal proof, and non-support does not disprove causation. |  |

## Run manifest

Not requested.
