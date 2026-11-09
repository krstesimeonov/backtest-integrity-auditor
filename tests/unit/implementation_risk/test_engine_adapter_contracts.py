from __future__ import annotations

from dataclasses import replace

import pytest

from backtest_auditor.implementation_risk import (
    ENGINE_ADAPTER_ROADMAP,
    AdapterCapability,
    AdapterWarning,
    CapabilityAvailability,
    ComparisonLevel,
    EngineAdapterDescriptor,
    EngineAdapterResult,
    EngineExportEnvelope,
    EngineExportFile,
    EngineExportPayload,
    EngineMappingOutput,
    EvidenceOrigin,
    SupportedEngine,
    VerifiedEngineExport,
)


def test_engine_roadmap_order_is_frozen() -> None:
    assert ENGINE_ADAPTER_ROADMAP == (
        SupportedEngine.VECTORBT,
        SupportedEngine.BT,
        SupportedEngine.BACKTRADER,
        SupportedEngine.QUANTCONNECT_LEAN,
        SupportedEngine.NAUTILUSTRADER,
    )


@pytest.mark.parametrize(
    ("availability", "origin", "message"),
    [
        (
            CapabilityAvailability.UNSUPPORTED,
            EvidenceOrigin.ENGINE_EXPORT,
            "unsupported capabilities",
        ),
        (
            CapabilityAvailability.ALWAYS,
            EvidenceOrigin.NONE,
            "supported capabilities",
        ),
        (
            CapabilityAvailability.CONDITIONAL,
            EvidenceOrigin.NONE,
            "supported capabilities",
        ),
    ],
)
def test_capability_rejects_contradictory_origin(
    availability: CapabilityAvailability,
    origin: EvidenceOrigin,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        AdapterCapability(
            ComparisonLevel.RETURN,
            availability,
            origin,
            "explanation",
        )


def test_descriptor_exposes_capabilities_by_level(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
) -> None:
    assert len(vectorbt_adapter_descriptor.capabilities) == 11
    assert (
        vectorbt_adapter_descriptor.capability_for(ComparisonLevel.RETURN).availability
        is CapabilityAvailability.CONDITIONAL
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"adapter_id": "Bad ID"}, "adapter_id must start"),
        ({"adapter_version": " "}, "adapter_version must not be empty"),
        ({"engine": "unknown"}, "supported V1.5 engine"),
        ({"display_name": ""}, "display_name must not be empty"),
        ({"export_format_id": "UPPER"}, "export_format_id must start"),
        ({"supported_export_format_versions": ()}, "at least one version"),
        (
            {"supported_export_format_versions": ("2.0", "1.0")},
            "lexical canonical order",
        ),
        (
            {"supported_export_format_versions": ("1.0", "1.0")},
            "must not contain duplicates",
        ),
        ({"tested_engine_versions": ()}, "at least one version"),
        ({"allow_undisclosed_engine_version": 1}, "must be a boolean"),
        ({"allow_untested_engine_version": 1}, "must be a boolean"),
        ({"capabilities": ()}, "every comparison level"),
    ],
)
def test_descriptor_rejects_invalid_declarations(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(vectorbt_adapter_descriptor, **changes)


def test_descriptor_allows_empty_tested_versions_only_with_opt_in(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
) -> None:
    descriptor = replace(
        vectorbt_adapter_descriptor,
        tested_engine_versions=(),
        allow_untested_engine_version=True,
    )
    assert descriptor.tested_engine_versions == ()


def test_descriptor_rejects_wrong_capability_order_or_type(
    vectorbt_adapter_descriptor: EngineAdapterDescriptor,
) -> None:
    reversed_capabilities = tuple(reversed(vectorbt_adapter_descriptor.capabilities))
    with pytest.raises(ValueError, match="canonical comparison-level order"):
        replace(vectorbt_adapter_descriptor, capabilities=reversed_capabilities)
    with pytest.raises(ValueError, match="only AdapterCapability"):
        replace(
            vectorbt_adapter_descriptor,
            capabilities=("invalid",),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"path": "/absolute.csv"}, "canonical relative POSIX"),
        ({"path": "../escape.csv"}, "canonical relative POSIX"),
        ({"path": "nested\\file.csv"}, "must use '/'"),
        ({"path": "nested//file.csv"}, "canonical relative POSIX"),
        ({"role": "Bad Role"}, "role must start"),
        ({"media_type": ""}, "media_type must not be empty"),
        ({"size_bytes": -1}, "non-negative integer"),
        ({"size_bytes": True}, "non-negative integer"),
        ({"sha256": "bad"}, "64 hexadecimal"),
    ],
)
def test_export_file_rejects_invalid_metadata(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "path": "returns.csv",
        "role": "returns",
        "media_type": "text/csv",
        "size_bytes": 1,
        "sha256": "a" * 64,
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        EngineExportFile(**values)  # type: ignore[arg-type]


def test_verified_export_factory_sorts_payloads_and_calculates_hashes() -> None:
    export = VerifiedEngineExport.create(
        run_id=" run-1 ",
        engine=SupportedEngine.BT,
        engine_version=None,
        export_format_id="backtest-auditor.bt",
        export_format_version="1.0",
        declared_levels=(ComparisonLevel.RETURN, ComparisonLevel.EQUITY),
        payloads=(
            EngineExportPayload("z.csv", "returns", "text/csv", b"z"),
            EngineExportPayload("a.csv", "equity", "text/csv", b"a"),
        ),
    )
    assert export.envelope.run_id == "run-1"
    assert tuple(item.path for item in export.payloads) == ("a.csv", "z.csv")
    assert export.envelope.declared_levels == (
        ComparisonLevel.EQUITY,
        ComparisonLevel.RETURN,
    )
    assert len(export.envelope.source_sha256) == 64


def test_envelope_rejects_changed_identity_or_noncanonical_collections(
    verified_engine_export: VerifiedEngineExport,
) -> None:
    envelope = verified_engine_export.envelope
    with pytest.raises(ValueError, match="source_sha256 must match"):
        replace(envelope, source_sha256="0" * 64)
    with pytest.raises(ValueError, match="at least one export payload"):
        EngineExportEnvelope.create(
            run_id="run",
            engine=SupportedEngine.VECTORBT,
            engine_version="1",
            export_format_id="format",
            export_format_version="1.0",
            declared_levels=(),
            files=(),
        )
    duplicate_file = envelope.files[0]
    with pytest.raises(ValueError, match="duplicate paths"):
        EngineExportEnvelope.create(
            run_id=envelope.run_id,
            engine=envelope.engine,
            engine_version=envelope.engine_version,
            export_format_id=envelope.export_format_id,
            export_format_version=envelope.export_format_version,
            declared_levels=envelope.declared_levels,
            files=(duplicate_file, duplicate_file),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"path": "../bad.csv"}, "canonical relative POSIX"),
        ({"role": "Bad"}, "role must start"),
        ({"media_type": ""}, "media_type must not be empty"),
        ({"data": bytearray(b"x")}, "immutable bytes"),
    ],
)
def test_export_payload_rejects_invalid_values(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "path": "returns.csv",
        "role": "returns",
        "media_type": "text/csv",
        "data": b"x",
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        EngineExportPayload(**values)  # type: ignore[arg-type]


def test_verified_export_rejects_missing_changed_or_unordered_payloads(
    verified_engine_export: VerifiedEngineExport,
) -> None:
    envelope = verified_engine_export.envelope
    with pytest.raises(ValueError, match="exactly match"):
        VerifiedEngineExport(envelope, ())
    changed = replace(verified_engine_export.payloads[0], data=b"changed")
    with pytest.raises(ValueError, match="exactly match"):
        VerifiedEngineExport(envelope, (changed,))
    second = EngineExportPayload("a.csv", "other", "text/csv", b"a")
    two_file_export = VerifiedEngineExport.create(
        run_id="run",
        engine=SupportedEngine.VECTORBT,
        engine_version="1",
        export_format_id="format",
        export_format_version="1.0",
        declared_levels=(),
        payloads=(verified_engine_export.payloads[0], second),
    )
    with pytest.raises(ValueError, match="canonical path order"):
        VerifiedEngineExport(
            two_file_export.envelope,
            tuple(reversed(two_file_export.payloads)),
        )


def test_verified_export_payload_accessors(
    verified_engine_export: VerifiedEngineExport,
) -> None:
    assert verified_engine_export.payload("returns.csv").role == "returns"
    assert verified_engine_export.payloads_for_role("returns") == (
        verified_engine_export.payloads[0],
    )
    assert verified_engine_export.payloads_for_role("missing") == ()
    with pytest.raises(KeyError, match="no payload"):
        verified_engine_export.payload("missing.csv")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"code": "Bad Code"}, "code must start"),
        ({"message": ""}, "message must not be empty"),
        ({"file_path": "../bad.csv"}, "canonical relative POSIX"),
        ({"row_number": 0}, "positive integer"),
        ({"row_number": True}, "positive integer"),
        ({"field": ""}, "field must not be empty"),
    ],
)
def test_adapter_warning_rejects_invalid_context(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {"code": "mapping.warning", "message": "warning"}
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        AdapterWarning(**values)  # type: ignore[arg-type]


def test_mapping_output_requires_canonical_unique_warnings(
    vectorbt_return_artifacts,
) -> None:
    first = AdapterWarning("a.warning", "A")
    second = AdapterWarning("b.warning", "B")
    assert EngineMappingOutput(vectorbt_return_artifacts, (first, second)).warnings
    with pytest.raises(ValueError, match="canonical order"):
        EngineMappingOutput(vectorbt_return_artifacts, (second, first))
    with pytest.raises(ValueError, match="duplicates"):
        EngineMappingOutput(vectorbt_return_artifacts, (first, first))
    with pytest.raises(ValueError, match="CanonicalRunArtifacts"):
        EngineMappingOutput("bad")  # type: ignore[arg-type]


def test_adapter_result_normalizes_digest_and_validates_warnings(
    vectorbt_adapter_descriptor,
    verified_engine_export,
    vectorbt_return_artifacts,
) -> None:
    warning = AdapterWarning("mapping.warning", "Retained warning")
    result = EngineAdapterResult(
        descriptor=vectorbt_adapter_descriptor,
        export=verified_engine_export.envelope,
        artifacts=vectorbt_return_artifacts,
        canonical_bundle_sha256="A" * 64,
        warnings=(warning,),
    )
    assert result.canonical_bundle_sha256 == "a" * 64
    with pytest.raises(ValueError, match="64 hexadecimal"):
        replace(result, canonical_bundle_sha256="bad")
