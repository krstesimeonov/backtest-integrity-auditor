import hashlib
from pathlib import Path

from backtest_auditor.domain.reproducibility import InputArtifactHash


def hash_input_file(role: str, path: Path) -> InputArtifactHash:
    """Hash one raw input without embedding a machine-specific absolute path."""

    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as input_file:
        while chunk := input_file.read(1024 * 1024):
            digest.update(chunk)
            size_bytes += len(chunk)
    return InputArtifactHash(
        role=role,
        file_name=path.name,
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
    )
