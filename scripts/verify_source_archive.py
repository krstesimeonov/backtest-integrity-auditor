"""Fail-closed structural verification for a V1.5 source ZIP candidate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import stat
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


MAX_ARCHIVE_FILES = 1_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 50_000_000
MAX_ARCHIVE_FILE_BYTES = 10_000_000
EXCLUDED_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


def _safe_path(name: str, expected_root: str) -> PurePosixPath:
    if "\\" in name or "\x00" in name:
        raise ValueError("archive member contains an unsafe path character.")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("archive member path is not relative and normalized.")
    if path.parts[0] != expected_root:
        raise ValueError("archive must contain exactly the declared top-level root.")
    if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in path.parts):
        raise ValueError("archive contains excluded cache or build material.")
    if path.suffix in {".pyc", ".pyo"} or path.name == ".coverage":
        raise ValueError("archive contains excluded generated material.")
    return path


def _declared_version(project: dict, package_init: str) -> str | None:
    """The archive's package version: a static ``[project].version``, or, when
    pyproject declares it dynamic from ``backtest_auditor.PACKAGE_VERSION``, that
    string literal in ``src/backtest_auditor/__init__.py`` (parsed, never run)."""

    table = project.get("project", {})
    if "version" in table:
        return table["version"]
    dynamic = project.get("tool", {}).get("setuptools", {}).get("dynamic", {})
    if "version" not in table.get("dynamic", []) or dynamic.get("version") != {
        "attr": "backtest_auditor.PACKAGE_VERSION"
    }:
        return None
    try:
        tree = ast.parse(package_init)
    except SyntaxError as error:
        raise ValueError(
            "source archive package __init__.py does not parse."
        ) from error
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and [ast.unparse(target) for target in node.targets] == ["PACKAGE_VERSION"]
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def verify_source_archive(
    source: Path,
    *,
    expected_root: str,
    expected_version: str,
) -> dict[str, object]:
    if source.is_symlink() or not source.is_file():
        raise ValueError("source archive must be a regular non-symlink file.")
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("source archive is not a valid ZIP file.") from error
    with archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if not infos or len(infos) > MAX_ARCHIVE_FILES:
            raise ValueError("source archive file count exceeds the release limit.")
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise ValueError("source archive contains duplicate members.")
        total = 0
        members: dict[PurePosixPath, zipfile.ZipInfo] = {}
        for info in infos:
            path = _safe_path(info.filename, expected_root)
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) == stat.S_IFLNK or info.flag_bits & 0x1:
                raise ValueError("source archive contains a link or encrypted member.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError(
                    "source archive uses an unsupported compression method."
                )
            if info.file_size > MAX_ARCHIVE_FILE_BYTES:
                raise ValueError("source archive member exceeds the release limit.")
            total += info.file_size
            members[path] = info
        if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("source archive exceeds the uncompressed release limit.")

        required = {
            PurePosixPath(expected_root, "pyproject.toml"),
            PurePosixPath(expected_root, "src/backtest_auditor/__init__.py"),
            PurePosixPath(expected_root, "docs/V1_5J_RELEASE_HARDENING.md"),
            PurePosixPath(expected_root, "scripts/generate_v1_5j_golden.py"),
            PurePosixPath(expected_root, "scripts/verify_v1_5_installed.py"),
            PurePosixPath(expected_root, "tests/fixtures/v1_5j_golden/SHA256SUMS"),
        }
        missing = required.difference(members)
        if missing:
            raise ValueError(
                f"source archive is missing required files: {sorted(missing)}"
            )
        project = tomllib.loads(
            archive.read(
                members[PurePosixPath(expected_root, "pyproject.toml")]
            ).decode("utf-8")
        )
        package_init = archive.read(
            members[PurePosixPath(expected_root, "src/backtest_auditor/__init__.py")]
        ).decode("utf-8")
        if _declared_version(project, package_init) != expected_version:
            raise ValueError("source archive package version does not match.")
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"source archive CRC verification failed for {bad!r}.")

    return {
        "archive_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "file_count": len(infos),
        "uncompressed_bytes": total,
        "version": expected_version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--expected-root", required=True)
    parser.add_argument("--expected-version", required=True)
    arguments = parser.parse_args()
    try:
        result = verify_source_archive(
            arguments.archive,
            expected_root=arguments.expected_root,
            expected_version=arguments.expected_version,
        )
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as error:
        print(f"source archive verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
