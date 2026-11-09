"""Portable SQLite/PostgreSQL audit repository."""

import hashlib
import json
import math
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Self
from uuid import uuid4

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    inspect,
    insert,
    or_,
    select,
)
from sqlalchemy.exc import ArgumentError, IntegrityError, SQLAlchemyError
from sqlalchemy.engine.url import make_url

from backtest_auditor.application.audit_repository import (
    AuditSnapshot,
    NormalizedObservation,
    NormalizedSeriesSnapshot,
    SaveAuditResult,
    StoredAudit,
    StoredAuditSummary,
)

SCHEMA_VERSION = 1
metadata = MetaData()

schema_versions = Table(
    "audit_schema_versions",
    metadata,
    Column("component", String(80), primary_key=True),
    Column("version", Integer, nullable=False),
)
audits = Table(
    "audits",
    metadata,
    Column("audit_id", String(36), primary_key=True),
    Column("fingerprint", String(64), nullable=False, unique=True),
    Column("audit_type", String(40), nullable=False),
    Column("subject_id", String(255), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("report_schema_version", String(20), nullable=False),
    Column("package_version", String(20), nullable=False),
    Column("json_report", Text, nullable=False),
    Column("markdown_report", Text, nullable=False),
    Column("manifest_json", Text),
)
series = Table(
    "normalized_series",
    metadata,
    Column("series_pk", Integer, primary_key=True, autoincrement=True),
    Column(
        "audit_id",
        String(36),
        ForeignKey("audits.audit_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("role", String(40), nullable=False),
    Column("series_id", String(255), nullable=False),
    Column("return_convention", String(20), nullable=False),
    Column("sampling_json", Text, nullable=False),
    UniqueConstraint("audit_id", "ordinal"),
)
observations = Table(
    "normalized_observations",
    metadata,
    Column(
        "series_pk",
        Integer,
        ForeignKey("normalized_series.series_pk", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("timestamp", String(64), nullable=False),
    Column("value", Float, nullable=False),
)


class PersistenceError(RuntimeError):
    """Database operation failed without exposing connection credentials."""


class UnsupportedSchemaError(PersistenceError):
    pass


class SQLAlchemyAuditRepository:
    def __init__(self, database_url: str, *, create_schema: bool = True) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise ValueError("database URL must not be empty.")
        try:
            url = make_url(database_url)
        except ArgumentError as error:
            raise ValueError("database URL is invalid.") from error
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        supported_drivers = {"sqlite", "sqlite+pysqlite", "postgresql+psycopg"}
        if url.drivername not in supported_drivers:
            raise ValueError(
                "V1.2 supports SQLite and PostgreSQL through the psycopg driver."
            )
        try:
            self._engine = create_engine(url, future=True, pool_pre_ping=True)
        except (ImportError, SQLAlchemyError) as error:
            raise PersistenceError("database engine creation failed.") from error
        if self._engine.dialect.name == "sqlite":
            event.listen(self._engine, "connect", _enable_sqlite_foreign_keys)
        if create_schema:
            self.initialize_schema()

    @property
    def backend(self) -> str:
        return self._engine.dialect.name

    def close(self) -> None:
        self._engine.dispose()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def initialize_schema(self) -> None:
        try:
            with self._engine.begin() as connection:
                version = None
                if inspect(connection).has_table(schema_versions.name):
                    version = connection.execute(
                        select(schema_versions.c.version).where(
                            schema_versions.c.component == "audit_repository"
                        )
                    ).scalar_one_or_none()
                    if version is not None and version != SCHEMA_VERSION:
                        raise UnsupportedSchemaError(
                            f"database schema version {version} is unsupported; "
                            f"expected {SCHEMA_VERSION}."
                        )

                metadata.create_all(connection)
                if version is None:
                    connection.execute(
                        insert(schema_versions).values(
                            component="audit_repository", version=SCHEMA_VERSION
                        )
                    )
        except UnsupportedSchemaError:
            raise
        except SQLAlchemyError as error:
            raise PersistenceError("database schema initialization failed.") from error

    def save(self, snapshot: AuditSnapshot) -> SaveAuditResult:
        _validate_snapshot(snapshot)
        fingerprint = _fingerprint(snapshot)
        legacy_fingerprint = _legacy_fingerprint(snapshot)
        audit_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            with self._engine.begin() as connection:
                existing = connection.execute(
                    _matching_audit_id_statement(
                        snapshot, fingerprint, legacy_fingerprint
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return SaveAuditResult(str(existing), False)
                connection.execute(
                    insert(audits).values(
                        audit_id=audit_id,
                        fingerprint=fingerprint,
                        audit_type=snapshot.audit_type,
                        subject_id=snapshot.subject_id,
                        created_at=created_at,
                        report_schema_version=snapshot.report_schema_version,
                        package_version=snapshot.package_version,
                        json_report=snapshot.json_report,
                        markdown_report=snapshot.markdown_report,
                        manifest_json=snapshot.manifest_json,
                    )
                )
                for series_ordinal, item in enumerate(snapshot.normalized_series):
                    result = connection.execute(
                        insert(series).values(
                            audit_id=audit_id,
                            ordinal=series_ordinal,
                            role=item.role,
                            series_id=item.series_id,
                            return_convention=item.return_convention,
                            sampling_json=item.sampling_json,
                        )
                    )
                    primary_key = result.inserted_primary_key
                    assert primary_key is not None
                    series_pk = primary_key[0]
                    connection.execute(
                        insert(observations),
                        [
                            {
                                "series_pk": series_pk,
                                "ordinal": ordinal,
                                "timestamp": observation.timestamp,
                                "value": observation.value,
                            }
                            for ordinal, observation in enumerate(item.observations)
                        ],
                    )
            return SaveAuditResult(audit_id, True)
        except IntegrityError as error:
            try:
                with self._engine.connect() as connection:
                    existing = connection.execute(
                        _matching_audit_id_statement(
                            snapshot, fingerprint, legacy_fingerprint
                        )
                    ).scalar_one_or_none()
                if existing is not None:
                    return SaveAuditResult(str(existing), False)
            except SQLAlchemyError:
                pass
            raise PersistenceError("saving the audit snapshot failed.") from error
        except SQLAlchemyError as error:
            raise PersistenceError("saving the audit snapshot failed.") from error

    def list(
        self, *, limit: int = 100, offset: int = 0
    ) -> tuple[StoredAuditSummary, ...]:
        if limit <= 0 or limit > 1000 or offset < 0:
            raise ValueError("limit must be 1..1000 and offset must be non-negative.")
        counts = (
            select(
                series.c.audit_id.label("audit_id"),
                func.count(func.distinct(series.c.series_pk)).label("series_count"),
                func.count(observations.c.ordinal).label("observation_count"),
            )
            .select_from(series.outerjoin(observations))
            .group_by(series.c.audit_id)
            .subquery()
        )
        statement = (
            select(
                audits.c.audit_id,
                audits.c.audit_type,
                audits.c.subject_id,
                audits.c.created_at,
                audits.c.report_schema_version,
                audits.c.package_version,
                func.coalesce(counts.c.series_count, 0).label("series_count"),
                func.coalesce(counts.c.observation_count, 0).label("observation_count"),
            )
            .outerjoin(counts, counts.c.audit_id == audits.c.audit_id)
            .order_by(audits.c.created_at.desc(), audits.c.audit_id.desc())
            .limit(limit)
            .offset(offset)
        )
        try:
            with self._engine.connect() as connection:
                return tuple(
                    StoredAuditSummary(**dict(row._mapping))
                    for row in connection.execute(statement)
                )
        except SQLAlchemyError as error:
            raise PersistenceError("listing audit history failed.") from error

    def get(self, audit_id: str) -> StoredAudit | None:
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    select(audits).where(audits.c.audit_id == audit_id)
                ).one_or_none()
                if row is None:
                    return None
                mapping = row._mapping
                series_rows = connection.execute(
                    select(series)
                    .where(series.c.audit_id == audit_id)
                    .order_by(series.c.ordinal)
                ).all()
                snapshots = []
                for series_row in series_rows:
                    item = series_row._mapping
                    observation_rows = connection.execute(
                        select(observations.c.timestamp, observations.c.value)
                        .where(observations.c.series_pk == item["series_pk"])
                        .order_by(observations.c.ordinal)
                    )
                    snapshots.append(
                        NormalizedSeriesSnapshot(
                            role=item["role"],
                            series_id=item["series_id"],
                            return_convention=item["return_convention"],
                            sampling_json=item["sampling_json"],
                            observations=tuple(
                                NormalizedObservation(
                                    timestamp=o.timestamp, value=o.value
                                )
                                for o in observation_rows
                            ),
                        )
                    )
                summary = StoredAuditSummary(
                    audit_id=mapping["audit_id"],
                    audit_type=mapping["audit_type"],
                    subject_id=mapping["subject_id"],
                    created_at=mapping["created_at"],
                    report_schema_version=mapping["report_schema_version"],
                    package_version=mapping["package_version"],
                    series_count=len(snapshots),
                    observation_count=sum(len(item.observations) for item in snapshots),
                )
                stored = StoredAudit(
                    summary,
                    mapping["json_report"],
                    mapping["markdown_report"],
                    mapping["manifest_json"],
                    tuple(snapshots),
                )
                try:
                    _validate_snapshot(
                        AuditSnapshot(
                            audit_type=summary.audit_type,
                            subject_id=summary.subject_id,
                            report_schema_version=summary.report_schema_version,
                            package_version=summary.package_version,
                            json_report=stored.json_report,
                            markdown_report=stored.markdown_report,
                            manifest_json=stored.manifest_json,
                            normalized_series=stored.normalized_series,
                        )
                    )
                except ValueError as error:
                    raise PersistenceError(
                        "stored audit snapshot failed integrity validation."
                    ) from error
                return stored
        except PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise PersistenceError("loading the audit snapshot failed.") from error


def _fingerprint(snapshot: AuditSnapshot) -> str:
    document = {
        "audit_type": snapshot.audit_type,
        "subject_id": snapshot.subject_id,
        "report_schema_version": snapshot.report_schema_version,
        "package_version": snapshot.package_version,
        "json_report": snapshot.json_report,
        "markdown_report": snapshot.markdown_report,
        "manifest_json": snapshot.manifest_json,
        "normalized_series": [
            {
                "role": item.role,
                "series_id": item.series_id,
                "return_convention": item.return_convention,
                "sampling_json": item.sampling_json,
                "observations": [[o.timestamp, o.value] for o in item.observations],
            }
            for item in snapshot.normalized_series
        ],
    }
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _legacy_fingerprint(snapshot: AuditSnapshot) -> str:
    document = {
        "audit_type": snapshot.audit_type,
        "subject_id": snapshot.subject_id,
        "json_report": snapshot.json_report,
        "markdown_report": snapshot.markdown_report,
        "normalized_series": [
            {
                "role": item.role,
                "series_id": item.series_id,
                "return_convention": item.return_convention,
                "sampling_json": item.sampling_json,
                "observations": [[o.timestamp, o.value] for o in item.observations],
            }
            for item in snapshot.normalized_series
        ],
    }
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _matching_audit_id_statement(
    snapshot: AuditSnapshot,
    fingerprint: str,
    legacy_fingerprint: str,
) -> Any:
    legacy_match = (
        (audits.c.fingerprint == legacy_fingerprint)
        & (audits.c.report_schema_version == snapshot.report_schema_version)
        & (audits.c.package_version == snapshot.package_version)
        & (audits.c.manifest_json == snapshot.manifest_json)
    )
    return select(audits.c.audit_id).where(
        or_(audits.c.fingerprint == fingerprint, legacy_match)
    )


def _validate_snapshot(snapshot: AuditSnapshot) -> None:
    _required_text(snapshot.audit_type, "audit_type", maximum=40)
    _required_text(snapshot.subject_id, "subject_id", maximum=255)
    _required_text(snapshot.report_schema_version, "report_schema_version", maximum=20)
    _required_text(snapshot.package_version, "package_version", maximum=20)
    _required_text(snapshot.markdown_report, "markdown_report")

    report = _json_object(snapshot.json_report, "json_report")
    if report.get("schema_version") != snapshot.report_schema_version:
        raise ValueError("json_report schema_version must match report_schema_version.")
    report_manifest = report.get("run_manifest")
    if snapshot.manifest_json is None:
        if report_manifest is not None:
            raise ValueError("manifest_json must preserve the report run_manifest.")
    else:
        manifest = _json_object(snapshot.manifest_json, "manifest_json")
        if manifest != report_manifest:
            raise ValueError("manifest_json must preserve the report run_manifest.")

    identities: set[tuple[str, str]] = set()
    for item in snapshot.normalized_series:
        role = _required_text(item.role, "series role", maximum=40)
        series_id = _required_text(item.series_id, "series_id", maximum=255)
        identity = (role, series_id)
        if identity in identities:
            raise ValueError("normalized series role and series_id must be unique.")
        identities.add(identity)
        if item.return_convention not in {"simple", "log"}:
            raise ValueError("return_convention must be simple or log.")
        _json_object(item.sampling_json, "sampling_json")
        if not item.observations:
            raise ValueError("normalized series observations must not be empty.")
        timestamps: set[str] = set()
        for observation in item.observations:
            timestamp = _required_text(
                observation.timestamp, "observation timestamp", maximum=64
            )
            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(
                    "observation timestamp must be valid ISO 8601."
                ) from error
            if timestamp in timestamps:
                raise ValueError("observation timestamps must be unique per series.")
            timestamps.add(timestamp)
            if (
                isinstance(observation.value, bool)
                or not isinstance(observation.value, (int, float))
                or not math.isfinite(observation.value)
            ):
                raise ValueError("normalized observation values must be finite.")
            if item.return_convention == "simple" and observation.value < -1.0:
                raise ValueError("simple normalized returns cannot be less than -1.0.")


def _required_text(value: str, field_name: str, *, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{field_name} must not exceed {maximum} characters.")
    return value


def _json_object(raw: str, field_name: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError(f"{field_name} must be JSON text.")
    try:
        value = json.loads(raw, parse_constant=_reject_json_constant)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must contain valid JSON.") from error
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must contain a JSON object.")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value} is not supported.")


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
