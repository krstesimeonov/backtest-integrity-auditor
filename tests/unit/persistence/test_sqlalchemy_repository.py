from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, insert, update

from backtest_auditor.application.audit_repository import (
    AuditSnapshot,
    NormalizedObservation,
    NormalizedSeriesSnapshot,
)
from backtest_auditor.persistence.sqlalchemy_repository import (
    PersistenceError,
    SQLAlchemyAuditRepository,
    UnsupportedSchemaError,
    _legacy_fingerprint,
    audits,
    schema_versions,
)


def _snapshot(subject: str = "strategy-one") -> AuditSnapshot:
    return AuditSnapshot(
        audit_type="single_run",
        subject_id=subject,
        report_schema_version="2.4",
        package_version="1.2.1",
        json_report='{"run_manifest":null,"schema_version":"2.4"}\n',
        markdown_report="# Audit\n",
        manifest_json=None,
        normalized_series=(
            NormalizedSeriesSnapshot(
                role="strategy",
                series_id=subject,
                return_convention="simple",
                sampling_json='{"periods_per_year":252}',
                observations=(
                    NormalizedObservation("2026-01-01T00:00:00", 0.01),
                    NormalizedObservation("2026-01-02T00:00:00", -0.02),
                ),
            ),
        ),
    )


def test_sqlite_repository_round_trip_and_idempotency(tmp_path: Path) -> None:
    repository = SQLAlchemyAuditRepository(f"sqlite:///{tmp_path / 'audits.db'}")

    first = repository.save(_snapshot())
    repeated = repository.save(_snapshot())
    second = repository.save(_snapshot("strategy-two"))

    assert first.created is True
    assert repeated == type(repeated)(first.audit_id, False)
    assert second.created is True
    summaries = repository.list()
    assert {item.subject_id for item in summaries} == {"strategy-one", "strategy-two"}
    assert all(item.series_count == 1 for item in summaries)
    assert all(item.observation_count == 2 for item in summaries)

    stored = repository.get(first.audit_id)
    assert stored is not None
    assert stored.summary.subject_id == "strategy-one"
    assert stored.json_report == _snapshot().json_report
    assert stored.normalized_series[0].observations[1].value == -0.02
    assert repository.get("missing") is None


def test_repository_validates_paging_and_supported_backend(tmp_path: Path) -> None:
    repository = SQLAlchemyAuditRepository(f"sqlite:///{tmp_path / 'audits.db'}")
    with pytest.raises(ValueError, match="limit"):
        repository.list(limit=0)
    with pytest.raises(ValueError, match="SQLite and PostgreSQL"):
        SQLAlchemyAuditRepository("mysql+pymysql://localhost/test", create_schema=False)
    with pytest.raises(ValueError, match="invalid"):
        SQLAlchemyAuditRepository("not a URL", create_schema=False)
    with pytest.raises(ValueError, match="must not be empty"):
        SQLAlchemyAuditRepository(" ", create_schema=False)
    with pytest.raises(ValueError, match="psycopg"):
        SQLAlchemyAuditRepository(
            "postgresql+asyncpg://localhost/test", create_schema=False
        )
    with SQLAlchemyAuditRepository(
        "postgresql://user:secret@localhost/test", create_schema=False
    ) as postgres:
        assert postgres.backend == "postgresql"


def test_repository_rejects_unknown_schema_version(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'future.db'}"
    engine = create_engine(url)
    schema_versions.create(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(schema_versions).values(component="audit_repository", version=999)
        )
    assert not inspect(engine).has_table(audits.name)
    with pytest.raises(UnsupportedSchemaError, match="unsupported"):
        SQLAlchemyAuditRepository(url)
    assert not inspect(engine).has_table(audits.name)


def test_snapshot_identity_includes_package_version(tmp_path: Path) -> None:
    repository = SQLAlchemyAuditRepository(f"sqlite:///{tmp_path / 'identity.db'}")
    original = _snapshot()

    first = repository.save(original)
    changed = repository.save(replace(original, package_version="1.2.2"))

    assert first.created is True
    assert changed.created is True
    assert first.audit_id != changed.audit_id


def test_legacy_v1_2_fingerprint_remains_idempotent(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    repository = SQLAlchemyAuditRepository(url)
    snapshot = replace(_snapshot(), package_version="1.2.0")
    first = repository.save(snapshot)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            update(audits)
            .where(audits.c.audit_id == first.audit_id)
            .values(fingerprint=_legacy_fingerprint(snapshot))
        )

    repeated = repository.save(snapshot)

    assert repeated.audit_id == first.audit_id
    assert repeated.created is False


@pytest.mark.parametrize(
    "snapshot",
    [
        replace(_snapshot(), json_report="[]"),
        replace(_snapshot(), json_report='{"schema_version":"9.9"}'),
        replace(
            _snapshot(),
            json_report=(
                '{"run_manifest":{"audit_id":"unexpected"},"schema_version":"2.4"}'
            ),
        ),
        replace(_snapshot(), json_report='{"schema_version":NaN}'),
        replace(_snapshot(), manifest_json="{}"),
        replace(_snapshot(), subject_id=" "),
        replace(_snapshot(), subject_id="x" * 256),
        replace(
            _snapshot(),
            normalized_series=(
                _snapshot().normalized_series[0],
                _snapshot().normalized_series[0],
            ),
        ),
        replace(
            _snapshot(),
            normalized_series=(
                replace(
                    _snapshot().normalized_series[0], return_convention="percentage"
                ),
            ),
        ),
        replace(
            _snapshot(),
            normalized_series=(
                replace(_snapshot().normalized_series[0], sampling_json="[]"),
            ),
        ),
        replace(
            _snapshot(),
            normalized_series=(
                replace(_snapshot().normalized_series[0], observations=()),
            ),
        ),
        replace(
            _snapshot(),
            normalized_series=(
                replace(
                    _snapshot().normalized_series[0],
                    observations=(NormalizedObservation("not-a-timestamp", 0.1),),
                ),
            ),
        ),
        replace(
            _snapshot(),
            normalized_series=(
                replace(
                    _snapshot().normalized_series[0],
                    observations=(
                        NormalizedObservation("2026-01-01T00:00:00", 0.1),
                        NormalizedObservation("2026-01-01T00:00:00", 0.2),
                    ),
                ),
            ),
        ),
        replace(
            _snapshot(),
            normalized_series=(
                replace(
                    _snapshot().normalized_series[0],
                    observations=(NormalizedObservation("2026-01-01T00:00:00", -1.01),),
                ),
            ),
        ),
        replace(
            _snapshot(),
            normalized_series=(
                replace(
                    _snapshot().normalized_series[0],
                    observations=(
                        NormalizedObservation("2026-01-01T00:00:00", float("nan")),
                    ),
                ),
            ),
        ),
    ],
)
def test_repository_rejects_invalid_snapshot_content(
    tmp_path: Path, snapshot: AuditSnapshot
) -> None:
    repository = SQLAlchemyAuditRepository(f"sqlite:///{tmp_path / 'invalid.db'}")

    with pytest.raises(ValueError):
        repository.save(snapshot)


def test_repository_rejects_corrupted_stored_snapshot(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'corrupted.db'}"
    repository = SQLAlchemyAuditRepository(url)
    saved = repository.save(_snapshot())
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            update(audits)
            .where(audits.c.audit_id == saved.audit_id)
            .values(json_report="[]")
        )

    with pytest.raises(PersistenceError, match="integrity validation"):
        repository.get(saved.audit_id)
