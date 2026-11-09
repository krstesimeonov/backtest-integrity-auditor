# IBKR Activity Flex Import

## Scope

V1.3 adds one deliberately narrow read-only broker adapter. It imports the
period-level `TWR` field from the **Change in NAV** section of an IBKR Activity
Flex query. The source may be one or more exported XML/CSV files or one response
retrieved through Flex Web Service v3.

The adapter does not request positions, trades, orders, fills, cash transfers,
or write access. It does not reconstruct executions, reconcile a backtest to a
broker, attribute performance to individual trades, or place orders. Those are
different evidence problems and remain outside V1.3.

## Required Flex query configuration

Create an **Activity Flex Query** in Client Portal with:

- output format XML or CSV;
- the **Change in NAV** section;
- `AccountId`, `FromDate`, `ToDate`, and `TWR` fields;
- column headers enabled for CSV; and
- a known date format matching `--date-format`.

The supported configured date formats are `yyyyMMdd` (default), `yyyy-MM-dd`,
`MM/dd/yyyy`, `MM/dd/yy`, `dd/MM/yyyy`, `dd/MM/yy`, and `dd-MMM-yy`.

IBKR documents Activity Flex query setup and output choices in its
[Activity Flex documentation](https://www.ibkrguides.com/clientportal/performanceandstatements/activityflex.htm)
and the exact Change in NAV fields in its
[reporting reference](https://ibkrguides.com/reportingreference/reportguide/changeinnav_fq.htm).

## Interval semantics

`ChangeInNAV.TWR` is a percentage return for the statement interval. The
adapter therefore emits exactly one simple-return observation per source
interval:

```text
timestamp     = ToDate
simple return = TWR / 100
period_start  = FromDate
period_end    = ToDate
```

A statement covering a month produces one monthly observation. It does not
contain a hidden daily return series. Build a daily series only from distinct
non-overlapping daily statements, and a monthly series only from distinct
non-overlapping monthly statements. Duplicate and overlapping intervals are
rejected. Inputs are ordered deterministically by interval start/end.

IBKR removed the Activity Flex NAV time-series section in 2017, as recorded in
its [archived statement release notes](https://ibkrguides.com/releasenotes/archive/statements-and-reports-archive.htm).
V1.3 consequently never expands a multi-day statement into fabricated daily
observations.

## Import exported files

Pass one or more statement files. A common time series will use multiple
one-period exports:

```bash
backtest-auditor ibkr files \
  statements/2026-01.xml \
  statements/2026-02.xml \
  statements/2026-03.xml \
  --declared-frequency ME \
  --periods-per-year 12 \
  --output ibkr_returns.csv
```

The command writes:

- `ibkr_returns.csv`, which follows the canonical Single-Run `timestamp` and
  `return` contract and retains `period_start`/`period_end` as extra evidence;
- `ibkr_returns.ibkr-import.json`, a deterministic import manifest containing
  source byte and filename hashes, conversion rules, interval bounds, scope
  hashes, warning codes, and the canonical CSV hash.

Source filenames, account IDs, and model names do not appear in clear text in
the manifest. If a
statement contains multiple account/model scopes, select exactly one:

```bash
backtest-auditor ibkr files statements/*.xml \
  --account-id U1234567 \
  --model Core \
  --output ibkr_returns.csv
```

The account/model selectors are necessarily visible in the local process command line.
Use the Streamlit password-style selector or a tightly controlled shell when
that local exposure matters.

Existing output files are not overwritten unless `--force` is supplied. Use
`--manifest-output` to choose a different manifest path.

## Import through the read-only API

Generate an IBKR Flex token and query ID in Client Portal. The token has no CLI
argument: it is read only from the process environment so it does not enter
shell history or process arguments.

```bash
export BACKTEST_AUDITOR_IBKR_FLEX_TOKEN='replace-with-token'
export BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID='replace-with-query-id'

backtest-auditor ibkr api \
  --from-date 2026-01-01 \
  --to-date 2026-01-31 \
  --output ibkr_returns.csv

unset BACKTEST_AUDITOR_IBKR_FLEX_TOKEN
unset BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID
```

`--query-id` may replace the query-ID environment variable, but the token is
environment-only. Date overrides are optional, must be supplied together, and
are bounded to at most 365 days. The client uses only IBKR's fixed
`SendRequest` and `GetStatement` endpoints, requires HTTP 200, refuses
redirects, bounds response size, ignores the service-returned URL, and never
includes request URLs or credentials in public exceptions.

The default 6.1-second interval between requests satisfies IBKR's documented
per-token limit of one request per second and ten per minute. Transient
statement-generation and service errors are retried up to ten polls; invalid,
expired, revoked, or unauthorized credentials fail immediately. IBKR's v3
parameters and error codes are documented in the
[Flex Web Service reference](https://www.ibkrguides.com/advisorportal/ug/flex3.htm)
and [v3 error table](https://www.ibkrguides.com/advisorportal/ug/flex3error.htm).

## Audit the canonical output

Run the unchanged Single-Run workflow on the canonical CSV:

```bash
backtest-auditor single ibkr_returns.csv \
  --run-id live-account-evidence \
  --declared-frequency ME \
  --periods-per-year 12 \
  --format json \
  --output ibkr_audit.json
```

Keep the import manifest beside the resulting audit. V1.4 audits emit report
schema `2.5` and audit-run-manifest schema `1.1`; broker provenance remains an input
adapter artifact rather than a statistical-report field.

The source return is account/model-level TWR. It is not automatically a
single-strategy track record. The operator remains responsible for establishing
that the selected account/model scope corresponds to the audited subject and
for declaring costs, leverage, currency, and other return-construction facts in
the Single-Run workflow. V1.3 does not infer those facts from account NAV.

## Streamlit workflow

Select **IBKR Flex Import**. Exported files remain in browser memory for the
import call. API mode reads the token from
`BACKTEST_AUDITOR_IBKR_FLEX_TOKEN`; there is no token text box. Download both
the canonical CSV and import manifest, then use the CSV in **Single-Run**.
Neither import artifact is automatically added to audit history.
