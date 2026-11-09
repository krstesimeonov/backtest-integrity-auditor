# V1.5I Reporting and Operator Integration

Status: implemented in package `1.5.0a11`.

V1.5I makes the completed V1.5A–H implementation-risk pipeline available as a
file-first operator workflow. It reads one canonical reference bundle and one
or more canonical candidate bundles, applies four explicit policies, and emits
one deterministic report. It never imports or executes a backtest engine.

## End-to-end flow

1. The V1.5C adapter validates every canonical directory or ZIP bundle.
2. The V1.5E service applies the exact normalization plan and records canonical
   bundle identities and every declared change.
3. V1.5F aligns and compares each requested evidence level exactly.
4. V1.5G projects selected numeric fields into the four divergence families.
5. V1.5H applies field-specific materiality thresholds, uncertainty, bounded
   scoring, and co-occurrence-only attribution.
6. V1.5I derives independent findings and serializes completed evidence. The
   renderer does not recalculate normalization, comparison, divergence, or
   score values.

The reference run is a comparison baseline, not an assertion of truth.
Agreement can be wrong, and disagreement does not identify which engine is
correct.

## Public contracts

V1.5I introduces two JSON Schema Draft 2020-12 resources:

| Catalog key | Schema ID |
|---|---|
| `implementation_risk_report_1_0` | `urn:backtest-integrity-auditor:schema:implementation-risk-report:1.0` |
| `implementation_risk_run_manifest_1_0` | `urn:backtest-integrity-auditor:schema:implementation-risk-run-manifest:1.0` |

They are deliberately separate from V1 Single-Run and Experiment-Family
report schema `2.5` and audit-run-manifest schema `1.1`. No V1 object gains an
informal V1.5 field.

```python
from backtest_auditor.implementation_risk import load_implementation_risk_schema

report_schema = load_implementation_risk_schema("implementation_risk_report_1_0")
manifest_schema = load_implementation_risk_schema(
    "implementation_risk_run_manifest_1_0"
)
```

The report contains:

- exact reference and candidate run provenance;
- requested-level availability, alignment mode, exact-match state, and record
  counts;
- normalized bundle SHA-256 identities, canonical frequency, and declared
  normalization changes;
- four policy SHA-256 identities;
- per-family evidence status and impaired-evidence counts;
- every numeric divergence, threshold, threshold ratio, and materiality class;
- bounded score or explicit withheld reason and uncertainty;
- attribution hypotheses with their evidence status and non-causal rationale;
- independent findings; and
- an optional implementation-risk manifest.

`overall_status` is required and always JSON `null`. Consumers must not replace
it with an inferred global pass/fail.

## Findings

Findings have four independent kinds:

- `supporting`: exact-zero or below-threshold evidence, or a declared
  attribution hypothesis not supported by material co-occurrence;
- `adverse`: material or extreme numeric divergence;
- `evidence_gap`: unavailable or impaired bilateral evidence, insufficient
  attribution evidence, or a withheld score; and
- `attribution_hypothesis`: complete material co-occurrence that warrants
  investigation but does not establish causation.

Every finding names one candidate and an evidence path. Supporting findings do
not certify either engine, and non-support of an attribution hypothesis does
not disprove a causal relationship.

## Run manifest

The optional manifest requires an explicit audit ID, timezone-aware timestamp,
and Git/source revision. It binds:

- reference and candidate source SHA-256 values;
- normalized canonical-bundle SHA-256 values;
- all four policy hashes;
- the exact serialized findings hash;
- method versions, package version, report schema version; and
- Python and platform metadata.

Its final SHA-256 covers the complete public manifest body except the digest
field itself. The timestamp is normalized to UTC. Source hashes are identities,
not signatures or proof that an export is truthful.

## CLI

```bash
backtest-auditor implementation-risk \
  reference-bundle.zip candidate-a.zip candidate-b.zip \
  --normalization-plan normalization-plan.json \
  --comparison-policy comparison-policy.json \
  --measurement-policy measurement-policy.json \
  --assessment-policy assessment-policy.json \
  --audit-id reconciliation-2026-08-21 \
  --audit-timestamp 2026-08-21T12:00:00Z \
  --git-commit abc123 \
  --format markdown \
  --output implementation-risk.md
```

The four policy documents must use their exact canonical V1.5 shapes. Duplicate
JSON keys, non-finite values, unknown fields, non-canonical ordering, scope
mismatches, and bundle validation failures are rejected. The manifest arguments
remain all-or-none. Omitting all three emits a valid report with `run_manifest`
set to `null`.

## Streamlit

Implementation Risk mode accepts canonical bundle ZIPs and the same four JSON
policy documents. Uploads are materialized in isolated role-specific temporary
directories, passed through the same application service as the CLI, and
deleted when the call returns. The result surface keeps candidate summaries,
findings, normalization evidence, and JSON/Markdown downloads separate.

V1.5I reports are not added to V1.2 audit-history persistence. That would
require an explicit database-schema and retention decision rather than silently
storing a new report kind under the V1 snapshot contract.

## Deterministic example

`examples/v1_5i_implementation_risk/` contains two canonical bundle ZIPs, four
policy documents, and complete JSON/Markdown reports. Regenerate or verify it
with:

```bash
python scripts/generate_v1_5i_report_example.py
python scripts/generate_v1_5i_report_example.py --check
```

This example is an integration fixture, not the V1.5J golden/reference corpus.

## Deliberate exclusions

V1.5I adds no persistence, backtest or engine execution, order submission,
broker connectivity, live reconciliation, causal proof, strategy-quality
certification, or future-performance claim. V1.5J remains responsible for the
golden datasets, independent reference cases, property tests, performance
budgets, installed-artifact checks, and final release hardening.
