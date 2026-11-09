# How to audit a QuantConnect LEAN backtest

Export the result files of a completed local LEAN backtest, map them to
canonical bundle 1.0, and audit them against a reference implementation. The
code blocks are quoted from `examples/notebooks/05_quantconnect_lean.ipynb`,
executed and committed with its outputs.

## Install

```bash
python -m pip install ".[quantconnect-lean]"
```

LEAN is not a pip package, and the exporter needs only the standard library,
so this extra installs nothing. LEAN itself runs in .NET; the result files used
here came from a local source build without Docker.

## 1. Run the backtest in LEAN

A local LEAN run writes `<algorithm>.json` and `<algorithm>-order-events.json`.
The notebook does not run LEAN; it reads the two files of a recorded run,
checked in verbatim, and shows LEAN's own summary:

```python
--8<-- "notebooks/05_quantconnect_lean/strategy.py"
```

## 2. Export the result files and map them to a canonical bundle

LEAN's result JSON does not contain its version, so you declare it; only the
conformance-tested 2.5.17999 is accepted.

```python
--8<-- "notebooks/05_quantconnect_lean/export.py"
```

```text
--8<-- "notebooks/05_quantconnect_lean/warnings.txt"
```

## 3. Audit it against a reference

LEAN samples equity at its own chart instants, so the reference equity is
sampled at the same instants; positions are compared after each fill.

```python
--8<-- "notebooks/05_quantconnect_lean/audit.py"
```

## Evidence this adapter provides

--8<-- "adapters/quantconnect_lean.levels.md"

## Limits

- Exactly the declared 2.5.17999. A source build of LEAN reports itself as
  2.5.0.0, so the declaration rests on the source commit it was built from.
- No trade level: LEAN's closed-trade grouping is not treated as a universal
  convention. Positions are derived from fills; returns from the equity chart.
- Final orders carry no separate submission time; the mapper uses the
  creation time and says so in a warning.
