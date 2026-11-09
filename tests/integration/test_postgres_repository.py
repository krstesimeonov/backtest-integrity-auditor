import os

import pytest

from backtest_auditor.application.audit_repository import AuditSnapshot
from backtest_auditor.persistence.sqlalchemy_repository import SQLAlchemyAuditRepository


@pytest.mark.skipif(
    "BACKTEST_AUDITOR_TEST_POSTGRES_URL" not in os.environ,
    reason="PostgreSQL integration URL is not configured.",
)
def test_postgresql_repository_round_trip() -> None:
    repository = SQLAlchemyAuditRepository(
        os.environ["BACKTEST_AUDITOR_TEST_POSTGRES_URL"]
    )
    snapshot = AuditSnapshot(
        audit_type="single_run",
        subject_id="postgres-integration",
        report_schema_version="2.4",
        package_version="1.2.1",
        json_report='{"schema_version":"2.4"}\n',
        markdown_report="# PostgreSQL integration\n",
        manifest_json=None,
        normalized_series=(),
    )
    saved = repository.save(snapshot)
    loaded = repository.get(saved.audit_id)
    assert loaded is not None
    assert loaded.summary.subject_id == "postgres-integration"
