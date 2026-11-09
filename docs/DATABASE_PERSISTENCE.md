# Database Persistence

V1.2 adds optional immutable audit history while preserving file-first and
CLI-only operation. The database stores completed deterministic reports,
reproducibility metadata, and canonical normalized returns. It never stores
original uploads, credentials, or temporary paths.

## Installation and configuration

```bash
python -m pip install -e ".[database]"       # SQLite
python -m pip install -e ".[postgres]"       # PostgreSQL
python -m pip install -e ".[ui,postgres]"    # Streamlit + PostgreSQL
```

The UI reads `BACKTEST_AUDITOR_DATABASE_URL`; without it, the default is
`sqlite:///backtest_auditor.db` in the working directory.

```bash
export BACKTEST_AUDITOR_DATABASE_URL='sqlite:////absolute/path/audits.db'
export BACKTEST_AUDITOR_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/DB'
```

An ordinary `postgresql://...` URL is normalized to the declared psycopg
driver. Other PostgreSQL drivers are rejected rather than loaded implicitly.

Supply PostgreSQL secrets through the deployment environment or secret
manager, never through source files, reports, or manifests.

## Stored model and guarantees

- `audits`: report identity, package/schema versions, creation time,
  deterministic JSON/Markdown, optional manifest, and content fingerprint.
- `normalized_series`: ordered strategy, completed-trial, and benchmark series
  with return convention and canonical sampling declaration.
- `normalized_observations`: ordered ISO-8601 timestamps and return values.
- `audit_schema_versions`: explicit repository schema version.

One audit is written in one transaction. A SHA-256 content fingerprint covering
the reports, manifest, normalized series, and package/report-schema identity
makes exact repeat saves idempotent. Existing V1.2.0 fingerprints remain
recognizable when their stored version identity also matches. Database IDs and
storage timestamps do not alter the deterministic report. SQLite foreign keys
are enabled on every connection.

Snapshots are validated before writing and after reading: report and manifest
JSON must agree, series identities must be unique, timestamps must be ISO 8601,
returns must be finite and valid for their convention, and bounded database
fields are checked consistently across SQLite and PostgreSQL. Streamlit closes
each repository engine after its save or history interaction.

The repository schema is version `1`; unknown versions are rejected rather
than silently changed. Rejection occurs before table creation, so older code
does not mutate a database that declares a future schema. Future structural
changes require explicit tested migrations.

## Streamlit history

The interface saves the current audit, lists prior audits, reopens a snapshot,
and downloads its original JSON and Markdown. V1.2 does not edit or delete
history. Reopened reports are not recalculated with the current package.
