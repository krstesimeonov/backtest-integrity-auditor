"""V4 Edge Audit: is there evidence of an edge in a realised trade log?

Layer 4 of Quant Integrity. Input: closed trades (``edge-audit-trades/1.0``),
optionally instrument prices (``edge-audit-prices/1.0``). Output: a report
(``edge-audit-report/1.1``, JSON + Markdown) answering four questions — is
there evidence of an edge, where does it come from, is it decaying, how
sensitive is it to costs. V1 statistics are imported, never copied.

Design: ``docs/edge_audit/DESIGN.md``. Learning notes: ``docs/edge_audit/LEARNING.md``.
"""

from backtest_auditor.edge_audit.audit import (
    AuditSettings,
    EdgeAuditResult,
    run_edge_audit,
)
from backtest_auditor.edge_audit.report import (
    REPORT_SCHEMA,
    build_report,
    render_json,
    render_markdown,
)
from backtest_auditor.edge_audit.schema import (
    PRICES_SCHEMA,
    TRADES_SCHEMA,
    PriceTable,
    TradeLog,
    load_price_table,
    load_trade_log,
    parse_price_table,
    parse_trade_log,
)

__all__ = [
    "AuditSettings",
    "EdgeAuditResult",
    "PRICES_SCHEMA",
    "PriceTable",
    "REPORT_SCHEMA",
    "TRADES_SCHEMA",
    "TradeLog",
    "build_report",
    "load_price_table",
    "load_trade_log",
    "parse_price_table",
    "parse_trade_log",
    "render_json",
    "render_markdown",
    "run_edge_audit",
]
