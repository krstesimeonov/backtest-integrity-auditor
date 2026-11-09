# How to audit a Backtrader backtest

Record a Backtrader 1.9.78.123 run with the package's analyzer, export it,
map it to canonical bundle 1.0, and audit it against a reference
implementation. The code blocks are quoted from
`examples/notebooks/03_backtrader.ipynb`, executed and committed with its
outputs.

## Install

```bash
python -m pip install ".[backtrader]"
```

The extra pins `backtrader==1.9.78.123`; the analyzer refuses any other
installed Backtrader.

## 1. Add the audit analyzer to the run

Backtrader has no export of its own. `create_backtrader_audit_analyzer`
returns an analyzer class that records orders, executions and the portfolio
on every bar. Backtrader datetimes are usually naive, so you must name the
timezone they are in; the exporter never guesses one.

```python
--8<-- "notebooks/03_backtrader/strategy.py"
```

## 2. Export it and map it to a canonical bundle

```python
--8<-- "notebooks/03_backtrader/export.py"
```

```text
--8<-- "notebooks/03_backtrader/warnings.txt"
```

## 3. Audit it against a reference

```python
--8<-- "notebooks/03_backtrader/audit.py"
```

In the notebook every measured field agrees exactly with the reference and
there is no `adverse` or `evidence_gap` finding, so no score with uncertainty
`not_assessed` means exact agreement here. Read the pair with the findings: a
run whose records cannot be paired at all also has no score and
`not_assessed`, but it carries `evidence_gap` findings.

## Evidence this adapter provides

--8<-- "adapters/backtrader.levels.md"

## Limits

- Exactly Backtrader 1.9.78.123. Every data feed needs a unique name; it
  becomes the canonical instrument id.
- No trade level. Unknown order types stay `custom` with a warning, and
  Backtrader's `Margin` status maps to `rejected` with a warning.
- With `broker.set_coc(True)` (cheat-on-close), the run maps with one
  documented gap: position, cash and equity at fill bars are then the
  pre-fill state (E02, a strict xfail in `tests/e2e`).
