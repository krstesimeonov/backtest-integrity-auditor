# Backtest Integrity Auditor

Backtest Integrity Auditor checks what a backtest result can and cannot
support. It audits return series and families of trials for statistical
evidence, and compares the same strategy across backtesting engines record by
record, without ever running a backtest or placing an order.

<div class="grid" markdown>

- **[Getting started](getting-started.md)**: install, audit one return
  series, read the report, in about five minutes.
- **[Concepts](concepts.md)**: the six layers of backtest integrity, the two
  this package covers, and what it does not claim.
- **How-to guides**: export and audit a backtest from
  [vectorbt](how-to/vectorbt.md), [bt](how-to/bt.md),
  [Backtrader](how-to/backtrader.md),
  [QuantConnect LEAN](how-to/quantconnect-lean.md) or
  [NautilusTrader](how-to/nautilustrader.md).
- **[API reference](reference/index.md)**: generated from the docstrings.
- **[FAQ and honest limits](faq.md)**

</div>

## What a report looks like

Every report states, per independent dimension, whether the configured
evidence supports a claim, and names the evidence that is missing. A
synthetic three-year track record with an annualized Sharpe ratio of about
0.55 reads like this once the statistical methods are configured:

--8<-- "quickstart/step2.profile.txt"

## Status

Package 1.5.2: report schema 2.5, run-manifest schema 1.1,
implementation-risk report and manifest schemas 1.0, canonical bundle 1.0.
Python 3.11+. Not yet published on PyPI; the licence is not decided.
