import json

from backtest_auditor.application.single_run_audit import (
    SingleRunAuditResult,
)
from backtest_auditor.application.experiment_family_audit import (
    ExperimentFamilyAuditResult,
)
from backtest_auditor.reporting.family_serialization import (
    experiment_family_audit_to_dict,
)
from backtest_auditor.reporting.serialization import (
    single_run_audit_to_dict,
)


def render_json_report(
    result: SingleRunAuditResult | ExperimentFamilyAuditResult,
) -> str:
    """Render deterministic, standards-compliant JSON."""

    return (
        json.dumps(
            (
                experiment_family_audit_to_dict(result)
                if isinstance(result, ExperimentFamilyAuditResult)
                else single_run_audit_to_dict(result)
            ),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
