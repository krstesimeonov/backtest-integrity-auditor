# Getting started

Install the package, audit one return series, and read the report. The audit
commands and every output block on this page come from one run of
`scripts/docs_snippets.py`, which re-runs them and fails (`--check`) when the
page no longer matches what the package prints. Only the install and copy
commands are written by hand.

## 1. Install

The package is not on PyPI yet. Install it from a checkout of the repository
into a fresh virtual environment (Python 3.11 or newer):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
```

The core install needs only NumPy, pandas and SciPy. Engine SDKs are optional
extras, one per adapter (see the [how-to guides](how-to/vectorbt.md)).

```text
--8<-- "quickstart/version.txt"
```

## 2. The input: `audit_returns.csv`

The single-run audit reads a CSV with a `timestamp` column and a `return`
column of simple decimal returns (`0.01` is 1 %). The quickstart file is
synthetic: three years of weekday returns (2023-01-02 to 2025-12-31) of an
invented strategy, drawn from a seeded fat-tailed distribution by
`examples/quickstart/make_audit_returns.py`. Copy it into your working
directory:

```bash
cp examples/quickstart/audit_returns.csv .
```

```text
--8<-- "quickstart/head.txt"
```

## 3. First audit

```bash
--8<-- "quickstart/step1.cmd.txt"
```

The command prints nothing and writes `report.md`. The sampling declaration
(`B`, 252 periods per year) is yours to state: the auditor infers the
frequency from the timestamps and checks it against yours, but it never
assumes an annualization scale, so without `--periods-per-year` nothing is
annualized. The three identity options declare the audit ID, the audit time
and the source revision. With them the report carries a content-hashed
run manifest; without them the `reproducibility` dimension reads
`insufficient_evidence`. The CLI requires all three or none, and never reads
your clock or Git state on its own.

The report opens with the **evidence profile**: one status per independent
dimension, no total score and no pass/fail.

--8<-- "quickstart/step1.profile.txt"

Most dimensions say `insufficient_evidence` because nothing beyond the bare
series was configured. The Sharpe ratio is not even computed, because no
risk-free rate was stated and the auditor will not assume one:

--8<-- "quickstart/step1.annualized.txt"

Each gap appears again as a finding with its implication and a remediation
(code and remediation shown):

--8<-- "quickstart/step1.findings.txt"

The **audit-run manifest** identifies exactly what was audited: the SHA-256 of
the raw file,

--8<-- "quickstart/step1.raw.txt"

and of the normalized data and the configuration (excerpt):

--8<-- "quickstart/step1.manifest.txt"

## 4. Ask the statistical questions

Add a risk-free rate, a Sharpe benchmark and a PSR confidence requirement, a
serial-dependence diagnostic, a HAC adjustment and a seeded bootstrap:

```bash
--8<-- "quickstart/step2.cmd.txt"
```

Three dimensions now carry evidence, and all three are `fragile`:

--8<-- "quickstart/step2.profile.txt"

The reasons are in the report. The annualized Sharpe ratio is about 0.55, but
its standard error is about as large, so the Probabilistic Sharpe Ratio
(the probability that the true Sharpe exceeds the benchmark of 0) stays below
the 0.95 that was asked for:

--8<-- "quickstart/step2.psr.txt"

The minimum track-record length says how many observations this Sharpe ratio
and this return distribution would need to meet that requirement:

--8<-- "quickstart/step2.mintrl.txt"

The bootstrap intervals for the annualized Sharpe ratio include zero:

--8<-- "quickstart/step2.bootstrap.txt"

One more line is worth reading closely. The synthetic returns were drawn
independently, yet the Ljung–Box test rejects "no autocorrelation" at the 5 %
level:

--8<-- "quickstart/step2.serial.txt"

A 5 % test rejects a true null hypothesis about once in twenty series; this
seed is one of them. The report says *detected*, not *proven*, and the runs
test on the same series finds nothing. Read each status as evidence under
stated assumptions, never as a verdict.

## 5. Machine-readable output

The same audit as JSON. `scripts/docs_snippets.py` validates this file against
the bundled single-run report schema 2.5 every time it regenerates this page:

```bash
--8<-- "quickstart/step3.cmd.txt"
```

```json
--8<-- "quickstart/step3.json.txt"
```

## Next steps

- [Concepts](concepts.md): the six layers of backtest integrity, the two this
  package covers, and what it does not claim.
- [Full CLI usage](guide/usage.md): calendars, benchmarks, risk-free and gross
  series, regimes, and the experiment-family audit (DSR, CSCV/PBO, Reality
  Check/SPA, robustness).
- The engine how-tos, starting with [vectorbt](how-to/vectorbt.md): export a
  backtest from an engine and audit its implementation against a reference.
