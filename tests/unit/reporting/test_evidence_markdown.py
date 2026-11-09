"""The populated run-manifest section of the Markdown report.

Both Markdown goldens are generated without a manifest, so until these tests
existed the populated branch below was executed by nothing: deleting it passed
every gate. Values are fixed here rather than taken from a real run, because a
real manifest records the interpreter, platform and dependency versions of
whichever machine produced it.
"""

from dataclasses import replace

from backtest_auditor.domain.reproducibility import (
    AuditRunManifestResult,
    DependencyVersion,
    InputArtifactHash,
    ManifestWarning,
    MethodVersion,
)
from backtest_auditor.reporting.evidence_markdown import append_run_manifest_section

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _manifest() -> AuditRunManifestResult:
    return AuditRunManifestResult(
        manifest_schema_version="1.0",
        audit_id="audit-42",
        audit_timestamp_utc="2026-01-02T03:04:05Z",
        audit_type="single_run",
        subject_id="alpha|beta",
        package_version="1.0.0",
        report_schema_version="2.4",
        git_commit="abc`123",
        input_artifacts=(
            InputArtifactHash(
                role="returns", file_name="returns.csv", size_bytes=1024, sha256=_SHA_A
            ),
            InputArtifactHash(
                role="benchmark", file_name="bench.csv", size_bytes=512, sha256=_SHA_B
            ),
        ),
        normalized_data_encoding="canonical-csv-v1",
        normalized_data_sha256="c" * 64,
        configuration_json='{"b": 1, "a": "é"}',
        configuration_sha256="d" * 64,
        random_seeds=(("bootstrap", 42),),
        method_versions=(MethodVersion(name="psr", version="1"),),
        warnings=(ManifestWarning(source="finding", code="ZERO_SAMPLE_VOLATILITY"),),
        python_implementation="CPython",
        python_version="3.12.0",
        platform_system="Linux",
        platform_machine="x86_64",
        dependencies=(DependencyVersion(name="numpy", version="2.0.0"),),
        manifest_sha256="e" * 64,
    )


def _render(manifest: AuditRunManifestResult | None) -> list[str]:
    lines: list[str] = []
    append_run_manifest_section(lines, manifest)
    return lines


def test_populated_manifest_renders_every_identity_row() -> None:
    lines = _render(_manifest())

    for row in (
        "| Manifest schema | 1.0 |",
        "| Audit ID | audit-42 |",
        "| Audit timestamp UTC | 2026-01-02T03:04:05Z |",
        "| Audit type | single_run |",
        "| Package version | 1.0.0 |",
        "| Report schema | 2.4 |",
        "| Normalized-data encoding | canonical-csv-v1 |",
        f"| Normalized-data SHA-256 | `{'c' * 64}` |",
        f"| Configuration SHA-256 | `{'d' * 64}` |",
        f"| Manifest SHA-256 | `{'e' * 64}` |",
        "| Python | CPython 3.12.0 |",
        "| Platform | Linux / x86_64 |",
    ):
        assert row in lines


def test_table_breaking_characters_are_escaped() -> None:
    # An unescaped "|" would split the row into an extra column, and a stray
    # backtick would open a code span that swallows the rest of the table.
    lines = _render(_manifest())

    assert "| Subject ID | alpha\\|beta |" in lines
    assert "| Git commit | abc\\`123 |" in lines


def test_every_input_artifact_method_and_dependency_gets_a_row() -> None:
    lines = _render(_manifest())

    assert f"| returns | returns.csv | 1024 | `{_SHA_A}` |" in lines
    assert f"| benchmark | bench.csv | 512 | `{_SHA_B}` |" in lines
    assert "| method | psr | 1 |" in lines
    assert "| dependency | numpy | 2.0.0 |" in lines


def test_seeds_and_warnings_are_tabulated_when_present() -> None:
    lines = _render(_manifest())

    assert "| bootstrap | 42 |" in lines
    assert "| finding | ZERO_SAMPLE_VOLATILITY |" in lines
    assert "No stochastic method was configured." not in lines
    assert "No input issue or audit finding code was recorded." not in lines


def test_absent_seeds_and_warnings_are_stated_rather_than_left_empty() -> None:
    lines = _render(replace(_manifest(), random_seeds=(), warnings=()))

    assert "No stochastic method was configured." in lines
    assert "No input issue or audit finding code was recorded." in lines
    assert "| Purpose | Seed |" not in lines


def test_configuration_is_rendered_canonically() -> None:
    text = "\n".join(_render(_manifest()))

    # Sorted keys, two-space indent, and literal UTF-8, inside a JSON fence.
    assert '```json\n{\n  "a": "é",\n  "b": 1\n}\n```' in text


def test_unconfigured_manifest_says_nothing_was_inferred() -> None:
    lines = _render(None)

    assert lines[-1] == (
        "No deterministic run manifest was configured. Audit ID, timestamp, "
        "and Git revision are never inferred."
    )
    assert "| Property | Value |" not in lines
