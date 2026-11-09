"""``edge-audit`` command line.

    edge-audit run trades.csv --trials N [--prices prices.csv] [--out DIR]
    edge-audit validate trades.csv [--prices prices.csv]

Exit codes: 0 report written (whatever the verdict), 2 invalid input or
arguments, 1 unexpected error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.edge_audit.audit import (
    DEFAULT_SEED,
    AuditSettings,
    run_edge_audit,
)
from backtest_auditor.edge_audit.report import (
    build_report,
    render_json,
    render_markdown,
)
from backtest_auditor.edge_audit.schema import load_price_table, load_trade_log

REPORT_JSON = "edge_audit_report.json"
REPORT_MARKDOWN = "edge_audit_report.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edge-audit",
        description="V4 Edge Audit: evidence of edge from a closed-trade log.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="audit a trade log and write the report")
    run.add_argument("trades", type=Path, help="edge-audit-trades/1.0 CSV")
    run.add_argument(
        "--trials",
        type=int,
        required=True,
        help="number of strategy variants tried before this one (>= 1); "
        "deflates the Sharpe ratio (DSR)",
    )
    run.add_argument("--prices", type=Path, help="edge-audit-prices/1.0 CSV")
    run.add_argument(
        "--out", type=Path, default=Path("edge_audit_out"), help="output directory"
    )
    run.add_argument("--confidence", type=float, default=0.95)
    run.add_argument("--seed", type=int, default=DEFAULT_SEED)
    run.add_argument("--bootstrap", type=int, default=2000, help="resamples")
    run.add_argument(
        "--block-length",
        type=int,
        default=1,
        help="mean block length of the trade bootstrap (1 = i.i.d.)",
    )
    run.add_argument(
        "--trial-sharpe-std",
        type=float,
        help="cross-trial SD of per-trade Sharpe ratios, if known "
        "(default: 1/sqrt(T-1), the spread of skill-less trials)",
    )
    run.add_argument("--timing-window", choices=("day", "holding"), default="day")
    run.add_argument("--day-timezone", default="UTC")
    run.add_argument("--timing-draws", type=int, default=2000)
    run.add_argument("--permutations", type=int, default=2000)
    run.add_argument("--vol-lookback-bars", type=int, default=50)
    run.add_argument(
        "--cost-grid",
        default="0,1,2,5,10,20,50",
        help="added round-trip costs in bps of notional, comma separated",
    )
    run.add_argument("--reference-trades", type=int)
    run.add_argument("--decay-shift", type=float, help="shift to detect, in SDs")
    run.add_argument(
        "--decay-false-alarm",
        type=float,
        default=0.05,
        help="false-alarm budget α of each decay detector over the horizon (0.005-0.2)",
    )
    run.add_argument(
        "--decay-horizon",
        type=int,
        default=1000,
        help="monitored trades the budget covers (30-10000; raised to the monitored "
        "count when that is larger)",
    )
    run.add_argument("--rolling-window", type=int)

    validate = commands.add_parser("validate", help="check input files only")
    validate.add_argument("trades", type=Path)
    validate.add_argument("--prices", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        trades = load_trade_log(args.trades)
        prices = None if args.prices is None else load_price_table(args.prices)
    except InputValidationError as error:
        print("edge-audit: invalid input", file=sys.stderr)
        for issue in error.issues:
            print(f"  [{issue.code}] {issue.message}", file=sys.stderr)
        return 2

    if args.command == "validate":
        print(
            f"ok: {len(trades)} trades"
            + (
                ""
                if prices is None
                else f", prices for {len(prices.timestamps)} instrument(s)"
            )
        )
        return 0

    try:
        grid = tuple(float(item) for item in args.cost_grid.split(",") if item.strip())
        settings = AuditSettings(
            declared_trials=args.trials,
            confidence_level=args.confidence,
            bootstrap_replications=args.bootstrap,
            mean_block_length=args.block_length,
            seed=args.seed,
            trial_sharpe_std=args.trial_sharpe_std,
            timing_mode=args.timing_window,
            day_timezone=args.day_timezone,
            timing_draws=args.timing_draws,
            permutation_draws=args.permutations,
            volatility_lookback_bars=args.vol_lookback_bars,
            cost_grid_bps=grid,
            reference_trades=args.reference_trades,
            decay_shift_sigma=args.decay_shift,
            decay_false_alarm_probability=args.decay_false_alarm,
            decay_horizon=args.decay_horizon,
            rolling_window=args.rolling_window,
        )
    except ValueError as error:
        print(f"edge-audit: {error}", file=sys.stderr)
        return 2

    result = run_edge_audit(trades, prices, settings)
    report = build_report(
        result,
        trades_path=args.trades,
        prices_path=args.prices,
        trade_rows=len(trades),
        schema_declared=trades.schema_declared,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / REPORT_JSON).write_text(render_json(report), encoding="utf-8")
    (args.out / REPORT_MARKDOWN).write_text(render_markdown(report), encoding="utf-8")
    print(
        f"{report['verdict']['edge']}: {report['verdict']['reason']} "
        f"-> {args.out / REPORT_MARKDOWN}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
