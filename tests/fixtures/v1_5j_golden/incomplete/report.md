# Backtest Implementation-Risk Report

- Report schema: `1.0`
- Reconciliation: `v1-5j-golden-incomplete`
- Reference: `reference-run` (Engine A)
- Candidates: 1
- Overall status: not produced

> The report identifies implementation divergence against a declared reference baseline. It does not establish that any engine is correct, prove causation, certify strategy skill, or predict future performance.

## Policy identity

| Policy | SHA-256 |
|---|---|
| Normalization | `a81d115a75f00354377c012f4da1d5a72c8f8d41bb211d2009d8b3d4ac87bcea` |
| Comparison | `61c32bfb83e79b4a464d0114e56facd0ba539abf979bc436f6ec33ba9cb9f112` |
| Measurement | `a27e0398c1b18b8bc09d313a8e9ce3d86f27d699b0ed1b97cc57b94feac7dcdc` |
| Assessment | `36b146d01e377acd1ed25179c722cf5204789d282c3a775cd6cc74137aa68d6f` |

## Candidate `candidate-run`

- Engine: Engine B
- Implementation-risk score: withheld
- Uncertainty: high
- Score note: score withheld because selected divergence evidence is incomplete

### Comparison levels

| Level | Status | Alignment | Exact match | Records |
|---|---|---|---:|---:|
| order | compared | semantic | false | 1 |
| cost | compared | semantic | false | 1 |
| equity | candidate_unavailable | semantic | unavailable | 0 |
| return | compared | semantic | false | 1 |

### Divergence families

| Family | Status | Maximum threshold ratio | Score contribution |
|---|---|---:|---:|
| transaction_cost | measured | 2.5 | 25 |

- `cost` `{"kind":"cost","mode":"semantic","values":[{"type":"datetime","value":"2026-01-02T14:30:00.000000Z"},{"type":"string","value":"USD"}]}` `pnl_impact`: delta `-0.25`, extreme at `2.5×` threshold.
| sizing | measured | 2 | 25 |

- `order` `{"kind":"order","mode":"semantic","values":[{"type":"datetime","value":"2026-01-02T14:30:00.000000Z"},{"type":"string","value":"AAPL"},{"type":"enum","value":"buy"}]}` `quantity`: delta `2`, material at `2×` threshold.
| accounting | unavailable | unavailable | unavailable |
| return | measured | 2.5 | 25 |

- `return` `{"kind":"return","mode":"semantic","values":[{"type":"datetime","value":"2026-01-01T14:30:00.000000Z"},{"type":"datetime","value":"2026-01-02T14:30:00.000000Z"}]}` `value`: delta `-0.000025`, extreme at `2.5×` threshold.

### Attribution hypotheses

| Hypothesis | Source | Target | Status |
|---|---|---|---|
| cost_may_explain_return | transaction_cost | return | supported_cooccurrence |

## Independent findings

| Code | Kind | Candidate | Family | Summary | Limitation | Action |
|---|---|---|---|---|---|---|
| IMPLEMENTATION_LEVEL_EVIDENCE_UNAVAILABLE | evidence_gap | candidate-run |  | equity evidence is candidate_unavailable. | No conclusion is available for this comparison level. | Supply bilateral canonical evidence for this level. |
| IMPLEMENTATION_DIVERGENCE_EXTREME | adverse | candidate-run | transaction_cost | transaction_cost pnl_impact divergence is extreme at 2.5× threshold. | The classification is conditional on the supplied field-specific threshold. | Review the canonical records and the declared materiality threshold. |
| IMPLEMENTATION_DIVERGENCE_MATERIAL | adverse | candidate-run | sizing | sizing quantity divergence is material at 2× threshold. | The classification is conditional on the supplied field-specific threshold. | Review the canonical records and the declared materiality threshold. |
| IMPLEMENTATION_FAMILY_EVIDENCE_IMPAIRED | evidence_gap | candidate-run | accounting | accounting evidence is unavailable. | Materiality and scoring are bounded by incomplete evidence. | Resolve unavailable, one-sided, ambiguous, or non-numeric evidence. |
| IMPLEMENTATION_DIVERGENCE_EXTREME | adverse | candidate-run | return | return value divergence is extreme at 2.5× threshold. | The classification is conditional on the supplied field-specific threshold. | Review the canonical records and the declared materiality threshold. |
| IMPLEMENTATION_ATTRIBUTION_SUPPORTED_COOCCURRENCE | attribution_hypothesis | candidate-run |  | Attribution hypothesis cost_may_explain_return is supported_cooccurrence. | Co-occurrence is not causal proof, and non-support does not disprove causation. | Investigate the hypothesis with independent causal evidence. |
| IMPLEMENTATION_RISK_SCORE_WITHHELD | evidence_gap | candidate-run |  | Score withheld because selected divergence evidence is incomplete. | No numeric score is reported when the configured evidence requirement fails. | Complete the selected evidence before interpreting a score. |

## Run manifest

Not requested.
