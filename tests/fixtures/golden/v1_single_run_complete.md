# Backtest Integrity Audit

- Schema version: `2.5`
- Audit type: `single_run`
- Run ID: `golden-single-run`

## Dimensioned evidence profile

- Method: `dimensioned_evidence_profile_v1`
- Overall status: `not calculated`
- Interpretation boundary: Each dimension is independent. No numeric score or global pass/fail is calculated, and no status certifies skill, profit, or future performance.

| Dimension | Status | Summary | Supporting evidence | Adverse evidence | Unavailable evidence | Assumptions | Next evidence required |
|---|---|---|---|---|---|---|---|
| input_integrity | supported_under_stated_assumptions | The input passed the canonical blocking validation contract. | CANONICAL_INPUT_ACCEPTED | none | none | BLOCKING_INPUT_ERRORS_REJECTED_BEFORE_AUDIT | none |
| return_methodology | supported_under_stated_assumptions | The return-construction declaration is complete without an explicit adverse flag. | RETURN_CONSTRUCTION_DECLARATION_COMPLETE | none | none | RETURN_CONSTRUCTION_FIELDS_ARE_PRODUCER_DECLARATIONS | none |
| sampling_eligibility | supported_under_stated_assumptions | Sampling supports annualization under the explicit frequency scale. | SAMPLING_STATUS_CALENDAR_VERIFIED, ANNUALIZATION_ELIGIBLE | none | none | PERIODS_PER_YEAR_EXPLICIT_OR_VERIFIED | none |
| statistical_evidence | supported_under_stated_assumptions | The configured PSR confidence requirement is met. | PROBABILISTIC_SHARPE_RATIO_AVAILABLE, PSR_CONFIDENCE_REQUIREMENT_MET, ADVANCED_DOWNSIDE_TAIL_STATISTICS_AVAILABLE, TIME_VARYING_RISK_FREE_SERIES_ALIGNED | none | none | ASYMPTOTIC_HIGHER_MOMENT_SHARPE_INFERENCE | none |
| serial_robustness | supported_under_stated_assumptions | The configured HAC adjustment is available without a failed requirement. | HAC_ADJUSTMENT_ELIGIBLE, PARTIAL_AUTOCORRELATIONS_AVAILABLE, HAC_PSR_CONFIDENCE_REQUIREMENT_MET | none | none | BARTLETT_HAC_WITH_EXPLICIT_BANDWIDTH | none |
| resampling_robustness | fragile | The bootstrap period-Sharpe interval is not strictly above zero. | BOOTSTRAP_PERIOD_SHARPE_INTERVAL_AVAILABLE | BOOTSTRAP_PERIOD_SHARPE_LOWER_BOUND_NOT_POSITIVE | none | MOVING_BLOCK_LENGTH_USER_SUPPLIED, ZERO_PERIOD_SHARPE_REFERENCE | Treat resampling support as fragile under the configured interval. |
| benchmark_evidence | supported_under_stated_assumptions | Benchmark-relative evidence is available on exact timestamps. | BENCHMARK_EXACT_TIMESTAMP_ALIGNMENT, BENCHMARK_ALPHA_HAC_INFERENCE_AVAILABLE | none | none | BENCHMARK_COMPARABILITY_DECLARATIONS_APPLY | none |
| temporal_robustness | supported_under_stated_assumptions | Conditional statistics are available for externally declared regimes. | DECLARED_REGIME_ANALYSIS_AVAILABLE | none | none | REGIME_LABELS_ARE_EXTERNAL_PRODUCER_DECLARATIONS, REGIMES_ARE_NOT_INFERRED_OR_OPTIMIZED | none |
| reproducibility | insufficient_evidence | A deterministic audit-run manifest was not configured. | none | none | AUDIT_RUN_MANIFEST_NOT_CONFIGURED | none | Supply an audit ID, timezone-aware audit timestamp, and Git revision together. |

## Audit-run manifest

No deterministic run manifest was configured. Audit ID, timestamp, and Git revision are never inferred.

## Sampling assessment

| Property | Value |
|---|---:|
| Status | calendar_verified |
| Declared frequency | D |
| Inferred frequency | D |
| Periods per year | 365 |
| Interval count | 4 |
| Minimum interval (seconds) | 86400 |
| Maximum interval (seconds) | 86400 |
| Annualization eligible | true |

## Descriptive statistics

| Metric | Value |
|---|---:|
| Observation count | 5 |
| Start timestamp | 2026-01-01T00:00:00 |
| End timestamp | 2026-01-05T00:00:00 |
| Mean return | 0.0024 |
| Sample volatility | 0.00647495173727 |
| Minimum return | -0.005 |
| Maximum return | 0.01 |
| Cumulative simple return | 0.0119732877841 |
| Input return convention | simple |

## Distribution statistics

| Metric | Value |
|---|---:|
| Return basis | simple |
| Sample skewness | 0.0137219764665 |
| Sample excess kurtosis | -2.40911714099 |
| Sample Pearson kurtosis | 0.590882859011 |

Method note: skewness and kurtosis use finite-sample bias corrections. Pearson kurtosis equals 3 for a normal distribution; excess kurtosis equals 0.

## Strategy observation calendar

| Property | Value |
|---|---:|
| Status | verified |
| Calendar name | 24/7 |
| Verification source | built_in_24_7 |
| Calendar timezone | UTC |
| Timestamp timezone | UTC |
| Observation count | 5 |
| Observed session count | 5 |
| Expected session count | 5 |
| Missing session dates | none |
| Unexpected session dates | none |

Method note: built-in `24/7` and `WEEKDAYS` policies generate daily sessions. A named exchange declaration is not treated as verified unless authoritative session dates are supplied. The weekday policy is not an exchange-holiday calendar.

## Strategy return construction

| Property | Value |
|---|---:|
| Metadata supplied | true |
| Declared / required fields | 13 / 13 |
| Completeness ratio | 1 |
| Cost basis | net_of_all_declared_costs |
| Transaction costs included | true |
| Fees included | true |
| Leverage policy | unlevered |
| Currency | USD |
| Price adjustment policy | adjusted |
| Data source | synthetic-release-example |
| Data vintage | 2026-08-12 |
| Stale-price policy | reject stale prices |
| Delisting-return policy | include terminal returns |
| Survivorship bias controlled | true |
| Look-ahead bias controlled | true |
| Signal timing | close t |
| Execution timing | open t+1 |

## Performance path evidence

| Metric | Value |
|---|---:|
| Return basis | simple |
| Starting wealth | 1 |
| Ending wealth | 1.01197328778 |
| Cumulative simple return | 0.0119732877841 |
| CAGR | 1.38418841306 |
| CAGR periods per year | 365 |
| Maximum drawdown | -0.005 |
| Maximum-drawdown peak | 2026-01-01T00:00:00 |
| Maximum-drawdown trough | 2026-01-02T00:00:00 |
| Maximum-drawdown recovery | 2026-01-03T00:00:00 |
| Maximum drawdown recovered | true |
| Maximum-drawdown duration (observations) | 2 |
| Longest time underwater (observations) | 1 |
| Longest-underwater start | 2026-01-02T00:00:00 |
| Longest-underwater end | 2026-01-02T00:00:00 |

Method note: wealth starts at 1.0 and all path calculations use period simple returns. CAGR uses the explicit eligible periods-per-year scale and observation count; it is not inferred from wall-clock time. Drawdown running peaks include initial wealth, so the peak timestamp is undefined when the path falls below 1.0 immediately.

## Downside, tail, and drawdown risk

| Metric | Value |
|---|---:|
| Status | eligible |
| Observation count | 5 |
| Return basis | simple |
| Minimum acceptable period return | 0 |
| Tail confidence level | 0.95 |
| Downside observations | 2 |
| Downside deviation | 0.00260768096208 |
| Period Sortino ratio | 0.920357986617 |
| Annualized Sortino ratio | 17.5834146453 |
| Omega ratio | 2.5 |
| Historical loss VaR | 0.005 |
| Historical expected shortfall | 0.005 |
| Calmar ratio | 276.837682611 |
| Ulcer Index | 0.00260768096208 |

Method note: historical VaR/expected shortfall are empirical loss statistics, Sortino and Omega use the declared period target, and Calmar/Ulcer use the supplied wealth path. No distribution is fitted.

## Time-varying risk-free evidence

| Metric | Value |
|---|---:|
| Alignment status | eligible |
| Paired role | risk_free |
| Strategy / paired observations | 5 / 5 |
| Exactly aligned observations | 5 |
| Strategy-only timestamps | none |
| Paired-only timestamps | none |
| Mean period risk-free return | 0.000104 |
| Cumulative risk-free return | 0.000520108111231 |
| Mean period excess return | 0.002296 |
| Excess-return sample volatility | 0.00647294600626 |
| Period excess Sharpe ratio | 0.35470711447 |
| Annualized excess Sharpe ratio | 6.77666990676 |

Boundary: this additive series calculation does not silently replace the explicitly configured scalar risk-free assumption used by the legacy Sharpe/PSR/HAC methods.

## Gross-to-net cost drag

| Metric | Value |
|---|---:|
| Alignment status | eligible |
| Paired role | gross_strategy |
| Strategy / paired observations | 5 / 5 |
| Exactly aligned observations | 5 |
| Strategy-only timestamps | none |
| Paired-only timestamps | none |
| Mean period cost drag | 0.0005 |
| Cumulative gross return | 0.0144997671832 |
| Cumulative net return | 0.0119732877841 |
| Cumulative cost drag | 0.00252647939915 |
| Annualized arithmetic cost drag | 0.1825 |
| Positive / negative drag periods | 5 / 0 |

## Declared-regime slices

| Property | Value |
|---|---:|
| Status | eligible |
| Aligned observations | 5 |
| Distinct regimes | 2 |
| Strategy-only timestamps | none |
| Regime-only timestamps | none |

| Regime | Observations | Mean return | Sample volatility | Cumulative return | Period Sharpe |
|---|---:|---:|---:|---:|---:|
| risk_off | 2 | -0.004 | 0.00141421356237 | -0.007985 | -2.89913780286 |
| risk_on | 3 | 0.00666666666667 | 0.00381881307913 | 0.0201189375 | 1.71584942171 |

Boundary: regimes are supplied labels, not inferred market states; these slices are descriptive and do not correct selection bias.

## Benchmark-relative evidence

| Alignment property | Value |
|---|---:|
| Status | eligible |
| Strategy observations | 5 |
| Benchmark observations | 5 |
| Aligned observations | 5 |
| Strategy-only timestamps | none |
| Benchmark-only timestamps | none |

| Relative metric | Value |
|---|---:|
| Benchmark ID | market |
| Return basis | simple |
| Strategy cumulative return | 0.0119732877841 |
| Benchmark cumulative return | 0.00598492008414 |
| Relative wealth return | 0.00595274102063 |
| Mean period active return | 0.0012 |
| Period tracking error | 0.00265988721565 |
| Annualized tracking error | 0.0508170739024 |
| Period information ratio | 0.451146948238 |
| Annualized information ratio | 8.61915034387 |
| Return correlation | 0.997972238162 |
| Beta | 1.68537414966 |
| Period arithmetic alpha | 0.000377551020408 |
| Annualized arithmetic alpha | 0.137806122449 |

Method note: active return is strategy simple return minus benchmark simple return. Information ratio uses sample tracking error. Beta and alpha are sample OLS moment estimates with an intercept. Annualized fields use the same explicit scale as the strategy audit and are withheld when that scale is ineligible. These relative annualizations are IID-style point estimates; Part H does not automatically adjust active-return statistics.

## Benchmark observation calendar

| Property | Value |
|---|---:|
| Status | verified |
| Calendar name | 24/7 |
| Verification source | built_in_24_7 |
| Calendar timezone | UTC |
| Timestamp timezone | UTC |
| Observation count | 5 |
| Observed session count | 5 |
| Expected session count | 5 |
| Missing session dates | none |
| Unexpected session dates | none |

Method note: built-in `24/7` and `WEEKDAYS` policies generate daily sessions. A named exchange declaration is not treated as verified unless authoritative session dates are supplied. The weekday policy is not an exchange-holiday calendar.

## Benchmark return construction

| Property | Value |
|---|---:|
| Metadata supplied | true |
| Declared / required fields | 13 / 13 |
| Completeness ratio | 1 |
| Cost basis | net_of_all_declared_costs |
| Transaction costs included | true |
| Fees included | true |
| Leverage policy | unlevered |
| Currency | USD |
| Price adjustment policy | adjusted |
| Data source | synthetic-release-example |
| Data vintage | 2026-08-12 |
| Stale-price policy | reject stale prices |
| Delisting-return policy | include terminal returns |
| Survivorship bias controlled | true |
| Look-ahead bias controlled | true |
| Signal timing | close t |
| Execution timing | open t+1 |

## Benchmark alpha inference

| Metric | Value |
|---|---:|
| Status | eligible |
| Observation count | 5 |
| Bartlett-HAC maximum lag | 1 |
| Confidence level | 0.95 |
| Period alpha | 0.000377551020408 |
| Beta | 1.68537414966 |
| HAC standard error | 0.0001616747547 |
| Test statistic | 2.33525030614 |
| Two-sided p-value | 0.0195303485269 |
| Confidence interval | [6.06743239863e-05, 0.00069442771683] |
| Statistically different from zero | true |

Method note: OLS estimates period alpha and beta; a Bartlett-HAC sandwich covariance supplies the two-sided normal approximation.

## Serial-dependence diagnostics

| Metric | Value |
|---|---:|
| Status | eligible |
| Observation count | 5 |
| Return basis | simple |
| Maximum lag | 1 |
| Significance level | 0.05 |
| Strongest absolute autocorrelation lag | 1 |
| Strongest absolute autocorrelation | 0.560584376863 |
| Ljung-Box statistic | 2.74972988135 |
| Degrees of freedom | 1 |
| p-value | 0.0972708601718 |
| Serial dependence detected | false |
| Approximate two-sided ACF confidence bound | 0.876522540577 |
| Mean long-run variance ratio | 0.103064997018 |
| Mean effective observation count | 48.5130756769 |
| Runs-test usable observations | 4 |
| Observed / expected runs | 4 / 3 |
| Runs z-statistic | 0.612372435696 |
| Runs p-value | 0.540291374607 |
| Runs dependence detected | false |

| Lag | Sample autocorrelation | Partial autocorrelation |
|---:|---:|---:|
| 1 | -0.560584376863 | -0.67857658438 |

Method note: ACF/PACF are descriptive; the ACF bound is the large-sample z_(1-alpha/2)/sqrt(n) reference. Ljung-Box tests joint zero autocorrelation, the median-sign runs test checks ordering, and Lo-MacKinlay variance ratios use heteroskedasticity-robust standard errors. All p-values are asymptotic; non-rejection does not prove IID returns.

## Annualized statistics

| Metric | Value |
|---|---:|
| Periods per year | 365 |
| Return basis | simple |
| Annualized arithmetic mean return | 0.876 |
| Annualized sample volatility | 0.123703779247 |
| Annual risk-free rate | 0 |
| Equivalent period risk-free rate | 0 |
| Annualized Sharpe ratio | 7.08143280126 |

Method note: these are point estimates using linear mean scaling and square-root-of-time volatility scaling.

## Sharpe uncertainty and PSR

| Metric | Value |
|---|---:|
| Observation count | 5 |
| Period Sharpe ratio | 0.37065913344 |
| Annualized Sharpe ratio | 7.08143280126 |
| Sharpe variance adjustment | 0.980861857892 |
| Period Sharpe standard error | 0.495192350984 |
| Annualized Sharpe standard error | 9.46063658179 |
| Benchmark period Sharpe ratio | 0 |
| Benchmark annualized Sharpe ratio | 0 |
| Probabilistic Sharpe Ratio | 0.772925350117 |

Method note: the Sharpe standard error and PSR use the higher-moment-adjusted asymptotic formula at the observation frequency. Serial dependence is diagnosed separately but is not corrected in these values. Resampling uncertainty and multiple-testing selection are also not corrected in this increment.

## Minimum track-record length

| Metric | Value |
|---|---:|
| Observation count | 5 |
| Required PSR confidence level | 0.75 |
| Observed Probabilistic Sharpe Ratio | 0.772925350117 |
| Confidence requirement met | true |
| Normal critical value | 0.674489750196 |
| Observed period Sharpe difference | 0.37065913344 |
| Minimum track-record length (observations) | 4.24794856678 |
| Minimum required whole observations | 5 |
| Equivalent track-record length (years) | 0.0116382152515 |
| Additional observations required | 0 |
| Observations above minimum | 0 |

Method note: MinTRL is a conditional asymptotic estimate using the observed Sharpe, skewness, kurtosis, benchmark, and periods-per-year scale. The whole-observation requirement is rounded up and never falls below the four observations needed for this implementation's moment estimates. It is not a guarantee that future returns will preserve the observed distribution.

## Serial-dependence adjustment

| Configuration | Value |
|---|---:|
| Status | eligible |
| Observation count | 5 |
| Return basis | simple |
| Maximum lag | 1 |
| Kernel | bartlett |
| Periods per year | 365 |

### HAC annualization comparison

| Metric | Value |
|---|---:|
| Return long-run variance ratio | 0.439415623137 |
| IID annualization factor | 19.1049731745 |
| HAC annualization factor | 28.8209760994 |
| Full Lo annual horizon | false |
| IID annualized Sharpe ratio | 7.08143280126 |
| HAC-adjusted annualized Sharpe ratio | 10.6827580259 |

| Return lag | Autocorrelation | Bartlett weight | Weighted contribution |
|---:|---:|---:|---:|
| 1 | -0.560584376863 | 0.5 | -0.280292188432 |

### HAC Sharpe uncertainty comparison

| Metric | Value |
|---|---:|
| Sharpe long-run variance ratio | 0.421225132902 |
| IID Sharpe variance adjustment | 0.980861857892 |
| HAC Sharpe variance adjustment | 0.413163666449 |
| IID period Sharpe standard error | 0.495192350984 |
| HAC period Sharpe standard error | 0.321389042458 |
| Effective observation count | 10.4961095328 |
| Benchmark period Sharpe ratio | 0 |
| IID Probabilistic Sharpe Ratio | 0.772925350117 |
| HAC Probabilistic Sharpe Ratio | 0.875607099509 |
| Required PSR confidence level | 0.75 |
| HAC confidence requirement met | true |
| HAC MinTRL (observations) | 2.3681175667 |
| HAC minimum required observations | 4 |
| HAC MinTRL (years) | 0.00648799333343 |
| HAC additional observations required | 0 |
| HAC observations above minimum | 1 |

| Influence lag | Autocorrelation | Bartlett weight | Weighted contribution |
|---:|---:|---:|---:|
| 1 | -0.578774867098 | 0.5 | -0.289387433549 |

Method note: return autocorrelations adjust the annualization factor. Influence-series autocorrelations adjust the higher-moment Sharpe variance, PSR, and MinTRL. Bartlett weights equal 1 - lag / (maximum lag + 1). When maximum lag equals periods per year minus one, the point-estimate factor spans Lo's full annual horizon; otherwise it is a truncated HAC approximation. These are asymptotic plug-in estimates and can be unstable in short samples; effective observations may exceed the raw count under negative dependence. Bandwidth uncertainty is not included.

## Bootstrap confidence intervals

| Configuration | Value |
|---|---:|
| Status | eligible |
| Observation count | 5 |
| Return basis | simple |
| Method | stationary |
| Interval method | percentile |
| Replications | 100 |
| Confidence level | 0.9 |
| Lower / upper quantiles | 0.05 / 0.95 |
| Block length | 2 |
| Random seed | 42 |
| Overlapping source blocks | undefined |
| Blocks per replication | undefined |
| Periods per year | 365 |
| HAC maximum lag | 1 |
| HAC kernel | bartlett |

| Metric | Status | Point estimate | Lower bound | Upper bound | Bootstrap SE | Successful / attempted |
|---|---|---:|---:|---:|---:|---:|
| period_mean_return | eligible | 0.0024 | -0.000105 | 0.0054 | 0.0016072748126 | 100 / 100 |
| period_sample_volatility | eligible | 0.00647495173727 | 0.0044213776715 | 0.00758287544405 | 0.00105046928876 | 100 / 100 |
| fixed_horizon_cumulative_simple_return | eligible | 0.0119732877841 | -0.000605707009636 | 0.0272291664944 | 0.00812843402952 | 100 / 100 |
| annualized_arithmetic_mean_return | eligible | 0.876 | -0.038325 | 1.971 | 0.586655306601 | 100 / 100 |
| iid_annualized_sample_volatility | eligible | 0.123703779247 | 0.0844703018085 | 0.144870631945 | 0.0200691875825 | 100 / 100 |
| period_sharpe_ratio | eligible | 0.37065913344 | -0.0167315413678 | 0.963287925641 | 0.372024557726 | 100 / 100 |
| iid_annualized_sharpe_ratio | eligible | 7.08143280126 | -0.319655649001 | 18.4035899787 | 7.10751919563 | 100 / 100 |
| hac_adjusted_annualized_sharpe_ratio | eligible | 10.6827580259 | -0.571919614645 | 25.5145398552 | 9.67175822747 | 100 / 100 |

Method note: moving-block resampling draws fixed-length overlapping blocks; stationary resampling draws circular blocks with geometrically distributed lengths and the configured mean. Both preserve local dependence. Two-sided percentile bounds are the configured lower and upper quantiles of each bootstrap distribution. The fixed-horizon cumulative-return interval always uses the original observation count. IID-labeled annualized metrics retain square-root-of-time scaling; the HAC-adjusted Sharpe interval instead re-estimates the selected Bartlett ratio in every replication. The result is conditional on stationarity, block length, finite replications, and the selected interval method.

## Input issues

No input issues were recorded.

## Findings

| Code | Category | Claim | Implication | Remediation |
|---|---|---|---|---|
| LOW_BOOTSTRAP_REPLICATION_COUNT | methodological_risk | The bootstrap uses fewer than 1,000 replications. | Estimated interval endpoints may have substantial Monte Carlo variation. | Increase the explicit replication count and retain the seed so the analysis remains reproducible. |
