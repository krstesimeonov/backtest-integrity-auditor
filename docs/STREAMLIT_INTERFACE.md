# Streamlit Interface

## Purpose and boundary

Package `1.5.0` includes the local browser interface introduced in V1.1,
optional V1 database-backed history, a separate IBKR Activity Flex importer,
and the V1.5I implementation-risk workflow.
The interface coordinates inputs and presents completed results. It does not
implement statistics, invoke the CLI, run a backtest, select parameters,
reconstruct broker trades, or place orders. Its only broker connection is the
explicit read-only Flex Web Service import.

Every upload follows the existing path:

```text
browser upload
  -> temporary role-specific file
  -> canonical ingestion and normalization
  -> immutable domain objects
  -> existing application audit service
  -> existing JSON and Markdown renderers
  -> browser tables and downloads
```

Temporary files are held in an isolated operating-system temporary directory
and removed when the audit call returns, including when canonical validation
raises an error. Original files remain temporary; an explicit save stores only
the completed reports, manifest metadata, and canonical normalized returns.
Submitting a replacement audit clears any earlier result before validation, so
a failed replacement cannot leave stale evidence visible below its error.
Browser filenames containing control characters or more than 255 UTF-8 bytes
are rejected before temporary materialization and provenance capture.

## Installation and launch

Install the optional interface dependencies and launch the installed app:

```bash
python3 -m pip install -e ".[ui]"
backtest-auditor-ui
```

For development, the `dev` extra includes Streamlit:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/unit/presentation
```

The base `backtest-auditor` CLI remains available and does not require the
`ui` extra. Calling `backtest-auditor-ui` without Streamlit installed produces
an explicit installation instruction rather than an import traceback.

## IBKR Flex Import workflow

The importer accepts one or more exported Activity Flex XML/CSV files or one
read-only Web Service v3 response. It recognizes only `AccountId`, `FromDate`,
`ToDate`, and period-level `TWR` from Change in NAV. Account and model selectors
use password-style fields and appear only as hashes in the downloaded import
manifest.

API mode has no token widget. Configure
`BACKTEST_AUDITOR_IBKR_FLEX_TOKEN` in the Streamlit process environment and
optionally `BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID`; the UI displays only whether
the token exists. Download the canonical CSV and deterministic import manifest,
then use the CSV in Single-Run. Import artifacts are not automatically persisted
to audit history. See [`IBKR_FLEX_IMPORT.md`](IBKR_FLEX_IMPORT.md) for the query
contract, interval semantics, and credential boundary.

## Single-Run workflow

The only required upload is a strategy return CSV. The default columns are
`timestamp` and `return`; both are configurable. The tabs expose:

| Area | Inputs |
|---|---|
| Files | Run ID, strategy CSV/columns/convention, optional benchmark, risk-free, gross-return, and declared-regime files with explicit columns/conventions |
| Sampling | Optional pandas frequency alias, periods per year, and strategy/benchmark timestamp timezones |
| Calendars | Optional built-in or named calendar declarations and authoritative session CSVs |
| Methodology | Optional strategy and benchmark `ReturnConstructionSpec` JSON objects |
| Methods | Annualized Sharpe, PSR and MTRL, extended serial diagnostics, Bartlett-HAC adjustment, moving-block/stationary percentile bootstrap, downside/tail risk, and Bartlett-HAC benchmark alpha inference |
| Reproducibility | Optional audit ID, timezone-aware ISO 8601 timestamp, and Git/source revision |

No annualization scale is invented. Clear **Declare periods per year** when it
is unknown. A regular timestamp series without an explicit positive scale can
still be audited, but annualized methods remain unavailable by design.

Return-methodology JSON accepts the public `ReturnConstructionSpec` fields:

```json
{
  "transaction_costs_included": true,
  "fees_included": true,
  "leverage_policy": "unlevered",
  "currency": "USD",
  "price_adjustment_policy": "adjusted",
  "data_source": "research warehouse",
  "data_vintage": "2026-08-13",
  "stale_price_policy": "reject",
  "delisting_return_policy": "include terminal return",
  "survivorship_bias_controlled": true,
  "lookahead_bias_controlled": true,
  "signal_timing": "close t",
  "execution_timing": "open t+1"
}
```

Unknown keys and invalid enum values are rejected. Leaving the object empty is
not treated as a default declaration; the resulting evidence remains explicitly
insufficient.

## Experiment-Family workflow

The manifest JSON, trial inventory CSV, and long-format trial returns CSV are
required. Split membership and the shared benchmark are optional in the UI but
must agree with the manifest contract when supplied. The family manifest
continues to control sampling, return convention, parameter schema, selection
rule, and benchmark identity.

The **Family methods** tab exposes all optional V1 family evidence:

- classical expected-maximum, location-only Deflated Sharpe Ratio;
- exhaustive equal-partition CSCV and Probability of Backtest Overfitting;
- standardized parameter-neighborhood robustness; and
- equal-window temporal and declared-fold robustness; and
- benchmark-relative White Reality Check and Hansen SPA with an explicit
  stationary-bootstrap configuration.

Parameter scales are entered as a non-empty JSON object. They are normalized
by parameter name before constructing the canonical specification:

```json
{"lookback": 5.0, "threshold": 0.25}
```

Scale names must match the family parameter schema. The interface never widens
a neighborhood, drops an undefined trial, or chooses a parameter scale.

## Implementation Risk workflow

The workflow requires:

- one canonical V1.5C reference bundle ZIP;
- one or more canonical V1.5C candidate bundle ZIPs;
- one normalization-plan JSON file;
- one exact-comparison-policy JSON file;
- one divergence-measurement-policy JSON file; and
- one risk-assessment-policy JSON file.

The optional reproducibility tab uses the same all-or-none audit ID,
timezone-aware timestamp, and Git/source identity rule as V1 audits, but emits
the separate implementation-risk manifest `1.0`.

The controller validates the bundles and policy documents, then invokes the
complete V1.5E–H service chain. It does not calculate evidence in presentation
code and does not invoke the CLI. The result surface separates candidate
score/uncertainty summaries, independent findings, normalization evidence, and
JSON/Markdown downloads. The report has no global status and explicitly warns
that a reference is not ground truth and co-occurrence is not causal proof.

Implementation-risk reports are not saved through the V1.2 history button.
Adding them to persistence requires an explicit database-schema and retention
decision.

## Results and downloads

The result surface deliberately keeps four views separate:

1. independent evidence-profile dimensions;
2. audit findings and their remediation;
3. preserved non-blocking input-normalization issues; and
4. deterministic report downloads and raw JSON preview.

JSON uses public report schema `2.5`; Markdown uses the same deterministic
human-readable renderer. When an
audit-run manifest is enabled, raw upload hashes retain the safe original
filename and role, while absolute temporary paths are never serialized.

Implementation Risk mode instead uses implementation-risk report schema `1.0`
and optional implementation-risk manifest schema `1.0`. Those contracts are
separate from the V1 schema `2.5` result surface.

## Deployment and security

The bundled app is intended for a trusted local workstation or a separately
secured internal deployment. It does not provide authentication,
authorization, multi-tenant isolation, per-user retention controls, malware
scanning, or network policy. Optional V1.2 history is durable but assumes one
trusted application context. Do not expose the app directly to the public
internet or upload confidential evidence to an environment you do not control.

Streamlit server settings, TLS termination, authentication, upload-size limits,
and process isolation belong to the deployment environment. Those concerns
must be designed explicitly before a shared hosted service is offered.

## Troubleshooting

- **Annualized results are unavailable:** declare a valid frequency and a
  positive periods-per-year value, then inspect the sampling findings.
- **Benchmark rejected:** its timestamps must satisfy the existing exact
  alignment and family-manifest contracts.
- **Configuration error:** verify JSON syntax, enum values, confidence bounds,
  positive lags/counts/scales, and timezone-aware audit timestamp.
- **Canonical input validation error:** use the displayed code, location, and
  message; the UI preserves the same typed errors as the CLI.
- **Large upload rejected before audit:** adjust the trusted deployment's
  Streamlit upload-size setting; the auditor itself does not bypass server
  limits.
