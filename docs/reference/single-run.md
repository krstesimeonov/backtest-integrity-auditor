# Single-run audit

Read one return series, configure the methods you want, audit it.

## Reading returns

::: backtest_auditor.ingestion.csv_returns.read_return_series_csv

::: backtest_auditor.ingestion.normalization.normalize_return_series

::: backtest_auditor.ingestion.normalization.ReturnSeriesNormalizationResult

::: backtest_auditor.domain.series.SamplingSpec

## Auditing

::: backtest_auditor.application.single_run_audit.audit_single_run

::: backtest_auditor.domain.runs.StrategyRun

::: backtest_auditor.application.single_run_audit.SingleRunAuditResult
    options:
      members: false

## Method specifications

Each method runs only when its specification is supplied.

::: backtest_auditor.domain.assumptions.SharpeRatioSpec

::: backtest_auditor.domain.assumptions.ProbabilisticSharpeRatioSpec

::: backtest_auditor.domain.assumptions.SerialDependenceSpec

::: backtest_auditor.domain.assumptions.SerialAdjustmentSpec

::: backtest_auditor.domain.assumptions.BootstrapSpec

::: backtest_auditor.domain.assumptions.AdvancedRiskSpec

::: backtest_auditor.domain.assumptions.BenchmarkInferenceSpec

::: backtest_auditor.domain.reproducibility.AuditRunSpec
