# Public Report Schemas

The V1 application packages seven machine-readable JSON Schemas using JSON
Schema Draft 2020-12. They are also present in
`src/backtest_auditor/schemas/`.

| Catalog key | Public object | Schema ID | File |
|---|---|---|---|
| `single_run_report_2_5` | Current Single-Run JSON report | `urn:backtest-integrity-auditor:schema:single-run-report:2.5` | `single-run-report-2.5.schema.json` |
| `experiment_family_report_2_5` | Current Experiment-Family JSON report | `urn:backtest-integrity-auditor:schema:experiment-family-report:2.5` | `experiment-family-report-2.5.schema.json` |
| `audit_run_manifest_1_1` | Current optional manifest embedded in both report modes | `urn:backtest-integrity-auditor:schema:audit-run-manifest:1.1` | `audit-run-manifest-1.1.schema.json` |
| `evidence_profile_1_0` | Evidence-profile object embedded in both report modes | `urn:backtest-integrity-auditor:schema:evidence-profile:1.0` | `evidence-profile-1.0.schema.json` |
| `single_run_report_2_4` | Complete Single-Run JSON report | `urn:backtest-integrity-auditor:schema:single-run-report:2.4` | `single-run-report-2.4.schema.json` |
| `experiment_family_report_2_4` | Complete Experiment-Family JSON report | `urn:backtest-integrity-auditor:schema:experiment-family-report:2.4` | `experiment-family-report-2.4.schema.json` |
| `audit_run_manifest_1_0` | Legacy optional manifest | `urn:backtest-integrity-auditor:schema:audit-run-manifest:1.0` | `audit-run-manifest-1.0.schema.json` |

V1.5I adds two separate contracts under
`src/backtest_auditor/implementation_risk/schemas/`:

| Catalog key | Public object | Schema ID | File |
|---|---|---|---|
| `implementation_risk_report_1_0` | Cross-engine implementation-risk report | `urn:backtest-integrity-auditor:schema:implementation-risk-report:1.0` | `implementation-risk-report-1.0.schema.json` |
| `implementation_risk_run_manifest_1_0` | Optional implementation-risk run manifest | `urn:backtest-integrity-auditor:schema:implementation-risk-run-manifest:1.0` | `implementation-risk-run-manifest-1.0.schema.json` |

These schemas do not extend or replace V1 report schema `2.5` or V1 manifest
schema `1.1`. V1.5J/package `1.5.0` hardens these exact objects with independent
golden/reference, property, performance, installation, and archive checks; it
does not change either V1.5 schema.

The report schemas reference the independent evidence-profile and manifest
schemas by their stable URNs. Consumers register the current report, profile,
and manifest resources before validating a V1.4 report. The retained legacy
resources support validation of already stored V1.0–V1.3 reports.

## Load bundled schemas

```python
from backtest_auditor.reporting.schema_catalog import load_public_schema

single_schema = load_public_schema("single_run_report_2_5")
family_schema = load_public_schema("experiment_family_report_2_5")
profile_schema = load_public_schema("evidence_profile_1_0")
manifest_schema = load_public_schema("audit_run_manifest_1_1")
```

Unknown catalog keys raise `KeyError`, and each call returns a new mapping so a
consumer cannot mutate the packaged resource for another caller.

Load V1.5I contracts from their separate catalog:

```python
from backtest_auditor.implementation_risk import load_implementation_risk_schema

report_schema = load_implementation_risk_schema("implementation_risk_report_1_0")
manifest_schema = load_implementation_risk_schema(
    "implementation_risk_run_manifest_1_0"
)
```

## Validate a report

```python
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backtest_auditor.reporting.schema_catalog import load_public_schema

schemas = {
    key: load_public_schema(key)
    for key in (
        "single_run_report_2_5",
        "experiment_family_report_2_5",
        "evidence_profile_1_0",
        "audit_run_manifest_1_1",
    )
}
registry = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
)
report = json.loads(Path("audit.json").read_text(encoding="utf-8"))
Draft202012Validator(schemas["single_run_report_2_5"], registry=registry).validate(
    report
)
```

## Compatibility rules

- Package releases may retain report schema `2.5` only when they preserve its
  serialized shape and interpretation.
- Adding, removing, renaming, or changing the meaning or nullability of a
  public field requires an intentional schema-version decision. The schemas
  reject unknown fields so additions are not silently treated as compatible.
- Evidence dimensions remain independent. `overall_status` is required to be
  JSON `null`; consumers must not synthesize a hidden aggregate pass.
- An audit-run manifest remains optional for compatibility, but when present it
  must be complete and valid under schema `1.1` for a `2.5` report. Legacy
  `2.4` reports remain governed by manifest schema `1.0`.
- A package-version change alone does not imply a report-schema change.
- An implementation-risk report requires `overall_status` to be JSON `null`;
  candidate scores, uncertainty, evidence gaps, and findings remain independent
  evidence rather than a global verdict.

## Generated contract fixtures

`scripts/release_contracts.py` is the deterministic source for current schemas
and complete JSON/Markdown golden reports in `tests/fixtures/golden/`. Legacy
schemas are retained immutable rather than regenerated from the new shape.

```bash
python scripts/release_contracts.py --check
```

The check fails when a committed schema or golden report differs from a fresh
generation. Maintainers use `--write` only after deliberately reviewing the
public-contract change.
