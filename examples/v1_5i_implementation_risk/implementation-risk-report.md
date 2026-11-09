# Backtest Implementation-Risk Report

- Report schema: `1.0`
- Reconciliation: `v1-5i-example`
- Reference: `reference-run` (Engine A)
- Candidates: 1
- Overall status: not produced

> The report identifies implementation divergence against a declared reference baseline. It does not establish that any engine is correct, prove causation, certify strategy skill, or predict future performance.

## Policy identity

| Policy | SHA-256 |
|---|---|
| Normalization | `ea42702a691977a42354031426b505ef25ab381eff60efc0ee824efdded8053e` |
| Comparison | `24f91fddd8e04ec333e0b1df147eda00d82356e3fe5a88e0ff17a83658cd430b` |
| Measurement | `707ea9137899733ff9be6de581646aeb29e68e6dc0c5ac186c90aef38ab1e0b9` |
| Assessment | `eddf804c426c4d7bdb5ecf02916e663e2467cbdfef477bb8da8a01274806a2ba` |

## Candidate `candidate-run`

- Engine: Engine B
- Implementation-risk score: 87.5
- Uncertainty: low

### Comparison levels

| Level | Status | Alignment | Exact match | Records |
|---|---|---|---:|---:|
| order | compared | semantic | false | 1 |
| cost | compared | semantic | false | 1 |
| equity | compared | semantic | false | 1 |
| return | compared | semantic | false | 1 |

### Divergence families

| Family | Status | Maximum threshold ratio | Score contribution |
|---|---|---:|---:|
| transaction_cost | measured | 2.5 | 25 |

- `cost` `{"kind":"cost","mode":"semantic","values":[{"type":"datetime","value":"2026-01-02T14:30:00.000000Z"},{"type":"string","value":"USD"}]}` `pnl_impact`: delta `-0.25`, extreme at `2.5×` threshold.
| sizing | measured | 2 | 25 |

- `order` `{"kind":"order","mode":"semantic","values":[{"type":"datetime","value":"2026-01-02T14:30:00.000000Z"},{"type":"string","value":"AAPL"},{"type":"enum","value":"buy"}]}` `quantity`: delta `2`, material at `2×` threshold.
| accounting | measured | 0.5 | 12.5 |

- `equity` `{"kind":"equity","mode":"semantic","values":[{"type":"datetime","value":"2026-01-02T14:30:00.000000Z"},{"type":"string","value":"USD"}]}` `total_equity`: delta `-2.5`, below_threshold at `0.5×` threshold.
| return | measured | 2.5 | 25 |

- `return` `{"kind":"return","mode":"semantic","values":[{"type":"datetime","value":"2026-01-01T14:30:00.000000Z"},{"type":"datetime","value":"2026-01-02T14:30:00.000000Z"}]}` `value`: delta `-0.000025`, extreme at `2.5×` threshold.

### Attribution hypotheses

| Hypothesis | Source | Target | Status |
|---|---|---|---|
| cost_may_explain_return | transaction_cost | return | supported_cooccurrence |

## Independent findings

| Code | Kind | Candidate | Family | Summary | Limitation | Action |
|---|---|---|---|---|---|---|
| IMPLEMENTATION_DIVERGENCE_EXTREME | adverse | candidate-run | transaction_cost | transaction_cost pnl_impact divergence is extreme at 2.5× threshold. | The classification is conditional on the supplied field-specific threshold. | Review the canonical records and the declared materiality threshold. |
| IMPLEMENTATION_DIVERGENCE_MATERIAL | adverse | candidate-run | sizing | sizing quantity divergence is material at 2× threshold. | The classification is conditional on the supplied field-specific threshold. | Review the canonical records and the declared materiality threshold. |
| IMPLEMENTATION_DIVERGENCE_BELOW_THRESHOLD | supporting | candidate-run | accounting | accounting total_equity divergence is below_threshold at 0.5× threshold. | The classification is conditional on the supplied field-specific threshold. |  |
| IMPLEMENTATION_DIVERGENCE_EXTREME | adverse | candidate-run | return | return value divergence is extreme at 2.5× threshold. | The classification is conditional on the supplied field-specific threshold. | Review the canonical records and the declared materiality threshold. |
| IMPLEMENTATION_ATTRIBUTION_SUPPORTED_COOCCURRENCE | attribution_hypothesis | candidate-run |  | Attribution hypothesis cost_may_explain_return is supported_cooccurrence. | Co-occurrence is not causal proof, and non-support does not disprove causation. | Investigate the hypothesis with independent causal evidence. |

## Run manifest

- Audit ID: `v1-5i-example-audit`
- Audit timestamp: `2026-08-21T12:00:00Z`
- Git identity: `v1.5.0-example`
- Manifest SHA-256: `949c4337c2a9c2cfc01da6061e13b03810428c998bd524260a35b1abbe212a2c`
