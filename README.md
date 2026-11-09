# Backtest Integrity Auditor

Backtest Integrity Auditor checks what a backtest result can and cannot support.
It tests the statistics behind a performance claim, from the Sharpe ratio to the
Deflated Sharpe Ratio and the probability of backtest overfitting across a family
of trials, and it compares the same strategy run in different backtesting engines,
record by record. It never runs a backtest or places an order, and it never picks a
risk-free rate, an annualization scale or an audit identity for you.

![Growth of 1 for a synthetic three-year return series with its maximum
drawdown shaded, next to its annualized Sharpe ratio of 0.55 with 95 %
bootstrap intervals that include zero](docs/assets/readme-figure.png)

*The demo's synthetic input after step 2 of [Getting started](docs/getting-started.md),
which adds a bootstrap: an annualized Sharpe ratio of 0.55 whose 95 % bootstrap
intervals include zero. `scripts/make_readme_figure.py` draws it from that
report's JSON.*

## A 5-minute demo on synthetic data

You need Python 3.11 or newer. The package is not on PyPI yet, so install it
from a clone of this repository:

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install .
```

The input is invented: 783 weekday returns of a made-up strategy, drawn from a
seeded Student-t distribution (fat tails) with a small positive drift. No market
data and no real strategy are involved. This rebuilds the file, and `git diff`
shows no change afterwards:

```bash
python examples/quickstart/make_audit_returns.py
```

Run the audit:

```bash
backtest-auditor examples/quickstart/audit_returns.csv \
  --run-id quickstart \
  --declared-frequency B \
  --periods-per-year 252 \
  --annual-risk-free-rate 0.0 \
  --benchmark-annualized-sharpe-ratio 0.0 \
  --required-psr-confidence-level 0.95 \
  --format markdown \
  --output report.md
```

`report.md` opens with one status per evidence dimension. There is no total
score and no pass or fail:

| Dimension | Status |
| --- | --- |
| input_integrity | supported_under_stated_assumptions |
| return_methodology | insufficient_evidence |
| sampling_eligibility | supported_under_stated_assumptions |
| statistical_evidence | fragile |
| serial_robustness | insufficient_evidence |
| resampling_robustness | insufficient_evidence |
| benchmark_evidence | insufficient_evidence |
| temporal_robustness | insufficient_evidence |
| reproducibility | insufficient_evidence |

The Probabilistic Sharpe Ratio is below the 95 % confidence the command asked
for, and the report says how long the track record would have to be:

| Metric | Value |
|---|---:|
| Required PSR confidence level | 0.95 |
| Observed Probabilistic Sharpe Ratio | 0.83282332394 |
| Minimum required whole observations | 2272 |

2,272 trading days is about nine years of this strategy, not three. Each
`insufficient_evidence` row names the evidence it is missing, such as a
serial-dependence diagnostic, a bootstrap, a benchmark or a declared audit
identity.
[Getting started](docs/getting-started.md) adds them one at a time. The outputs
quoted here are regenerated and compared by
`python scripts/docs_snippets.py --check`.

## What else it does

- **Families of trials.** Deflated Sharpe Ratio, CSCV and the probability of
  backtest overfitting, White's Reality Check, Hansen's SPA test, parameter and
  temporal robustness, over every trial you supply.
- **Implementation risk.** Exporters for vectorbt, bt, Backtrader,
  NautilusTrader and QuantConnect LEAN map a finished run to one canonical
  bundle; the audit compares it with a declared reference, level by level,
  under explicit policies. One executed notebook per engine is in
  `examples/notebooks/`.
- **Edge audit** (`python -m backtest_auditor.edge_audit`): a realised trade
  log in, evidence of edge, timing and sizing, decay and cost sensitivity out
  (`docs/edge_audit/DESIGN.md`).
- **Reproducibility.** With `--audit-id`, `--audit-timestamp` and
  `--git-commit`, a report carries a manifest with SHA-256 identities of its
  inputs and settings. The same inputs and environment give the same report.

## Limitations

- A `supported_under_stated_assumptions` status does not certify skill, profit
  or future performance.
- It cannot see your code. A single-run audit records whether look-ahead and
  survivorship controls were declared. It cannot check them.
- Selection-bias evidence covers only the trials you supply.
- The classical plug-in standard error is too optimistic on fat-tailed data.
  On 4,000 simulated fat-tailed trade logs with no edge, the Deflated Sharpe
  test with that error fired in 6.22 % of logs at a nominal 5 %
  (`docs/edge_audit/DESIGN.md`). The edge audit uses the error under the null
  hypothesis instead; the single-run and family reports still use the plug-in.
- The edge audit's decay detectors are calibrated for independent, normal
  trades. Under Student t(3) trades they alarm in 5.9–20.8 % of logs with no
  change, under AR(1) φ = 0.3 in 17.0–68.2 % (`docs/edge_audit/CALIBRATION.md`).
- Each engine adapter is tested against one engine version and refuses any
  other: vectorbt 1.1.0, bt 1.2.0, Backtrader 1.9.78.123, NautilusTrader
  1.231.0, QuantConnect LEAN 2.5.17999.
- Six tests are strict expected failures on purpose. Four pin behaviour that is
  documented as a choice, not a defect: two conventions, one property of the
  method and one safety rule (`FINDINGS_DISPOSITION.md`). Two are open adapter
  limits: a NautilusTrader bundle has no equity level, and Backtrader
  cheat-on-close snapshots show the state before the fill (`tests/e2e/MATRIX.md`).
- Simulation realism, portfolio risk and live performance are outside the
  package ([Concepts](docs/concepts.md)).

## Documentation

`docs/` is a MkDocs site: getting started, concepts, one how-to per engine, an
API reference built from the docstrings, and an FAQ.

```bash
python -m pip install -e . -r requirements-docs.txt
mkdocs serve
```

## Tests

```bash
python -m pip install -e ".[dev]" -r requirements-dev.txt
python -m pytest -q
```

`requirements-adapters.txt` adds the pinned engine SDKs; without them the
engine tests skip themselves.

## Licence, citation, contributing

Apache License 2.0 (`LICENSE`, `NOTICE`). Citation metadata is in
`CITATION.cff`. See `CONTRIBUTING.md` and `SECURITY.md`. I build this package
with AI coding agents (Claude Code) and check their output with tests.
