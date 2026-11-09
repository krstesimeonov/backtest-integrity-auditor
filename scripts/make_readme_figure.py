"""Draw the README figure from the quickstart's JSON report.

    python scripts/make_readme_figure.py     # writes docs/assets/readme-figure.png

The script runs step 2 of docs/getting-started.md (the same command as
``scripts/docs_snippets.py``) with ``--format json`` and plots only what that
report states: the maximum-drawdown window and ending wealth from
``performance_path``, the bootstrap intervals of the annualized Sharpe ratio,
the Probabilistic Sharpe Ratio and the minimum track-record length. The
wealth line itself is the cumulative product of the input returns; the script
checks that it ends at the report's ``ending_wealth``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import pandas as pd
from docs_snippets import INPUT, ROOT, STEP3, run

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

OUTPUT = ROOT / "docs" / "assets" / "readme-figure.png"

# Reference palette of the dataviz method: one series colour plus neutral ink.
SURFACE = "#fcfcfb"
SERIES = "#2a78d6"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"


def signed(value: float, spec: str) -> str:
    """Format like the tick labels: a true minus sign, not a hyphen."""

    return format(value, spec).replace("-", "\u2212")


def audit(directory: Path) -> dict:
    (directory / "audit_returns.csv").write_bytes(INPUT.read_bytes())
    run(STEP3, directory)
    return json.loads((directory / "report.json").read_text(encoding="utf-8"))


def style(axis: plt.Axes) -> None:
    axis.set_facecolor(SURFACE)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(BASELINE)
        axis.spines[side].set_linewidth(0.8)
    axis.tick_params(colors=INK_MUTED, labelcolor=INK_SECONDARY, labelsize=8)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        report = audit(Path(temporary))
    path = report["performance_path"]
    sharpe = report["sharpe_uncertainty"]
    track = report["track_record_length"]
    intervals = {
        item["metric"]: item
        for item in report["bootstrap"]["metrics"]
        if item["metric"]
        in ("iid_annualized_sharpe_ratio", "hac_adjusted_annualized_sharpe_ratio")
    }

    returns = pd.read_csv(INPUT, parse_dates=["timestamp"]).set_index("timestamp")
    wealth = (1 + returns["return"]).cumprod()
    if abs(wealth.iloc[-1] - path["ending_wealth"]) > 1e-9:
        raise SystemExit("wealth path does not end at the report's ending_wealth")

    plt.rcParams["font.family"] = "DejaVu Sans"
    figure, (left, right) = plt.subplots(
        1,
        2,
        figsize=(9.6, 3.4),
        gridspec_kw={"width_ratios": [1.55, 1], "wspace": 0.28},
        facecolor=SURFACE,
    )

    # Left: growth of 1 with the maximum-drawdown window from the report.
    style(left)
    peak = pd.Timestamp(path["maximum_drawdown_peak_timestamp"])
    trough = pd.Timestamp(path["maximum_drawdown_trough_timestamp"])
    left.axvspan(peak, trough, color=GRID, alpha=0.6, linewidth=0)
    left.plot(wealth.index, wealth.to_numpy(), color=SERIES, linewidth=2,
              solid_joinstyle="round", solid_capstyle="round")  # fmt: skip
    left.scatter([wealth.index[-1]], [wealth.iloc[-1]], s=36, color=SERIES,
                 edgecolors=SURFACE, linewidths=2, zorder=3)  # fmt: skip
    left.annotate(
        f"{path['ending_wealth']:.2f}",
        (wealth.index[-1], wealth.iloc[-1]),
        xytext=(6, 0),
        textcoords="offset points",
        va="center",
        fontsize=8,
        color=INK,
    )
    left.text(
        peak + (trough - peak) / 2,
        wealth.min(),
        f"maximum\ndrawdown\n{signed(path['maximum_drawdown'], '.1%')}",
        ha="center",
        va="bottom",
        fontsize=7.5,
        color=INK_SECONDARY,
    )
    left.grid(axis="y", color=GRID, linewidth=0.8)
    left.set_axisbelow(True)
    left.xaxis.set_major_locator(mdates.YearLocator())
    left.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    left.set_title(
        f"Growth of 1 over {path['observation_count']} weekday returns (synthetic)",
        loc="left",
        fontsize=9,
        color=INK,
    )

    # Right: annualized Sharpe ratio with its 95 % bootstrap intervals.
    style(right)
    rows = [
        ("HAC-adjusted\nSharpe", intervals["hac_adjusted_annualized_sharpe_ratio"]),
        ("IID-annualized\nSharpe", intervals["iid_annualized_sharpe_ratio"]),
    ]
    right.axvline(0, color=INK_MUTED, linewidth=0.8)
    for position, (_, item) in enumerate(rows):
        right.plot([item["lower_bound"], item["upper_bound"]], [position, position],
                   color=SERIES, linewidth=2, solid_capstyle="round")  # fmt: skip
        right.scatter([item["point_estimate"]], [position], s=44, color=SERIES,
                      edgecolors=SURFACE, linewidths=2, zorder=3)  # fmt: skip
        right.annotate(
            signed(item["point_estimate"], ".2f"),
            (item["point_estimate"], position),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=INK,
        )
        for bound in ("lower_bound", "upper_bound"):
            right.annotate(
                signed(item[bound], ".2f"),
                (item[bound], position),
                xytext=(0, -12),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color=INK_MUTED,
            )
    right.set_yticks(range(len(rows)), [label for label, _ in rows])
    right.set_ylim(-0.6, len(rows) - 0.4)
    right.set_xlim(-0.8, 2.0)
    right.tick_params(axis="y", length=0)
    right.grid(axis="x", color=GRID, linewidth=0.8)
    right.set_axisbelow(True)
    right.set_title(
        "Annualized Sharpe ratio, 95 % stationary-bootstrap intervals",
        loc="left",
        fontsize=9,
        color=INK,
    )
    right.text(
        0.0,
        -0.16,
        (
            f"PSR {sharpe['probabilistic_sharpe_ratio']:.2f} against a required "
            f"{track['required_psr_confidence_level']:.2f}; meeting it would take "
            f"{track['minimum_required_observations']:,} observations "
            f"(about {track['minimum_track_record_length_years']:.0f} years), "
            f"not {track['observation_count']}."
        ),
        transform=right.transAxes,
        fontsize=7.5,
        color=INK_SECONDARY,
        wrap=True,
        va="top",
    )

    figure.text(
        0.01,
        0.005,
        "Source: backtest-auditor report on examples/quickstart/audit_returns.csv "
        "(scripts/make_readme_figure.py)",
        fontsize=6.5,
        color=INK_MUTED,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        OUTPUT,
        dpi=200,
        facecolor=SURFACE,
        bbox_inches="tight",
        metadata={"Software": None},
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
