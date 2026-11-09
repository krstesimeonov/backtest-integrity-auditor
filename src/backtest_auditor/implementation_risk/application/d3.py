"""Explicit composition root for the complete V1.5D3 engine roadmap."""

from backtest_auditor.implementation_risk.adapters.backtrader import (
    BacktraderArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.bt import BtArtifactMapper
from backtest_auditor.implementation_risk.adapters.canonical_bundle import (
    CanonicalArtifactFileBundleAdapter,
)
from backtest_auditor.implementation_risk.adapters.engine_export import (
    EngineExportFileBundleAdapter,
)
from backtest_auditor.implementation_risk.adapters.nautilustrader import (
    NautilusTraderArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.quantconnect_lean import (
    QuantConnectLeanArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.vectorbt import (
    VectorbtArtifactMapper,
)
from backtest_auditor.implementation_risk.application.engine_adapter_service import (
    EngineAdapterRegistry,
    EngineAdapterService,
)


def build_v1_5d3_registry() -> EngineAdapterRegistry:
    """Return a fresh, complete, fail-closed registry in roadmap order."""

    registry = EngineAdapterRegistry(
        (
            VectorbtArtifactMapper(),
            BtArtifactMapper(),
            BacktraderArtifactMapper(),
            QuantConnectLeanArtifactMapper(),
            NautilusTraderArtifactMapper(),
        )
    )
    registry.assert_complete_roadmap()
    return registry


def build_v1_5d3_service() -> EngineAdapterService:
    """Compose the verified reader, complete registry, and canonical identity."""

    return EngineAdapterService(
        export_reader=EngineExportFileBundleAdapter(),
        registry=build_v1_5d3_registry(),
        canonical_identity=CanonicalArtifactFileBundleAdapter(),
    )


__all__ = ["build_v1_5d3_registry", "build_v1_5d3_service"]
