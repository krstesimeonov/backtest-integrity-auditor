# How to audit a vectorbt backtest

Export an executed vectorbt 1.1.0 portfolio, map it to canonical bundle 1.0,
and audit it against a reference implementation. The code blocks on this page
are quoted from `examples/notebooks/01_vectorbt.ipynb`, which was executed
with `jupyter nbconvert --execute` and is committed with its outputs.

## Install

```bash
python -m pip install ".[vectorbt]"
```

The extra pins `vectorbt==1.1.0` and `plotly<7` (vectorbt 1.1.0 does not
import under plotly 7). The exporter refuses any other installed vectorbt.
Mapping an existing export needs no engine at all.

## 1. Run the backtest as usual

The toy strategy of the examples, written the vectorbt way (`ts` is the
example's `toy_strategy` module: prices, the SMA windows, the short window):

```python
--8<-- "notebooks/01_vectorbt/strategy.py"
```

## 2. Export it and map it to a canonical bundle

`export_vectorbt_portfolio` reads the executed one-column portfolio; it never
re-runs it. Pass the instrument id explicitly: vectorbt's own column label
can be `0`. Multi-column portfolios must be exported one column at a time, so
that independent cash books are never added together.

```python
--8<-- "notebooks/01_vectorbt/export.py"
```

The adapter reports every reconstruction it makes:

```text
--8<-- "notebooks/01_vectorbt/warnings.txt"
```

`vectorbt.filled_orders_reconstructed`: vectorbt keeps filled orders only, so
one canonical order is reconstructed per fill. `vectorbt.initial_return_omitted`:
the undefined first period return is left out rather than set to zero.

## 3. Audit it against a reference

The notebook's reference is an independent pandas implementation of the same
rules, turned into canonical artifacts. `kit.implementation_risk` builds the
four policies (normalization plan, comparison policy, measurement policy,
assessment policy) and calls `ImplementationRiskAuditService`:

```python
--8<-- "notebooks/01_vectorbt/audit.py"
```

The same audit runs from the command line once the policies are written as
JSON (see [Implementation-risk policies](implementation-risk-policies.md)).

## Evidence this adapter provides

--8<-- "adapters/vectorbt.levels.md"

## Limits

- Exactly vectorbt 1.1.0; one instrument per export.
- No signal, market-data or strategy-specification evidence: an equity match
  says nothing about whether the signals were the intended ones.
- Orders are reconstructed from fills, so order-level comparison cannot reveal
  orders that never filled.
