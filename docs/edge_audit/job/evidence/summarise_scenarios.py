"""Print the known-truth scenario numbers for TEST_RESULTS.txt.

    .venv/bin/python docs/edge_audit/job/evidence/summarise_scenarios.py

Reads scenario_results.json next to this file (written by
tests/edge_audit/test_edge_audit_scenarios.py when EDGE_AUDIT_EVIDENCE_DIR
points here).
"""

import json
from pathlib import Path

results = json.loads((Path(__file__).parent / "scenario_results.json").read_text())


def pct(value: float) -> str:
    return f"{100 * value:.2f} %"


f = results["a_noise_500_fresh_seeds"]
low, high = f["acceptance_band_counts"]
print(
    f"(a) SPEC result — 500 noise logs on seeds never run before the verdict changed "
    f"({f['seed_range'][0]}-{f['seed_range'][1]}), 250 trades each, --trials 1: "
    f"{f['evidence_verdicts']}/{f['seeds']} 'evidence' = {pct(f['false_positive_rate'])} "
    f"(Clopper-Pearson 95 % {pct(f['clopper_pearson_95'][0])}-{pct(f['clopper_pearson_95'][1])}); "
    f"'no evidence' in {pct(1 - f['false_positive_rate'])}; band {low}-{high}: PASS. "
    f"Classical plug-in DSR on the same logs: "
    f"{round(f['classical_plug_in_dsr_false_positive_rate'] * f['seeds'])}/{f['seeds']}."
)
h = results["a_extended_4000_held_out_seeds"]
print(
    f"(a) 4,000 held-out logs, seeds {h['seed_range'][0]}-{h['seed_range'][1]}: verdict "
    f"{round(h['verdict_false_positive_rate'] * h['seeds'])}/{h['seeds']} = "
    f"{pct(h['verdict_false_positive_rate'])} (95 % {pct(h['verdict_clopper_pearson_95'][0])}-"
    f"{pct(h['verdict_clopper_pearson_95'][1])}); classical plug-in DSR "
    f"{round(h['classical_plug_in_dsr_false_positive_rate'] * h['seeds'])}/{h['seeds']} (95 % "
    f"{pct(h['plug_in_clopper_pearson_95'][0])}-{pct(h['plug_in_clopper_pearson_95'][1])})."
)
a = results["a_noise_false_positive_rate"]
low, high = a["acceptance_band_counts"]
print(
    f"(a) after the fact — the original seeds 0-499, whose failure caused the change: "
    f"{a['evidence_verdicts']}/{a['seeds']} = {pct(a['false_positive_rate'])} (Clopper-Pearson "
    f"95 % {pct(a['clopper_pearson_95'][0])}-{pct(a['clopper_pearson_95'][1])}, excludes 5 %); "
    f"band {low}-{high}: pass; a one-sided Student t-test rejects on the same 36 logs "
    f"(fpr_diagnosis_output.txt). Classical plug-in DSR: "
    f"{round(a['classical_plug_in_dsr_false_positive_rate'] * a['seeds'])}/{a['seeds']}."
)
s = results["a_best_of_ten_selection"]
print(
    f"(a) best of {s['family_size']} noise strategies, {s['seeds']} seeds: undeflated test "
    f"{pct(s['naive_trials_1_false_positive_rate'])} (theory {pct(s['theory_naive'])}); "
    f"DSR at --trials {s['family_size']} {pct(s['dsr_trials_10_false_positive_rate'])}."
)
b = results["b_entry_alpha_attribution"]
sk, co = b["skilled_flag_counts"], b["control_flag_counts"]
print(
    f"(b) entry alpha ({b['skill']}), {b['seeds']} seeds: entry flagged 'adds P&L' in "
    f"{sk['entry_timing']}/{b['seeds']}, exit {sk['exit_timing']}, holding {sk['holding']}; "
    f"median entry share of gross P&L {pct(sk['median_entry_share'])}. No-skill control: entry "
    f"{co['entry_timing']}, exit {co['exit_timing']}, holding {co['holding']} (band <= "
    f"{b['false_flag_upper_band']})."
)
c = results["c_decay_detection"]
print(
    f"(c) edge SR {c['sharpe_per_trade_before_after'][0]} -> {c['sharpe_per_trade_before_after'][1]} "
    f"after trade {c['change_after_trade']} of {c['trades']}, reference {c['reference_trades']} "
    f"trades, {c['seeds']} seeds; detection delay in trades after the change:"
)
for name in ("cusum", "page_hinkley", "sprt"):
    d = c["decay"][name]
    print(
        f"    {name:12s} detected {pct(d['detected_after_change'])}, false alarm before change "
        f"{pct(d['false_alarm_before_change'])}, missed {pct(d['missed'])}; delay p10 "
        f"{d['delay_p10']:.0f}, p25 {d['delay_p25']:.0f}, median {d['delay_median']:.1f}, p75 "
        f"{d['delay_p75']:.0f}, p90 {d['delay_p90']:.0f}"
    )
control = c["no_change_control_any_alarm"]
low, high = c["control_acceptance_band_counts"]
print(
    f"    no-change control (any alarm over 400 monitored trades, target 5 %): cusum "
    f"{pct(control['cusum'])}, page_hinkley {pct(control['page_hinkley'])} (band {low}-{high} "
    f"of {c['seeds']}), sprt {pct(control['sprt'])} (not calibrated to the horizon)."
)
d = results["d_break_even_recovery"]
low, high = d["acceptance_band_counts"]
print(
    f"(d) break-even: exact without noise (6.0 bps, |error| < 1e-9); with noise, {d['seeds']} "
    f"seeds: 95 % interval covers the true {d['true_added_break_even_bps']} bps in "
    f"{pct(d['coverage_95_interval'])} (band {low}-{high}), mean error {d['mean_error_bps']:.3f} "
    f"bps, median |error| {d['median_absolute_error_bps']:.2f} bps."
)
e = results["e_sizing_counterfactual"]
low, high = e["coverage_acceptance_band_counts"]
print(
    f"(e) sizing, {e['seeds']} seeds: fixed-size expectancy interval covers the true 0 in "
    f"{pct(e['fixed_size_interval_covers_zero'])}; sizing-contribution interval covers the true "
    f"{e['true_sizing_contribution_per_trade']:.2f} in {pct(e['sizing_interval_covers_truth'])} "
    f"(band {low}-{high}); fixed-size verdict 'evidence' in {pct(e['fixed_size_evidence_rate'])}, "
    f"actual log 'evidence' in {pct(e['actual_evidence_rate'])}."
)
