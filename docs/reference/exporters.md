# Engine exporters

Each exporter reads one completed run of one engine version and writes an
export directory; `build_v1_5d2_service()` (vectorbt, bt, Backtrader) or
`build_v1_5d3_service()` (all five) maps it to canonical artifacts.

::: backtest_auditor.implementation_risk.exporters.vectorbt.export_vectorbt_portfolio

::: backtest_auditor.implementation_risk.exporters.bt.export_bt_result

::: backtest_auditor.implementation_risk.exporters.backtrader.create_backtrader_audit_analyzer

::: backtest_auditor.implementation_risk.exporters.backtrader.export_backtrader_analysis

::: backtest_auditor.implementation_risk.exporters.nautilustrader.export_nautilustrader_reports

::: backtest_auditor.implementation_risk.exporters.nautilustrader.export_nautilustrader_engine

::: backtest_auditor.implementation_risk.exporters.quantconnect_lean.export_quantconnect_lean_results

## Mapping exports

::: backtest_auditor.implementation_risk.application.d2.build_v1_5d2_service

::: backtest_auditor.implementation_risk.application.d3.build_v1_5d3_service

::: backtest_auditor.implementation_risk.application.engine_adapter_service.EngineAdapterService
    options:
      members: [adapt]
