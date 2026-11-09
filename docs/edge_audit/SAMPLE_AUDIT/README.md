# SAMPLE_AUDIT — V4 Edge Audit on a synthetic client log

| File | What it is |
|---|---|
| `AUDIT_LETTER.md` | the client deliverable: summary, recommendations, method, limits |
| `output/edge_audit_report.md` | the full report the CLI writes (all tables) |
| `output/edge_audit_report.json` | the same report as data (schema `edge-audit-report/1.1`) |
| `inputs/trades.csv` | 420 closed trades, schema `edge-audit-trades/1.0` |
| `inputs/prices.csv` | 30-minute prices for ALPHA and BETA, schema `edge-audit-prices/1.0` |
| `make_sample.py` | generates the inputs and runs `edge-audit run inputs/trades.csv --trials 12 --prices inputs/prices.csv --out output` |

Reproduce (repository root, ~7 s): `.venv/bin/python docs/edge_audit/SAMPLE_AUDIT/make_sample.py`.
`tests/edge_audit/test_edge_audit_sample.py` rebuilds everything in a temporary folder,
requires byte-identical files, and checks every number in `AUDIT_LETTER.md` and in the table
below against the JSON.

## Planted truth versus what the audit found

Everything is synthetic: no real person, account or instrument.

| Planted in `make_sample.py` | Found by the audit |
|---|---|
| entry = best of 6 random bars of the day, until session 200 | entry timing +12.26 USD per trade, p = 0.0005 |
| exits at random bars | exit timing p = 0.37 |
| side by coin flip | holding (direction) p = 0.84 |
| fills 1 bp worse than the bar on each side | execution −2.18 USD per trade (2 bps of the 10'907.58 mean notional is 2.18) |
| fees 1.5 bps of notional on each side | fees paid 3.00 bps per round trip |
| quantity independent of everything | sizing permutation p = 0.056 |
| skill stops for trades entered from session 200 (2025-10-13): exit-order trades 295–420 | alarms at trades 344 (rolling expectancy), 367 (Page–Hinkley): 49 and 72 trades after trade 295; CUSUM and mixture SPRT below their thresholds (horizon 1,000 trades) |
| client declares 12 variants | DSR 0.711 → no evidence; with 1 variant the same log would pass (DSR 0.987) |

The generator's skill and volatility parameters were chosen from four tried variants so that
every section of the report has something to show. The sample demonstrates the deliverable;
calibration evidence is in the tests (`TEST_RESULTS.txt`).
