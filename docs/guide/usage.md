# Full CLI usage (the 1.5.2 README)

This page is the complete README of package 1.5.2, kept as it was apart from
link targets and heading levels when the README was shortened for the public
release. It documents every CLI mode and option group: single-run and
experiment-family audits, V1.4 additive evidence, IBKR Flex import, the
Streamlit interface and the implementation-risk audit. Its opening paragraphs
describe the internal increments (V1.4, V1.5A–J) by which the package was
built.


V1.5J completes the Implementation Risk Engine in package `1.5.0`. It freezes
the V1.5I report/manifest semantics and adds independent golden/reference cases,
deterministic property tests, time/memory budgets, installed-wheel verification,
bounded policy/candidate inputs, atomic opt-in CLI overwrite, and fail-closed
source-archive checks. See
[`docs/V1_5J_RELEASE_HARDENING.md`](../V1_5J_RELEASE_HARDENING.md).

V1.5I introduced the distinct versioned implementation-risk report and manifest,
deterministic findings, and complete CLI/Streamlit workflows over exported
canonical bundles. It preserves the policy-explicit materiality, uncertainty,
bounded scoring, and co-occurrence-only attribution from V1.5H. The
pipeline retains the explicit, fail-closed V1.5E normalization boundary for
strategy, instrument/symbol, denomination, UTC timestamp, and frequency
identities. It retains every source run identity and numerical value, never
resamples observations, and records deterministic plan and normalized-bundle
SHA-256 evidence. See
[`docs/V1_5I_REPORTING_AND_INTEGRATION.md`](../V1_5I_REPORTING_AND_INTEGRATION.md),
[`docs/V1_5E_CROSS_ENGINE_NORMALIZATION.md`](../V1_5E_CROSS_ENGINE_NORMALIZATION.md),
[`docs/V1_5D3_LEAN_NAUTILUS_AND_HARDENING.md`](../V1_5D3_LEAN_NAUTILUS_AND_HARDENING.md),
[`docs/V1_5D2_CONCRETE_ENGINE_ADAPTERS.md`](../V1_5D2_CONCRETE_ENGINE_ADAPTERS.md)
and
[`docs/V1_5D1_SHARED_ADAPTER_FOUNDATION.md`](../V1_5D1_SHARED_ADAPTER_FOUNDATION.md).

V1.5C adds the first external boundary for the Implementation Risk Engine: a
strict hybrid JSON/CSV bundle that can be stored as a directory or deterministic
ZIP. It includes engine-neutral reader/writer ports, typed validation failures,
file hashes and counts, formal schemas, and an inspectable example. It still
does not implement concrete engine mappings or cross-run comparisons. See
[`docs/V1_5C_FILE_BUNDLE_CONTRACT.md`](../V1_5C_FILE_BUNDLE_CONTRACT.md),
[`docs/V1_5B_CANONICAL_CONTRACTS.md`](../V1_5B_CANONICAL_CONTRACTS.md) and
[`docs/V1_5A_ARCHITECTURE.md`](../V1_5A_ARCHITECTURE.md).

V1.4 adds explicitly configured serial-dependence, downside/tail-risk,
benchmark-inference, stationary-bootstrap, and family-level data-snooping
evidence. It also accepts exactly aligned risk-free, gross-return, and declared
regime series. The V1.3 credential-safe, read-only IBKR Activity Flex adapter
remains unchanged. See
[`docs/V1_4_STATISTICAL_METHODS.md`](../V1_4_STATISTICAL_METHODS.md) and
[`docs/IBKR_FLEX_IMPORT.md`](../IBKR_FLEX_IMPORT.md).

V1 audits either one existing timestamped return series or the complete family
of trials that produced a selected strategy. It validates the input, calculates
objective evidence, generates structured findings, and renders a deterministic
report. It never executes trades. Its only broker connection is the explicit,
read-only IBKR Flex import path described below.

### Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

Install the exact optional Python SDK versions when generating D2/D3 exports:

```bash
python3 -m pip install -e ".[engine-exporters]"
```

The base package can verify and map any existing D2/D3 export without an engine
SDK installed. NautilusTrader `1.231.0` requires Python 3.12 or newer; LEAN is
read from completed local result files and is not installed as a Python SDK.

### Run the optional Streamlit interface

V1.1 added a local presentation layer for both existing audit workflows. It
uses the same ingestion, domain, application, manifest, and reporting services
as the CLI; it is not a second audit engine.

```bash
python3 -m pip install -e ".[ui]"
backtest-auditor-ui
```

Upload a strategy-return CSV for Single-Run mode, or the manifest, trial, and
return files for Experiment-Family mode. Optional benchmark, calendar,
methodology, split, statistical-method, robustness, and audit-identity inputs
are available in the corresponding tabs. Completed reports can be inspected
in the browser and downloaded as deterministic JSON or Markdown.

Implementation Risk mode accepts one reference bundle ZIP, one or more
candidate bundle ZIPs, and explicit normalization, comparison, measurement,
and assessment policy JSON files. It uses the same complete V1.5 application
pipeline as the CLI and never executes a backtest.

The UI processes audit uploads in a temporary directory and discards those
temporary files when the audit completes. V1.2 can explicitly persist completed
reports and normalized returns. V1.3 adds a separate IBKR Flex Import screen;
API mode reads its token only from the environment and never places orders. The
UI does not authenticate users or select parameters. See
[`docs/STREAMLIT_INTERFACE.md`](../STREAMLIT_INTERFACE.md) for the complete
input map, security boundary, and troubleshooting guide.

### Audit cross-engine implementation risk

The reference is a declared baseline, never ground truth. Every policy file is
required and hashed into the output:

```bash
backtest-auditor implementation-risk \
  examples/v1_5i_implementation_risk/reference-bundle.zip \
  examples/v1_5i_implementation_risk/candidate-bundle.zip \
  --normalization-plan examples/v1_5i_implementation_risk/normalization-plan.json \
  --comparison-policy examples/v1_5i_implementation_risk/comparison-policy.json \
  --measurement-policy examples/v1_5i_implementation_risk/measurement-policy.json \
  --assessment-policy examples/v1_5i_implementation_risk/assessment-policy.json \
  --audit-id example-implementation-audit \
  --audit-timestamp 2026-08-21T12:00:00Z \
  --git-commit example-revision \
  --format json \
  --output implementation-risk.json
```

The report uses implementation-risk schema `1.0`; it does not alter V1 report
schema `2.5`. No global pass/fail is produced, and a co-occurrence attribution
remains an investigation hypothesis rather than causal proof.
Existing output is refused by default. Add `--force` only when atomic
replacement is intentional; an output path can never alias an input file.

### Import IBKR Activity Flex evidence

Exported files and the read-only API use the same strict Change-in-NAV parser:

```bash
backtest-auditor ibkr files statements/2026-01.xml statements/2026-02.xml \
  --declared-frequency ME \
  --periods-per-year 12 \
  --output ibkr_returns.csv
```

For API retrieval, keep the token out of command arguments:

```bash
export BACKTEST_AUDITOR_IBKR_FLEX_TOKEN='replace-with-token'
export BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID='replace-with-query-id'
backtest-auditor ibkr api --output ibkr_returns.csv
```

Each source statement interval becomes one observation at `ToDate`, with
`simple_return = TWR_percent / 100`. A multi-day statement remains one
multi-day observation; V1.3 never invents daily returns. The command also writes
`ibkr_returns.ibkr-import.json` with source hashes and canonicalization
provenance but no clear-text token, query ID, account ID, or model name. Use the
canonical CSV in the unchanged Single-Run workflow. Full query configuration,
date-format, scope-selection, credential, rate-limit, and interpretation
details are in [`docs/IBKR_FLEX_IMPORT.md`](../IBKR_FLEX_IMPORT.md).

### Run a Single-Run audit

The default CSV contract has two columns named `timestamp` and `return`:

```bash
backtest-auditor examples/sample_returns.csv \
  --run-id example-run \
  --format json \
  --output audit.json
```

Use `--format markdown` for a human-readable report. Use
`--timestamp-column` and `--return-column` when the CSV uses different column
names. Simple returns are assumed unless `--return-convention log` is passed.
Returns are decimals (`0.01` is 1 %). A mean absolute return above 0.05 per
period at daily or faster sampling (scaled by the square root of the median
interval in days for slower sampling) adds the warning
`RETURN_MAGNITUDE_SUGGESTS_PERCENT_UNITS`, and a simple return below -1 is
rejected with a message that names percent units.

Sampling regularity is assessed from the timestamps. You may provide a
declared pandas frequency alias and an explicit annualization scale:

```bash
backtest-auditor examples/sample_returns.csv \
  --run-id example-run \
  --declared-frequency D \
  --periods-per-year 365 \
  --annual-risk-free-rate 0.03 \
  --benchmark-annualized-sharpe-ratio 0.0 \
  --required-psr-confidence-level 0.95 \
  --serial-max-lag 2 \
  --serial-significance-level 0.05 \
  --hac-max-lag 2 \
  --hac-kernel bartlett \
  --bootstrap-method moving_block \
  --bootstrap-interval-method percentile \
  --bootstrap-replications 2000 \
  --bootstrap-confidence-level 0.95 \
  --bootstrap-block-length 2 \
  --bootstrap-seed 42 \
  --timestamp-timezone UTC \
  --observation-calendar 24/7 \
  --calendar-timezone UTC \
  --format markdown
```

`--periods-per-year` has no default. In particular, the auditor never silently
assumes 252 periods per year. At least three observations are required to
assess regularity. A regular inferred or confirmed declared frequency and an
explicit positive periods-per-year value are both required before
annualization becomes eligible. When it is ineligible, the report contains
`null` for annualized statistics rather than presenting a misleading estimate.
The declared value is used as given; when it differs from the observation rate
the timestamps imply (intervals per 365.25-day year over the observed span) by
more than a factor of 1.2, over a span of at least 28 days, the report adds the
warning `PERIODS_PER_YEAR_SAMPLING_MISMATCH` (for example 252 on a daily 24/7
series, or 365 on business days).

#### V1.4 additive Single-Run evidence

All V1.4 inputs are opt-in. This example combines the new evidence without
changing the default audit:

```bash
backtest-auditor examples/sample_returns.csv \
  --run-id advanced-example \
  --declared-frequency D \
  --periods-per-year 365 \
  --risk-free-csv examples/sample_risk_free.csv \
  --gross-returns-csv examples/sample_gross_returns.csv \
  --regimes-csv examples/sample_regimes.csv \
  --minimum-acceptable-period-return 0.0 \
  --tail-confidence-level 0.95 \
  --serial-max-lag 3 \
  --serial-significance-level 0.05 \
  --bootstrap-method stationary \
  --bootstrap-interval-method percentile \
  --bootstrap-replications 2000 \
  --bootstrap-confidence-level 0.95 \
  --bootstrap-block-length 3 \
  --bootstrap-seed 42 \
  --benchmark-csv examples/sample_benchmark.csv \
  --benchmark-id market \
  --benchmark-alpha-hac-max-lag 2 \
  --benchmark-alpha-confidence-level 0.95 \
  --format markdown
```

Auxiliary series require exact timestamp equality. The auditor reports both
one-sided timestamp differences and withholds paired statistics on mismatch;
it never repairs the evidence with an inner join. Regime labels are external
declarations, not inferred hidden states. Time-varying risk-free calculations
remain additive evidence and do not silently replace the explicit scalar
risk-free assumptions in the legacy Sharpe/PSR/HAC methods.

### Audit an Experiment-Family

Part L added a second, backward-compatible CLI route. Parts M–P add optional
family-level DSR, CSCV/PBO, parameter-neighborhood, temporal evidence, a
dimensioned evidence profile, and an audit-run manifest:

```bash
backtest-auditor family \
  examples/cscv_family_manifest_v1_4.json \
  examples/cscv_family_trials.csv \
  examples/cscv_family_returns.csv \
  --benchmark-csv examples/cscv_family_benchmark.csv \
  --dsr-method classic_expected_maximum \
  --dsr-trial-count-policy selection_eligible \
  --dsr-annual-risk-free-rate 0.03 \
  --dsr-confidence-level 0.95 \
  --cscv-method combinatorially_symmetric \
  --cscv-performance-metric period_sharpe_ratio \
  --cscv-selection-metric-name period_sharpe_ratio \
  --cscv-partitions 4 \
  --cscv-annual-risk-free-rate 0.03 \
  --cscv-maximum-combinations 100 \
  --cscv-rank-tie-method average \
  --cscv-winner-tie-policy first_by_attempt_index \
  --cscv-maximum-acceptable-pbo 0.05 \
  --data-snooping-replications 2000 \
  --data-snooping-mean-block-length 3 \
  --data-snooping-seed 42 \
  --data-snooping-significance-level 0.05 \
  --format markdown \
  --output family_audit.md
```

The default command remains Single-Run mode. `backtest-auditor single ...` is
also accepted as an explicit alias. Experiment-Family mode uses four separate
evidence contracts so none of the following is inferred from a winning return
series:

1. The JSON manifest declares family identity, input schema `1.0`, total
   attempted trials, search completeness, winner, selection rule and metric,
   parameter names, return convention, sampling, and an optional shared
   benchmark.
2. The trial CSV records `trial_id`, one-based `attempt_index`, `outcome`,
   `included_in_selection`, `selected`, `selection_score`, and a JSON
   `parameters` object. Optional `source` and `reason` columns preserve
   provenance, failure reasons, and completed-trial exclusions.
3. The long-format return CSV contains exactly `timestamp`, `trial_id`, and
   `return`. Every completed trial must have one finite return at every shared
   timestamp; failed trials must not have fabricated curves.
4. The optional split CSV contains `split_id`, `timestamp`, and `role`, where
   role is `in_sample` or `out_of_sample`. Every supplied split must assign each
   family timestamp exactly once and contain both roles.

Exactly one trial must be selected, the manifest winner must match the selected
row, and a maximize/minimize winner must have the optimum finite declared score
among all included completed trials; ties are allowed. Parameter keys must
exactly equal the declared schema, and a declaration of complete search history
requires every attempt index from 1 through the declared total. Unknown fields
and columns are rejected so misspellings cannot silently erase evidence.
Unordered valid rows are normalized deterministically and recorded as input
issues.

The family report distinguishes attempted, documented, completed, failed,
selection-eligible, excluded, supplied, and selected trials. Its `eligible`
status means only that the complete aligned family has at least two eligible
trials and at least four observations. It does not claim that DSR, CSCV, PBO,
or any other evidence supports the selected strategy. The complete file
contract is documented in
[`docs/EXPERIMENT_FAMILY_INPUT_SCHEMA.md`](../EXPERIMENT_FAMILY_INPUT_SCHEMA.md).

### V1 public contracts and release gates

Package `1.5.0` retains V1 report schema `2.5` and audit-run-manifest schema
`1.1`; V1.5I adds no fields to either frozen V1 contract. Its separate
implementation-risk report and manifest schemas are both version `1.0`.
Seven bundled JSON Schema Draft 2020-12 resources cover current Single-Run and
Experiment-Family reports, the shared evidence profile, the current manifest,
and the retained `2.4`/`1.0` legacy contracts:

```python
from backtest_auditor.reporting.schema_catalog import load_public_schema

single_schema = load_public_schema("single_run_report_2_5")
```

The complete catalog, stable schema IDs, validation example, and compatibility
rules are documented in
[`docs/PUBLIC_REPORT_SCHEMAS.md`](../PUBLIC_REPORT_SCHEMAS.md).

Part Q completed the V1 audit engine with deterministic full-report JSON/Markdown golden files,
independent numerical reference data, a large-family benchmark harness, and CI
across Python 3.11–3.13. V1.1 added the optional Streamlit adapter without
changing those statistical or serialized contracts. The local release gates are:

```bash
ruff format --check src tests scripts benchmarks
ruff check src tests scripts benchmarks
mypy
python scripts/release_contracts.py --check
python scripts/generate_v1_5c_bundle_example.py --check
python scripts/generate_v1_5d1_engine_export_example.py --check
python scripts/generate_v1_5d2_engine_examples.py --check
python scripts/generate_v1_5d3_engine_examples.py --check
python scripts/generate_v1_5e_normalization_example.py --check
python scripts/generate_v1_5f_comparison_example.py --check
python scripts/generate_v1_5g_divergence_example.py --check
python scripts/generate_v1_5h_risk_example.py --check
python scripts/generate_v1_5i_report_example.py --check
python scripts/generate_v1_5j_golden.py --check
python benchmarks/benchmark_implementation_risk.py
python -m pytest --cov=backtest_auditor --cov-fail-under=95
python -m build
python -m twine check dist/*
```

See
[`docs/NUMERICAL_REFERENCE_AND_BENCHMARKS.md`](../NUMERICAL_REFERENCE_AND_BENCHMARKS.md)
and [`docs/RELEASE_CHECKLIST.md`](../RELEASE_CHECKLIST.md) for numerical,
performance, packaging, installation, and deterministic-output checks.

### Deflated Sharpe Ratio and multiple-testing evidence

Part M calculates classical expected-maximum, location-only DSR only when all
four base choices are explicit:

```text
--dsr-method classic_expected_maximum
--dsr-trial-count-policy selection_eligible
--dsr-annual-risk-free-rate 0.03
--dsr-confidence-level 0.95
```

There is no default risk-free rate, confidence level, method, or trial-count
policy. Every completed trial's period Sharpe is recalculated from canonical
simple returns using the same annual-to-period risk-free conversion. The
selected trial must be the maximum observed Sharpe among every declared
selection-eligible trial. A zero-volatility eligible trial, incomplete search
history, missing periods-per-year declaration, unavailable selected moments,
or a selected non-maximum produces a typed ineligible result rather than a
partial DSR calculated after silently dropping evidence.

For `N` trials, Euler–Mascheroni constant `gamma`, and cross-trial sample Sharpe
standard deviation `sigma_SR`, the expected-maximum benchmark is:

```text
E[max Z] ≈
    (1 - gamma) * Phi_inverse(1 - 1/N)
    + gamma * Phi_inverse(1 - 1/(N * e))

expected maximum period Sharpe = sigma_SR * E[max Z]
```

For selected period Sharpe `SR`, observation count `n`, sample skewness
`gamma3`, and sample Pearson kurtosis `gamma4`:

```text
A = 1 - gamma3 * SR + ((gamma4 - 1) / 4) * SR**2

DSR = Phi(
    (SR - expected maximum period Sharpe)
    / sqrt(A / (n - 1))
)
```

The report provides two built-in trial-count scenarios without pretending they
are interchangeable:

1. `selection_eligible` uses the complete declared selection set under the
   classical independent-trials approximation.
2. `declared_attempts` retains failed and excluded attempts in a conservative
   search-count sensitivity while using only real selection-eligible Sharpe
   estimates for cross-trial dispersion.

Part M also reports pairwise return-correlation summaries. It deliberately does
not turn those sample correlations into a supposedly exact effective number of
independent trials. An external effective count can be supplied only together
with a methodology statement:

```text
--dsr-effective-independent-trials 3
--dsr-effective-trial-count-methodology "predeclared cluster analysis"
```

That scenario is labeled user-supplied and unverified. The count must be a
positive integer no greater than the selection-eligible count. When it is not
supplied, its value and verification state are reported as `null`.

Classical DSR is asymptotic plug-in inference. It can be unstable with few
trials or observations, and its standard error does not apply Part H's HAC
serial-dependence adjustment. IID-scaled annualized Sharpe values are included
only as views; DSR itself is calculated at the observation frequency. DSR does
not measure out-of-sample rank degradation and is not CSCV or PBO. A high DSR
is evidence conditional on the complete stated assumptions, not proof of edge
or future profitability. The complete method contract is documented in
[`docs/DEFLATED_SHARPE_RATIO_METHODOLOGY.md`](../DEFLATED_SHARPE_RATIO_METHODOLOGY.md).

### CSCV and Probability of Backtest Overfitting

Part N implements the paper's deterministic Combinatorially Symmetric
Cross-Validation procedure. It partitions the aligned trial matrix into an
explicit even number `S` of equal contiguous slices and enumerates every one of
the `C(S, S/2)` half-sample combinations. Each half-sample is used once as IS
and once as the complementary OOS set.

For every combination, the auditor recalculates period Sharpe for every
selection-eligible completed trial, selects the highest IS value, observes that
same trial's OOS rank, and records:

```text
relative OOS rank = OOS rank / (eligible trials + 1)
rank logit = log(relative rank / (1 - relative rank))
PBO = proportion of rank logits <= 0
```

The complete configuration is required. There are no defaults for the method,
metric confirmation, risk-free rate, partition count, tie handling,
combination limit, or acceptable PBO:

```text
--cscv-method combinatorially_symmetric
--cscv-performance-metric period_sharpe_ratio
--cscv-selection-metric-name validation_sharpe
--cscv-partitions 4
--cscv-annual-risk-free-rate 0.03
--cscv-maximum-combinations 100
--cscv-rank-tie-method average
--cscv-winner-tie-policy first_by_attempt_index
--cscv-maximum-acceptable-pbo 0.05
```

`--cscv-selection-metric-name` must exactly match the manifest's declared
metric. This is an explicit confirmation that the configured period Sharpe is
the same criterion used by the research selection process. Only maximize is
currently supported. OOS ties receive average ranks. IS winner ties are
preserved in the report and resolved by canonical attempt order.

The implementation refuses to trim observations when `T` is not divisible by
`S`, refuses to sample a subset when `C(S, S/2)` exceeds the explicit limit,
and refuses to calculate a partial PBO when any trial/split Sharpe is undefined.
It also reports split-level IS/OOS scores and ranks, the probability that the
selected OOS score is below zero, and linear performance-degradation evidence.

The optional externally declared split CSV is never repurposed as CSCV input.
Those folds preserve the original research design; CSCV constructs its own
equal, exhaustive symmetric partitions. PBO audits how often IS selection
ranks poorly OOS. It does not replace PSR's one-series benchmark question or
DSR's full-sample expected-maximum question, and it is not a strategy-selection
objective. The complete method contract is documented in
[`docs/CSCV_PBO_METHODOLOGY.md`](../CSCV_PBO_METHODOLOGY.md).

### Parameter-neighborhood and temporal robustness

Part O adds two separate explicit diagnostics. A parameter neighborhood uses
user-declared numeric scales and a standardized Euclidean radius around the
selected trial. Every unscaled parameter remains exactly fixed. Equal
contiguous temporal windows report the selected trial's score, average-tie
rank, logit, top-half status, tied-best status, and sign. When a split CSV is
supplied, each declared IS winner is evaluated on its own OOS observations in a
separate fold-consistency object.

```bash
backtest-auditor family \
  examples/cscv_family_manifest.json \
  examples/cscv_family_trials.csv \
  examples/cscv_family_returns.csv \
  --splits-csv examples/cscv_family_splits.csv \
  --parameter-robustness-metric period_sharpe_ratio \
  --parameter-selection-metric-name period_sharpe_ratio \
  --parameter-annual-risk-free-rate 0.03 \
  --parameter-distance-metric standardized_euclidean \
  --parameter-scale lookback=5 \
  --parameter-maximum-distance 3 \
  --parameter-minimum-neighbors 2 \
  --parameter-maximum-score-difference 0.10 \
  --parameter-minimum-acceptable-neighbor-fraction 0.75 \
  --temporal-robustness-metric period_sharpe_ratio \
  --temporal-selection-metric-name period_sharpe_ratio \
  --temporal-annual-risk-free-rate 0.03 \
  --temporal-windows 4 \
  --temporal-rank-tie-method average \
  --temporal-winner-tie-policy first_by_attempt_index \
  --temporal-minimum-acceptable-top-half-fraction 0.75 \
  --temporal-maximum-acceptable-below-zero-fraction 0.25 \
  --format markdown
```

No scale, radius, window count, threshold, or tie rule is assumed. The auditor
does not widen a sparse neighborhood, trim an unequal temporal remainder, or
drop a zero-volatility trial. External folds remain distinct from CSCV. Equal
windows are a limited descriptive stability view, not a formal
structural-break test. The full contract is documented in
[`docs/PARAMETER_TEMPORAL_ROBUSTNESS_METHODOLOGY.md`](../PARAMETER_TEMPORAL_ROBUSTNESS_METHODOLOGY.md).

### Dimensioned evidence profile and audit-run manifest

Part P adds an evidence profile to every Single-Run and Experiment-Family
report. Each dimension independently uses one of four categorical states:

- `ineligible`: a required structural or methodological precondition failed;
- `insufficient_evidence`: the dimension could be evaluated only after more
  evidence or an explicit method configuration is supplied;
- `fragile`: the method ran, but an explicit evidence requirement failed or a
  material adverse condition was observed;
- `supported_under_stated_assumptions`: the available evidence meets the
  configured requirement, conditional on the assumptions preserved beside it.

There is intentionally no total score, weighted average, global status, or
`pass`. Every dimension preserves supporting, adverse, and unavailable codes,
assumptions, and the next evidence required. A supported dimension does not
certify skill, profit, causality, or future performance, and it cannot cancel
an adverse or unavailable dimension.

Both CLI modes can also emit a content-hashed audit-run manifest. The identity
is opt-in for backward compatibility, but its three fields are all-or-none:

```bash
backtest-auditor examples/sample_returns.csv \
  --run-id example-run \
  --audit-id audit-2026-08-12-001 \
  --audit-timestamp 2026-08-12T20:00:00+02:00 \
  --git-commit abc123def456 \
  --format json \
  --output audit.json
```

The timestamp must be timezone-aware and is recorded in UTC. The auditor never
uses the current clock or infers a Git revision. The Git value is a producer
declaration: it is recorded but not independently verified.

The manifest separates three identities:

1. Every raw input file has its bytes, size, basename, role, and SHA-256
   recorded. Absolute paths are excluded.
2. Canonical normalized data has its own SHA-256. Timestamps use ISO 8601 and
   floating-point values use exact hexadecimal encodings, so semantically
   equivalent row ordering produces the same normalized-data identity.
3. The normalized explicit audit configuration has a separate canonical JSON
   representation and SHA-256.

It also records package and report-schema versions, versioned audit methods,
random seeds, input/finding warning codes, Python and platform identity, and
NumPy, pandas, and SciPy versions. A final SHA-256 covers the complete public
manifest body. Because environment versions are evidence, different execution
environments intentionally produce different manifest hashes. The complete
contract and interpretation boundaries are documented in
[`docs/EVIDENCE_PROFILE_AND_RUN_MANIFEST.md`](../EVIDENCE_PROFILE_AND_RUN_MANIFEST.md).

### Annualized statistics and basic Sharpe

Once sampling is eligible, the auditor calculates:

- annualized arithmetic mean return using `period mean × periods per year`;
- annualized sample volatility using the square-root-of-time rule;
- a basic annualized Sharpe ratio when an annual risk-free rate is supplied.

Both simple-return and log-return inputs are supported. Log returns are
converted period by period to simple returns before these calculations, and the
report records `simple` as the return basis. This avoids mixing a log-return
mean with a simple risk-free rate.

`--annual-risk-free-rate` is an effective annual simple rate expressed as a
decimal, so `0.03` means 3%. It has no default. The auditor converts it to the
equivalent compounded period rate:

```text
period rate = (1 + annual rate) ** (1 / periods per year) - 1
```

Sharpe remains undefined when the rate is not supplied or sample volatility is
zero. Missing values are reported as JSON `null` and Markdown `undefined`.

These point estimates use linear mean scaling and square-root-of-time
volatility scaling. Those transformations still require a defensible sampling
policy and are not a substitute for checking serial dependence.

### Distribution shape and Probabilistic Sharpe Ratio

Part E estimates sample skewness, excess kurtosis, and Pearson kurtosis on
period-by-period simple returns. Log-return inputs are converted before the
moments are estimated. The skewness and kurtosis estimates use finite-sample
bias corrections. Pearson kurtosis is reported explicitly because the PSR
formula uses the convention where a normal distribution has kurtosis 3; excess
kurtosis is also reported, where normal equals 0.

At least three varying observations are needed for skewness and four for
kurtosis. Because PSR needs both higher moments, at least four varying returns
are required before Sharpe uncertainty is eligible.

For period Sharpe ratio `SR`, observation count `n`, sample skewness `gamma3`,
and sample Pearson kurtosis `gamma4`, the auditor estimates:

```text
Sharpe variance adjustment =
    1 - gamma3 * SR + ((gamma4 - 1) / 4) * SR**2

period Sharpe standard error =
    sqrt(Sharpe variance adjustment / (n - 1))
```

PSR answers the probability-style question: how strongly does the observed
Sharpe ratio exceed an explicitly chosen benchmark after accounting for track
record length, skewness, and kurtosis?

```text
PSR(SR*) = Phi((SR - SR*) / period Sharpe standard error)
```

`Phi` is the standard normal cumulative distribution function. The formula is
evaluated at the observation frequency. The CLI accepts an annualized benchmark
for usability and converts it to the equivalent period Sharpe by dividing by
the square root of periods per year.

`--benchmark-annualized-sharpe-ratio` has no default. To test against a
zero-Sharpe benchmark, supply `0.0` explicitly. A PSR value is evidence relative
to that selected benchmark; it is not itself proof of trading skill.

### Minimum track-record length and confidence requirements

Part F turns PSR into an explicit evidence decision only when the user supplies
`--required-psr-confidence-level`. The value must be strictly between `0.5`
and `1.0`; there is deliberately no default of 95%. The confidence requirement
also requires an explicit Sharpe benchmark because MinTRL answers how much
evidence is needed to exceed that particular benchmark.

For confidence level `c`, standard-normal critical value `z_c`, period Sharpe
`SR`, benchmark `SR*`, skewness `gamma3`, and Pearson kurtosis `gamma4`:

```text
Sharpe variance adjustment =
    1 - gamma3 * SR + ((gamma4 - 1) / 4) * SR**2

MinTRL =
    1 + Sharpe variance adjustment * (z_c / (SR - SR*))**2
```

The formula returns a continuous observation count. The operational minimum
is rounded up to a whole observation and cannot be below four, because this
implementation needs four varying observations to estimate skewness and
kurtosis. The report shows the continuous estimate, whole-observation minimum,
equivalent years under the explicit periods-per-year scale, and the current
shortfall or surplus.

If the observed Sharpe does not exceed the selected benchmark, no finite
MinTRL is reported: adding observations cannot produce confidence above 50%
while the estimated Sharpe and distribution remain unchanged. If the observed
Sharpe does exceed the benchmark but PSR is below the requested confidence,
the reported additional observations are conditional on the strategy and its
return distribution remaining unchanged. They are not a promise that future
performance will preserve the current estimates.

### Serial-dependence diagnostics

Part G calculates the sample autocorrelation function and one Ljung-Box
portmanteau test through an explicitly selected maximum lag. Both choices must
be supplied together:

```text
--serial-max-lag 2
--serial-significance-level 0.05
```

Neither value has a default. The maximum lag determines which return delays
are examined, while the significance level determines the rejection decision.
The maximum lag must be positive and strictly below the number of return
observations. The significance level must be strictly between 0 and 1.

For demeaned period returns and sample autocorrelations `rho_k`, Part G uses:

```text
rho_k =
    sum((r_t - mean) * (r_(t-k) - mean))
    / sum((r_t - mean)**2)

Q = n * (n + 2) * sum(rho_k**2 / (n - k), k=1..h)
```

Under the zero-autocorrelation null, `Q` is compared with an asymptotic
chi-square distribution with `h` degrees of freedom. The report marks serial
dependence as detected only when:

```text
p-value < significance level
```

The report includes every sample autocorrelation through the selected lag, the
strongest absolute autocorrelation, the Ljung-Box statistic, degrees of freedom,
p-value, significance level, and decision. Simple returns are the canonical
basis; log-return inputs are converted period by period first, consistently
with the annualized and PSR calculations.

If annualized statistics are eligible but the diagnostic is not configured,
the report records `SERIAL_DEPENDENCE_DIAGNOSTIC_NOT_CONFIGURED`. A configured
diagnostic with a lag that is not below the sample size, or a zero-variance
series, produces a structured ineligibility finding instead of a fabricated
test result.

A Ljung-Box rejection is evidence that the IID-style interpretation behind
square-root-of-time scaling, the base Sharpe uncertainty, PSR, and MinTRL may
be unreliable. Failure to reject is not proof that returns are independent,
and the chi-square p-value is an asymptotic approximation that deserves extra
caution with short samples. Part G diagnoses dependence without changing the
earlier metrics; Part H reports a separately configured adjustment beside them.

### Serial-dependence adjustment

Part H applies a Bartlett heteroskedasticity-and-autocorrelation-consistent
(HAC) adjustment only when both choices are explicit:

```text
--hac-max-lag 2
--hac-kernel bartlett
```

The maximum lag is the HAC bandwidth. It must be a positive integer below the
number of observations. The kernel has no default; `bartlett` is the only
supported kernel in this increment. Ljung-Box diagnostic choices are not
silently reused because testing for dependence and choosing an adjustment are
different methodological decisions.

For bandwidth `H`, Part H assigns each lag `k` the Bartlett weight:

```text
w_k = 1 - k / (H + 1)
```

#### Annualized Sharpe point estimate

The return long-run variance ratio is:

```text
D_returns = 1 + 2 * sum(w_k * rho_k, k=1..H)
```

where `rho_k` is the sample return autocorrelation. The IID annualization
factor `sqrt(P)` becomes:

```text
HAC annualization factor = sqrt(P / D_returns)
```

Positive dependence generally produces `D_returns > 1` and reduces the
annualized Sharpe; negative dependence can have the opposite effect. When
`H = P - 1`, the Bartlett weights equal the finite-horizon weights in Lo's
time-aggregation formula. Otherwise, the report labels the result as a
truncated HAC approximation rather than claiming it is the complete Lo
annual-horizon calculation.

#### Sharpe uncertainty, PSR, and MinTRL

Raw-return autocorrelation alone is not the correct dependence adjustment for
the sampling uncertainty of a Sharpe estimator. Part H therefore constructs
the first-order Sharpe influence series:

```text
psi_t = z_t - (SR / 2) * (z_t**2 - 1)
```

where `z_t` is the centered return divided by sample volatility and `SR` is
the period Sharpe. A second Bartlett ratio is estimated from the influence
autocorrelations:

```text
D_sharpe = 1 + 2 * sum(w_k * rho_psi,k, k=1..H)
```

The existing higher-moment variance adjustment `A` is retained, then scaled:

```text
HAC Sharpe variance adjustment = A * D_sharpe
HAC period Sharpe SE = sqrt(A * D_sharpe / (n - 1))
effective observations = 1 + (n - 1) / D_sharpe
```

The HAC-adjusted PSR uses this standard error at the observation frequency.
When an explicit confidence requirement exists, adjusted MinTRL is:

```text
HAC MinTRL =
    1 + A * D_sharpe * (z_confidence / (SR - SR_benchmark))**2
```

The report preserves all IID-style values beside the HAC values. It does not
retroactively overwrite Part D-F results. A configured but ineligible
adjustment also remains visible with its bandwidth, kernel, status, and any
partial point-estimate evidence that could be calculated.

These HAC quantities are asymptotic plug-in estimates. They can be unstable in
short samples, especially when several autocorrelations are estimated from few
observations. Negative dependence can produce an effective observation count
above the raw count; that is a variance-equivalence interpretation, not extra
data.

Part H assumes stationarity over the sample and treats the selected bandwidth
and estimated autocorrelations as fixed plug-in quantities. It does not include
bandwidth-selection uncertainty, automatic bandwidth selection, alternative
kernels, prewhitening, or structural-break correction. Part I adds a separate
resampling view rather than changing these point and asymptotic estimates.

### Dependent-data bootstrap confidence intervals

Part I calculates resampling-based uncertainty only when every methodological
choice is supplied explicitly:

```text
--bootstrap-method moving_block
--bootstrap-interval-method percentile
--bootstrap-replications 2000
--bootstrap-confidence-level 0.95
--bootstrap-block-length 2
--bootstrap-seed 42
```

There are no defaults. V1.4 supports `moving_block` and `stationary`; percentile
is the supported interval method. The seed is mandatory so the report is
exactly reproducible. The confidence level must be strictly between `0.5` and
`1.0`, the replication count must be at least two, and the fixed or mean block
length must be a positive integer strictly below the observation count at
calculation time.

The moving-block bootstrap constructs all overlapping consecutive source
blocks of length `L`. For each replication it draws enough block starts with
replacement to reconstruct `n` returns, concatenates the selected blocks, and
truncates the final block if `n` is not divisible by `L`. This preserves local
ordering inside each block. A block length of one is permitted but produces an
explicit warning because it is equivalent to an IID bootstrap and preserves no
serial dependence.

For `--bootstrap-method stationary`, `--bootstrap-block-length L` is the mean
block length. The first source index is uniform; each later index restarts from
a uniform source position with probability `1/L`, otherwise it advances one
position circularly. This is the Politis–Romano stationary bootstrap and avoids
the fixed block boundaries of moving-block resampling.

For confidence level `c`, the two-sided percentile interval uses the empirical
bootstrap quantiles:

```text
lower quantile = (1 - c) / 2
upper quantile = 1 - (1 - c) / 2
```

Each metric records its point estimate, lower and upper bounds, bootstrap
standard error, attempted replications, successful replications, and a typed
status. Part I covers:

- period arithmetic mean;
- period sample volatility;
- cumulative simple return over the original fixed observation horizon;
- annualized arithmetic mean;
- IID-scaled annualized sample volatility;
- period Sharpe;
- IID-scaled annualized Sharpe;
- Bartlett-HAC-adjusted annualized Sharpe when the Part H point estimate exists.

For the HAC-adjusted Sharpe interval, Part I re-estimates the configured
Bartlett return long-run-variance ratio inside every bootstrap replication.
Replications with zero volatility, a non-positive HAC ratio, or a non-finite
estimate are counted and excluded for that metric only; the report never hides
the successful-versus-attempted count.

Dependent-data resampling requires a regular declared or inferred sampling
sequence. An irregular, ambiguous, or conflicting schedule produces a typed
`sampling_ineligible` result while retaining the entire specification. Fewer
than 1,000 replications produce a warning about Monte Carlo variation.

These intervals are conditional on stationarity, the selected block length,
the finite replication count, and the percentile construction. They do not
select an optimal block length, test structural stability, use a dependent-data
BCa or studentized interval, or remove backtest selection bias. A reproducible
interval is not automatically a well-calibrated interval.

### Observation calendars and return construction

Parts J and K close the contextual single-run contract. Calendar verification
is distinct from generic pandas-frequency inference. `24/7` generates every
calendar date, while `WEEKDAYS` generates Monday through Friday and is
explicitly not an exchange-holiday calendar. A named exchange such as `XNYS`
is preserved as `declared_unverified` unless an authoritative session-date CSV
is supplied:

```text
--timestamp-timezone America/New_York
--observation-calendar XNYS
--calendar-timezone America/New_York
--calendar-sessions-csv xnys_sessions.csv
--calendar-session-column session
```

The session file must contain unique, strictly increasing dates. Exact matches
receive `calendar_verified` sampling status and can qualify for annualization
with an explicit periods-per-year value. Missing and unexpected dates remain in
the public report. Multiple observations on one local date are not treated as
verified because intraday bar boundaries require a richer market schedule.

Return construction is a partial-evidence contract rather than an all-or-
nothing parser. The auditor records 13 fields covering transaction costs,
fees, leverage, currency, price adjustment, source, data vintage, stale-price
treatment, delisting-return treatment, survivorship control, look-ahead
control, signal timing, and execution timing. Missing fields generate grouped
findings; no value is inferred. The boolean bias-control fields are declarations
from the producer of the returns, not independent proof that the controls were
implemented correctly.

### Performance path and benchmark-relative evidence

Part K adds a deliberately small path section: terminal wealth, cumulative
simple return, CAGR when annualization is eligible, maximum drawdown with
peak/trough/recovery timestamps, drawdown duration, and longest time
underwater. Wealth starts at 1.0. CAGR uses the explicit periods-per-year scale
and observation count rather than wall-clock inference.

An optional benchmark is supplied as a second return CSV:

```text
--benchmark-csv examples/sample_benchmark.csv
--benchmark-id market
--benchmark-return-convention simple
```

The benchmark must have exactly the same timestamps as the strategy. The
auditor never silently inner-joins or drops unmatched observations; a mismatch
withholds all relative statistics and reports both one-sided timestamp sets.
When eligible, the report includes cumulative benchmark performance, relative
terminal wealth, mean active return, sample tracking error, information ratio,
return correlation, beta, and arithmetic alpha. Annualized tracking error,
information ratio, and alpha use the same explicit strategy scale and remain
undefined when that scale is ineligible.

Benchmark return-construction and calendar flags use the `--benchmark-`
prefix. Currency and gross/net cost-basis differences generate comparability
findings even when the numerical series align.

V1 contains calendar and methodology evidence, descriptive
statistics, path evidence, optional benchmark-relative evidence, sampling
assessment, eligible annualized statistics, a basic Sharpe point estimate,
distribution shape, higher-moment-adjusted Sharpe uncertainty, PSR, MinTRL,
serial-dependence diagnostics, Bartlett-HAC annualization and inference
adjustments, moving-block or stationary percentile bootstrap intervals, canonical
Experiment-Family ingestion, classical DSR with explicit trial-count
sensitivities, exhaustive CSCV/PBO with split-level evidence, and structured
evidence findings. It also includes explicit parameter/temporal robustness,
dimensioned evidence profiles, and deterministic audit-run manifests.
Automatic bandwidth or block-length selection, alternative kernels and
bootstrap interval methods, HTML, and cross-engine reconciliation belong to
later versions.

The PSR implementation follows Bailey and López de Prado, *The Sharpe Ratio
Efficient Frontier* (2012):
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643

The classical location-only DSR follows Bailey and López de Prado, *The
Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and
Non-Normality* (2014):
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

The explicit location-only label also reflects López de Prado and Porcu, *The
Deflated Sharpe Ratio: A Unified Framework for Search-Adjusted Performance
Inference*:
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7198158

The CSCV/PBO implementation follows Bailey, Borwein, López de Prado, and Zhu,
*The Probability of Backtest Overfitting*:
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

The Ljung-Box statistic follows the NIST Engineering Statistics Handbook:
https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/ljungbox.htm

The serial-correlation-aware Sharpe time aggregation follows Andrew Lo,
*The Statistics of Sharpe Ratios* (2002):
https://rpc.cfainstitute.org/research/financial-analysts-journal/2002/the-statistics-of-sharpe-ratios

The positive semi-definite Bartlett HAC construction follows Newey and West,
*A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation
Consistent Covariance Matrix* (1987):
https://www.nber.org/papers/t0055

The moving-block bootstrap follows Kunsch, *The Jackknife and the Bootstrap for
General Stationary Observations* (1989):
https://projecteuclid.org/journals/annals-of-statistics/volume-17/issue-3/The-Jackknife-and-the-Bootstrap-for-General-Stationary-Observations/10.1214/aos/1176347265.full

The stationary bootstrap follows Politis and Romano, *The Stationary
Bootstrap* (1994):
https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870

The heteroskedasticity-robust variance-ratio statistic follows Lo and
MacKinlay, *Stock Market Prices Do Not Follow Random Walks* (1988):
https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/8729.pdf

White Reality Check and Hansen SPA follow their primary papers:
https://users.ssc.wisc.edu/~behansen/718/White2000.pdf
https://www.tandfonline.com/doi/abs/10.1198/073500105000000063

The target-dependent downside measures follow Sortino and Price, and Omega
follows Keating and Shadwick:
https://research.rug.nl/files/604914965/DOWNSIDE_RISK_Capturing_what_s_at_stake.pdf
https://oxfordstrat.com/coasdfASD32/uploads/2016/03/A-Universal-Performance-Measure.pdf

The expected-shortfall interpretation follows Rockafellar and Uryasev,
*Optimization of Conditional Value-at-Risk*:
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=267256

The percentile interval definition follows the SciPy statistical documentation:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html
