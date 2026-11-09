from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest_auditor.domain.reproducibility import (
    AuditRunSpec,
    InputArtifactHash,
)
from backtest_auditor.ingestion.file_hashing import hash_input_file


def test_audit_run_spec_requires_timezone_and_normalizes_to_utc() -> None:
    with pytest.raises(ValueError, match="timezone offset"):
        AuditRunSpec(
            audit_id="audit-1",
            audit_timestamp=datetime(2026, 8, 12, 10, 30),
            git_commit="abc123",
        )

    spec = AuditRunSpec(
        audit_id=" audit-1 ",
        audit_timestamp=datetime.fromisoformat("2026-08-12T12:30:00+02:00"),
        git_commit=" abc123 ",
    )

    assert spec.audit_id == "audit-1"
    assert spec.audit_timestamp == datetime(2026, 8, 12, 10, 30, tzinfo=timezone.utc)
    assert spec.git_commit == "abc123"


def test_input_artifact_hash_rejects_invalid_digest() -> None:
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        InputArtifactHash(
            role="strategy_returns",
            file_name="returns.csv",
            size_bytes=1,
            sha256="not-a-digest",
        )


def test_file_hashing_records_bytes_and_basename_only(tmp_path: Path) -> None:
    source = tmp_path / "raw-returns.csv"
    source.write_bytes(b"timestamp,return\n2026-01-01,0.01\n")

    artifact = hash_input_file("strategy_returns", source)

    assert artifact.role == "strategy_returns"
    assert artifact.file_name == "raw-returns.csv"
    assert artifact.size_bytes == source.stat().st_size
    assert str(tmp_path) not in artifact.file_name
    assert len(artifact.sha256) == 64
