"""Generate or verify the frozen V1 schemas and complete golden reports."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backtest_auditor.cli import main


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = ROOT / "src" / "backtest_auditor" / "schemas"
GOLDEN_DIRECTORY = ROOT / "tests" / "fixtures" / "golden"

EVIDENCE_SCHEMA_ID = "urn:backtest-integrity-auditor:schema:evidence-profile:1.0"
MANIFEST_SCHEMA_ID = "urn:backtest-integrity-auditor:schema:audit-run-manifest:1.1"
SINGLE_REPORT_SCHEMA_ID = "urn:backtest-integrity-auditor:schema:single-run-report:2.5"
FAMILY_REPORT_SCHEMA_ID = (
    "urn:backtest-integrity-auditor:schema:experiment-family-report:2.5"
)

_SINGLE_FULL_ARGUMENTS = (
    "examples/sample_returns.csv",
    "--run-id",
    "golden-single-run",
    "--declared-frequency",
    "D",
    "--periods-per-year",
    "365",
    "--annual-risk-free-rate",
    "0.0",
    "--benchmark-annualized-sharpe-ratio",
    "0.0",
    "--required-psr-confidence-level",
    "0.75",
    "--serial-max-lag",
    "1",
    "--serial-significance-level",
    "0.05",
    "--hac-max-lag",
    "1",
    "--hac-kernel",
    "bartlett",
    "--bootstrap-method",
    "stationary",
    "--bootstrap-interval-method",
    "percentile",
    "--bootstrap-replications",
    "100",
    "--bootstrap-confidence-level",
    "0.9",
    "--bootstrap-block-length",
    "2",
    "--bootstrap-seed",
    "42",
    "--minimum-acceptable-period-return",
    "0.0",
    "--tail-confidence-level",
    "0.95",
    "--risk-free-csv",
    "examples/sample_risk_free.csv",
    "--gross-returns-csv",
    "examples/sample_gross_returns.csv",
    "--regimes-csv",
    "examples/sample_regimes.csv",
    "--timestamp-timezone",
    "UTC",
    "--observation-calendar",
    "24/7",
    "--calendar-timezone",
    "UTC",
    "--transaction-costs-included",
    "true",
    "--fees-included",
    "true",
    "--leverage-policy",
    "unlevered",
    "--currency",
    "USD",
    "--price-adjustment-policy",
    "adjusted",
    "--data-source",
    "synthetic-release-example",
    "--data-vintage",
    "2026-08-12",
    "--stale-price-policy",
    "reject stale prices",
    "--delisting-return-policy",
    "include terminal returns",
    "--survivorship-bias-controlled",
    "true",
    "--lookahead-bias-controlled",
    "true",
    "--signal-timing",
    "close t",
    "--execution-timing",
    "open t+1",
    "--benchmark-csv",
    "examples/sample_benchmark.csv",
    "--benchmark-id",
    "market",
    "--benchmark-alpha-hac-max-lag",
    "1",
    "--benchmark-alpha-confidence-level",
    "0.95",
    "--benchmark-timestamp-timezone",
    "UTC",
    "--benchmark-observation-calendar",
    "24/7",
    "--benchmark-calendar-timezone",
    "UTC",
    "--benchmark-transaction-costs-included",
    "true",
    "--benchmark-fees-included",
    "true",
    "--benchmark-leverage-policy",
    "unlevered",
    "--benchmark-currency",
    "USD",
    "--benchmark-price-adjustment-policy",
    "adjusted",
    "--benchmark-data-source",
    "synthetic-release-example",
    "--benchmark-data-vintage",
    "2026-08-12",
    "--benchmark-stale-price-policy",
    "reject stale prices",
    "--benchmark-delisting-return-policy",
    "include terminal returns",
    "--benchmark-survivorship-bias-controlled",
    "true",
    "--benchmark-lookahead-bias-controlled",
    "true",
    "--benchmark-signal-timing",
    "close t",
    "--benchmark-execution-timing",
    "open t+1",
)

_FAMILY_FULL_ARGUMENTS = (
    "family",
    "examples/cscv_family_manifest_v1_4.json",
    "examples/cscv_family_trials.csv",
    "examples/cscv_family_returns.csv",
    "--splits-csv",
    "examples/cscv_family_splits.csv",
    "--benchmark-csv",
    "examples/cscv_family_benchmark.csv",
    "--dsr-method",
    "classic_expected_maximum",
    "--dsr-trial-count-policy",
    "selection_eligible",
    "--dsr-annual-risk-free-rate",
    "0.0",
    "--dsr-confidence-level",
    "0.75",
    "--cscv-method",
    "combinatorially_symmetric",
    "--cscv-performance-metric",
    "period_sharpe_ratio",
    "--cscv-selection-metric-name",
    "period_sharpe_ratio",
    "--cscv-partitions",
    "4",
    "--cscv-annual-risk-free-rate",
    "0.0",
    "--cscv-maximum-combinations",
    "100",
    "--cscv-rank-tie-method",
    "average",
    "--cscv-winner-tie-policy",
    "first_by_attempt_index",
    "--cscv-maximum-acceptable-pbo",
    "0.75",
    "--parameter-robustness-metric",
    "period_sharpe_ratio",
    "--parameter-selection-metric-name",
    "period_sharpe_ratio",
    "--parameter-annual-risk-free-rate",
    "0.0",
    "--parameter-distance-metric",
    "standardized_euclidean",
    "--parameter-scale",
    "lookback=5",
    "--parameter-maximum-distance",
    "3",
    "--parameter-minimum-neighbors",
    "2",
    "--parameter-maximum-score-difference",
    "1",
    "--parameter-minimum-acceptable-neighbor-fraction",
    "0.5",
    "--temporal-robustness-metric",
    "period_sharpe_ratio",
    "--temporal-selection-metric-name",
    "period_sharpe_ratio",
    "--temporal-annual-risk-free-rate",
    "0.0",
    "--temporal-windows",
    "4",
    "--temporal-rank-tie-method",
    "average",
    "--temporal-winner-tie-policy",
    "first_by_attempt_index",
    "--temporal-minimum-acceptable-top-half-fraction",
    "0.5",
    "--temporal-maximum-acceptable-below-zero-fraction",
    "0.5",
    "--data-snooping-replications",
    "100",
    "--data-snooping-mean-block-length",
    "2",
    "--data-snooping-seed",
    "73",
    "--data-snooping-significance-level",
    "0.05",
)

_SINGLE_MINIMAL_ARGUMENTS = (
    "examples/sample_returns.csv",
    "--run-id",
    "schema-minimal-single-run",
)
_FAMILY_MINIMAL_ARGUMENTS = (
    "family",
    "examples/experiment_family_manifest.json",
    "examples/experiment_family_trials.csv",
    "examples/experiment_family_returns.csv",
    "--splits-csv",
    "examples/experiment_family_splits.csv",
    "--benchmark-csv",
    "examples/sample_benchmark.csv",
)
_MANIFEST_IDENTITY_ARGUMENTS = (
    "--audit-id",
    "schema-example-audit",
    "--audit-timestamp",
    "2026-08-12T20:00:00+02:00",
    "--git-commit",
    "abc123def456",
)

# Additional schema-corpus invocations. The published schema is a type
# contract, so it must be derived from runs that reach every state the engine
# can legitimately emit -- not from whichever two runs happened to be handy.
# Each entry below exists to reach a specific state the full/minimal pair
# cannot, and removing one silently re-freezes the fields it covers.

# Reaches benchmark.observation_calendar = null: a benchmark supplied without
# a benchmark observation calendar. This is the README's minimal benchmark
# invocation, and the full example configures the calendar, so without this
# run the published schema types the field as a non-nullable object.
_SINGLE_BENCHMARK_MINIMAL_ARGUMENTS = (
    "examples/sample_returns.csv",
    "--run-id",
    "schema-benchmark-minimal-single-run",
    "--benchmark-csv",
    "examples/sample_benchmark.csv",
    "--benchmark-id",
    "market",
)

# Reaches bootstrap.blocks_per_replication and overlapping_block_count: the
# moving-block bootstrap, the original V1 method and the one the README's
# single-run example uses. The 2.5 full example uses the stationary bootstrap,
# so without this run both fields were null in every example and the published
# 2.5 schema froze them to {"type": "null"}, rejecting every moving-block report.
_SINGLE_MOVING_BLOCK_ARGUMENTS = tuple(
    {
        "golden-single-run": "schema-moving-block-single-run",
        "stationary": "moving_block",
    }.get(argument, argument)
    for argument in _SINGLE_FULL_ARGUMENTS
)

# Reaches a populated input_issues array. Every other single-run example
# parses cleanly, so the array was empty in all of them and the generator had
# nothing to infer an item schema from -- it published {"items": {}}, which
# validates literally any content. An unsorted export is ordinary real-world
# input and produces the non-blocking TIMESTAMPS_SORTED issue.
_SINGLE_UNSORTED_ARGUMENTS = (
    "examples/unsorted_returns.csv",
    "--run-id",
    "schema-unsorted-single-run",
)

# Reaches serial_dependence.variance_ratios: Lo-MacKinlay variance ratios
# exist only for horizons of two or more, and the full example uses
# --serial-max-lag 1, so the array was empty in every example. This is the
# README's serial-dependence invocation.
_SINGLE_VARIANCE_RATIO_ARGUMENTS = (
    "examples/sample_returns.csv",
    "--run-id",
    "schema-variance-ratio-single-run",
    "--declared-frequency",
    "D",
    "--periods-per-year",
    "365",
    "--serial-max-lag",
    "2",
    "--serial-significance-level",
    "0.05",
)

# Reaches deflated_sharpe_ratio.trial_counts.effective_* : an externally
# supplied effective independent-trial count. Neither existing family example
# passes --dsr-effective-independent-trials, so all three fields were null in
# every example and the published schema froze them to {"type": "null"}.
_FAMILY_EFFECTIVE_TRIALS_ARGUMENTS = _FAMILY_FULL_ARGUMENTS + (
    "--dsr-effective-independent-trials",
    "3",
    "--dsr-effective-trial-count-methodology",
    "externally justified independent-trial count",
)

# Reaches parameter_robustness.axis_sensitivities[].closest_lower_* : a family
# whose selected trial is not the minimum on an axis. The CSCV example selects
# trial-001 at lookback=5, the lowest point on its only axis, so no lower
# neighbour exists and both fields were frozen to {"type": "null"}.
_FAMILY_LOWER_NEIGHBOUR_ARGUMENTS = (
    "family",
    "examples/experiment_family_manifest.json",
    "examples/experiment_family_trials.csv",
    "examples/experiment_family_returns.csv",
    "--splits-csv",
    "examples/experiment_family_splits.csv",
    "--benchmark-csv",
    "examples/sample_benchmark.csv",
    "--parameter-robustness-metric",
    "period_sharpe_ratio",
    "--parameter-selection-metric-name",
    "validation_sharpe",
    "--parameter-annual-risk-free-rate",
    "0.0",
    "--parameter-distance-metric",
    "standardized_euclidean",
    "--parameter-scale",
    "lookback=10",
    "--parameter-scale",
    "threshold=0.5",
    "--parameter-maximum-distance",
    "2",
    "--parameter-minimum-neighbors",
    "1",
    "--parameter-maximum-score-difference",
    "1",
    "--parameter-minimum-acceptable-neighbor-fraction",
    "0.5",
)

# Object-valued keys the serializers can emit as null. Derived from the
# `X if ... else None` guards in reporting/serialization.py and
# reporting/family_serialization.py, which are the source of truth for the
# published shape. Nullability is DECLARED here rather than inferred from
# whichever states the corpus happens to reach, because an object that is
# merely non-null in every example is not thereby non-nullable.
_NULLABLE_OBJECT_KEYS = {
    "annualized_statistics",
    "benchmark",
    "bootstrap",
    "comparison",
    "correlation_summary",
    "observation_calendar",
    "return_construction",
    "serial_adjustment",
    "serial_dependence",
    "sharpe_uncertainty",
    "track_record_length",
}

# Keys that are null by contract rather than by circumstance. evidence_profile
# .overall_status is null in every report on purpose: the profile publishes
# per-dimension statuses and refuses to roll them into a single verdict.
# Anything NOT listed here that is null across the whole corpus is a corpus
# gap, and _schema_for_values raises rather than freezing it to {"type":
# "null"} -- see the comment there.
_CONTRACTUALLY_NULL_KEYS = {
    "overall_status",
}

#: Arrays that are legitimately empty in every corpus run, with their item
#: type DECLARED from the domain dataclass annotation rather than inferred.
#:
#: Every one of these is a list of what went wrong -- timestamps present on
#: only one side, sessions missing from a calendar, trials whose returns could
#: not be resolved. They are empty in a clean example by construction, so no
#: reasonable corpus populates all of them, and an empty array leaves "items"
#: unconstrained: the published schema would validate any content at all.
#:
#: The annotations these come from are in domain/results.py and
#: domain/experiment.py; each is tuple[str, ...] except the attempt indices.
_DECLARED_ARRAY_ITEM_TYPES: dict[str, dict[str, Any]] = {
    "benchmark_only_timestamps": {"type": "string"},
    "strategy_only_timestamps": {"type": "string"},
    "missing_session_dates": {"type": "string"},
    "unexpected_session_dates": {"type": "string"},
    "unavailable_trial_ids": {"type": "string"},
    "duplicate_configuration_trial_ids": {"type": "string"},
    "unavailable_neighbor_trial_ids": {"type": "string"},
    "undocumented_attempt_indices": {"type": "integer"},
    "regime_only_timestamps": {"type": "string"},
    "paired_only_timestamps": {"type": "string"},
}

_DYNAMIC_OBJECT_KEYS = {
    "configuration",
    "parameters",
    "parameter_scales",
    "random_seeds",
}
_NON_NULL_SCALAR_KEYS = {
    "schema_version",
    "manifest_schema_version",
    "report_schema_version",
    "audit_type",
    "run_id",
    "family_id",
    "audit_id",
    "audit_timestamp_utc",
    "git_commit",
    "subject_id",
    "package_version",
    "method",
    "dimension",
    "status",
    "summary",
    "interpretation_boundary",
    "code",
    "category",
    "claim",
    "implication",
    "remediation",
    "role",
    "file_name",
    "sha256",
    "manifest_sha256",
    "configuration_sha256",
    "normalized_data_sha256",
    "normalized_data_encoding",
    "name",
    "version",
}


def build_runtime_examples() -> dict[str, dict[str, Any]]:
    """Build representative public objects without reading golden files."""

    single_full = _run_json(_SINGLE_FULL_ARGUMENTS)
    single_minimal = _run_json(_SINGLE_MINIMAL_ARGUMENTS)
    family_full = _run_json(_FAMILY_FULL_ARGUMENTS)
    family_minimal = _run_json(_FAMILY_MINIMAL_ARGUMENTS)
    single_manifested = _run_json(_SINGLE_FULL_ARGUMENTS + _MANIFEST_IDENTITY_ARGUMENTS)
    family_manifested = _run_json(_FAMILY_FULL_ARGUMENTS + _MANIFEST_IDENTITY_ARGUMENTS)
    single_benchmark_minimal = _run_json(_SINGLE_BENCHMARK_MINIMAL_ARGUMENTS)
    single_moving_block = _run_json(_SINGLE_MOVING_BLOCK_ARGUMENTS)
    single_unsorted = _run_json(_SINGLE_UNSORTED_ARGUMENTS)
    single_variance_ratio = _run_json(_SINGLE_VARIANCE_RATIO_ARGUMENTS)
    family_effective_trials = _run_json(_FAMILY_EFFECTIVE_TRIALS_ARGUMENTS)
    family_lower_neighbour = _run_json(_FAMILY_LOWER_NEIGHBOUR_ARGUMENTS)
    return {
        "single_full": single_full,
        "single_minimal": single_minimal,
        "single_benchmark_minimal": single_benchmark_minimal,
        "single_moving_block": single_moving_block,
        "single_unsorted": single_unsorted,
        "single_variance_ratio": single_variance_ratio,
        "family_full": family_full,
        "family_minimal": family_minimal,
        "family_effective_trials": family_effective_trials,
        "family_lower_neighbour": family_lower_neighbour,
        "single_manifested": single_manifested,
        "family_manifested": family_manifested,
        "single_manifest": single_manifested["run_manifest"],
        "family_manifest": family_manifested["run_manifest"],
    }


#: Corpus members the published report schemas are derived from, in a fixed
#: order so generation stays deterministic.
SINGLE_SCHEMA_CORPUS = (
    "single_full",
    "single_minimal",
    "single_benchmark_minimal",
    "single_moving_block",
    "single_unsorted",
    "single_variance_ratio",
    "single_manifested",
)
FAMILY_SCHEMA_CORPUS = (
    "family_full",
    "family_minimal",
    "family_effective_trials",
    "family_lower_neighbour",
    "family_manifested",
)


def build_release_documents() -> dict[Path, str]:
    """Return every generated release contract keyed by repository path."""

    examples = build_runtime_examples()
    single_full_text = _render_json(examples["single_full"])
    family_full_text = _render_json(examples["family_full"])
    single_markdown = _run_report(_SINGLE_FULL_ARGUMENTS, "markdown")
    family_markdown = _run_report(_FAMILY_FULL_ARGUMENTS, "markdown")

    evidence_schema = _evidence_schema(
        [
            examples["single_full"]["evidence_profile"],
            examples["family_full"]["evidence_profile"],
        ]
    )
    manifest_schema = _manifest_schema(
        [examples["single_manifest"], examples["family_manifest"]]
    )
    single_schema = _report_schema(
        [examples[name] for name in SINGLE_SCHEMA_CORPUS],
        schema_id=SINGLE_REPORT_SCHEMA_ID,
        title="Backtest Integrity Auditor Single-Run Report 2.5",
        audit_type="single_run",
    )
    family_schema = _report_schema(
        [examples[name] for name in FAMILY_SCHEMA_CORPUS],
        schema_id=FAMILY_REPORT_SCHEMA_ID,
        title="Backtest Integrity Auditor Experiment-Family Report 2.5",
        audit_type="experiment_family",
    )
    return {
        SCHEMA_DIRECTORY / "evidence-profile-1.0.schema.json": _render_json(
            evidence_schema
        ),
        SCHEMA_DIRECTORY / "audit-run-manifest-1.1.schema.json": _render_json(
            manifest_schema
        ),
        SCHEMA_DIRECTORY / "single-run-report-2.5.schema.json": _render_json(
            single_schema
        ),
        SCHEMA_DIRECTORY / "experiment-family-report-2.5.schema.json": _render_json(
            family_schema
        ),
        GOLDEN_DIRECTORY / "v1_single_run_complete.json": single_full_text,
        GOLDEN_DIRECTORY / "v1_single_run_complete.md": single_markdown,
        GOLDEN_DIRECTORY / "v1_experiment_family_complete.json": family_full_text,
        GOLDEN_DIRECTORY / "v1_experiment_family_complete.md": family_markdown,
    }


def _run_json(arguments: Sequence[str]) -> dict[str, Any]:
    raw = _run_report(arguments, "json")
    value: dict[str, Any] = json.loads(raw)
    # Goldens are compared after re-rendering, so without this check the
    # engine's own formatting -- the bytes report_sha256 is computed over --
    # would be verified by nothing.
    if raw != _render_json(value):
        raise ValueError(
            "The engine's JSON report is not in canonical form "
            f"(sorted keys, indent 2, literal UTF-8, no NaN) for {list(arguments)}."
        )
    return value


def _run_report(arguments: Sequence[str], report_format: str) -> str:
    original_directory = Path.cwd()
    try:
        os.chdir(ROOT)
        with tempfile.TemporaryDirectory(prefix="backtest-auditor-release-") as raw:
            output_path = Path(raw) / f"report.{report_format}"
            exit_code = main(
                [
                    *arguments,
                    "--format",
                    report_format,
                    "--output",
                    str(output_path),
                ]
            )
            if exit_code != 0:
                raise RuntimeError(
                    f"release report generation failed with exit code {exit_code}."
                )
            return output_path.read_text(encoding="utf-8")
    finally:
        os.chdir(original_directory)


def _evidence_schema(examples: list[dict[str, Any]]) -> dict[str, Any]:
    schema = _schema_for_values(examples, ())
    schema.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": EVIDENCE_SCHEMA_ID,
            "title": "Backtest Integrity Auditor Evidence Profile 1.0",
        }
    )
    properties = schema["properties"]
    properties["method"] = {"const": "dimensioned_evidence_profile_v1"}
    properties["audit_type"] = {"enum": ["experiment_family", "single_run"]}
    properties["overall_status"] = {"type": "null"}
    dimension_properties = properties["dimensions"]["items"]["properties"]
    dimension_properties["dimension"] = {
        "enum": sorted(
            {
                item["dimension"]
                for example in examples
                for item in example["dimensions"]
            }
        )
    }
    dimension_properties["status"] = {
        "enum": [
            "fragile",
            "ineligible",
            "insufficient_evidence",
            "supported_under_stated_assumptions",
        ]
    }
    properties["dimensions"]["minItems"] = 1
    return schema


def _manifest_schema(examples: list[dict[str, Any]]) -> dict[str, Any]:
    schema = _schema_for_values(examples, ())
    schema.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": MANIFEST_SCHEMA_ID,
            "title": "Backtest Integrity Auditor Audit-Run Manifest 1.1",
        }
    )
    properties = schema["properties"]
    properties["manifest_schema_version"] = {"const": "1.1"}
    properties["report_schema_version"] = {"const": "2.5"}
    properties["audit_type"] = {"enum": ["experiment_family", "single_run"]}
    properties["audit_timestamp_utc"] = {
        "type": "string",
        "format": "date-time",
        "pattern": "Z$",
    }
    for name in (
        "configuration_sha256",
        "manifest_sha256",
        "normalized_data_sha256",
    ):
        properties[name] = {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        }
    artifact_schema = properties["input_artifacts"]
    artifact_schema["minItems"] = 1
    artifact_schema["items"]["properties"]["sha256"] = {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    return schema


def _report_schema(
    examples: list[dict[str, Any]],
    *,
    schema_id: str,
    title: str,
    audit_type: str,
) -> dict[str, Any]:
    schema = _schema_for_values(examples, ())
    schema.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": schema_id,
            "title": title,
        }
    )
    properties = schema["properties"]
    properties["schema_version"] = {"const": "2.5"}
    properties["audit_type"] = {"const": audit_type}
    properties["evidence_profile"] = {"$ref": EVIDENCE_SCHEMA_ID}
    properties["run_manifest"] = {
        "anyOf": [
            {"$ref": MANIFEST_SCHEMA_ID},
            {"type": "null"},
        ]
    }
    return schema


def _schema_for_values(
    values: Sequence[Any],
    path: tuple[str, ...],
) -> dict[str, Any]:
    has_null = any(value is None for value in values)
    non_null = [value for value in values if value is not None]
    if not non_null:
        key = path[-1] if path else ""
        if key not in _CONTRACTUALLY_NULL_KEYS:
            # Freezing the field to {"type": "null"} here is what published a
            # schema that rejects the engine's own valid output: a field that
            # merely happened to be null in every example became a field that
            # can only ever be null. Refuse to guess. Either add a corpus run
            # that populates the field, or declare it in
            # _CONTRACTUALLY_NULL_KEYS if it is null by design.
            raise ValueError(
                f"{'.'.join(path) or '<root>'} is null in every schema corpus "
                "example, so its type cannot be inferred. Add a corpus run "
                "that populates it, or add its key to _CONTRACTUALLY_NULL_KEYS "
                "if it is null by contract."
            )
        return {"type": "null"}

    if all(isinstance(value, dict) for value in non_null):
        key = path[-1] if path else ""
        if key in _DYNAMIC_OBJECT_KEYS:
            return _dynamic_object_schema(key, has_null)
        objects: list[dict[str, Any]] = non_null
        keys = sorted({name for value in objects for name in value})
        required = sorted(set.intersection(*(set(value) for value in objects)))
        object_schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                name: _schema_for_values(
                    [value[name] for value in objects if name in value],
                    path + (name,),
                )
                for name in keys
            },
            "required": required,
        }
        nullable = has_null or key in _NULLABLE_OBJECT_KEYS
        return _with_null(object_schema) if nullable else object_schema

    if all(isinstance(value, list) for value in non_null):
        arrays: list[list[Any]] = non_null
        items = [item for value in arrays for item in value]
        key = path[-1] if path else ""
        if not items:
            declared = _DECLARED_ARRAY_ITEM_TYPES.get(key)
            if declared is not None:
                array_schema = {"type": "array", "items": dict(declared)}
                return _with_null(array_schema) if has_null else array_schema
            # An empty array in every example leaves "items" unconstrained, so
            # the published schema validates ANY content at that path -- the
            # same example-inference defect as the all-null case, in a
            # different disguise. input_issues shipped exactly this way.
            raise ValueError(
                f"{'.'.join(path) or '<root>'} is empty in every schema "
                "corpus example, so its item type cannot be inferred. Add a "
                "corpus run that populates it, or declare its item type in "
                "_DECLARED_ARRAY_ITEM_TYPES."
            )
        array_schema: dict[str, Any] = {
            "type": "array",
            "items": (_schema_for_values(items, path + ("[]",)) if items else {}),
        }
        return _with_null(array_schema) if has_null else array_schema

    if all(isinstance(value, bool) for value in non_null):
        scalar: dict[str, Any] = {"type": "boolean"}
    elif all(
        isinstance(value, int) and not isinstance(value, bool) for value in non_null
    ):
        scalar = {"type": "integer"}
    elif all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in non_null
    ):
        scalar = {"type": "number"}
    elif all(isinstance(value, str) for value in non_null):
        scalar = {"type": "string"}
    else:
        return {}

    key = path[-1] if path else ""
    allow_null = has_null or (key not in _NON_NULL_SCALAR_KEYS and key != "[]")
    return _with_null(scalar) if allow_null else scalar


def _dynamic_object_schema(key: str, has_null: bool) -> dict[str, Any]:
    if key == "configuration":
        additional: dict[str, Any] | bool = True
    elif key == "random_seeds":
        additional = {"type": "integer", "minimum": 0}
    elif key == "parameter_scales":
        additional = {"type": "number", "exclusiveMinimum": 0}
    else:
        additional = {"type": ["boolean", "integer", "number", "string"]}
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": additional,
    }
    return _with_null(schema) if has_null else schema


def _with_null(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _render_json(value: dict[str, Any]) -> str:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _json_values_match(expected: Any, actual: Any) -> bool:
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict):
        return expected.keys() == actual.keys() and all(
            _json_values_match(expected[key], actual[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(
            _json_values_match(expected_item, actual_item)
            for expected_item, actual_item in zip(expected, actual, strict=True)
        )
    if isinstance(expected, float):
        tolerance = 8 * max(math.ulp(expected), math.ulp(actual))
        return abs(expected - actual) <= tolerance
    return expected == actual


def _document_matches(path: Path, expected: str, actual: str) -> bool:
    if actual == expected:
        return True
    if path.suffix != ".json":
        return False
    try:
        expected_value = json.loads(expected)
        actual_value = json.loads(actual)
    except json.JSONDecodeError:
        return False
    return actual == _render_json(actual_value) and _json_values_match(
        expected_value,
        actual_value,
    )


def _write_documents(documents: dict[Path, str]) -> None:
    for path, content in documents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def _check_documents(documents: dict[Path, str]) -> int:
    stale = []
    for path, expected in documents.items():
        if not path.exists() or not _document_matches(
            path,
            expected,
            path.read_text(encoding="utf-8"),
        ):
            stale.append(path.relative_to(ROOT))
    if stale:
        print("Generated release contracts are missing or stale:")
        for path in stale:
            print(f"- {path}")
        print("Run: python scripts/release_contracts.py --write")
        return 1
    print(f"Verified {len(documents)} generated release contracts.")
    return 0


def main_entry(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    documents = build_release_documents()
    if arguments.write:
        _write_documents(documents)
        print(f"Wrote {len(documents)} generated release contracts.")
        return 0
    return _check_documents(documents)


if __name__ == "__main__":
    raise SystemExit(main_entry())
