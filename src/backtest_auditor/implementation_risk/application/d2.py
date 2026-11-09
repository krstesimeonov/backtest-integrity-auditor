"""Explicit composition root for the three concrete V1.5D2 adapters."""

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
from backtest_auditor.implementation_risk.adapters.vectorbt import (
    VectorbtArtifactMapper,
)
from backtest_auditor.implementation_risk.application.engine_adapter_service import (
    EngineAdapterRegistry,
    EngineAdapterService,
)


def build_v1_5d2_registry() -> EngineAdapterRegistry:
    """Return a fresh registry in the frozen engine-roadmap order."""

    return EngineAdapterRegistry(
        (
            VectorbtArtifactMapper(),
            BtArtifactMapper(),
            BacktraderArtifactMapper(),
        )
    )


def build_v1_5d2_service() -> EngineAdapterService:
    """Compose the verified file reader, D2 registry, and canonical identity."""

    return EngineAdapterService(
        export_reader=EngineExportFileBundleAdapter(),
        registry=build_v1_5d2_registry(),
        canonical_identity=CanonicalArtifactFileBundleAdapter(),
    )


__all__ = ["build_v1_5d2_registry", "build_v1_5d2_service"]
