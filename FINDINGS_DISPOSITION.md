# FINDINGS_DISPOSITION — the 16 strict xfails open in 1.5.1, settled in 1.5.2

Branch `wave2/1.5.2-report-fix`. 1.5.1 (tag `v1.5.1`, 21600b3) carried 16 strict xfails for 12 findings.
**12 xfails (8 findings) are fixed** and now pass unchanged; **4 xfails (4 findings) are kept**,
because the behaviour they pin is a documented convention or a property of the method, not a
defect. `tests/test_findings_disposition.py` parses the two tables below and fails if the strict
xfails in `tests/` differ from the "Kept" table, or if a "Fixed" row still has a marker.

Consolidation (W5-J1, `wave5/rc-1.5.2`): `wave3/adapter-e2e` added two strict xfails in `tests/e2e`
after this file was written. They are registered below as **E01** and **E02**, kept as open limits that wait for Krste's choice (W3-J12 REVIEW
8a, 8b); unlike F01, F02, F05 and F07 they are not judged correct behaviour. The rule above still holds for every
strict xfail in `tests/`: 6 kept, none unregistered.

Verdict key: **defect** = the code does something its own contract says it must not; **convention**
= a documented choice between estimators that the literature uses both ways; **method property** =
the code computes the documented method exactly and the method itself behaves this way; **design** =
a deliberate safety rule with a documented route around it; **open (decision)** = a known limit kept as a strict
xfail until Krste chooses the fix, not a verdict that the behaviour is correct (E01, E02 only).

## Fixed (xfail removed, test body unchanged)

| id | claim (from the xfail) | verdict | fix commit | evidence (fails on 1.5.1, passes here) |
|---|---|---|---|---|
| N18 | variance-ratio z too small by √n: SE = √θ, not √(θ/n); also the p-value needs a tail-accurate normal | defect | e1fc1cd | `tests/adversarial/test_v14_statistics_reference.py::test_variance_ratio_z_standard_error_and_p_match_lo_mackinlay_1988`, `::test_variance_ratio_z_is_standard_normal_under_iid_and_detects_ar1`; `tests/test_contradiction_stat_bug.py` (1.5.1: sd(z) 0.0324, AR(1) z 0.27; branch: sd(z) 1.0255, z 8.5036 = Lo–MacKinlay z\*); `tests/unit/test_v152_report_consequences.py::test_n18_an_ar1_series_now_carries_the_variance_ratio_finding` |
| N21 | runs-test continuity correction adds 0.5 when R = E (z 0.38, p 0.70 instead of 0, 1) | defect | e5667a9 | `test_v14_statistics_reference.py::test_runs_continuity_correction_when_runs_equal_their_expectation`; `test_v152_report_consequences.py::test_n21_runs_within_half_a_run_of_their_expectation_publish_z_0_p_1` |
| N13 | canonical decimals silently rounded to 28 significant digits (bundle and vectorbt mapping) | defect | 8fade30, 5d5e5bd, 1db9494 | `tests/adversarial/test_v15_bundle_and_adapters.py::test_canonical_bundle_does_not_silently_round_high_precision_decimal`, `::test_vectorbt_adapter_does_not_silently_round_high_precision_values`; `tests/unit/implementation_risk/test_decimal_precision.py`; `tests/adversarial/test_v152_decimal_arithmetic.py` (5d5e5bd, after the adversarial review: 8fade30 alone made the bundle's fill sums reject a 30-digit filled order, and the Lean and Nautilus position sums still rounded; sums and negations are now exact; 1db9494, after the third pass: abs() and unary minus in the bt, Backtrader, Lean, Nautilus and vectorbt adapters and the LEAN exporter, and a 100-digit bound on exact sums) |
| N14 | the header_mismatch error does not name the missing CSV column | defect | fd379f1 | `test_v15_bundle_and_adapters.py::test_adapter_missing_column_error_names_the_missing_column`; `tests/unit/implementation_risk/test_header_names.py` (the bundle's own CSV readers too) |
| N15 | the invalid_metadata error does not name the missing adapter-metadata key | defect | 1eaccd3 | `test_v15_bundle_and_adapters.py::test_adapter_missing_metadata_key_error_names_the_key`; `tests/unit/implementation_risk/test_metadata_key_names.py` |
| F06 | mixed UTC offsets raise a pandas ValueError out of normalize_return_series, not INVALID_TIMESTAMP | defect | b926a0f, 1df5407, 773d3e4 | `tests/adversarial/test_index_hygiene.py::test_mixed_offsets_in_one_file_are_rejected_inside_the_validation_contract`; `test_v152_report_consequences.py::test_f06_mixed_offsets_get_the_machine_readable_envelope`; `tests/unit/ingestion/test_mixed_offsets.py` (family returns, splits, regimes, sessions: each raised the same ValueError; 773d3e4: an unparseable row beside mixed offsets is still reported, and offsets are named only when two rows differ) |
| F04 | percent-unit returns pass silently (cumulative −100 % vs +8 %); the −1 rejection does not mention percent units | defect | dff4216 | `tests/adversarial/test_annualization_units.py::test_percent_units_without_large_losses_pass_silently`, `::test_percent_units_with_a_loss_over_one_percent_are_rejected_with_a_misleading_code`; `test_v152_report_consequences.py::test_f04_*` (silent on four real decimal curves) |
| F03 | periods_per_year is never compared with the sampling it scales (24/7 daily with 252, business days with 365) | defect | b48d554 | `test_annualization_units.py::test_crypto_daily_series_declared_252_is_flagged`, `::test_business_day_series_declared_365_is_flagged`; `test_v152_report_consequences.py::test_f03_*` (silent on B/252, D/365, W/52, MS/12, h/8760) |

F03 and F04 are new warnings rather than changed numbers: the declaration and the input are still
used as given, and the report says when they look inconsistent. Thresholds (Krste can change
them; docs/history/w2-j6/ASSUMPTIONS.md J6-5, J6-6): F03 reports a declared periods-per-year more than a factor 1.2
away from the rate the timestamps imply, over spans of 28 days or more; F04 reports a mean absolute
return above 0.05 per period at daily or faster sampling, 0.05·√(median interval in days) slower.
F04 is a magnitude heuristic with known limits, found by the adversarial review and kept as
designed (night 3's rule). It also fires on genuine decimal series with daily volatility above about
6 % (a 7 % altcoin, a 6.5 % triple-leveraged ETF) and on a three-observation series of ±8 %. It
misses percent-unit data whose magnitudes stay small: 1-minute equity bars at mean |r| 0.04 and a
T-bill series at 0.02, because faster-than-daily sampling keeps the 0.05 floor. The warning is
non-blocking.

### The twelve tests that were strict xfails in 1.5.1 (now passing, unchanged)

`tests/test_findings_disposition.py` collects the suite and requires each of these to be collected with no
xfail, skip or skipif marker, unless its module is skipped at collection for a missing optional dependency
(statsmodels/arch).

```text
N18 tests/adversarial/test_v14_statistics_reference.py::test_variance_ratio_z_standard_error_and_p_match_lo_mackinlay_1988
N18 tests/adversarial/test_v14_statistics_reference.py::test_variance_ratio_z_is_standard_normal_under_iid_and_detects_ar1
N21 tests/adversarial/test_v14_statistics_reference.py::test_runs_continuity_correction_when_runs_equal_their_expectation
N13 tests/adversarial/test_v15_bundle_and_adapters.py::test_canonical_bundle_does_not_silently_round_high_precision_decimal
N13 tests/adversarial/test_v15_bundle_and_adapters.py::test_vectorbt_adapter_does_not_silently_round_high_precision_values
N14 tests/adversarial/test_v15_bundle_and_adapters.py::test_adapter_missing_column_error_names_the_missing_column
N15 tests/adversarial/test_v15_bundle_and_adapters.py::test_adapter_missing_metadata_key_error_names_the_key
F06 tests/adversarial/test_index_hygiene.py::test_mixed_offsets_in_one_file_are_rejected_inside_the_validation_contract
F04 tests/adversarial/test_annualization_units.py::test_percent_units_with_a_loss_over_one_percent_are_rejected_with_a_misleading_code
F04 tests/adversarial/test_annualization_units.py::test_percent_units_without_large_losses_pass_silently
F03 tests/adversarial/test_annualization_units.py::test_crypto_daily_series_declared_252_is_flagged
F03 tests/adversarial/test_annualization_units.py::test_business_day_series_declared_365_is_flagged
```

## Kept (strict xfail stays; the reason is the verdict below)

| id | test | claim | verdict | evidence |
|---|---|---|---|---|
| F01 | `tests/adversarial/test_sharpe_psr_dsr.py::test_dsr_variance_convention_ddof` | the DSR uses the n − 1 cross-trial variance; the test expects the plug-in (ddof = 0) of López de Prado's published code | convention | The README defines the benchmark from the "cross-trial sample Sharpe standard deviation" (README.md:422, Deflated Sharpe Ratio section); `test_dsr_matches_reference` (ddof = 1, BLdP 2014 eq. 7–8) passes. Run as a plain test: `DSR ddof=1 (V1)=0.392456 vs ddof=0=0.427062`. The n − 1 spread is larger, so the threshold is higher and the DSR lower: the conservative side. The sample report states the convention next to the number (§3.3). Flips only if the estimator is changed. |
| F02 | `tests/adversarial/test_bootstrap.py::test_ninety_five_percent_interval_coverage_on_iid_normal_sharpe` | the percentile moving-block 95 % interval covers 92.6 % (500 simulations, n = 500) | method property | `test_percentile_interval_matches_reference_given_same_resampling_rng` passes: the bounds equal an independent implementation given the same draws, so the arithmetic is exact. The 92.6 % is one seed set: the same construction on four disjoint sets of 500 seeds gives 92.6 / 97.0 / 95.0 / 92.6 %, pooled 94.3 % (SE 0.5 points, `notes/evidence/f02_coverage_seeds.py`). The W2-J6 reviewer's own seed sets pooled 93.3 %. So any under-coverage is one to two points, as night 3 expected for Efron percentile intervals of a ratio statistic. Night 3 measured the iid percentile bootstrap at the same 92.6 %, so the block design is not the cause. README.md:915–919 defines the interval as the empirical quantiles; the report calls it "approximately 95 %". A different interval (basic, BCa, studentized) is a new feature, not a repair. The test's fixed seeds make the xfail deterministic, and with a 2-point band on 500 runs it would pass or fail with the seed set. |
| F05 | `tests/adversarial/test_index_hygiene.py::test_single_holiday_gap_makes_a_business_day_series_ineligible_for_annualization` | one missing exchange holiday makes a business-day series ineligible for annualization (declared B, undeclared, and the weekday calendar alike) | design | Regularity is exact on purpose: a gap the auditor cannot explain is not annualized. The documented route is a sessions CSV (README.md:958–970: exact matches receive `calendar_verified` and can qualify for annualization). `tests/test_findings_disposition.py::test_f05_a_sessions_csv_without_the_holiday_makes_the_same_series_eligible` passes: the same 119 returns with the holiday left out of the session list are `calendar_verified`, annualization-eligible, with a Sharpe ratio. The sample report uses this route (§3.4, 51 holidays nulled nothing). Run as a plain test: `calendar status=mismatch, missing=('2024-02-19',)`. Accepting gaps silently would be a behaviour change Krste would have to choose. |
| F07 | `tests/adversarial/test_serial.py::test_negative_autocorrelation_raises_hac_psr_and_effective_observations_above_n` | under negative autocorrelation the HAC adjustment raises the PSR and the effective count exceeds n (569 from 300); the test expects the count capped at n | convention | Lo (2002) eq. 20 gives the same numbers: `test_full_lo_horizon_equals_lo_2002_equation_20` and `test_hac_with_tiny_sample_and_max_lag_close_to_n` pass. docs/V1_4_STATISTICAL_METHODS.md:55–57: "It is a variance-equivalence diagnostic, not additional data; negative dependence can make it exceed `n`." The sample report says the adjustment raised the figures and quotes the IID rows (§5.1). Run as a plain test: `n=300 but effective_observation_count=569.1`. Flips only if the package caps the count. |
| E01 | `tests/e2e/test_nautilustrader.py::test_lookahead_defect_is_flagged` | a one-bar look-ahead in a real NautilusTrader 1.231.0 run is named as adverse divergence | open (decision) | Added by `wave3/adapter-e2e` (W3-J12; `tests/e2e/MATRIX.md` note D). The D3 Nautilus bundle has no fixed-grid level (no equity or return; cash rows only at account events), so the shifted run makes every fill, cost, trade and balance row one-sided: `evidence_gap` findings, never adverse. An adapter-design limit, not an engine defect (`docs/history/w3-j12/BLOCKED.md`). Flips only if the Nautilus exporter records per-bar equity, a choice W3-J12 left to Krste. |
| E02 | `tests/e2e/test_backtrader.py::test_cheat_on_close_snapshots_include_same_bar_fills` | with `broker.set_coc(True)`, the bundle's position, cash and equity at a fill bar include that bar's fill | open (decision) | Added by `wave3/adapter-e2e` (W3-J12; `tests/e2e/MATRIX.md` note E). Backtrader dates the fill at bar t but books it in the next cycle, after the audit analyzer recorded bar t, so every fill bar shows the pre-fill state (position off by 100 shares, cash by price·100 + fee, equity by the $1 fee). Flips only if the exporter re-dates cheat-on-close executions or refuses such runs, a choice W3-J12 left to Krste. |

Re-run the four as plain tests (each fails with the numbers quoted above):

```
.venv/bin/python -m pytest -q --runxfail \
  tests/adversarial/test_sharpe_psr_dsr.py::test_dsr_variance_convention_ddof \
  tests/adversarial/test_serial.py::test_negative_autocorrelation_raises_hac_psr_and_effective_observations_above_n \
  tests/adversarial/test_index_hygiene.py::test_single_holiday_gap_makes_a_business_day_series_ineligible_for_annualization \
  tests/adversarial/test_bootstrap.py::test_ninety_five_percent_interval_coverage_on_iid_normal_sharpe
```

Re-run E01 and E02 the same way (each fails with the mismatch its reason describes; needs `requirements-adapters.txt`):

```
.venv/bin/python -m pytest -q --runxfail \
  tests/e2e/test_nautilustrader.py::test_lookahead_defect_is_flagged \
  tests/e2e/test_backtrader.py::test_cheat_on_close_snapshots_include_same_bar_fills
```
