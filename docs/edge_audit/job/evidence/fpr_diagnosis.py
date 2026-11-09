"""Re-run the diagnosis behind the verdict change (DESIGN.md §3.2).

    .venv/bin/python docs/edge_audit/job/evidence/fpr_diagnosis.py

Compares three one-sided 5 % tests on noise_log P&L (the same P&L the audit
sees): V1's classical plug-in DSR/PSR (N = 1), Student's t, and the DSR with
the standard error under H0. Seeds 0..499 are the SPEC scenario's; seeds
10000..13999 are the ones the diagnosis used before the verdict changed.
"""

import math
import warnings
from statistics import NormalDist

import numpy as np
from scipy import stats

from backtest_auditor.edge_audit.skill import assess_luck_vs_skill
from backtest_auditor.edge_audit.synthetic import noise_log

warnings.filterwarnings("ignore")


def pnl_of(frame):
    sign = np.where(frame["side"] == "long", 1.0, -1.0)
    return (
        sign * frame["quantity"] * (frame["exit_price"] - frame["entry_price"])
    ).to_numpy()


def rates(seeds, **options):
    plug_in = student = null = 0
    pairs = []
    for seed in seeds:
        values = pnl_of(noise_log(seed, **options).trades)
        result = assess_luck_vs_skill(values, span_years=1.0, declared_trials=1)
        plug_in += result.dsr_plug_in >= 0.95
        student += stats.ttest_1samp(values, 0.0, alternative="greater").pvalue < 0.05
        null += (
            NormalDist().cdf(result.sharpe_per_trade * math.sqrt(values.size - 1))
            >= 0.95
        )
        pairs.append((result.sharpe_per_trade, result.sample_skewness))
    pairs = np.asarray(pairs)
    count = len(seeds)
    return (
        f"plug-in {plug_in}/{count} = {plug_in / count:.4f}; Student t {student}/{count} = "
        f"{student / count:.4f}; null-SE {null}/{count} = {null / count:.4f}; "
        f"corr(SR, skew) = {np.corrcoef(pairs[:, 0], pairs[:, 1])[0, 1]:.2f}"
    )


print("fat-tailed, seeds 0..499:      ", rates(range(500)))
verdict_hits, student_hits = set(), set()
for seed in range(500):
    values = pnl_of(noise_log(seed).trades)
    if assess_luck_vs_skill(values, span_years=1.0, declared_trials=1).verdict == (
        "evidence_of_edge"
    ):
        verdict_hits.add(seed)
    if stats.ttest_1samp(values, 0.0, alternative="greater").pvalue < 0.05:
        student_hits.add(seed)
print(
    "seeds 0..499, verdict vs Student t: "
    f"{len(verdict_hits)} and {len(student_hits)} rejections, "
    f"{len(verdict_hits & student_hits)} in common"
)
print("normal moves, seeds 0..499:    ", rates(range(500), tail_df=None))
print("fat-tailed, seeds 10000..13999:", rates(range(10_000, 14_000)))
