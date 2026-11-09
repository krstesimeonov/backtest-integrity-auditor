# Experiment-Family Input Schema 1.0

Part L defines the file-first contract for V1 Mode B. The input schema version
`1.0` is independent of public report schema `2.5`.

## Invocation

```bash
backtest-auditor family MANIFEST_JSON TRIALS_CSV RETURNS_CSV \
  [--splits-csv SPLITS_CSV] \
  [--benchmark-csv BENCHMARK_CSV] \
  [--dsr-method classic_expected_maximum \
   --dsr-trial-count-policy selection_eligible \
   --dsr-annual-risk-free-rate RATE \
   --dsr-confidence-level LEVEL] \
  [--cscv-method combinatorially_symmetric \
   --cscv-performance-metric period_sharpe_ratio \
   --cscv-selection-metric-name MANIFEST_METRIC \
   --cscv-partitions EVEN_INTEGER \
   --cscv-annual-risk-free-rate RATE \
   --cscv-maximum-combinations POSITIVE_INTEGER \
   --cscv-rank-tie-method average \
   --cscv-winner-tie-policy first_by_attempt_index \
   --cscv-maximum-acceptable-pbo PROBABILITY] \
  [--format json|markdown] \
  [--output PATH]
```

The manifest declares whether a benchmark exists. Therefore,
`--benchmark-csv` and the manifest benchmark fields are all-or-nothing.

## Manifest JSON

Unknown fields are blocking errors. JSON `NaN`, `Infinity`, and `-Infinity` are
not accepted.

| Field | Required | Contract |
|---|---:|---|
| `schema_version` | yes | Exact string `1.0` |
| `family_id` | yes | Non-empty stable family ID |
| `declared_total_attempted_trials` | yes | Positive integer; booleans are not integers |
| `search_complete` | yes | JSON boolean declaration, never inferred from file counts |
| `selected_trial_id` | yes | Must equal the single trial row with `selected=true` |
| `selection_rule` | yes | Non-empty description of the rule used to select the winner |
| `selection_metric` | yes | Non-empty metric identity |
| `selection_direction` | yes | `maximize`, `minimize`, or `custom` |
| `parameter_names` | yes | Alphabetically ordered array of unique strings; may be empty |
| `return_convention` | yes | `simple` or `log` for every trial curve |
| `declared_frequency` | no | Valid pandas offset alias |
| `periods_per_year` | no | Positive integer; no default is assumed |
| `timezone` | no | Valid IANA timezone declaration |
| `source` | no | Non-empty provenance text |
| `benchmark_id` | no | Non-empty shared benchmark ID |
| `benchmark_return_convention` | no | `simple` or `log`; required with `benchmark_id` |

When `search_complete=true`, the trial table must contain every integer attempt
index from 1 through `declared_total_attempted_trials`. When it is false, gaps
are retained and reported as undocumented attempts. Supplying the same number
of rows as the declared total does not override an explicit false declaration.

## Trial metadata CSV

Required columns:

| Column | Contract |
|---|---|
| `trial_id` | Non-empty and unique |
| `attempt_index` | Positive, unique, one-based integer not exceeding the declared total |
| `outcome` | `completed` or `failed` |
| `included_in_selection` | Explicit `true` or `false` |
| `selected` | Explicit `true` or `false`; exactly one row must be true |
| `selection_score` | Finite number for each included completed trial under `maximize` or `minimize`; blank is allowed for failed trials and `custom` rules |
| `parameters` | JSON object whose keys exactly equal `parameter_names` |

Optional columns:

| Column | Contract |
|---|---|
| `source` | Non-empty provenance text when supplied |
| `reason` | Required for failed trials and completed trials excluded from selection |

Parameter values are finite JSON scalars: string, number, or boolean. Empty
strings, `null`, arrays, objects, and non-finite numbers are rejected. A failed
trial cannot be selected, included in selection, or assigned a selection score.
A selected trial must be completed and included in selection. For `maximize`
and `minimize`, every included completed trial requires a score and the winner
must equal the declared optimum; equal-score ties are accepted. A `custom` rule
may omit numeric scores because its decision may not reduce to one scalar.

This model deliberately separates completion, inclusion, and selection. A
completed trial can have a real return curve while being excluded from the
declared selection set; its curve and reason remain evidence rather than being
dropped.

## Long-format return CSV

The only supported columns are:

```text
timestamp,trial_id,return
```

The pair `(trial_id, timestamp)` must be unique. All values must be numeric and
finite; simple returns cannot be below `-1.0`. Every completed trial must have a
series, every failed trial must lack one, and every completed series must contain
the exact same timestamp set. The adapter does not inner-join, forward-fill,
truncate, or manufacture missing observations.

The canonical matrix orders columns by `attempt_index` and rows by ascending
timestamp. A valid but differently ordered CSV is normalized and produces the
non-blocking `FAMILY_RETURNS_SORTED` input issue.

## Optional split-membership CSV

The only supported columns are:

```text
split_id,timestamp,role
```

`role` is `in_sample` or `out_of_sample`. Within each split, every canonical
family timestamp must appear exactly once, both roles must be non-empty, and a
timestamp cannot carry both roles. The same timestamp may have different roles
in different named splits. Exact memberships are retained in JSON, with counts
and date ranges in Markdown.

These declared folds preserve an external train/test design. They are not a
substitute for Part N's explicitly configured combinatorial partitions and are
never silently reused by CSCV.

## Optional benchmark CSV

The benchmark uses the canonical Single-Run columns:

```text
timestamp,return
```

Its ID and convention live in the family manifest. Its timestamps must exactly
match the family matrix. Part L preserves benchmark identity and alignment but
does not calculate per-trial benchmark-relative statistics.

## Structural status

Part L returns one of these family statuses:

| Status | Meaning |
|---|---|
| `eligible` | Complete declared search, at least two selection-eligible trials, and at least four aligned observations |
| `incomplete_search_history` | The search is declared incomplete or attempt metadata is missing |
| `insufficient_eligible_trials` | Complete history but fewer than two trials are in the selection set |
| `insufficient_observations` | Complete multi-trial history but fewer than four aligned observations |

This is only an input-structure gate for family-level methods. Parts M–O
apply additional DSR, CSCV/PBO, parameter-neighborhood, and temporal evidence
gates and return their own statuses.
Family eligibility is not a profitability verdict, statistical validation, DSR
result, PBO result, parameter-neighborhood result, or temporal result. The report
schema is `2.5`; the independent family input
schema remains `1.0`.
