# Canonical artifacts

The engine-neutral records an adapter produces and canonical bundle 1.0
stores. A level that an engine does not provide is `None` (unavailable), which
is different from an empty tuple (available, no records).

::: backtest_auditor.implementation_risk.adapters.canonical_bundle.CanonicalArtifactFileBundleAdapter
    options:
      members: [read, write]

::: backtest_auditor.implementation_risk.domain.bundle.CanonicalRunArtifacts
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.scope.EngineRunReference
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.OrderRecord
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.FillRecord
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.TradeRecord
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.PositionSnapshot
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.CashBalance
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.CashArtifacts
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.CostRecord
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.EquityPoint
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.artifacts.ReturnPoint
    options:
      members: false
