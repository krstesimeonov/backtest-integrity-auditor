from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.verify_source_archive import verify_source_archive


ROOT = "V1.5J-backtest-integrity-auditor"
REQUIRED = {
    "pyproject.toml": '[project]\nversion = "1.5.0"\n',
    "src/backtest_auditor/__init__.py": 'PACKAGE_VERSION = "1.5.0"\n',
    "docs/V1_5J_RELEASE_HARDENING.md": "# V1.5J\n",
    "scripts/generate_v1_5j_golden.py": "# fixture\n",
    "scripts/verify_v1_5_installed.py": "# fixture\n",
    "tests/fixtures/v1_5j_golden/SHA256SUMS": "fixture\n",
}


def _archive(path: Path, extra: dict[str, str] | None = None) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, content in {**REQUIRED, **(extra or {})}.items():
            archive.writestr(f"{ROOT}/{relative}", content)


def test_source_archive_verifier_accepts_only_clean_complete_candidates(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.zip"
    _archive(candidate)

    result = verify_source_archive(
        candidate,
        expected_root=ROOT,
        expected_version="1.5.0",
    )

    assert result["file_count"] == len(REQUIRED)
    assert result["version"] == "1.5.0"


@pytest.mark.parametrize(
    "member",
    (
        "../escape.txt",
        ".pytest_cache/state",
        "build/output.txt",
        "src/backtest_auditor/module.pyc",
    ),
)
def test_source_archive_verifier_rejects_unsafe_or_generated_members(
    tmp_path: Path,
    member: str,
) -> None:
    candidate = tmp_path / "candidate.zip"
    _archive(candidate, {member: "bad"})

    with pytest.raises(ValueError):
        verify_source_archive(
            candidate,
            expected_root=ROOT,
            expected_version="1.5.0",
        )


DYNAMIC = {
    "pyproject.toml": (
        '[project]\nname = "backtest-integrity-auditor"\ndynamic = ["version"]\n\n'
        '[tool.setuptools.dynamic]\nversion = { attr = "backtest_auditor.PACKAGE_VERSION" }\n'
    ),
    "src/backtest_auditor/__init__.py": 'PACKAGE_VERSION = "1.5.2"\n__version__ = PACKAGE_VERSION\n',
}


def test_source_archive_verifier_reads_a_single_sourced_dynamic_version(
    tmp_path: Path,
) -> None:
    """Since 1.5.2 pyproject reads the version from PACKAGE_VERSION (W5-J1)."""
    candidate = tmp_path / "candidate.zip"
    _archive(candidate, DYNAMIC)

    result = verify_source_archive(
        candidate, expected_root=ROOT, expected_version="1.5.2"
    )
    assert result["version"] == "1.5.2"
    with pytest.raises(ValueError, match="version does not match"):
        verify_source_archive(candidate, expected_root=ROOT, expected_version="1.5.1")


@pytest.mark.parametrize(
    "override",
    (
        # dynamic, but from another attribute: not trusted
        {
            "pyproject.toml": DYNAMIC["pyproject.toml"].replace(
                "PACKAGE_VERSION", "OTHER"
            )
        },
        # dynamic, but no string literal to read
        {"src/backtest_auditor/__init__.py": "PACKAGE_VERSION = compute()\n"},
        # neither static nor dynamic
        {"pyproject.toml": '[project]\nname = "backtest-integrity-auditor"\n'},
    ),
)
def test_source_archive_verifier_fails_closed_on_an_unreadable_version(
    tmp_path: Path, override: dict[str, str]
) -> None:
    candidate = tmp_path / "candidate.zip"
    _archive(candidate, {**DYNAMIC, **override})

    with pytest.raises(ValueError, match="version does not match"):
        verify_source_archive(candidate, expected_root=ROOT, expected_version="1.5.2")
