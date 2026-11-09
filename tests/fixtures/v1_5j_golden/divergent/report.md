# Backtest Implementation-Risk Report

- Report schema: `1.0`
- Reconciliation: `v1-5j-golden-divergent`
- Reference: `reference-run` (Engine A)
- Candidates: 1
- Overall status: not produced

> The report identifies implementation divergence against a declared reference baseline. It does not establish that any engine is correct, prove causation, certify strategy skill, or predict future performance.

## Policy identity

| Policy | SHA-256 |
|---|---|
| Normalization | `98bafebb3b17adc056de382c5f5400b3d79dd0a8b7604a37ffc92b62f402a87f` |
| Comparison | `60539a5e6e4445d646ddaa90ef74f4dbea8c2d0f34f8f19c46d99b0fcd967114` |
| Measurement | `89677f35f9c778f28991cb25fa36e819f3e5e3e04051397fb82c2771d50c612d` |
| Assessment | `358e05e54d492f18f79602988209ee53ac64852b149fa13295bead41fcd61eb7` |

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

Not requested.
