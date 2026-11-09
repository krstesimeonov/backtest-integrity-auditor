"""Validate the published schemas against reports they were NOT derived from.

tests/release/test_public_schemas.py validates the same objects that
build_runtime_examples() feeds to the schema generator, so it cannot detect a
schema that rejects the engine's own valid output -- the schema and the
instance come from one source. These invocations are deliberately disjoint
from SINGLE_SCHEMA_CORPUS and FAMILY_SCHEMA_CORPUS: if a future change infers
a type from too narrow a corpus again, one of these fails.
"""

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from backtest_auditor.reporting.schema_catalog import (
    PUBLIC_SCHEMA_FILES,
    load_public_schema,
)
from scripts.release_contracts import (
    FAMILY_SCHEMA_CORPUS,
    SINGLE_SCHEMA_CORPUS,
    _run_json,
)

_SINGLE_CASES = {
    # Log returns rather than simple: exercises the return_basis enum paths.
    "log_convention": (
        "examples/sample_returns.csv",
        "--run-id",
        "corpus-log",
        "--return-convention",
        "log",
    ),
    # Bootstrap configured with no benchmark and no serial diagnostics.
    "bootstrap_without_benchmark": (
        "examples/sample_returns.csv",
        "--run-id",
        "corpus-bootstrap",
        "--declared-frequency",
        "D",
        "--periods-per-year",
        "365",
        "--annual-risk-free-rate",
        "0.01",
        "--bootstrap-method",
        "moving_block",
        "--bootstrap-interval-method",
        "percentile",
        "--bootstrap-replications",
        "20",
        "--bootstrap-confidence-level",
        "0.9",
        "--bootstrap-block-length",
        "2",
        "--bootstrap-seed",
        "7",
    ),
    # PSR configured without a required confidence level, so the minimum
    # track-record length section is legitimately absent.
    "psr_without_track_record_length": (
        "examples/sample_returns.csv",
        "--run-id",
        "corpus-psr",
        "--declared-frequency",
        "D",
        "--periods-per-year",
        "365",
        "--annual-risk-free-rate",
        "0.0",
        "--benchmark-annualized-sharpe-ratio",
        "0.0",
    ),
    # A benchmark with construction metadata but no benchmark calendar. The
    # schema corpus reaches the same null via a bare --benchmark-csv, so this
    # is an independent route to benchmark.observation_calendar = null.
    "benchmark_metadata_without_calendar": (
        "examples/sample_returns.csv",
        "--run-id",
        "corpus-benchmark-metadata",
        "--benchmark-csv",
        "examples/sample_benchmark.csv",
        "--benchmark-id",
        "market",
        "--benchmark-currency",
        "EUR",
        "--benchmark-leverage-policy",
        "unlevered",
        "--benchmark-fees-included",
        "true",
    ),
    # An observation calendar with no benchmark and no statistical methods.
    "calendar_without_statistics": (
        "examples/sample_returns.csv",
        "--run-id",
        "corpus-calendar",
        "--observation-calendar",
        "24/7",
        "--calendar-timezone",
        "UTC",
        "--timestamp-timezone",
        "UTC",
    ),
}

_FAMILY_CASES = {
    # CSCV configured alone: no DSR, no robustness, no temporal section.
    "cscv_only": (
        "family",
        "examples/cscv_family_manifest.json",
        "examples/cscv_family_trials.csv",
        "examples/cscv_family_returns.csv",
        "--splits-csv",
        "examples/cscv_family_splits.csv",
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
    ),
    # Every optional family method switched off at once.
    "no_methods_configured": (
        "family",
        "examples/cscv_family_manifest.json",
        "examples/cscv_family_trials.csv",
        "examples/cscv_family_returns.csv",
    ),
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    schemas = [load_public_schema(name) for name in PUBLIC_SCHEMA_FILES]
    return Registry().with_resources(
        [(schema["$id"], Resource.from_contents(schema)) for schema in schemas]
    )


def _validate(instance: dict, schema_name: str, registry: Registry) -> None:
    Draft202012Validator(
        load_public_schema(schema_name),
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(instance)


@pytest.mark.parametrize("name", sorted(_SINGLE_CASES))
def test_single_run_reports_outside_the_schema_corpus_validate(
    name: str,
    registry: Registry,
) -> None:
    _validate(_run_json(_SINGLE_CASES[name]), "single_run_report_2_5", registry)


@pytest.mark.parametrize("name", sorted(_FAMILY_CASES))
def test_family_reports_outside_the_schema_corpus_validate(
    name: str,
    registry: Registry,
) -> None:
    _validate(
        _run_json(_FAMILY_CASES[name]),
        "experiment_family_report_2_5",
        registry,
    )


def test_no_published_field_is_frozen_to_null() -> None:
    """A field typed {"type": "null"} can never carry a value.

    Five fields reached the tagged V1 release in this state, so the engine
    could emit a documented, valid report that its own published schema
    rejected. The generator now raises instead of inferring this, and this
    test pins the resulting invariant.
    """

    def frozen(schema: dict) -> list[str]:
        found: list[str] = []

        def walk(node: object, path: str) -> None:
            if not isinstance(node, dict):
                return
            for name, sub in (node.get("properties") or {}).items():
                child = f"{path}.{name}"
                if sub == {"type": "null"}:
                    found.append(child)
                    continue
                walk(sub, child)
                for branch in sub.get("anyOf", []):
                    walk(branch, child)
                items = sub.get("items")
                if isinstance(items, dict):
                    walk(items, f"{child}[]")
                    for branch in items.get("anyOf", []):
                        walk(branch, f"{child}[]")
            for branch in node.get("anyOf", []):
                walk(branch, path)
            items = node.get("items")
            if isinstance(items, dict):
                walk(items, f"{path}[]")

        walk(schema, "")
        return sorted(set(found))

    for name in (
        "single_run_report_2_4",
        "experiment_family_report_2_4",
        "single_run_report_2_5",
        "experiment_family_report_2_5",
    ):
        assert frozen(load_public_schema(name)) == []


def test_no_published_array_is_unconstrained() -> None:
    """An array with `items: {}` validates literally any content.

    input_issues shipped this way in the single-run schema: every corpus run
    parsed cleanly, so the array was empty in all of them and the generator
    had no item to infer from. Generated TypeScript typed it `unknown[]`,
    which is how this was noticed. Same root cause as a field that is null in
    every example, in a different disguise.
    """

    def unconstrained(schema: dict) -> list[str]:
        found: list[str] = []

        def walk(node: object, path: str) -> None:
            if not isinstance(node, dict):
                return
            for name, sub in (node.get("properties") or {}).items():
                child = f"{path}.{name}"
                if (
                    isinstance(sub, dict)
                    and sub.get("type") == "array"
                    and sub.get("items") == {}
                ):
                    found.append(child)
                walk(sub, child)
                for branch in sub.get("anyOf") or []:
                    walk(branch, child)
                items = sub.get("items")
                if isinstance(items, dict):
                    walk(items, f"{child}[]")
            for branch in node.get("anyOf") or []:
                walk(branch, path)
            items = node.get("items")
            if isinstance(items, dict):
                walk(items, f"{path}[]")

        walk(schema, "")
        return sorted(set(found))

    for name in (
        "single_run_report_2_4",
        "experiment_family_report_2_4",
        "single_run_report_2_5",
        "experiment_family_report_2_5",
    ):
        assert unconstrained(load_public_schema(name)) == []


def test_input_issues_items_are_typed() -> None:
    """The specific regression: input_issues must describe its members."""

    for name in (
        "single_run_report_2_4",
        "experiment_family_report_2_4",
        "single_run_report_2_5",
        "experiment_family_report_2_5",
    ):
        items = load_public_schema(name)["properties"]["input_issues"]["items"]
        assert set(items["properties"]) == {
            "blocking",
            "code",
            "location",
            "message",
            "severity",
        }


def test_schema_corpus_covers_more_than_a_full_and_minimal_pair() -> None:
    """Guard the corpus itself.

    The defect this file exists to catch was caused by deriving a 67 KB type
    contract from exactly two CLI invocations. Shrinking the corpus back to a
    full/minimal pair must not pass silently.
    """

    assert len(SINGLE_SCHEMA_CORPUS) >= 7
    assert len(FAMILY_SCHEMA_CORPUS) >= 5
    assert "single_benchmark_minimal" in SINGLE_SCHEMA_CORPUS
    assert "single_moving_block" in SINGLE_SCHEMA_CORPUS
    assert "single_unsorted" in SINGLE_SCHEMA_CORPUS
    assert "single_variance_ratio" in SINGLE_SCHEMA_CORPUS
    assert "family_effective_trials" in FAMILY_SCHEMA_CORPUS
    assert "family_lower_neighbour" in FAMILY_SCHEMA_CORPUS
