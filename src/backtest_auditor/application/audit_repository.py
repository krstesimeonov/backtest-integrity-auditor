"""Persistence contracts kept independent from any database framework."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    timestamp: str
    value: float


@dataclass(frozen=True, slots=True)
class NormalizedSeriesSnapshot:
    role: str
    series_id: str
    return_convention: str
    sampling_json: str
    observations: tuple[NormalizedObservation, ...]


@dataclass(frozen=True, slots=True)
class AuditSnapshot:
    audit_type: str
    subject_id: str
    report_schema_version: str
    package_version: str
    json_report: str
    markdown_report: str
    manifest_json: str | None
    normalized_series: tuple[NormalizedSeriesSnapshot, ...]


@dataclass(frozen=True, slots=True)
class StoredAuditSummary:
    audit_id: str
    audit_type: str
    subject_id: str
    created_at: str
    report_schema_version: str
    package_version: str
    series_count: int
    observation_count: int


@dataclass(frozen=True, slots=True)
class StoredAudit:
    summary: StoredAuditSummary
    json_report: str
    markdown_report: str
    manifest_json: str | None
    normalized_series: tuple[NormalizedSeriesSnapshot, ...]


@dataclass(frozen=True, slots=True)
class SaveAuditResult:
    audit_id: str
    created: bool


class AuditRepository(Protocol):
    def save(self, snapshot: AuditSnapshot) -> SaveAuditResult: ...

    def list(
        self, *, limit: int = 100, offset: int = 0
    ) -> tuple[StoredAuditSummary, ...]: ...

    def get(self, audit_id: str) -> StoredAudit | None: ...

    def close(self) -> None: ...
