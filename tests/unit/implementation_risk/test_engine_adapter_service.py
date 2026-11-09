from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import backtest_auditor.implementation_risk.application.engine_adapter_service as service_module
from backtest_auditor.implementation_risk import (
    AdapterCapability,
    AdapterWarning,
    CanonicalArtifactBundleIdentity,
    CanonicalArtifactFileBundleAdapter,
    CanonicalRunArtifacts,
    CapabilityAvailability,
    ComparisonLevel,
    EngineAdapterDescriptor,
    EngineAdapterError,
    EngineAdapterErrorCode,
    EngineAdapterRegistry,
    EngineAdapterResult,
    EngineAdapterService,
    EngineArtifactMapper,
    EngineExportFileBundleAdapter,
    EngineMappingOutput,
    EvidenceOrigin,
    SupportedEngine,
    VerifiedEngineExport,
)


class FakeMapper:
    def __init__(
        self,
        descriptor: EngineAdapterDescriptor,
        output: object,
        error: Exception | None = None,
    ) -> None:
        self._descriptor = descriptor
        self.output = output
        self.error = error
        self.calls: list[VerifiedEngineExport] = []

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        return self._descriptor

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        self.calls.append(export)
        if self.error is not None:
            raise self.error
        return self.output  # type: ignore[return-value]


def _service(
    mapper: FakeMapper,
    *,
    identity: object | None = None,
) -> EngineAdapterService:
    return EngineAdapterService(
        export_reader=EngineExportFileBundleAdapter(),
        registry=EngineAdapterRegistry((mapper,)),
        canonical_identity=identity or CanonicalArtifactFileBundleAdapter(),  # type: ignore[arg-type]
    )


def test_registry_is_deterministic_and_implements_mapper_protocol(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    vectorbt = FakeMapper(
        vectorbt_adapter_descriptor,
        EngineMappingOutput(vectorbt_return_artifacts),
    )
    backtrader_descriptor = replace(
        vectorbt_adapter_descriptor,
        adapter_id="backtest-auditor.backtrader",
        engine=SupportedEngine.BACKTRADER,
        display_name="Backtrader",
        export_format_id="backtest-auditor.backtrader",
    )
    backtrader = FakeMapper(
        backtrader_descriptor,
        EngineMappingOutput(vectorbt_return_artifacts),
    )
    registry = EngineAdapterRegistry((backtrader, vectorbt))

    assert isinstance(vectorbt, EngineArtifactMapper)
    assert tuple(item.engine for item in registry.descriptors) == (
        SupportedEngine.VECTORBT,
        SupportedEngine.BACKTRADER,
    )
    assert (
        registry.resolve(
            SupportedEngine.VECTORBT,
            "backtest-auditor.vectorbt",
        )
        is vectorbt
    )


def test_registry_rejects_duplicate_ids_and_routes(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    output = EngineMappingOutput(vectorbt_return_artifacts)
    first = FakeMapper(vectorbt_adapter_descriptor, output)
    same = FakeMapper(vectorbt_adapter_descriptor, output)
    with pytest.raises(EngineAdapterError) as captured:
        EngineAdapterRegistry((first, same))
    assert captured.value.code is EngineAdapterErrorCode.DUPLICATE_ADAPTER

    different_id = FakeMapper(
        replace(vectorbt_adapter_descriptor, adapter_id="another.vectorbt"),
        output,
    )
    with pytest.raises(EngineAdapterError) as captured:
        EngineAdapterRegistry((first, different_id))
    assert captured.value.code is EngineAdapterErrorCode.DUPLICATE_ADAPTER


def test_registry_rejects_invalid_iterable_or_mapper() -> None:
    with pytest.raises(EngineAdapterError) as captured:
        EngineAdapterRegistry(None)  # type: ignore[arg-type]
    assert captured.value.code is EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION
    with pytest.raises(EngineAdapterError) as captured:
        EngineAdapterRegistry((object(),))  # type: ignore[arg-type]
    assert captured.value.code is EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION


def test_registry_reports_missing_adapter(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    mapper = FakeMapper(
        vectorbt_adapter_descriptor,
        EngineMappingOutput(vectorbt_return_artifacts),
    )
    registry = EngineAdapterRegistry((mapper,))
    with pytest.raises(EngineAdapterError) as captured:
        registry.resolve(SupportedEngine.BT, "backtest-auditor.bt")
    assert captured.value.code is EngineAdapterErrorCode.ADAPTER_NOT_FOUND
    assert captured.value.engine is SupportedEngine.BT


def test_service_happy_path_validates_and_hashes_canonical_output(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    warning = AdapterWarning(
        "vectorbt.return_precision",
        "Source values were serialized as decimal text.",
        file_path="returns.csv",
    )
    mapper = FakeMapper(
        vectorbt_adapter_descriptor,
        EngineMappingOutput(vectorbt_return_artifacts, (warning,)),
    )
    source = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / "source.zip",
    )

    result = _service(mapper).adapt(source)

    assert isinstance(result, EngineAdapterResult)
    assert result.artifacts == vectorbt_return_artifacts
    assert result.export == verified_engine_export.envelope
    assert result.warnings == (warning,)
    assert len(result.canonical_bundle_sha256) == 64
    assert mapper.calls == [verified_engine_export]


@pytest.mark.parametrize(
    ("descriptor_changes", "export_changes", "code"),
    [
        (
            {},
            {"export_format_version": "9.0"},
            EngineAdapterErrorCode.UNSUPPORTED_EXPORT_FORMAT_VERSION,
        ),
        (
            {},
            {"engine_version": None},
            EngineAdapterErrorCode.ENGINE_VERSION_UNDISCLOSED,
        ),
        (
            {},
            {"engine_version": "0.99.0"},
            EngineAdapterErrorCode.UNTESTED_ENGINE_VERSION,
        ),
    ],
)
def test_descriptor_export_version_contracts_fail_closed(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    verified_engine_export: VerifiedEngineExport,
    descriptor_changes: dict[str, object],
    export_changes: dict[str, object],
    code: EngineAdapterErrorCode,
) -> None:
    descriptor = replace(vectorbt_adapter_descriptor, **descriptor_changes)
    envelope = verified_engine_export.envelope
    changed = verified_engine_export.create(
        run_id=envelope.run_id,
        engine=envelope.engine,
        engine_version=export_changes.get("engine_version", envelope.engine_version),
        export_format_id=envelope.export_format_id,
        export_format_version=export_changes.get(
            "export_format_version", envelope.export_format_version
        ),
        declared_levels=envelope.declared_levels,
        payloads=verified_engine_export.payloads,
    )
    with pytest.raises(EngineAdapterError) as captured:
        service_module._validate_descriptor_export(descriptor, changed)
    assert captured.value.code is code


def test_descriptor_can_explicitly_accept_missing_or_untested_engine_versions(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    descriptor = replace(
        vectorbt_adapter_descriptor,
        allow_undisclosed_engine_version=True,
        allow_untested_engine_version=True,
    )
    for version in (None, "future-version"):
        export = VerifiedEngineExport.create(
            run_id="run",
            engine=SupportedEngine.VECTORBT,
            engine_version=version,
            export_format_id="backtest-auditor.vectorbt",
            export_format_version="1.0",
            declared_levels=(ComparisonLevel.RETURN,),
            payloads=verified_engine_export.payloads,
        )
        service_module._validate_descriptor_export(descriptor, export)


def test_descriptor_rejects_engine_format_and_capability_mismatches(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    verified_engine_export: VerifiedEngineExport,
) -> None:
    with pytest.raises(EngineAdapterError) as captured:
        service_module._validate_descriptor_export(
            replace(vectorbt_adapter_descriptor, engine=SupportedEngine.BT),
            verified_engine_export,
        )
    assert captured.value.code is EngineAdapterErrorCode.ENGINE_MISMATCH

    with pytest.raises(EngineAdapterError) as captured:
        service_module._validate_descriptor_export(
            replace(vectorbt_adapter_descriptor, export_format_id="another.format"),
            verified_engine_export,
        )
    assert captured.value.code is EngineAdapterErrorCode.EXPORT_FORMAT_MISMATCH

    unsupported = tuple(
        AdapterCapability(
            level=item.level,
            availability=CapabilityAvailability.UNSUPPORTED,
            origin=EvidenceOrigin.NONE,
            explanation="Unsupported for this test.",
        )
        for item in vectorbt_adapter_descriptor.capabilities
    )
    with pytest.raises(EngineAdapterError) as captured:
        service_module._validate_descriptor_export(
            replace(vectorbt_adapter_descriptor, capabilities=unsupported),
            verified_engine_export,
        )
    assert captured.value.code is EngineAdapterErrorCode.CAPABILITY_CONTRACT_VIOLATION


@pytest.mark.parametrize(
    "run_changes",
    [
        {"run_id": "wrong"},
        {"engine_name": "bt"},
        {"engine_version": "wrong"},
        {"source_sha256": "0" * 64},
    ],
)
def test_service_rejects_canonical_run_identity_mismatch(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
    run_changes: dict[str, object],
) -> None:
    bad_run = replace(vectorbt_return_artifacts.run, **run_changes)
    artifacts = replace(vectorbt_return_artifacts, run=bad_run)
    mapper = FakeMapper(
        vectorbt_adapter_descriptor,
        EngineMappingOutput(artifacts),
    )
    source = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / str(abs(hash(tuple(run_changes)))),
    )
    with pytest.raises(EngineAdapterError) as captured:
        _service(mapper).adapt(source)
    assert captured.value.code is EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION


def test_service_rejects_declared_and_actual_level_mismatch(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    artifacts = CanonicalRunArtifacts(run=vectorbt_return_artifacts.run)
    mapper = FakeMapper(vectorbt_adapter_descriptor, EngineMappingOutput(artifacts))
    source = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / "source",
    )
    with pytest.raises(EngineAdapterError) as captured:
        _service(mapper).adapt(source)
    assert captured.value.code is EngineAdapterErrorCode.CAPABILITY_CONTRACT_VIOLATION


def test_service_enforces_always_capability(
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    capabilities = tuple(
        replace(
            item,
            availability=(
                CapabilityAvailability.ALWAYS
                if item.level is ComparisonLevel.EQUITY
                else item.availability
            ),
            origin=(
                EvidenceOrigin.ENGINE_EXPORT
                if item.level is ComparisonLevel.EQUITY
                else item.origin
            ),
        )
        for item in vectorbt_adapter_descriptor.capabilities
    )
    descriptor = replace(vectorbt_adapter_descriptor, capabilities=capabilities)
    with pytest.raises(EngineAdapterError) as captured:
        service_module._validate_mapping_output(
            descriptor,
            verified_engine_export,
            EngineMappingOutput(vectorbt_return_artifacts),
        )
    assert captured.value.code is EngineAdapterErrorCode.CAPABILITY_CONTRACT_VIOLATION


def test_service_rejects_warning_reference_outside_verified_export(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    warning = AdapterWarning("vectorbt.warning", "warning", "missing.csv")
    mapper = FakeMapper(
        vectorbt_adapter_descriptor,
        EngineMappingOutput(vectorbt_return_artifacts, (warning,)),
    )
    source = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / "source",
    )
    with pytest.raises(EngineAdapterError) as captured:
        _service(mapper).adapt(source)
    assert captured.value.code is EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION


@pytest.mark.parametrize(
    ("output", "error", "code"),
    [
        (object(), None, EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION),
        (None, RuntimeError("boom"), EngineAdapterErrorCode.MAPPING_FAILED),
    ],
)
def test_service_converts_invalid_mapper_behavior_to_typed_failure(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    output: object,
    error: Exception | None,
    code: EngineAdapterErrorCode,
) -> None:
    mapper = FakeMapper(vectorbt_adapter_descriptor, output, error)
    source = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / code.value,
    )
    with pytest.raises(EngineAdapterError) as captured:
        _service(mapper).adapt(source)
    assert captured.value.code is code


def test_service_preserves_typed_engine_specific_failure(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
) -> None:
    expected = EngineAdapterError(
        EngineAdapterErrorCode.MAPPING_FAILED,
        "missing vectorbt column",
        engine=SupportedEngine.VECTORBT,
        engine_error_code="vectorbt.missing_column",
        file_path="returns.csv",
        field="return",
    )
    mapper = FakeMapper(vectorbt_adapter_descriptor, None, expected)
    source = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / "source",
    )
    with pytest.raises(EngineAdapterError) as captured:
        _service(mapper).adapt(source)
    assert captured.value is expected


class BadIdentity:
    def content_sha256(self, bundle: CanonicalRunArtifacts) -> str:
        raise ValueError("cannot hash")


def test_service_rejects_canonical_identity_failure(
    tmp_path: Path,
    verified_engine_export: VerifiedEngineExport,
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    vectorbt_return_artifacts: CanonicalRunArtifacts,
) -> None:
    mapper = FakeMapper(
        vectorbt_adapter_descriptor,
        EngineMappingOutput(vectorbt_return_artifacts),
    )
    source = EngineExportFileBundleAdapter().write(
        verified_engine_export,
        tmp_path / "source",
    )
    assert isinstance(BadIdentity(), CanonicalArtifactBundleIdentity)
    with pytest.raises(EngineAdapterError) as captured:
        _service(mapper, identity=BadIdentity()).adapt(source)
    assert captured.value.code is EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION


def test_service_constructor_requires_all_ports() -> None:
    registry = EngineAdapterRegistry()
    identity = CanonicalArtifactFileBundleAdapter()
    reader = EngineExportFileBundleAdapter()
    with pytest.raises(ValueError, match="export_reader"):
        EngineAdapterService(
            export_reader=object(),  # type: ignore[arg-type]
            registry=registry,
            canonical_identity=identity,
        )
    with pytest.raises(ValueError, match="registry"):
        EngineAdapterService(
            export_reader=reader,
            registry=object(),  # type: ignore[arg-type]
            canonical_identity=identity,
        )
    with pytest.raises(ValueError, match="canonical_identity"):
        EngineAdapterService(
            export_reader=reader,
            registry=registry,
            canonical_identity=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"message": ""},
        {"engine": "unknown"},
        {"row_number": 0},
        {"adapter_id": ""},
    ],
)
def test_engine_adapter_error_validates_context(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "code": EngineAdapterErrorCode.MAPPING_FAILED,
        "message": "failed",
    }
    values.update(changes)
    with pytest.raises(ValueError):
        EngineAdapterError(**values)  # type: ignore[arg-type]
