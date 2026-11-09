# Evidence Profile and Audit-Run Manifest

Part P adds two report-level contracts without changing the mathematical
results from earlier increments. Report schema `2.5` exposes a dimensioned
evidence profile and an optional deterministic audit-run manifest for both
audit modes.

## Evidence-profile contract

The profile is a structured interpretation of completed typed results. It does
not parse report prose and it does not recalculate statistical methods.

Every dimension has:

- a stable dimension name and categorical status;
- a short summary;
- supporting, adverse, and unavailable evidence codes;
- explicit assumption codes; and
- the next evidence required when the dimension is not supported.

The only statuses are:

| Status | Meaning |
|---|---|
| `ineligible` | A structural, sampling, alignment, or method precondition failed, so the claimed evidence is withheld. |
| `insufficient_evidence` | The needed declaration, comparator, method, or threshold was not configured or supplied. |
| `fragile` | The method ran, but an explicit requirement failed or a material adverse condition remains. |
| `supported_under_stated_assumptions` | The available evidence meets the declared requirement, conditional on all preserved assumptions and limitations. |

These categories are not ordinal grades and must not be converted to numbers.
JSON includes `"overall_status": null` as an explicit interoperability
boundary; the typed domain result has no overall-status field. Markdown states
that overall status is not calculated.

No profile status certifies skill, alpha, correctness of an upstream backtest,
causality, profit, or future performance. Dimensions are deliberately
independent. For example, an eligible sampling dimension cannot compensate for
missing leakage declarations, and a met PSR requirement cannot compensate for
an incomplete experiment family.

### Single-Run dimensions

| Dimension | Main evidence interpreted |
|---|---|
| `input_integrity` | Canonical blocking validation and preserved normalization issue codes |
| `return_methodology` | Cost basis, timing, data provenance, survivorship, and look-ahead declarations |
| `sampling_eligibility` | Frequency/calendar assessment and annualization eligibility |
| `statistical_evidence` | Annualized point estimates, PSR, and the configured confidence requirement |
| `serial_robustness` | Serial diagnostic and explicit Bartlett-HAC adjustment |
| `resampling_robustness` | Moving-block bootstrap eligibility and the period-Sharpe interval |
| `benchmark_evidence` | Exact timestamp alignment for benchmark-relative evidence |
| `reproducibility` | Presence of the complete Part P audit-run manifest |

The resampling dimension uses a zero period-Sharpe reference only as an
explicit Part P interpretation rule. A configured eligible interval is
`fragile` when its lower bound is not strictly positive. This does not turn the
bootstrap interval into a strategy-selection objective.

### Experiment-Family dimensions

| Dimension | Main evidence interpreted |
|---|---|
| `input_integrity` | Canonical family validation and preserved normalization issue codes |
| `experiment_completeness` | Complete declared search, eligible trial count, and aligned observation matrix |
| `multiple_testing_evidence` | Complementary DSR confidence and CSCV/PBO requirements |
| `parameter_robustness` | Frozen parameter-neighborhood density, plateau tolerance, and local-maximum evidence |
| `temporal_robustness` | Equal-window requirements and declared-fold winner retention |
| `reproducibility` | Presence of the complete Part P audit-run manifest |

The multiple-testing dimension requires both DSR and CSCV/PBO before it can be
supported. The methods retain their distinct questions and assumptions; the
profile does not blend their values.

## Audit-run manifest contract

The CLI creates a manifest only when all three identity fields are explicit:

```text
--audit-id <stable audit execution ID>
--audit-timestamp <timezone-aware ISO 8601 timestamp>
--git-commit <source revision declaration>
```

Partial identity is a CLI error. A timestamp without an offset is a CLI error.
The timestamp is normalized to UTC. The current clock, repository state, and
Git revision are never inferred. `--git-commit` is intentionally a free-form
non-empty source identity so an explicitly declared non-commit state can be
preserved; the auditor does not verify that declaration.

### Raw input identity

Every supplied external input is streamed through SHA-256 before the audit
result is built. The manifest records:

- a stable semantic role;
- the basename, never the absolute path;
- the byte length; and
- the lowercase SHA-256 digest.

Single-Run roles cover strategy returns, optional strategy calendar sessions,
benchmark returns, and benchmark calendar sessions. Experiment-Family roles
cover the manifest, trials, return matrix, optional split file, and optional
shared benchmark.

### Normalized-data identity

The normalized-data hash is calculated after file adapters have applied the
canonical validation and ordering contract. The encoding is named
`canonical_json_float_hex_v1`:

- mapping keys are sorted;
- timestamps use ISO 8601;
- finite floating-point observations use Python's exact hexadecimal form; and
- JSON uses UTF-8 with no insignificant whitespace.

The Single-Run normalized-data identity includes timestamps, exact return
values, return convention, and optional benchmark observations. Sampling,
calendar, construction, and statistical-method declarations belong to the
configuration identity. Consequently, changing a periods-per-year declaration
does not pretend that the observed return data changed.

The Experiment-Family identity covers the normalized family manifest, complete
trial table, aligned return matrix, declared splits, and optional benchmark.
The family contract itself is source evidence and is therefore part of the
normalized family identity.

### Configuration identity

The manifest retains normalized JSON and a separate SHA-256 for every explicit
audit declaration and method specification. This includes sampling and return
construction declarations, benchmark declarations, risk-free rates,
confidence requirements, lag/bandwidth choices, bootstrap settings, DSR/CSCV
settings, and parameter/temporal robustness settings as applicable.

No output path or current process directory is included.

### Versions, seeds, warnings, and environment

The manifest records:

- the installed package version (currently `1.5.0`), report schema `2.5`, and
  manifest schema `1.1`;
- every configured method name and method version;
- every configured random seed by purpose;
- input normalization issue and audit-finding codes;
- Python implementation/version and operating-system/machine identity; and
- NumPy, pandas, and SciPy versions.

The final `manifest_sha256` is SHA-256 over canonical JSON for the complete
public manifest body excluding only that final hash field. A consumer can
remove `manifest_sha256`, serialize the remaining object with sorted keys and
compact separators, and recompute the recorded value.

Environment and dependency versions are included because they are material
reproducibility evidence. Two runs in different environments may have the same
raw, normalized-data, and configuration hashes while correctly having
different final manifest hashes.

## Determinism boundary

With identical explicit identity, normalized inputs, configuration, package,
method versions, warnings, seeds, and environment, the manifest and rendered
report are byte-for-byte deterministic. Determinism identifies an execution;
it does not establish that the upstream backtest engine produced correct
returns or that a supplied Git declaration is truthful.
