# How to audit a bt backtest

Export a completed bt 1.2.0 result, map it to canonical bundle 1.0, and audit
it against a reference implementation. The code blocks are quoted from
`examples/notebooks/02_bt.ipynb`, executed and committed with its outputs.

## Install

```bash
python -m pip install ".[bt]"
```

The extra pins `bt==1.2.0`; the exporter refuses any other installed bt.

## 1. Run the backtest as usual

```python
--8<-- "notebooks/02_bt/strategy.py"
```

## 2. Export it and map it to a canonical bundle

`export_bt_result` reads a completed `bt.Result`. If the result holds more
than one backtest, name the one to export with `strategy_name=`.

```python
--8<-- "notebooks/02_bt/export.py"
```

```text
--8<-- "notebooks/02_bt/warnings.txt"
```

`bt.aggregate_fees_unlinked`: bt records fees per timestamp, so commissions
are not linked to individual fills. `bt.transactions_reconstructed_orders`:
one filled order is reconstructed per transaction.

## 3. Audit it against a reference

bt prepends a virtual row one calendar day before the data to hold the
initial capital, and the adapter maps it as position, cash and equity
evidence. The notebook's reference carries the same initial-capital
observation (`prestart=`); against an engine without such a row, it would
appear as one-sided evidence.

```python
--8<-- "notebooks/02_bt/audit.py"
```

## Evidence this adapter provides

--8<-- "adapters/bt.levels.md"

## Limits

- Exactly bt 1.2.0.
- No trade level, and fees are per timestamp, not per fill.
- Position, cash, value and price histories must share one increasing,
  timezone-aware index; the exporter refuses anything else rather than
  repairing it.
