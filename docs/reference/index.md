# API reference

The versioned public contracts are the published JSON schemas: report schema
2.5 and run-manifest schema 1.1 for the V1 audits, implementation-risk report
and manifest schemas 1.0, and canonical bundle 1.0, with the compatibility
rules in [Public report schemas](../PUBLIC_REPORT_SCHEMAS.md). The pages below
document the Python objects the CLI calls, generated from the docstrings in
`src/backtest_auditor`.

| Page | Start with |
|---|---|
| [Single-run audit](single-run.md) | `read_return_series_csv`, `audit_single_run` |
| [Experiment-family audit](experiment-family.md) | `audit_experiment_family` |
| [V1 reports](reporting.md) | `render_json_report`, `render_markdown_report` |
| [Engine exporters](exporters.md) | `export_vectorbt_portfolio` and its siblings |
| [Implementation-risk audit](implementation-risk.md) | `ImplementationRiskAuditService`, the four policies |
| [Canonical artifacts](artifacts.md) | `CanonicalRunArtifacts` and its records |
