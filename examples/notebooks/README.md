# Example notebooks: one per engine adapter

Each notebook runs the same toy strategy in one backtesting engine, exports
the result with `backtest_auditor`, maps it to canonical bundle 1.0, checks it
against an independent pandas reference, and runs the implementation-risk
audit twice: on the correct run and on a copy with an injected one-bar
look-ahead.

| Notebook | Engine | How it runs the engine |
|---|---|---|
| `01_vectorbt.ipynb` | vectorbt 1.1.0 | natively, in the notebook |
| `02_bt.ipynb` | bt 1.2.0 | natively, in the notebook |
| `03_backtrader.ipynb` | Backtrader 1.9.78.123 | natively, in the notebook |
| `04_nautilustrader.ipynb` | NautilusTrader 1.231.0 | natively, in the notebook (Python 3.12+) |
| `05_quantconnect_lean.ipynb` | QuantConnect LEAN 2.5.17999 (declared) | not run: reads LEAN's own result files from a recorded local run, checked in under `data/lean/` |

- `toy_strategy.py`: the strategy, the synthetic bars (`data/syn_daily.csv`)
  and the independent reference (pandas and `decimal`, no engine, no auditor).
- `audit_kit.py`: reference bundle, bundle writing with schema validation,
  the implementation-risk policy, and small display helpers.
- `make_notebooks.py`: writes the notebook sources; `run_notebooks.sh`
  executes them with `jupyter nbconvert --execute --to notebook --inplace`.
  Reports land in `_output/` (not committed).

The toy strategy, its reference, the LEAN algorithm (`lean/`) and the LEAN
result files come from W3-J12's end-to-end adapter tests (branch
`wave3/adapter-e2e`, `tests/e2e/`). The data, the LEAN algorithm and the LEAN
result files are byte-identical copies. `toy_strategy.py` is adapted from
`reference.py` (the price generator, its seed and the command-line options are
removed; the short-window test is a function) and `audit_kit.py` from
`harness.py`.

## Which package code produced the outputs

Notebooks 01–04 were executed against this branch's package, 1.5.2. The 1.5.2
LEAN exporter cannot read LEAN 2.5's serialization, so notebook 05 was
executed against a temporary merge of 1.5.2 with `wave3/adapter-e2e`, which
carries the fixes; its first cell prints where the package was imported from.
Executed against that merge, notebooks 01–04 produce the same findings, scores
and compared values as on 1.5.2 (evidence in the release-kit job's
`evidence/notebooks/`).

Notebook 04 calls `export_nautilustrader_reports` with the reports read from
`engine.trader`; the convenience function `export_nautilustrader_engine` fails
on a real 1.231.0 engine in 1.5.2 (also fixed on `wave3/adapter-e2e`).
