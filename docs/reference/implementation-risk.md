# Implementation-risk audit

::: backtest_auditor.implementation_risk.application.audit_service.ImplementationRiskAuditService
    options:
      members: [audit]

::: backtest_auditor.implementation_risk.domain.reporting.ImplementationRiskAuditResult
    options:
      members: false

## Policies

::: backtest_auditor.implementation_risk.domain.normalization.ReconciliationNormalizationPlan
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.comparison.ReconciliationComparisonPolicy
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.divergence.DivergenceMeasurementPolicy
    options:
      members: false

::: backtest_auditor.implementation_risk.domain.risk_assessment.RiskAssessmentPolicy
    options:
      members: false

## Policy files

::: backtest_auditor.implementation_risk.adapters.policy_json.load_policy_json_file

::: backtest_auditor.implementation_risk.adapters.policy_json.normalization_plan_from_json

::: backtest_auditor.implementation_risk.adapters.policy_json.comparison_policy_from_json

::: backtest_auditor.implementation_risk.adapters.policy_json.divergence_policy_from_json

::: backtest_auditor.implementation_risk.adapters.policy_json.risk_policy_from_json

## Reports

::: backtest_auditor.implementation_risk.reporting.serialization.render_implementation_risk_json

::: backtest_auditor.implementation_risk.reporting.markdown.render_implementation_risk_markdown
