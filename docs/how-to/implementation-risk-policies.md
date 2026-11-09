# How to write implementation-risk policies

An implementation-risk audit takes a reference bundle, one or more candidate
bundles, and four policies. Nothing in the policy files has a default (the
CLI's loader requires every field): each choice is written down, hashed, and
named in the report.

| Policy | File the CLI reads | What it decides |
|---|---|---|
| Normalization plan | `--normalization-plan` | For each run (identified by run id, engine, version and source SHA-256): which source instrument ids, currencies, timestamps and frequency map to which canonical ones. Nothing unmapped is guessed. |
| Comparison policy | `--comparison-policy` | Which levels to compare (fill, trade, position, cash, cost, equity, return, …) and how to align records: by economic identity (`semantic`) or by source ids. |
| Measurement policy | `--measurement-policy` | Which fields count as divergence, in which family: transaction cost, sizing, accounting, return. |
| Assessment policy | `--assessment-policy` | The materiality threshold and "extreme" multiple per field, the family weights of the bounded score, whether incomplete evidence withholds the score, and which co-occurrence hypotheses to report. |

## From Python objects to policy files

The policy types serialize themselves (`normalization_plan_to_json`,
`comparison_policy_to_json`, `divergence_policy_to_json`,
`risk_policy_to_json`), so a policy built in Python can be written out for the
CLI. From `examples/notebooks/01_vectorbt.ipynb`, where `kit.policies` builds
the four objects:

```python
--8<-- "notebooks/01_vectorbt/cli-files.py"
```

The same audit from the command line; its JSON report equals the one from
the Python call:

```python
--8<-- "notebooks/01_vectorbt/cli-run.py"
```

## A complete example in the repository

`examples/v1_5i_implementation_risk/` holds a reference bundle, a candidate
bundle, the four policy files and the resulting reports:

```bash
backtest-auditor implementation-risk \
  examples/v1_5i_implementation_risk/reference-bundle.zip \
  examples/v1_5i_implementation_risk/candidate-bundle.zip \
  --normalization-plan examples/v1_5i_implementation_risk/normalization-plan.json \
  --comparison-policy examples/v1_5i_implementation_risk/comparison-policy.json \
  --measurement-policy examples/v1_5i_implementation_risk/measurement-policy.json \
  --assessment-policy examples/v1_5i_implementation_risk/assessment-policy.json \
  --audit-id v1-5i-example-audit \
  --audit-timestamp 2026-08-21T12:00:00Z \
  --git-commit v1.5.0-example \
  --format json \
  --output implementation-risk.json
```

`scripts/check_package.sh` runs exactly this command from an installed wheel
and checks that the report equals the committed
`implementation-risk-report.json` apart from environment fields.

## Choosing thresholds

A threshold says how large a difference must be before it counts. The
examples use values far above floating-point noise and far below the
smallest effect of the defect they look for: a one-bar shift moves a fill
price by at least a cent on 100 shares, so a price threshold of 0.005 and an
equity threshold of 0.01 separate the two cleanly. Thresholds are a modelling
decision; the report lists them so that a reader can disagree.
