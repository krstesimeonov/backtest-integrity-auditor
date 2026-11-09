# How to audit a NautilusTrader backtest

Export the reports of a completed NautilusTrader 1.231.0 backtest, map them to
canonical bundle 1.0, and audit them against a reference implementation. The
code blocks are quoted from `examples/notebooks/04_nautilustrader.ipynb`,
executed and committed with its outputs.

## Install

```bash
python -m pip install ".[nautilustrader]"
```

The extra pins `nautilus_trader==1.231.0`, which needs Python 3.12 or newer;
the exporter refuses any other installed version.

## 1. Run the backtest as usual

```python
--8<-- "notebooks/04_nautilustrader/strategy.py"
```

## 2. Export the four reports and map them to a canonical bundle

`export_nautilustrader_reports` takes the orders, fills, positions and
account reports of one completed run and one account. A `BacktestEngine`
generates them through `engine.trader`:

```python
--8<-- "notebooks/04_nautilustrader/export.py"
```

```text
--8<-- "notebooks/04_nautilustrader/warnings.txt"
```

## 3. Audit it against a reference

The adapter has no equity or return level, and positions only at round-trip
closes, so the notebook compares fills, trades, cash and costs. The venue is a
MARGIN account (a cash account would deny the short), whose balance does not
debit the notional of an open position; the reference cash is the matching
margin balance.

```python
--8<-- "notebooks/04_nautilustrader/audit.py"
```

## Evidence this adapter provides

--8<-- "adapters/nautilustrader.levels.md"

## Limits

- Exactly NautilusTrader 1.231.0, one account and venue per export.
- No equity or return level. In the notebook, a one-bar look-ahead therefore
  shows up only as one-sided records (evidence gaps), never as a measured
  divergence; a per-bar equity record would be needed for that.
- Position snapshots are quantity-only, at position updates; the report does
  not list the fills behind each position, and the mapper does not invent
  those links.
- NautilusTrader puts a random UUID into every position id, so trade ids and
  the bundle's hashes change from run to run, while the compared values do
  not.
