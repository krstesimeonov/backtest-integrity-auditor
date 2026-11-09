# V1.5C Hybrid Canonical File-Bundle Contract

Status: implemented in package `1.5.0a3`.

V1.5C defines how an external adapter exchanges the immutable V1.5B domain
objects without making the domain aware of files. The same logical bundle can
be stored as an inspectable directory or a deterministic ZIP archive.

This increment does not map any concrete engine. V1.5D1 defines the shared
verified engine-export boundary and registry; D2/D3 mappers convert those
exports into this canonical contract through engine-neutral ports.

## Why JSON and CSV are combined

The format follows the shape of the evidence instead of forcing one encoding
onto every object:

- JSON represents nested strategy, model, parameter, universe, simulation, and
  manifest structures without flattening away types.
- CSV represents long, flat artifact histories that users commonly inspect in
  pandas, spreadsheets, SQL importers, and text tools.
- ZIP packages the exact same top-level files for transport. Directory and ZIP
  forms have identical semantics.

A single JSON document was rejected because large market-data, position, and
equity histories would be awkward to inspect and load. A pure CSV bundle was
rejected because nested typed parameters and simulation models would require
fragile conventions or JSON embedded inside CSV cells.

## Public API

```python
from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
)

adapter = CanonicalArtifactFileBundleAdapter()
bundle = adapter.read("reference-run.zip")
adapter.write(bundle, "canonical-reference-run")
adapter.write(bundle, "canonical-reference-run.zip")
```

The destination selects the container:

- a `.zip` suffix writes a deterministic ZIP;
- a suffix-free path writes a directory;
- other suffixes are rejected rather than guessed.

Existing destinations are protected by default. Replacement requires the
explicit `overwrite=True` argument. Directory replacement uses a temporary
directory and rollback path; ZIP replacement uses a temporary file and atomic
publication.

`CanonicalArtifactBundleReader` and `CanonicalArtifactBundleWriter` are
runtime-checkable application protocols. The file adapter implements both.

## Bundle layout

All files are regular top-level files. Subdirectories, symbolic links,
encrypted ZIP entries, path traversal, duplicate ZIP names, and unlisted files
are rejected.

| File | Encoding | Present when |
|---|---|---|
| `manifest.json` | Canonical JSON | Always |
| `specification.json` | Canonical JSON | Strategy specification is available |
| `market_data.csv` | CSV | Market-data level is available |
| `signals.csv` | CSV | Signal level is available |
| `orders.csv` | CSV | Order level is available |
| `fills.csv` | CSV | Fill level is available |
| `trades.csv` | CSV | Trade level is available |
| `trade_fills.csv` | CSV relation | Trade level is available |
| `positions.csv` | CSV | Position level is available |
| `cash_balances.csv` | CSV | Cash balances are available |
| `cash_movements.csv` | CSV | Cash movements are available |
| `costs.csv` | CSV | Cost level is available |
| `equity.csv` | CSV | Equity level is available |
| `returns.csv` | CSV | Return level is available |

Trade-to-fill membership is normalized into `trade_fills.csv` with columns
`trade_id,fill_id`. This keeps `trades.csv` flat and prevents a JSON array from
being hidden in one CSV cell.

## Manifest 1.0

`manifest.json` declares:

- bundle schema version `1.0`;
- canonical artifact schema version `1.0`;
- run ID, engine name, optional engine version, and source SHA-256;
- availability and exact physical files for all eleven comparison levels;
- media type, byte size, SHA-256, and record count for every payload file; and
- `bundle_content_sha256`, calculated from canonical compact JSON for the
  complete manifest body excluding that final identity field.

The content identity includes the file hashes, so it identifies the logical
bundle independently from ZIP timestamps or compression metadata. It is still
provenance, not a digital signature or proof that the originating engine is
correct.

The file inventory must be sorted by path and match the union of files declared
by the levels exactly. File hashes and sizes are verified before parsing.
Record counts are verified after parsing.

## Missing versus empty evidence

V1.5B's distinction is represented physically:

- **Unavailable:** the manifest declares `status: "unavailable"`, its file list
  is empty, and no file exists.
- **Available but empty:** the manifest declares `status: "available"`, and the
  CSV exists with the exact header and no data rows.

The reader rejects all inconsistent combinations. An absent file is never
interpreted as an empty history. Cash remains special because balances and
movements can be independently unavailable; at least one cash file is required
when the cash level is available.

## Canonical JSON rules

JSON files use:

- UTF-8 without a byte-order mark;
- two-space indentation, sorted object keys, and one final newline;
- no duplicate keys or non-finite numbers;
- exact versioned fields with no unknown keys; and
- explicit `null` for optional JSON fields.

Typed specification parameters use `value_type` plus `value`. Supported types
are `boolean`, `decimal`, `integer`, `null`, and `string`. Decimal values are
strings so JSON parsing cannot silently convert them through binary floating
point.

## Canonical CSV rules

CSV files use:

- UTF-8 without a byte-order mark;
- comma delimiter, minimal necessary quoting, LF line endings, and one final
  newline;
- exact header names and order;
- no missing or additional columns;
- blank cells only for optional fields;
- finite canonical decimal strings without exponent notation;
- UTC timestamps with `Z` and exactly six fractional digits;
- lower-snake-case enum values; and
- domain-defined canonical record ordering.

The reader parses and reserializes each CSV. A semantically similar but
noncanonical representation—such as CRLF, unnecessary quoting, `10.0` instead
of `10`, or a timestamp without microseconds—is rejected rather than silently
rewritten.

### CSV headers

| File | Exact columns |
|---|---|
| `market_data.csv` | `observation_id,instrument_id,event_timestamp,available_timestamp,field,value,unit` |
| `signals.csv` | `signal_id,timestamp,instrument_id,signal_type,value,source_data_timestamp` |
| `orders.csv` | `order_id,created_at,instrument_id,side,quantity,order_type,time_in_force,status,signal_id,parent_order_id,submitted_at,last_updated_at,expires_at,limit_price,stop_price` |
| `fills.csv` | `fill_id,order_id,timestamp,instrument_id,side,quantity,price,currency,liquidity_role,venue` |
| `trades.csv` | `trade_id,instrument_id,direction,opened_at,quantity,entry_price,currency,grouping_method,closed_at,exit_price,realized_pnl` |
| `trade_fills.csv` | `trade_id,fill_id` |
| `positions.csv` | `timestamp,instrument_id,quantity,currency,market_price,market_value,average_cost,realized_pnl,unrealized_pnl` |
| `cash_balances.csv` | `timestamp,currency,total,settled` |
| `cash_movements.csv` | `movement_id,timestamp,currency,amount,movement_type,related_artifact_id` |
| `costs.csv` | `cost_id,timestamp,cost_type,pnl_impact,currency,order_id,fill_id,trade_id` |
| `equity.csv` | `timestamp,currency,total_equity,cash,gross_exposure,net_exposure` |
| `returns.csv` | `start_timestamp,end_timestamp,value,convention` |

## Fail-closed validation

`BundleContractError` is a `ValueError` with a stable `BundleErrorCode` and
optional file, row, and field context. Codes distinguish:

- missing, unsupported, or unsafe sources and destinations;
- malformed or noncanonical JSON and CSV;
- invalid manifest or specification shape;
- unsupported schema versions;
- missing and undeclared files;
- byte-size, SHA-256, and record-count mismatches;
- CSV header and row failures;
- resource-limit violations;
- V1.5B domain contradictions; and
- write failures.

Validation does not sort, deduplicate, trim, infer, repair, or discard evidence.
After parsing, the complete V1.5B bundle validation runs again, followed by an
exact serialization round trip.

## Safety limits

The reader bounds the attack surface before materializing a bundle:

- at most 20 payload entries;
- manifest at most 1 MB;
- each payload file at most 512 MB; and
- total uncompressed content at most 1 GB.

ZIP entries must be unencrypted stored or deflated regular files. The reader
rejects nested paths, traversal, directories, symbolic links, duplicates, and
unsupported compression methods.

These are file-safety limits, not trading or comparison materiality thresholds.

## Schemas and example

Two bundled JSON Schema Draft 2020-12 resources document the JSON portions:

```python
from backtest_auditor.implementation_risk import load_canonical_bundle_schema

manifest_schema = load_canonical_bundle_schema("canonical_artifact_bundle_manifest_1_0")
specification_schema = load_canonical_bundle_schema("canonical_run_specification_1_0")
```

The inspectable example is in `examples/v1_5c_canonical_bundle`. Regenerate or
verify it with:

```bash
python scripts/generate_v1_5c_bundle_example.py
python scripts/generate_v1_5c_bundle_example.py --check
```

## Boundaries and next increment

V1.5C deliberately does not include:

- mappings for Backtrader, vectorbt, Zipline, LEAN, or another concrete engine;
- symbol, venue, currency, session, or frequency normalization across engines;
- tolerance or alignment policy;
- trade reconstruction;
- cross-run comparisons or root-cause attribution;
- V1.5 reports, CLI, Streamlit, or persistence workflows; or
- any order execution or broker action.

V1.5D can now implement selected engine adapters against a stable port and file
contract. Engine-specific column names and semantics must terminate at that
adapter boundary.

V1 report schema `2.5`, audit-run-manifest schema `1.1`, database schema `1`,
and all V1 statistical behavior remain unchanged.
