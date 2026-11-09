"""Engine-neutral ports for canonical artifact bundle persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from backtest_auditor.implementation_risk.domain import CanonicalRunArtifacts
from backtest_auditor.implementation_risk.domain.engine_adapters import (
    EngineAdapterDescriptor,
    EngineMappingOutput,
    VerifiedEngineExport,
)


@runtime_checkable
class CanonicalArtifactBundleReader(Protocol):
    """Load one validated canonical bundle from an external representation."""

    def read(self, source: str | Path) -> CanonicalRunArtifacts:
        """Read a directory or archive without repairing invalid evidence."""


@runtime_checkable
class CanonicalArtifactBundleWriter(Protocol):
    """Persist one canonical bundle using a deterministic external contract."""

    def write(
        self,
        bundle: CanonicalRunArtifacts,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Write a directory or archive selected from the destination suffix."""


@runtime_checkable
class CanonicalArtifactBundleIdentity(Protocol):
    """Calculate the deterministic identity of a canonical output bundle."""

    def content_sha256(self, bundle: CanonicalRunArtifacts) -> str:
        """Return the canonical manifest identity without writing a file."""


@runtime_checkable
class EngineExportReader(Protocol):
    """Load and verify a common engine-export envelope plus its payloads."""

    def read(self, source: str | Path) -> VerifiedEngineExport:
        """Read a directory or ZIP without repairing provenance failures."""


@runtime_checkable
class EngineArtifactMapper(Protocol):
    """Map one verified engine export into canonical V1.5B artifacts."""

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        """Return the mapper's immutable version/capability declaration."""

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        """Normalize verified bytes without executing the source engine."""
