# Contributing

Thank you for looking. Bug reports, reproducible cases (synthetic data only,
please) and questions are welcome as GitHub issues. Before you write code for a
pull request, open an issue first so we can agree on the change.

The project is licensed under the Apache License 2.0. Under its section 5, a
contribution you submit for inclusion is licensed under the same terms, unless
you state otherwise.

## Set up

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

`requirements-dev.txt` adds the independent references `tests/adversarial`
compares against (statsmodels, arch); `requirements-adapters.txt` adds the
pinned engine SDKs that `tests/e2e` runs. Without them those modules skip
themselves:

```bash
python -m pip install -e ".[dev]" -r requirements-dev.txt -r requirements-adapters.txt
```

Engine SDKs and the notebook toolchain: `-r requirements-examples.txt`
(Python 3.12+ for NautilusTrader). Documentation: `-r requirements-docs.txt`.

## The checks a change must pass

```bash
ruff format --check src tests scripts benchmarks examples
ruff check src tests scripts benchmarks examples
mypy
python -m pytest -q
python scripts/docs_snippets.py --check
mkdocs build --strict
```

`scripts/docs_snippets.py` regenerates every command, output, table and code
block the documentation quotes; run it without `--check` after a change that
alters them. After changing a notebook (`examples/notebooks/make_notebooks.py`),
format and re-execute it with `examples/notebooks/run_notebooks.sh`.

## How the package is meant to behave

- **No silent defaults for the choices that decide a conclusion**: no default
  risk-free rate, annualization scale, audit time, Git revision or instrument
  mapping. Add an explicit option instead. (The documented defaults today: simple
  returns unless `--return-convention log`, and a sampling frequency inferred
  from the timestamps.)
- **Fail closed.** Reject or flag ambiguous input with a message that says what
  to change; never repair it silently.
- **Unavailable is not zero.** Report missing evidence as missing.
- **Public schemas are contracts.** Adding, removing or renaming a report field,
  or changing its meaning, needs an explicit schema-version decision
  (`docs/PUBLIC_REPORT_SCHEMAS.md`).
- **Every behaviour change comes with a test** that fails without it.

## Golden reports

`tests/fixtures/golden/` holds full reports. Their floating-point values can
differ by up to about 120 ULP between NumPy/pandas builds, and
`python scripts/release_contracts.py --check` allows 8 ULP, so the check can
fail on your machine without any code change; `--write` then rewrites the
goldens with that noise. Only regenerate them when a change really alters a
report, and check the diff.
