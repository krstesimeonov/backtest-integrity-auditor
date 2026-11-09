"""Registry and fail-closed orchestration for engine-export normalization."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from backtest_auditor.implementation_risk.application.errors import (
    EngineAdapterError,
    EngineAdapterErrorCode,
)
from backtest_auditor.implementation_risk.application.ports import (
    CanonicalArtifactBundleIdentity,
    EngineArtifactMapper,
    EngineExportReader,
)
from backtest_auditor.implementation_risk.domain.engine_adapters import (
    ENGINE_ADAPTER_ROADMAP,
    CapabilityAvailability,
    EngineAdapterDescriptor,
    EngineAdapterResult,
    EngineMappingOutput,
    SupportedEngine,
    VerifiedEngineExport,
)


_ENGINE_ORDER = {engine: index for index, engine in enumerate(SupportedEngine)}


class EngineAdapterRegistry:
    """Deterministic registry keyed by engine and export-format identity."""

    def __init__(self, adapters: Iterable[EngineArtifactMapper] = ()) -> None:
        try:
            supplied = tuple(adapters)
        except TypeError as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                "adapters must be an iterable.",
            ) from error
        normalized: list[EngineArtifactMapper] = []
        adapter_ids: set[str] = set()
        routing_keys: set[tuple[SupportedEngine, str]] = set()
        for adapter in supplied:
            if not isinstance(adapter, EngineArtifactMapper):
                raise EngineAdapterError(
                    EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                    "registry values must implement EngineArtifactMapper.",
                )
            descriptor = adapter.descriptor
            if not isinstance(descriptor, EngineAdapterDescriptor):
                raise EngineAdapterError(
                    EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                    "mapper descriptor must be an EngineAdapterDescriptor.",
                )
            routing_key = (descriptor.engine, descriptor.export_format_id)
            if descriptor.adapter_id in adapter_ids or routing_key in routing_keys:
                raise EngineAdapterError(
                    EngineAdapterErrorCode.DUPLICATE_ADAPTER,
                    "adapter_id and engine/export-format routes must be unique.",
                    engine=descriptor.engine,
                    adapter_id=descriptor.adapter_id,
                )
            adapter_ids.add(descriptor.adapter_id)
            routing_keys.add(routing_key)
            normalized.append(adapter)
        self._adapters = tuple(
            sorted(
                normalized,
                key=lambda item: (
                    _ENGINE_ORDER[item.descriptor.engine],
                    item.descriptor.export_format_id,
                    item.descriptor.adapter_id,
                ),
            )
        )
        self._by_route = {
            (item.descriptor.engine, item.descriptor.export_format_id): item
            for item in self._adapters
        }

    @property
    def descriptors(self) -> tuple[EngineAdapterDescriptor, ...]:
        return tuple(item.descriptor for item in self._adapters)

    def assert_complete_roadmap(self) -> None:
        """Fail unless one fail-closed adapter covers every accepted engine."""

        descriptors = self.descriptors
        engines = tuple(item.engine for item in descriptors)
        if engines != ENGINE_ADAPTER_ROADMAP or len(set(engines)) != len(engines):
            raise EngineAdapterError(
                EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                "registry must contain exactly one adapter for every roadmap engine.",
            )
        for descriptor in descriptors:
            if (
                descriptor.allow_undisclosed_engine_version
                or descriptor.allow_untested_engine_version
                or len(descriptor.tested_engine_versions) != 1
            ):
                raise EngineAdapterError(
                    EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                    "complete registry adapters must require one exact engine version.",
                    engine=descriptor.engine,
                    adapter_id=descriptor.adapter_id,
                )
            prefix = "backtest-auditor."
            if not descriptor.adapter_id.startswith(prefix) or not (
                descriptor.export_format_id.startswith(prefix)
            ):
                raise EngineAdapterError(
                    EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                    "complete registry adapter and format IDs must use the project namespace.",
                    engine=descriptor.engine,
                    adapter_id=descriptor.adapter_id,
                )

    def resolve(
        self,
        engine: SupportedEngine,
        export_format_id: str,
    ) -> EngineArtifactMapper:
        try:
            normalized_engine = SupportedEngine(engine)
        except (TypeError, ValueError) as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.ADAPTER_NOT_FOUND,
                "engine is outside the accepted V1.5 adapter roadmap.",
            ) from error
        mapper = self._by_route.get((normalized_engine, export_format_id))
        if mapper is None:
            raise EngineAdapterError(
                EngineAdapterErrorCode.ADAPTER_NOT_FOUND,
                "no adapter is registered for the engine/export-format pair.",
                engine=normalized_engine,
            )
        return mapper


def _validate_descriptor_export(
    descriptor: EngineAdapterDescriptor,
    export: VerifiedEngineExport,
) -> None:
    envelope = export.envelope
    if envelope.engine is not descriptor.engine:
        raise EngineAdapterError(
            EngineAdapterErrorCode.ENGINE_MISMATCH,
            "envelope engine does not match the selected adapter.",
            engine=envelope.engine,
            adapter_id=descriptor.adapter_id,
        )
    if envelope.export_format_id != descriptor.export_format_id:
        raise EngineAdapterError(
            EngineAdapterErrorCode.EXPORT_FORMAT_MISMATCH,
            "envelope export format does not match the selected adapter.",
            engine=envelope.engine,
            adapter_id=descriptor.adapter_id,
        )
    if (
        envelope.export_format_version
        not in descriptor.supported_export_format_versions
    ):
        raise EngineAdapterError(
            EngineAdapterErrorCode.UNSUPPORTED_EXPORT_FORMAT_VERSION,
            "envelope export-format version is not supported by this adapter.",
            engine=envelope.engine,
            adapter_id=descriptor.adapter_id,
        )
    if envelope.engine_version is None:
        if not descriptor.allow_undisclosed_engine_version:
            raise EngineAdapterError(
                EngineAdapterErrorCode.ENGINE_VERSION_UNDISCLOSED,
                "engine version is required by this adapter.",
                engine=envelope.engine,
                adapter_id=descriptor.adapter_id,
            )
    elif (
        envelope.engine_version not in descriptor.tested_engine_versions
        and not descriptor.allow_untested_engine_version
    ):
        raise EngineAdapterError(
            EngineAdapterErrorCode.UNTESTED_ENGINE_VERSION,
            "engine version is outside this adapter's exact tested set.",
            engine=envelope.engine,
            adapter_id=descriptor.adapter_id,
        )
    for level in envelope.declared_levels:
        capability = descriptor.capability_for(level)
        if capability.availability is CapabilityAvailability.UNSUPPORTED:
            raise EngineAdapterError(
                EngineAdapterErrorCode.CAPABILITY_CONTRACT_VIOLATION,
                f"export declares unsupported evidence level {level.value!r}.",
                engine=envelope.engine,
                adapter_id=descriptor.adapter_id,
            )


def _validate_mapping_output(
    descriptor: EngineAdapterDescriptor,
    export: VerifiedEngineExport,
    output: EngineMappingOutput,
) -> None:
    envelope = export.envelope
    artifacts = output.artifacts
    expected_run = (
        envelope.run_id,
        envelope.engine.value,
        envelope.engine_version,
        envelope.source_sha256,
    )
    actual_run = (
        artifacts.run.run_id,
        artifacts.run.engine_name,
        artifacts.run.engine_version,
        artifacts.run.source_sha256,
    )
    if actual_run != expected_run:
        raise EngineAdapterError(
            EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
            "canonical run identity must exactly match the verified export.",
            engine=envelope.engine,
            adapter_id=descriptor.adapter_id,
        )
    if artifacts.available_levels != envelope.declared_levels:
        raise EngineAdapterError(
            EngineAdapterErrorCode.CAPABILITY_CONTRACT_VIOLATION,
            "canonical available levels must exactly match declared export levels.",
            engine=envelope.engine,
            adapter_id=descriptor.adapter_id,
        )
    available = set(artifacts.available_levels)
    for capability in descriptor.capabilities:
        if (
            capability.availability is CapabilityAvailability.ALWAYS
            and capability.level not in available
        ):
            raise EngineAdapterError(
                EngineAdapterErrorCode.CAPABILITY_CONTRACT_VIOLATION,
                f"adapter omitted always-available level {capability.level.value!r}.",
                engine=envelope.engine,
                adapter_id=descriptor.adapter_id,
            )
        if (
            capability.availability is CapabilityAvailability.UNSUPPORTED
            and capability.level in available
        ):
            raise EngineAdapterError(
                EngineAdapterErrorCode.CAPABILITY_CONTRACT_VIOLATION,
                f"adapter emitted unsupported level {capability.level.value!r}.",
                engine=envelope.engine,
                adapter_id=descriptor.adapter_id,
            )
    payload_paths = {item.path for item in export.payloads}
    for warning in output.warnings:
        if warning.file_path is not None and warning.file_path not in payload_paths:
            raise EngineAdapterError(
                EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                "warning file_path must reference a verified export payload.",
                engine=envelope.engine,
                adapter_id=descriptor.adapter_id,
            )


class EngineAdapterService:
    """Verify, resolve, map, and revalidate one engine export."""

    def __init__(
        self,
        *,
        export_reader: EngineExportReader,
        registry: EngineAdapterRegistry,
        canonical_identity: CanonicalArtifactBundleIdentity,
    ) -> None:
        if not isinstance(export_reader, EngineExportReader):
            raise ValueError("export_reader must implement EngineExportReader.")
        if not isinstance(registry, EngineAdapterRegistry):
            raise ValueError("registry must be an EngineAdapterRegistry.")
        if not isinstance(canonical_identity, CanonicalArtifactBundleIdentity):
            raise ValueError(
                "canonical_identity must implement CanonicalArtifactBundleIdentity."
            )
        self._export_reader = export_reader
        self._registry = registry
        self._canonical_identity = canonical_identity

    def adapt(self, source: str | Path) -> EngineAdapterResult:
        export = self._export_reader.read(source)
        if not isinstance(export, VerifiedEngineExport):
            raise EngineAdapterError(
                EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                "export reader returned an invalid object.",
            )
        mapper = self._registry.resolve(
            export.envelope.engine,
            export.envelope.export_format_id,
        )
        descriptor = mapper.descriptor
        _validate_descriptor_export(descriptor, export)
        try:
            output = mapper.map(export)
        except EngineAdapterError:
            raise
        except Exception as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.MAPPING_FAILED,
                "engine mapper failed without a typed adapter error.",
                engine=export.envelope.engine,
                adapter_id=descriptor.adapter_id,
            ) from error
        if not isinstance(output, EngineMappingOutput):
            raise EngineAdapterError(
                EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                "engine mapper must return EngineMappingOutput.",
                engine=export.envelope.engine,
                adapter_id=descriptor.adapter_id,
            )
        _validate_mapping_output(descriptor, export, output)
        try:
            canonical_sha256 = self._canonical_identity.content_sha256(output.artifacts)
        except (TypeError, ValueError) as error:
            raise EngineAdapterError(
                EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION,
                "canonical output could not be assigned a deterministic identity.",
                engine=export.envelope.engine,
                adapter_id=descriptor.adapter_id,
            ) from error
        return EngineAdapterResult(
            descriptor=descriptor,
            export=export.envelope,
            artifacts=output.artifacts,
            canonical_bundle_sha256=canonical_sha256,
            warnings=output.warnings,
        )
