import re
from dataclasses import dataclass
from datetime import datetime, timezone


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AuditRunSpec:
    """Explicit non-derived identity required for a deterministic run manifest."""

    audit_id: str
    audit_timestamp: datetime
    git_commit: str

    def __post_init__(self) -> None:
        audit_id = _required_text(self.audit_id, "audit_id")
        git_commit = _required_text(self.git_commit, "git_commit")
        timestamp = self.audit_timestamp
        if not isinstance(timestamp, datetime):
            raise ValueError("audit_timestamp must be a datetime.")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("audit_timestamp must include a timezone offset.")
        timestamp = timestamp.astimezone(timezone.utc)
        object.__setattr__(self, "audit_id", audit_id)
        object.__setattr__(self, "audit_timestamp", timestamp)
        object.__setattr__(self, "git_commit", git_commit)


@dataclass(frozen=True, slots=True)
class InputArtifactHash:
    role: str
    file_name: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        role = _required_text(self.role, "role")
        file_name = _required_text(self.file_name, "file_name")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative integer.")
        sha256 = self.sha256.strip().lower()
        if _SHA256_PATTERN.fullmatch(sha256) is None:
            raise ValueError("sha256 must contain 64 lowercase hexadecimal characters.")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "file_name", file_name)
        object.__setattr__(self, "sha256", sha256)


@dataclass(frozen=True, slots=True)
class DependencyVersion:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class MethodVersion:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class ManifestWarning:
    source: str
    code: str


@dataclass(frozen=True, slots=True)
class AuditRunManifestResult:
    manifest_schema_version: str
    audit_id: str
    audit_timestamp_utc: str
    audit_type: str
    subject_id: str
    package_version: str
    report_schema_version: str
    git_commit: str
    input_artifacts: tuple[InputArtifactHash, ...]
    normalized_data_encoding: str
    normalized_data_sha256: str
    configuration_json: str
    configuration_sha256: str
    random_seeds: tuple[tuple[str, int], ...]
    method_versions: tuple[MethodVersion, ...]
    warnings: tuple[ManifestWarning, ...]
    python_implementation: str
    python_version: str
    platform_system: str
    platform_machine: str
    dependencies: tuple[DependencyVersion, ...]
    manifest_sha256: str


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized
