from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from backtest_auditor.implementation_risk import (
    ENGINE_ADAPTER_ROADMAP,
    BacktraderArtifactMapper,
    BtArtifactMapper,
    ComparisonLevel,
    EngineAdapterError,
    EngineAdapterErrorCode,
    EngineAdapterRegistry,
    EngineMappingOutput,
    NautilusTraderArtifactMapper,
    QuantConnectLeanArtifactMapper,
    VectorbtArtifactMapper,
    VerifiedEngineExport,
    build_v1_5d2_registry,
    build_v1_5d3_registry,
    build_v1_5d3_service,
)
from backtest_auditor.implementation_risk.adapters.vectorbt import (
    VECTORBT_DESCRIPTOR,
)
from backtest_auditor.implementation_risk.domain import EngineAdapterDescriptor


class DescriptorOverride:
    def __init__(
        self,
        mapper: VectorbtArtifactMapper,
        descriptor: EngineAdapterDescriptor,
    ) -> None:
        self._mapper = mapper
        self._descriptor = descriptor

    @property
    def descriptor(self) -> EngineAdapterDescriptor:
        return self._descriptor

    def map(self, export: VerifiedEngineExport) -> EngineMappingOutput:
        return self._mapper.map(export)


def _registry_with_vectorbt_descriptor(
    descriptor: EngineAdapterDescriptor,
) -> EngineAdapterRegistry:
    return EngineAdapterRegistry(
        (
            DescriptorOverride(VectorbtArtifactMapper(), descriptor),
            BtArtifactMapper(),
            BacktraderArtifactMapper(),
            QuantConnectLeanArtifactMapper(),
            NautilusTraderArtifactMapper(),
        )
    )


def test_complete_registry_descriptor_matrix_and_committed_examples() -> None:
    registry = build_v1_5d3_registry()
    assert tuple(item.engine for item in registry.descriptors) == ENGINE_ADAPTER_ROADMAP
    for descriptor in registry.descriptors:
        assert tuple(item.level for item in descriptor.capabilities) == tuple(
            ComparisonLevel
        )
        assert len(descriptor.tested_engine_versions) == 1
        assert not descriptor.allow_undisclosed_engine_version
        assert not descriptor.allow_untested_engine_version

    service = build_v1_5d3_service()
    digests = []
    for engine in ("quantconnect_lean", "nautilustrader"):
        source = Path("examples/v1_5d3_engine_exports", engine)
        first = service.adapt(source)
        second = service.adapt(source)
        assert first == second
        digests.append(first.canonical_bundle_sha256)
    assert len(set(digests)) == 2


def test_complete_registry_hardening_rejects_incomplete_permissive_or_foreign() -> None:
    with pytest.raises(EngineAdapterError) as captured:
        build_v1_5d2_registry().assert_complete_roadmap()
    assert captured.value.code is EngineAdapterErrorCode.OUTPUT_CONTRACT_VIOLATION

    permissive = replace(
        VECTORBT_DESCRIPTOR,
        allow_untested_engine_version=True,
    )
    with pytest.raises(EngineAdapterError, match="one exact engine version"):
        _registry_with_vectorbt_descriptor(permissive).assert_complete_roadmap()

    foreign = replace(VECTORBT_DESCRIPTOR, adapter_id="foreign.vectorbt")
    with pytest.raises(EngineAdapterError, match="project namespace"):
        _registry_with_vectorbt_descriptor(foreign).assert_complete_roadmap()


def test_base_import_and_complete_mapping_do_not_import_engine_sdks() -> None:
    code = """
import sys

blocked = {'vectorbt', 'bt', 'backtrader', 'nautilus_trader', 'QuantConnect'}
class BlockEngines:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise RuntimeError(f'engine SDK import attempted: {fullname}')
        return None

sys.meta_path.insert(0, BlockEngines())
from backtest_auditor.implementation_risk import build_v1_5d3_service
service = build_v1_5d3_service()
for engine in ('quantconnect_lean', 'nautilustrader'):
    result = service.adapt(f'examples/v1_5d3_engine_exports/{engine}')
    assert result.export.engine.value == engine
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
