"""Known-truth scenarios (SPEC deliverable 3, a-e).

Each scenario generates synthetic trade logs whose truth is known, runs the
real audit (CSV-shaped strings -> parse_trade_log -> run_edge_audit) and
compares what the audit reports with the truth over many seeds.

Acceptance bands were fixed in this file before the first run:
* a rate that should be 5 % (a false-positive or false-attribution rate) must
  lie in the two-sided 99 % binomial acceptance region for p = 0.05;
* an interval coverage that should be 95 % must lie in the two-sided 99 %
  region for p = 0.95.
With every seed fixed the outcome is deterministic; under perfect
calibration a band would be missed with probability about 1 %.

Set EDGE_AUDIT_EVIDENCE_DIR to write every measured number to
scenario_results.json there (TEST_RESULTS.txt quotes that file).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from backtest_auditor.edge_audit.audit import AuditSettings, run_edge_audit
from backtest_auditor.edge_audit.costs import break_even_added_cost_bps
from backtest_auditor.edge_audit.decay import DETECTORS
from backtest_auditor.edge_audit.schema import parse_price_table, parse_trade_log
from backtest_auditor.edge_audit.skill import EVIDENCE, assess_luck_vs_skill
from backtest_auditor.edge_audit.synthetic import (
    cost_log,
    decaying_edge_log,
    noise_log,
    sizing_log,
    timing_log,
    to_strings,
)

pytestmark = [
    pytest.mark.filterwarnings(
        "ignore:A future version of pandas will return a BaseOffset"
    ),
    pytest.mark.edge_audit_calibration,
]

RESULTS: dict[str, dict] = {}


@pytest.fixture(scope="module", autouse=True)
def write_evidence():
    yield
    directory = os.environ.get("EDGE_AUDIT_EVIDENCE_DIR")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        path = Path(directory) / "scenario_results.json"
        path.write_text(json.dumps(RESULTS, indent=2, sort_keys=True) + "\n")


def band(count: int, probability: float) -> tuple[int, int]:
    """Two-sided 99 % binomial acceptance region for a count out of ``count``."""

    return (
        int(stats.binom.ppf(0.005, count, probability)),
        int(stats.binom.ppf(0.995, count, probability)),
    )


def clopper_pearson(hits: int, count: int) -> tuple[float, float]:
    lower = 0.0 if hits == 0 else stats.beta.ppf(0.025, hits, count - hits + 1)
    upper = 1.0 if hits == count else stats.beta.ppf(0.975, hits + 1, count - hits)
    return float(lower), float(upper)


def audit(log, *, trials: int = 1, **overrides):
    trades = parse_trade_log(to_strings(log.trades))
    prices = None if log.prices is None else parse_price_table(to_strings(log.prices))
    options = dict(
        declared_trials=trials,
        bootstrap_replications=20,
        permutation_draws=20,
        timing_draws=50,
    )
    options.update(overrides)
    return trades, run_edge_audit(trades, prices, AuditSettings(**options))


# (a) ---------------------------------------------------------------------------


def test_a_noise_logs_false_positive_rate_over_500_seeds():
    seeds = 500
    results = [audit(noise_log(seed))[1].luck_vs_skill for seed in range(seeds)]
    verdicts = [result.verdict for result in results]
    positives = sum(verdict == EVIDENCE for verdict in verdicts)
    plug_in = sum(result.dsr_plug_in >= 0.95 for result in results)
    low, high = band(seeds, 0.05)
    RESULTS["a_noise_false_positive_rate"] = {
        "seeds": seeds,
        "trades_per_log": 250,
        "declared_trials": 1,
        "evidence_verdicts": positives,
        "false_positive_rate": positives / seeds,
        "clopper_pearson_95": clopper_pearson(positives, seeds),
        "acceptance_band_counts": [low, high],
        "insufficient_data_verdicts": sum(v == "insufficient_data" for v in verdicts),
        "classical_plug_in_dsr_false_positive_rate": plug_in / seeds,
    }
    assert low <= positives <= high
    assert "insufficient_data" not in verdicts


def test_a_noise_logs_on_500_fresh_seeds():
    """The SPEC's 500-seed requirement on seeds never run before.

    Seeds 0..499 above produced the failure that changed the verdict's
    standard error, so their second evaluation is after the fact. This block
    (2,000,000..2,000,499) was committed before its first run, with the same
    band as the original test.
    """

    seeds = 500
    first = 2_000_000
    results = [
        audit(noise_log(seed))[1].luck_vs_skill for seed in range(first, first + seeds)
    ]
    positives = sum(result.verdict == EVIDENCE for result in results)
    low, high = band(seeds, 0.05)
    RESULTS["a_noise_500_fresh_seeds"] = {
        "seed_range": [first, first + seeds - 1],
        "seeds": seeds,
        "evidence_verdicts": positives,
        "false_positive_rate": positives / seeds,
        "clopper_pearson_95": clopper_pearson(positives, seeds),
        "classical_plug_in_dsr_false_positive_rate": sum(
            result.dsr_plug_in >= 0.95 for result in results
        )
        / seeds,
        "acceptance_band_counts": [low, high],
    }
    assert low <= positives <= high


def test_a_extended_verdict_calibration_on_4000_held_out_seeds():
    """The verdict function alone (the audit's verdict is exactly this, see
    test_cli_runs_end_to_end_and_the_report_validates) on 4,000 seeds that
    were never run before the verdict's standard error was chosen: seeds
    0..499 and 10000..13999 were used to diagnose the first failure
    (docs/edge_audit/job/evidence/fpr_diagnosis.py), these were not."""

    seeds = 4000
    positives = plug_in = 0
    for seed in range(1_000_000, 1_000_000 + seeds):
        frame = noise_log(seed).trades
        sign = np.where(frame["side"] == "long", 1.0, -1.0)
        pnl = (
            sign * frame["quantity"] * (frame["exit_price"] - frame["entry_price"])
        ).to_numpy()
        result = assess_luck_vs_skill(pnl, span_years=1.0, declared_trials=1)
        positives += result.verdict == EVIDENCE
        plug_in += result.dsr_plug_in >= 0.95
    low, high = band(seeds, 0.05)
    RESULTS["a_extended_4000_held_out_seeds"] = {
        "seed_range": [1_000_000, 1_000_000 + seeds - 1],
        "seeds": seeds,
        "verdict_false_positive_rate": positives / seeds,
        "verdict_clopper_pearson_95": clopper_pearson(positives, seeds),
        "classical_plug_in_dsr_false_positive_rate": plug_in / seeds,
        "plug_in_clopper_pearson_95": clopper_pearson(plug_in, seeds),
        "acceptance_band_counts": [low, high],
    }
    assert low <= positives <= high


def test_a_selection_of_best_of_ten_noise_strategies_is_deflated():
    seeds, family = 300, 10
    naive = deflated = 0
    for seed in range(seeds):
        candidates = [
            noise_log(seed * family + member + 10_000) for member in range(family)
        ]
        sharpes = []
        for candidate in candidates:
            frame = candidate.trades
            sign = np.where(frame["side"] == "long", 1.0, -1.0)
            pnl = (
                sign * frame["quantity"] * (frame["exit_price"] - frame["entry_price"])
            )
            sharpes.append(float(np.mean(pnl) / np.std(pnl, ddof=1)))
        best = candidates[int(np.argmax(sharpes))]
        trades = parse_trade_log(to_strings(best.trades))
        naive += (
            assess_luck_vs_skill(
                trades.net_pnl, span_years=trades.span_years, declared_trials=1
            ).verdict
            == EVIDENCE
        )
        deflated += audit(best, trials=family)[1].luck_vs_skill.verdict == EVIDENCE
    RESULTS["a_best_of_ten_selection"] = {
        "seeds": seeds,
        "family_size": family,
        "naive_trials_1_false_positive_rate": naive / seeds,
        "theory_naive": 1 - 0.95**family,
        "dsr_trials_10_false_positive_rate": deflated / seeds,
        "dsr_clopper_pearson_95": clopper_pearson(deflated, seeds),
    }
    assert naive / seeds > 0.25  # selection inflates the naive test (theory 40 %)
    assert deflated <= band(seeds, 0.05)[1]  # DSR keeps it at or below 5 %


# (b) ---------------------------------------------------------------------------


def _timing_flags(seeds: int, offset: int, **generator) -> dict[str, int]:
    flags = {"entry_timing": 0, "exit_timing": 0, "holding": 0}
    shares = []
    for seed in range(seeds):
        _, result = audit(
            timing_log(seed + offset, **generator),
            timing_draws=1000,
            bootstrap_replications=100,
        )
        components = {item.name: item for item in result.timing.components}
        for name in flags:
            if components[name].finding == "adds P&L (significant)":
                flags[name] += 1
        shares.append(components["entry_timing"].share_of_gross)
    flags["median_entry_share"] = float(np.median(shares))
    return flags


def test_b_injected_entry_alpha_is_attributed_to_entry():
    seeds = 100
    skilled = _timing_flags(seeds, 0, entry_candidates=2)
    control = _timing_flags(seeds, 50_000)
    high = band(seeds, 0.05)[1]
    RESULTS["b_entry_alpha_attribution"] = {
        "seeds": seeds,
        "skill": "entry bar = best of 2 random bars of the entry day",
        "skilled_flag_counts": skilled,
        "control_flag_counts": control,
        "false_flag_upper_band": high,
    }
    assert skilled["entry_timing"] >= 95
    assert skilled["exit_timing"] <= high and skilled["holding"] <= high
    for name in ("entry_timing", "exit_timing", "holding"):
        assert control[name] <= high


# (c) ---------------------------------------------------------------------------


def _alarms(seeds: int, offset: int, **generator) -> dict[str, list]:
    alarms: dict[str, list] = {name: [] for name in DETECTORS}
    for seed in range(seeds):
        # Horizon = the 400 monitored trades, as J9 calibrated (W5-J14: the
        # thresholds now come from the table; 1,000 is only the default).
        _, result = audit(
            decaying_edge_log(seed + offset, **generator), decay_horizon=400
        )
        assert result.decay.status == "computed"
        for item in result.decay.detectors:
            assert item.status == "computed", (item.name, item.reason)
            alarms[item.name].append(item.alarm_trade_number)
    return alarms


def _summary(alarms: list, change_after: int, trades: int) -> dict:
    early = sum(a is not None and a <= change_after for a in alarms)
    delays = [a - change_after for a in alarms if a is not None and a > change_after]
    seeds = len(alarms)
    summary = {
        "false_alarm_before_change": early / seeds,
        "detected_after_change": len(delays) / seeds,
        "missed": sum(a is None for a in alarms) / seeds,
        "post_change_trades": trades - change_after,
    }
    if delays:
        summary.update(
            {
                f"delay_{name}": float(np.percentile(delays, q))
                for name, q in (
                    ("p10", 10),
                    ("p25", 25),
                    ("median", 50),
                    ("p75", 75),
                    ("p90", 90),
                )
            }
        )
    return summary


def test_c_edge_that_disappears_halfway_detection_delay():
    seeds = 200
    decay = _alarms(seeds, 0, trades=600, change_at=300, sharpe_before=0.3)
    control = _alarms(seeds, 70_000, trades=600, change_at=600, sharpe_before=0.3)
    low, high = band(seeds, 0.05)
    RESULTS["c_decay_detection"] = {
        "seeds": seeds,
        "trades": 600,
        "change_after_trade": 300,
        "sharpe_per_trade_before_after": [0.3, 0.0],
        "reference_trades": 200,
        "false_alarm_probability_target": 0.05,
        "horizon": 400,
        "decay": {name: _summary(values, 300, 600) for name, values in decay.items()},
        "no_change_control_any_alarm": {
            name: sum(a is not None for a in values) / seeds
            for name, values in control.items()
        },
        "control_acceptance_band_counts": [low, high],
    }
    cusum = RESULTS["c_decay_detection"]["decay"]["cusum"]
    assert cusum["detected_after_change"] >= 0.70
    assert cusum["false_alarm_before_change"] <= 0.10
    # The table thresholds hold the no-change false-alarm rate at 5 % for every
    # detector (J9: CUSUM and Page-Hinkley only; its Wald SPRT gave 37/200).
    for name in DETECTORS:
        hits = sum(a is not None for a in control[name])
        assert low <= hits <= high, (name, hits)
    # Floors for the calibrated detectors, written by W5-J14 before their first
    # run (J9's post-run guards were SPRT >= 0.80 and Page-Hinkley >= 0.40 for
    # the uncalibrated Wald SPRT): they stop a detector from silently never (or
    # always) alarming.
    decayed = RESULTS["c_decay_detection"]["decay"]
    floors = {
        "rolling_expectancy": 0.70,
        "cusum": 0.70,
        "page_hinkley": 0.40,
        "mixture_sprt": 0.70,
    }
    for name, floor in floors.items():
        assert decayed[name]["detected_after_change"] >= floor, name
        assert decayed[name]["false_alarm_before_change"] <= 0.10, name


# (d) ---------------------------------------------------------------------------


def test_d_break_even_cost_is_recovered_exactly_without_noise():
    log = cost_log(1, gross_edge_bps=8.0, fee_bps=2.0, noise_bps=0.0)
    trades, result = audit(log)
    assert result.costs.break_even_added_cost_bps.point == pytest.approx(6.0, abs=1e-9)
    assert result.costs.gross_break_even_cost_bps == pytest.approx(8.0, abs=1e-9)
    assert result.costs.fees_paid_bps == pytest.approx(2.0, abs=1e-9)
    curve = {
        round(point.added_cost_bps, 6): point.expectancy for point in result.costs.curve
    }
    assert curve[6.0] == pytest.approx(0.0, abs=1e-6)
    assert break_even_added_cost_bps(trades.net_pnl, trades.notional) == pytest.approx(
        6.0
    )


def test_d_break_even_interval_covers_the_truth_over_seeds():
    seeds = 200
    covered = 0
    errors = []
    for seed in range(seeds):
        log = cost_log(seed, gross_edge_bps=8.0, fee_bps=2.0, noise_bps=40.0)
        _, result = audit(log, bootstrap_replications=500)
        interval = result.costs.break_even_added_cost_bps
        covered += interval.lower <= 6.0 <= interval.upper
        errors.append(interval.point - 6.0)
    low, high = band(seeds, 0.95)
    RESULTS["d_break_even_recovery"] = {
        "seeds": seeds,
        "true_added_break_even_bps": 6.0,
        "coverage_95_interval": covered / seeds,
        "acceptance_band_counts": [low, high],
        "mean_error_bps": float(np.mean(errors)),
        "median_absolute_error_bps": float(np.median(np.abs(errors))),
    }
    assert low <= covered <= high
    assert abs(np.mean(errors)) < 0.5


# (e) ---------------------------------------------------------------------------


def test_e_fixed_size_counterfactual_removes_the_sizing_contribution():
    seeds = 200
    trades_per_log = 400
    fixed_covers_zero = sizing_covers_truth = fixed_evidence = actual_evidence = 0
    for seed in range(seeds):
        log = sizing_log(seed, trades=trades_per_log)
        trades, result = audit(log, bootstrap_replications=500, permutation_draws=200)
        sizing = result.sizing
        truth = (
            log.truth["sizing_contribution_per_trade"]
            * (trades_per_log - 1)
            / trades_per_log
        )
        notional, net_return = trades.notional, trades.net_return
        covariance = np.mean(
            (notional - notional.mean()) * (net_return - net_return.mean())
        )
        assert sizing.sizing_contribution_per_trade.point == pytest.approx(
            covariance, rel=1e-9
        )
        fixed = sizing.fixed_size_expectancy
        fixed_covers_zero += fixed.lower <= 0.0 <= fixed.upper
        contribution = sizing.sizing_contribution_per_trade
        sizing_covers_truth += contribution.lower <= truth <= contribution.upper
        fixed_evidence += sizing.fixed_size_verdict == EVIDENCE
        actual_evidence += result.luck_vs_skill.verdict == EVIDENCE
    low, high = band(seeds, 0.95)
    RESULTS["e_sizing_counterfactual"] = {
        "seeds": seeds,
        "true_fixed_size_expectancy": 0.0,
        "true_sizing_contribution_per_trade": 8.0
        * (trades_per_log - 1)
        / trades_per_log,
        "fixed_size_interval_covers_zero": fixed_covers_zero / seeds,
        "sizing_interval_covers_truth": sizing_covers_truth / seeds,
        "fixed_size_evidence_rate": fixed_evidence / seeds,
        "actual_evidence_rate": actual_evidence / seeds,
        "coverage_acceptance_band_counts": [low, high],
    }
    assert low <= fixed_covers_zero <= high
    assert low <= sizing_covers_truth <= high
    assert fixed_evidence <= band(seeds, 0.05)[1]
    assert actual_evidence >= 0.8 * seeds
