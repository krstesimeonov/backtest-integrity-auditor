"""Optional engine-side exporters for concrete V1.5D2/D3 mappings.

Importing this package does not import an engine SDK. Each exporter accepts
completed engine results or documented post-run reports and writes only files.
"""

from backtest_auditor.implementation_risk.exporters.backtrader import (
    create_backtrader_audit_analyzer,
    export_backtrader_analysis,
)
from backtest_auditor.implementation_risk.exporters.bt import export_bt_result
from backtest_auditor.implementation_risk.exporters.vectorbt import (
    export_vectorbt_portfolio,
)
from backtest_auditor.implementation_risk.exporters.nautilustrader import (
    export_nautilustrader_engine,
    export_nautilustrader_reports,
)
from backtest_auditor.implementation_risk.exporters.quantconnect_lean import (
    export_quantconnect_lean_results,
)

__all__ = [
    "create_backtrader_audit_analyzer",
    "export_backtrader_analysis",
    "export_bt_result",
    "export_vectorbt_portfolio",
    "export_nautilustrader_engine",
    "export_nautilustrader_reports",
    "export_quantconnect_lean_results",
]
