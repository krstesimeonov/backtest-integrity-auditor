"""Tables (tables.md) and figures (docs/edge_audit/figures/) from results_*.json.

Called by ``evaluate_detectors.py report``. Every number in CALIBRATION.md's
tables is a cell of tables.md; tests/edge_audit/test_edge_audit_calibration_doc.py
regenerates the tables from the JSON files and requires CALIBRATION.md to
contain them verbatim.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

# Detector, its name in the "before" run (J9 as shipped), in the "after" run.
DETECTORS = (
    ("Rolling expectancy", "rolling_rule", "rolling_expectancy"),
    ("CUSUM", "cusum", "cusum"),
    ("Page–Hinkley", "page_hinkley", "page_hinkley"),
    ("SPRT", "sprt", "mixture_sprt"),
)
FIGURE_TITLE = {
    "rolling_expectancy": "Rolling expectancy",
    "cusum": "CUSUM",
    "page_hinkley": "Page–Hinkley",
    "mixture_sprt": "SPRT (before: Wald with restarts; after: mixture SPRT)",
}
BEFORE_LABEL = {
    "rolling_rule": "before: average of the last w trades < 0 (J9's series read literally)",
    "cusum": "before: J9, threshold simulated per audit (2,000 draws)",
    "page_hinkley": "before: J9, threshold simulated per audit (2,000 draws)",
    "sprt": "before: J9 Wald SPRT (α 0.01, β 0.10, restarts)",
}
AFTER_LABEL = {
    "rolling_expectancy": "after: rolling-expectancy alarm, table threshold",
    "cusum": "after: table threshold",
    "page_hinkley": "after: table threshold",
    "mixture_sprt": "after: mixture SPRT, table threshold",
}
NULL_LABEL = {
    "iid_normal": "i.i.d. normal (the calibration null)",
    "student_t3": "Student t, 3 degrees of freedom",
    "ar1_t3": "AR(1), φ = 0.3, t(3) innovations",
}
CHANGE_LABEL = {
    "halving": "edge halves (SR 0.3 → 0.15)",
    "to_zero": "edge goes to zero (SR 0.3 → 0)",
}
# Validated categorical slots (dataviz reference palette, light mode).
NULL_COLOUR = {"iid_normal": "#2a78d6", "student_t3": "#eb6834", "ar1_t3": "#1baf7a"}
CHANGE_COLOUR = {"halving": "#008300", "to_zero": "#6250d6"}
INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"


def load(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    before = json.loads((directory / "results_before.json").read_text(encoding="utf-8"))
    after = json.loads((directory / "results_after.json").read_text(encoding="utf-8"))
    return before, after


def percent(value: float) -> str:
    return f"{100.0 * value:.1f} %"


def rate_cell(entry: dict[str, Any]) -> str:
    low, high = entry["wilson95"]
    return f"{percent(entry['rate'])} ({100.0 * low:.1f}–{100.0 * high:.1f})"


def delay_cell(entry: dict[str, Any]) -> str:
    def fmt(value: float | None) -> str:
        return "not reached" if value is None else f"{value:.0f}"

    return (
        f"{fmt(entry['delay_median'])} / {fmt(entry['delay_p90'])}; "
        f"early {percent(entry['alarm_before_change_rate'])}"
    )


def false_alarm_tables(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    horizons = before["horizons"]
    lines: list[str] = []
    for null, label in NULL_LABEL.items():
        lines += [
            f"**False alarms, {label}** — share of logs with any alarm within the N "
            "monitored trades, Wilson 95 % interval in brackets.",
            "",
            "| Detector | " + " | ".join(f"N = {n:,}" for n in horizons) + " |",
            "|---|" + "---|" * len(horizons),
        ]
        for title, old, new in DETECTORS:
            for run, name, tag in (
                (before, old, BEFORE_LABEL[old]),
                (after, new, AFTER_LABEL[new]),
            ):
                cells = [
                    rate_cell(run["scenarios"][f"{null}/{n}"]["detectors"][name])
                    for n in horizons
                ]
                lines.append(f"| {title} — {tag} | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def delay_tables(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    horizons = before["horizons"]
    lines: list[str] = []
    for change, label in CHANGE_LABEL.items():
        lines += [
            f"**Detection delay, {label} after N/4 monitored trades** — median / 90th "
            "percentile of trades from the change to the alarm (no alarm by trade N "
            'counts as never: "not reached"); "early" = alarm before the change.',
            "",
            "| Detector | " + " | ".join(f"N = {n:,}" for n in horizons) + " |",
            "|---|" + "---|" * len(horizons),
        ]
        for title, old, new in DETECTORS:
            for run, name, tag in ((before, old, "before"), (after, new, "after")):
                cells = [
                    delay_cell(run["scenarios"][f"{change}/{n}"]["detectors"][name])
                    for n in horizons
                ]
                lines.append(f"| {title} — {tag} | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def mechanism_table(before: dict[str, Any]) -> list[str]:
    horizons = before["horizons"]
    rows = (
        (
            "μ₀, σ₀ known, one SPRT cycle (stops at the first 'intact')",
            "sprt_known_parameters_single_cycle",
        ),
        ("μ₀, σ₀ known, restarts after 'intact' (open-ended)", "sprt_known_parameters"),
        ("μ₀, σ₀ estimated from R trades, one cycle", "sprt_single_cycle"),
        ("μ₀, σ₀ estimated, restarts: J9 as shipped", "sprt"),
    )
    lines = [
        "| Wald SPRT variant, i.i.d. normal null | "
        + " | ".join(f"N = {n:,}" for n in horizons)
        + " |",
        "|---|" + "---|" * len(horizons),
    ]
    for label, name in rows:
        cells = [
            rate_cell(before["scenarios"][f"iid_normal/{n}"]["detectors"][name])
            for n in horizons
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    for null in ("student_t3", "ar1_t3"):
        cells = [
            rate_cell(before["scenarios"][f"{null}/{n}"]["detectors"]["sprt"])
            for n in horizons
        ]
        lines.append(
            f"| J9 as shipped, {NULL_LABEL[null]} | " + " | ".join(cells) + " |"
        )
    return lines + [""]


def formula_table(after: dict[str, Any]) -> list[str]:
    horizons = after["horizons"]
    rows = (
        (
            "CUSUM, Siegmund ARL₀ formula for 5 % over N (μ₀, σ₀ treated as known)",
            "formula_cusum_siegmund",
        ),
        (
            "Mixture SPRT, Ville bound log(1/α), μ₀ and σ₀ known (true values)",
            "formula_mixture_sprt_ville_known_parameters",
        ),
        (
            "Mixture SPRT, Ville bound log(1/α), μ₀ and σ₀ estimated",
            "formula_mixture_sprt_ville",
        ),
        (
            "Rolling expectancy, one-sided 5 % normal limit per window",
            "formula_rolling_per_window_5pct",
        ),
    )
    lines: list[str] = []
    for null in NULL_LABEL:
        lines += [
            f"| Formula threshold, {NULL_LABEL[null]} | "
            + " | ".join(f"N = {n:,}" for n in horizons)
            + " |",
            "|---|" + "---|" * len(horizons),
        ]
        for label, name in rows:
            cells = [
                rate_cell(after["scenarios"][f"{null}/{n}"]["detectors"][name])
                for n in horizons
            ]
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def render_tables(before: dict[str, Any], after: dict[str, Any]) -> str:
    sections = [
        "<!-- generated by docs/edge_audit/calibration/evaluate_detectors.py report -->",
        "",
        "## Table A — false alarms before and after",
        "",
        *false_alarm_tables(before, after),
        "## Table B — detection delay before and after",
        "",
        *delay_tables(before, after),
        "## Table C — where J9's SPRT false alarms come from",
        "",
        *mechanism_table(before),
        "## Table D — formula thresholds on the same logs",
        "",
        *formula_table(after),
    ]
    return "\n".join(sections)


def draw_figures(
    before: dict[str, Any], after: dict[str, Any], figures: Path
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures.mkdir(parents=True, exist_ok=True)
    horizons = before["horizons"]
    paths = []
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.facecolor": SURFACE,
            "figure.facecolor": SURFACE,
        }
    )
    for title, old, new in DETECTORS:
        figure, (left, right) = plt.subplots(1, 2, figsize=(11.0, 5.0))
        figure.suptitle(FIGURE_TITLE[new], color=INK, fontsize=11)
        for null, colour in NULL_COLOUR.items():
            for run, name, style, fill in (
                (before, old, "--", "none"),
                (after, new, "-", colour),
            ):
                entries = [
                    run["scenarios"][f"{null}/{n}"]["detectors"][name] for n in horizons
                ]
                rates = [100.0 * e["rate"] for e in entries]
                low = [
                    max(0.0, 100.0 * (e["rate"] - e["wilson95"][0])) for e in entries
                ]
                high = [
                    max(0.0, 100.0 * (e["wilson95"][1] - e["rate"])) for e in entries
                ]
                left.errorbar(
                    horizons,
                    rates,
                    yerr=[low, high],
                    color=colour,
                    linestyle=style,
                    linewidth=2,
                    marker="o",
                    markersize=7,
                    markerfacecolor=fill,
                    markeredgecolor=colour,
                    capsize=3,
                    label=f"{NULL_LABEL[null].split(' (')[0]} — {'before' if run is before else 'after'}",
                )
        left.axhline(5.0, color=INK, linewidth=1, linestyle=":")
        left.text(200, 5.5, "α = 5 %", color=INK, fontsize=8, ha="center")
        left.set_xscale("log")
        left.set_xticks(horizons, [f"{n:,}" for n in horizons])
        left.set_yscale("symlog", linthresh=10)
        left.set_ylim(0, 100)
        left.set_yticks(
            [0, 2, 5, 10, 20, 50, 100], ["0", "2", "5", "10", "20", "50", "100"]
        )
        left.set_xlabel("monitored trades N (= calibrated horizon after the fix)")
        left.set_ylabel("false alarms, % of logs (Wilson 95 %)")
        left.set_title("false alarms when nothing changes", color=INK)
        left.grid(True, color="#e4e3df", linewidth=0.6)
        left.legend(
            fontsize=7,
            frameon=False,
            loc="upper center",
            ncol=2,
            bbox_to_anchor=(0.5, -0.18),
        )
        for change, colour in CHANGE_COLOUR.items():
            for run, name, style, fill in (
                (before, old, "--", "none"),
                (after, new, "-", colour),
            ):
                entries = [
                    run["scenarios"][f"{change}/{n}"]["detectors"][name]
                    for n in horizons
                ]
                xs = [
                    n
                    for n, e in zip(horizons, entries, strict=True)
                    if e["delay_median"] is not None
                ]
                medians = [
                    e["delay_median"] for e in entries if e["delay_median"] is not None
                ]
                right.plot(
                    xs,
                    medians,
                    color=colour,
                    linestyle=style,
                    linewidth=2,
                    marker="o",
                    markersize=7,
                    markerfacecolor=fill,
                    markeredgecolor=colour,
                    label=f"{CHANGE_LABEL[change]} — {'before' if run is before else 'after'}",
                )
        right.set_xscale("log")
        right.set_yscale("log")
        right.set_xticks(horizons, [f"{n:,}" for n in horizons])
        right.set_xlabel("monitored trades N (change after N/4)")
        right.set_ylabel("median delay, trades (missing: not reached)")
        right.set_title("detection delay", color=INK)
        right.grid(True, color="#e4e3df", linewidth=0.6)
        right.legend(
            fontsize=7,
            frameon=False,
            loc="upper center",
            ncol=2,
            bbox_to_anchor=(0.5, -0.18),
        )
        figure.tight_layout()
        path = figures / f"{new}.png"
        figure.savefig(path, dpi=130)
        plt.close(figure)
        paths.append(path)
    return paths


def write_report(directory: Path, figures: Path) -> None:
    before, after = load(directory)
    (directory / "tables.md").write_text(
        render_tables(before, after) + "\n", encoding="utf-8"
    )
    for path in draw_figures(before, after, figures):
        print(f"wrote {path}")
    print(f"wrote {directory / 'tables.md'}")


def table_blocks(directory: Path) -> list[str]:
    """The tables as blocks of consecutive '|' lines (what CALIBRATION.md must contain)."""

    before, after = load(directory)
    blocks, current = [], []
    for line in render_tables(before, after).splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


if __name__ == "__main__":  # pragma: no cover
    here = Path(__file__).resolve().parent
    write_report(here, here.parent / "figures")
    _ = math
