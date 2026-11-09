"""Edge-audit report: one dict, rendered as JSON and as Markdown.

The Markdown is rendered from the same dict that is written as JSON, so the
two cannot disagree. No wall-clock time is written: the same inputs and
settings give byte-identical files.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backtest_auditor import PACKAGE_VERSION
from backtest_auditor.edge_audit.audit import EdgeAuditResult
from backtest_auditor.edge_audit.decay import CALIBRATION_NULL, CALIBRATION_NULL_TEXT
from backtest_auditor.edge_audit.schema import PRICES_SCHEMA, TRADES_SCHEMA
from backtest_auditor.edge_audit.skill import (
    EVIDENCE,
    INSUFFICIENT,
    MINIMUM_TRADES_FOR_VERDICT,
)

REPORT_SCHEMA = "edge-audit-report/1.1"
_SPARKS = "▁▂▃▄▅▆▇█"


def file_digest(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def plain(value: Any) -> Any:
    """Dataclasses, tuples and numpy scalars to JSON-ready values.

    Non-finite floats become ``None``: json.dumps(allow_nan=False) would
    otherwise abort the whole report over one undefined ratio.
    """

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: plain(getattr(value, item.name))
            for item in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def build_report(
    result: EdgeAuditResult,
    *,
    trades_path: str | Path,
    prices_path: str | Path | None,
    trade_rows: int,
    schema_declared: bool,
) -> dict[str, Any]:
    luck = result.luck_vs_skill
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "generated_by": {
            "package": "backtest-integrity-auditor",
            "version": PACKAGE_VERSION,
            "component": "edge_audit",
        },
        "input": {
            "trades": {
                "file": Path(trades_path).name,
                "sha256": file_digest(trades_path),
                "schema": TRADES_SCHEMA,
                "schema_declared_in_file": schema_declared,
                "rows": trade_rows,
            },
            "prices": None
            if prices_path is None
            else {
                "file": Path(prices_path).name,
                "sha256": file_digest(prices_path),
                "schema": PRICES_SCHEMA,
            },
        },
        "settings": plain(result.settings),
        "verdict": {
            "edge": luck.verdict,
            "reason": luck.verdict_reason,
            "test": "DSR at the declared trial count >= confidence level",
            "dsr": plain(luck.dsr),
            "declared_trials": luck.declared_trials,
            "confidence_level": luck.confidence_level,
        },
        "performance": plain(result.performance),
        "luck_vs_skill": plain(luck),
        "timing": plain(result.timing),
        "conditional": {
            "holding_period": plain(result.holding_period),
            "volatility_regime": plain(result.volatility_regime),
        },
        "costs": plain(result.costs),
        "decay": plain(result.decay),
        "sizing": plain(result.sizing),
        "warnings": list(result.warnings),
    }
    report["answers"] = _answers(report)
    return report


def render_json(report: dict[str, Any]) -> str:
    return (
        json.dumps(
            report, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n"
    )


def _fmt(value: Any, digits: int = 2, *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}".replace(",", "'")
    if isinstance(value, float):
        text = f"{value:+,.{digits}f}" if signed else f"{value:,.{digits}f}"
        return text.replace(",", "'")
    return str(value)


def _p(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}" if value >= 0.0001 else "<0.0001"


def _interval(item: dict[str, Any] | None, digits: int = 2) -> str:
    if item is None or (item.get("point") is None and not item.get("point_unbounded")):
        return "n/a"
    point = "∞" if item.get("point_unbounded") else _fmt(item["point"], digits)
    upper = "∞" if item.get("upper_unbounded") else _fmt(item.get("upper"), digits)
    return f"{point} [{_fmt(item.get('lower'), digits)}, {upper}]"


def _answers(report: dict[str, Any]) -> dict[str, str]:
    luck = report["luck_vs_skill"]
    perf = report["performance"]
    verdict = report["verdict"]
    level = int(round(verdict["confidence_level"] * 100))
    currency = perf["currency"] or "account currency"
    if verdict["edge"] == EVIDENCE:
        evidence = (
            f"Yes. DSR {luck['dsr']:.3f} at {luck['declared_trials']} declared "
            f"trial(s) clears {verdict['confidence_level']:g}. Expectancy "
            f"{_interval(perf['expectancy'])} {currency} per trade ({level} % "
            f"interval) over {perf['trade_count']} trades; t = {luck['t_statistic']:.2f}."
        )
    elif verdict["edge"] == INSUFFICIENT:
        evidence = f"Cannot say: {verdict['reason']}."
    else:
        extra = ""
        if luck.get("deflated_min_track_record_trades"):
            extra = (
                f" If the per-trade Sharpe ratio stayed at "
                f"{luck['sharpe_per_trade']:.3f}, about "
                f"{luck['deflated_min_track_record_trades']} trades would be needed."
            )
        elif luck.get("sharpe_per_trade") is not None and luck["sharpe_per_trade"] <= 0:
            extra = " The observed per-trade Sharpe ratio is not positive."
        evidence = (
            f"No. DSR {luck['dsr']:.3f} at {luck['declared_trials']} declared "
            f"trial(s) is below {verdict['confidence_level']:g}. Expectancy "
            f"{_interval(perf['expectancy'])} {currency} per trade ({level} % "
            f"interval) over {perf['trade_count']} trades.{extra}"
        )

    sources = []
    timing = report["timing"]
    if timing["status"] == "computed":
        for component in timing["components"]:
            if component["name"] == "execution":
                continue
            text = f"{component['name'].replace('_', ' ')}: {component['finding']}"
            if component["finding"].startswith("costs"):
                text += f" (p = {_p(component['p_value_negative'])} for costing P&L)"
            elif component["p_value_positive"] is not None:
                text += f" (p = {_p(component['p_value_positive'])} for adding P&L)"
            sources.append(text)
    else:
        sources.append(f"timing not assessed ({timing['reason']})")
    sizing = report["sizing"]
    sources.append(
        f"sizing: {sizing['finding']} (permutation p = {_p(sizing['permutation_p_value'])})"
    )
    for name, split in report["conditional"].items():
        if split["status"] == "computed":
            differs = split["permutation_p_value"] < 1 - verdict["confidence_level"]
            sources.append(
                f"{name.replace('_', ' ')}: expectancy "
                + ("differs" if differs else "does not differ detectably")
                + f" across terciles (p = {_p(split['permutation_p_value'])})"
            )
    source = "; ".join(sources) + "."

    decay = report["decay"]
    if decay["status"] != "computed":
        decay_text = f"Not assessed: {decay['reason']}."
    else:
        alarms = [
            f"{item['name']} at trade #{item['alarm_trade_number']}"
            for item in decay["detectors"]
            if item["alarm_trade_number"] is not None
        ]
        difference = decay["monitored_minus_reference"]
        tail = (
            f" Expectancy after the first {decay['reference_trades']} trades minus "
            f"before: {_interval(difference)} {currency}."
        )
        budget = (
            f" Each detector allows a {decay['false_alarm_probability']:.1%} chance of a "
            f"false alarm within {decay['horizon']:,} monitored trades if nothing changes, "
            f"for i.i.d. normal trades (null `{decay['calibration_null']}`)."
        )
        if alarms:
            decay_text = "Decay alarm: " + ", ".join(alarms) + "." + budget + tail
        else:
            decay_text = (
                f"No alarm over {decay['monitored_trades']} monitored trades."
                + budget
                + tail
            )
        missing = [
            item["name"] for item in decay["detectors"] if item["status"] != "computed"
        ]
        if missing:
            decay_text += " Not run: " + ", ".join(missing) + " (see section 6)."

    costs = report["costs"]
    break_even = costs["break_even_added_cost_bps"]
    cost_text = (
        f"Break-even at {_interval(break_even)} bps of notional added per round "
        f"trip (fees already paid: {_fmt(costs['fees_paid_bps'])} bps)."
    )
    if costs["evidence_lost_at_added_cost_bps"] is not None:
        cost_text += (
            f" Statistical evidence disappears from "
            f"{_fmt(costs['evidence_lost_at_added_cost_bps'])} bps added."
        )
    return {
        "is_there_evidence_of_an_edge": evidence,
        "where_does_it_come_from": source,
        "is_it_decaying": decay_text,
        "how_sensitive_to_costs": cost_text,
    }


def _null_label(null: str) -> str:
    if null == CALIBRATION_NULL:
        return CALIBRATION_NULL_TEXT
    return null


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    points = np.asarray(values, dtype=np.float64)
    if points.size > 60:
        edges = np.linspace(0, points.size, 61).astype(int)
        points = np.asarray([points[a:b].mean() for a, b in zip(edges[:-1], edges[1:])])
    low, high = float(points.min()), float(points.max())
    if high == low:
        return _SPARKS[3] * points.size
    scaled = (points - low) / (high - low) * (len(_SPARKS) - 1)
    return "".join(_SPARKS[int(round(value))] for value in scaled)


def render_markdown(report: dict[str, Any]) -> str:
    perf = report["performance"]
    luck = report["luck_vs_skill"]
    verdict = report["verdict"]
    answers = report["answers"]
    currency = perf["currency"] or "account currency"
    level = f"{verdict['confidence_level']:.0%}"
    verdict_minimum = MINIMUM_TRADES_FOR_VERDICT
    lines = [
        "# Edge Audit",
        "",
        f"Trades: `{report['input']['trades']['file']}` "
        f"(sha256 `{report['input']['trades']['sha256'][:16]}…`, "
        f"{perf['trade_count']} closed trades, {perf['first_entry']} → {perf['last_exit']}). "
        + (
            f"Prices: `{report['input']['prices']['file']}`."
            if report["input"]["prices"]
            else "No price file."
        ),
        f"Declared trials: **{verdict['declared_trials']}**. Confidence level: {level}. "
        f"Seed: {report['settings']['seed']}. Report schema `{report['schema']}`, "
        f"package {report['generated_by']['version']}.",
        "",
        "## Verdict",
        "",
        f"**{verdict['edge'].replace('_', ' ')}** — {verdict['reason']}.",
        "",
        "| Question | Answer |",
        "|---|---|",
        f"| Is there evidence of an edge? | {answers['is_there_evidence_of_an_edge']} |",
        f"| Where does it come from? | {answers['where_does_it_come_from']} |",
        f"| Is it decaying? | {answers['is_it_decaying']} |",
        f"| How sensitive is it to costs? | {answers['how_sensitive_to_costs']} |",
        "",
        "## 1. Performance (net of logged fees)",
        "",
        f"Intervals: {level} percentile bootstrap over trades "
        f"({report['settings']['bootstrap_replications']} resamples, mean block "
        f"length {report['settings']['mean_block_length']}).",
        "",
        "| Metric | Value [interval] |",
        "|---|---|",
        f"| Expectancy per trade ({currency}) | {_interval(perf['expectancy'])} |",
        f"| Profit factor | {_interval(perf['profit_factor'], 3)} |",
        f"| Win rate | {_interval(perf['win_rate'], 3)} |",
        f"| Total net P&L | {_fmt(perf['total_net_pnl'])} |",
        f"| Total fees | {_fmt(perf['total_fees'])} |",
        f"| Average win / average loss | {_fmt(perf['average_win'])} / {_fmt(perf['average_loss'])} |",
        f"| Mean net return per trade | {_fmt(perf['mean_net_return_bps'])} bps |",
        f"| Median holding period | {_fmt(perf['median_holding_hours'])} h |",
        f"| Most trades open at once | {perf['max_concurrent_trades']} |",
        f"| Lag-1 autocorrelation of trade P&L | {_fmt(perf['lag_one_autocorrelation'], 3)} "
        f"(Ljung-Box p = {_p(perf['serial_dependence_p_value'])}) |",
        "",
        "## 2. Luck or skill",
        "",
        "| Quantity | Value |",
        "|---|---|",
        f"| Sharpe ratio per trade (SR) | {_fmt(luck['sharpe_per_trade'], 4)} |",
        f"| t = SR·√T | {_fmt(luck['t_statistic'], 3)} (one-sided p = {_p(luck['t_p_value_one_sided'])}) |",
        f"| Trades per year (trade clock) | {_fmt(luck['trades_per_year'], 1)} |",
        f"| Annualised SR (trade clock) | {_fmt(luck['annualized_sharpe'], 3)} |",
        f"| Skewness / Pearson kurtosis | {_fmt(luck['sample_skewness'], 3)} / {_fmt(luck['sample_pearson_kurtosis'], 3)} |",
        f"| SE of SR: under H0 (1/√(T-1)) / plug-in (V1) | {_fmt(luck['null_standard_error'], 4)} / {_fmt(luck['sharpe_standard_error'], 4)} |",
        f"| PSR vs SR* = 0 (V1, plug-in SE) | {_fmt(luck['psr_vs_zero'], 4)} |",
        f"| Declared trials N | {luck['declared_trials']} |",
        f"| Cross-trial SD of SR ({luck['trial_sharpe_std_source'].replace('_', ' ')}) | {_fmt(luck['trial_sharpe_std'], 4)} |",
        f"| Expected max SR of N skill-less trials | {_fmt(luck['expected_max_sharpe_per_trade'], 4)} |",
        f"| **DSR (verdict; SE under H0)** | **{_fmt(luck['dsr'], 4)}** |",
        f"| DSR, classical plug-in SE (V1) | {_fmt(luck['dsr_plug_in'], 4)} |",
        f"| MinTRL vs SR* = 0 (V1, plug-in SE; trades; before the {verdict_minimum}-trade floor) | {_fmt(luck['min_track_record_trades'])} |",
        f"| Trades needed for the verdict DSR ≥ {verdict['confidence_level']:g} at this SR | {_fmt(luck['deflated_min_track_record_trades'])} |",
        "",
    ]

    timing = report["timing"]
    lines += ["## 3. Where the P&L comes from: timing", ""]
    if timing["status"] != "computed":
        lines += [f"Not assessed: {timing['reason']}.", ""]
    else:
        lines += [
            f"Window mode `{timing['mode']}` (days in {timing['day_timezone']}); "
            f"{timing['covered_trades']} trades with price coverage"
            + (
                " (excluded: "
                + ", ".join(
                    f"{count} {reason.replace('_', ' ')}"
                    for reason, count in sorted(timing["excluded"].items())
                )
                + ")"
                if timing["excluded"]
                else ""
            )
            + "; "
            + f"{timing['draws']} random-time draws per test. Gross P&L of these "
            f"trades: {_fmt(timing['gross_pnl_covered'])} {currency}.",
            "",
            "| Component | Total | Share of gross | Mean per trade [interval] | p (adds) | p (costs) | Finding |",
            "|---|---|---|---|---|---|---|",
        ]
        for component in timing["components"]:
            share = component["share_of_gross"]
            lines.append(
                f"| {component['name'].replace('_', ' ')} | {_fmt(component['total'])} | "
                f"{'n/a' if share is None else f'{share:.1%}'} | "
                f"{_interval(component['mean_per_trade'])} | "
                f"{_p(component['p_value_positive'])} | {_p(component['p_value_negative'])} | "
                f"{component['finding']} |"
            )
        lines.append("")
    lines += ["## 4. Holding period and volatility regime", ""]
    for name, split in report["conditional"].items():
        title = name.replace("_", " ")
        if split["status"] != "computed":
            lines += [f"*{title}*: not assessed ({split['reason']}).", ""]
            continue
        lines += [
            f"*{title}* (source: {split['source']}; {split['trades_with_value']} of "
            f"{perf['trade_count']} trades have a value); permutation p = "
            f"{_p(split['permutation_p_value'])} for 'expectancy differs across terciles'.",
            "",
            "| Tercile | Trades | Range | Expectancy [interval] | Win rate |",
            "|---|---|---|---|---|",
        ]
        for row in split["rows"]:
            lines.append(
                f"| {row['label']} | {row['count']} | "
                f"{row['variable_min']:.4g} – {row['variable_max']:.4g} | "
                f"{_interval(row['expectancy'])} | {row['win_rate']:.1%} |"
            )
        lines.append("")

    costs = report["costs"]
    lines += [
        "## 5. Cost sensitivity",
        "",
        f"Unit: {costs['unit']}. Mean notional {_fmt(costs['mean_notional'])} {currency}; "
        f"fees already paid {_fmt(costs['fees_paid_bps'])} bps; gross edge can carry "
        f"{_fmt(costs['gross_break_even_cost_bps'])} bps in total.",
        "",
        f"Break-even added cost: **{_interval(costs['break_even_added_cost_bps'])} bps**. "
        + (
            f"Evidence lost at: **{_fmt(costs['evidence_lost_at_added_cost_bps'])} bps** "
            f"({costs['evidence_note']})."
            if costs["evidence_lost_at_added_cost_bps"] is not None
            else costs["evidence_note"].capitalize() + "."
        ),
        "",
        "| Added cost (bps) | Expectancy [interval] | DSR | Verdict |",
        "|---|---|---|---|",
    ]
    for point in costs["curve"]:
        lines.append(
            f"| {_fmt(point['added_cost_bps'])} | {_fmt(point['expectancy'])} "
            f"[{_fmt(point['expectancy_lower'])}, {_fmt(point['expectancy_upper'])}] | "
            f"{_fmt(point['dsr'], 4)} | {point['verdict'].replace('_', ' ')} |"
        )
    lines.append("")

    decay = report["decay"]
    lines += ["## 6. Decay", ""]
    if decay["rolling_expectancy"]:
        lines += [
            f"Rolling expectancy, {decay['rolling_window']}-trade window "
            f"(min {_fmt(min(decay['rolling_expectancy']))}, "
            f"max {_fmt(max(decay['rolling_expectancy']))}, "
            f"last {_fmt(decay['rolling_expectancy'][-1])}):",
            "",
            f"`{_sparkline(decay['rolling_expectancy'])}`",
            "",
        ]
    if decay["status"] != "computed":
        lines += [f"Detectors not run: {decay['reason']}.", ""]
    else:
        horizon_note = (
            ""
            if decay["horizon"] == decay["horizon_requested"]
            else f" (requested {decay['horizon_requested']:,}, raised to the monitored trades)"
        )
        lines += [
            f"Reference: first {decay['reference_trades']} trades, mean "
            f"{_fmt(decay['reference_mean'])}, SD {_fmt(decay['reference_std'])}, "
            f"SR {_fmt(decay['reference_sharpe'], 4)}. Shift to detect δ = "
            f"{_fmt(decay['shift_sigma'], 4)} SD ({decay['shift_source'].replace('_', ' ')}). "
            f"Monitored: {decay['monitored_trades']} trades.",
            "",
            f"False-alarm budget: α = {decay['false_alarm_probability']:.1%} per detector "
            f"within a horizon of {decay['horizon']:,} monitored trades{horizon_note}. "
            f"Thresholds from {decay['calibration_table']}, calibrated under the null "
            f"`{decay['calibration_null']}`: {_null_label(decay['calibration_null'])}. "
            "Serially dependent or fat-tailed trades raise the false-alarm rate above α "
            "(docs/edge_audit/CALIBRATION.md).",
            "",
            "| Detector | Threshold | Calibrated α within N trades | False-alarm chance over the monitored trades | Alarm at trade # | Alarm exit time | Max statistic |",
            "|---|---|---|---|---|---|---|",
        ]
        for item in decay["detectors"]:
            calibrated = (
                f"{item['false_alarm_probability']:.1%} within {item['horizon']:,} "
                f"({item['calibration_null']})"
            )
            if item["status"] != "computed":
                lines.append(
                    f"| {item['name']} | — | {calibrated} | — | not run: {item['reason']} | — | — |"
                )
                continue
            chance = item["false_alarm_probability_over_monitored"]
            if chance is None:
                chance_text = "—"
            elif item["extra"].get("false_alarm_over_monitored_is_upper_bound"):
                chance_text = f"< {chance:.1%}"
            else:
                chance_text = f"{chance:.1%}"
            lines.append(
                f"| {item['name']} | {_fmt(item['threshold'], 3)} | {calibrated} | "
                f"{chance_text} | "
                f"{_fmt(item['alarm_trade_number'])} | {item['alarm_exit_time'] or '—'} | "
                f"{_fmt(item['max_statistic'], 3)} |"
            )
        rolling_item = next(
            (
                item
                for item in decay["detectors"]
                if item["name"] == "rolling_expectancy" and item["status"] == "computed"
            ),
            None,
        )
        if rolling_item is not None:
            lines += [
                "",
                f"Rolling-expectancy alarm level: the {decay['rolling_window']}-trade "
                f"average P&L below {_fmt(rolling_item['extra']['alarm_level_mean_pnl'])} "
                f"{currency}.",
            ]
        lines += [
            "",
            f"Monitored minus reference expectancy: {_interval(decay['monitored_minus_reference'])} {currency}.",
            "",
        ]

    sizing = report["sizing"]
    lines += [
        "## 7. Position sizing",
        "",
        "| Quantity | Value [interval] |",
        "|---|---|",
        f"| Actual expectancy | {_interval(sizing['actual_expectancy'])} |",
        f"| Fixed-size expectancy (mean notional {_fmt(sizing['mean_notional'])}) | {_interval(sizing['fixed_size_expectancy'])} |",
        f"| Sizing contribution per trade | {_interval(sizing['sizing_contribution_per_trade'])} |",
        f"| Sizing contribution, total | {_fmt(sizing['sizing_contribution_total'])} |",
        f"| Correlation of notional and net return | {_fmt(sizing['size_return_correlation'], 3)} |",
        f"| Permutation p (two-sided) | {_p(sizing['permutation_p_value'])} |",
        f"| Fixed-size DSR / verdict | {_fmt(sizing['fixed_size_dsr'], 4)} / {sizing['fixed_size_verdict'].replace('_', ' ')} |",
        "",
        f"Finding: {sizing['finding']}. The finding uses the permutation test, exact "
        "if sizes are unrelated to outcomes; the bootstrap interval describes the "
        "estimate's uncertainty without that assumption, so the two can disagree "
        "near the 5 % line.",
        "",
    ]
    if report["warnings"]:
        lines += (
            ["## Warnings", ""] + [f"- {item}" for item in report["warnings"]] + [""]
        )
    lines += [
        "## Method notes",
        "",
        "Methods, assumptions and failure cases: `docs/edge_audit/DESIGN.md`. "
        "The verdict uses no random numbers; every interval and p-value is "
        "reproducible from the seed above.",
        "",
    ]
    return "\n".join(lines)
