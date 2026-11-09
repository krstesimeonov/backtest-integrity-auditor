# Backtest Integrity Audit

- Schema version: `2.5`
- Audit type: `experiment_family`
- Family ID: `cscv-example-family`

## Dimensioned evidence profile

- Method: `dimensioned_evidence_profile_v1`
- Overall status: `not calculated`
- Interpretation boundary: Each dimension is independent. No numeric score or global pass/fail is calculated, and no status certifies skill, profit, or future performance.

| Dimension | Status | Summary | Supporting evidence | Adverse evidence | Unavailable evidence | Assumptions | Next evidence required |
|---|---|---|---|---|---|---|---|
| input_integrity | supported_under_stated_assumptions | The input passed blocking validation with preserved normalization issues. | CANONICAL_INPUT_ACCEPTED_AFTER_NORMALIZATION | SPLIT_MEMBERSHIP_SORTED | none | BLOCKING_INPUT_ERRORS_REJECTED_BEFORE_AUDIT | none |
| experiment_completeness | supported_under_stated_assumptions | The complete declared experiment family supports family-level methods. | COMPLETE_SEARCH_HISTORY, ALIGNED_SELECTION_ELIGIBLE_TRIAL_MATRIX | none | none | SEARCH_COMPLETE_DECLARATION_IS_ACCURATE | none |
| multiple_testing_evidence | fragile | At least one configured selection-bias requirement fails. | DSR_CONFIDENCE_REQUIREMENT_MET, WHITE_REALITY_CHECK_AVAILABLE, HANSEN_SPA_AVAILABLE | PBO_REQUIREMENT_NOT_MET, WHITE_REALITY_CHECK_NULL_NOT_REJECTED, HANSEN_SPA_NULL_NOT_REJECTED | none | DSR_CLASSICAL_INDEPENDENT_TRIAL_APPROXIMATION, CSCV_EQUAL_SYMMETRIC_PARTITIONS | Treat the selection process as fragile; do not optimize against these diagnostics. |
| parameter_robustness | supported_under_stated_assumptions | The selected configuration meets the declared local robustness requirements. | PARAMETER_NEIGHBOR_FRACTION_REQUIREMENT_MET, SELECTED_TRIAL_IS_LOCAL_MAXIMUM | none | none | USER_DECLARED_PARAMETER_GEOMETRY | none |
| temporal_robustness | fragile | At least one temporal or declared-fold consistency condition fails. | TEMPORAL_TOP_HALF_REQUIREMENT_MET, TEMPORAL_BELOW_ZERO_REQUIREMENT_MET | EXTERNAL_SPLIT_WINNER_NOT_RETAINED | none | EQUAL_CONTIGUOUS_WINDOWS_ARE_DESCRIPTIVE, SUBPERIOD_SHARPES_NOT_HAC_ADJUSTED | Treat temporal evidence as fragile and inspect every preserved window and fold. |
| reproducibility | insufficient_evidence | A deterministic audit-run manifest was not configured. | none | none | AUDIT_RUN_MANIFEST_NOT_CONFIGURED | none | Supply an audit ID, timezone-aware audit timestamp, and Git revision together. |

## Audit-run manifest

No deterministic run manifest was configured. Audit ID, timestamp, and Git revision are never inferred.

## Experiment-family completeness

| Property | Value |
|---|---:|
| Status | eligible |
| Declared attempted trials | 4 |
| Documented trials | 4 |
| Completed trials | 4 |
| Failed trials | 0 |
| Selection-eligible trials | 4 |
| Completed trials excluded from selection | 0 |
| Supplied return series | 4 |
| Search complete declared | true |
| Complete search history | true |
| Undocumented attempt indices | none |
| Winner-only evidence | false |
| Later selection-bias methods structurally eligible | true |

Structural eligibility means only that the family contract is complete enough for family-level methods. It does not mean that DSR, CSCV, or PBO supports the strategy.

## Selection record

| Property | Value |
|---|---:|
| Selected trial ID | trial-001 |
| Selected attempt index | 1 |
| Rule | Maximize period Sharpe among all predeclared trials |
| Metric | period_sharpe_ratio |
| Direction | maximize |

## Deflated Sharpe Ratio

| Property | Value |
|---|---:|
| Status | eligible |
| Method | classic_expected_maximum |
| Trial-count policy | selection_eligible |
| Return basis | simple |
| Annual risk-free rate | 0 |
| Period risk-free rate | 0 |
| Required confidence | 0.75 |
| Declared attempts | 4 |
| Selection-eligible trials | 4 |
| Valid selection-trial Sharpes | 4 |
| Selected period Sharpe | 0.504016128774 |
| Selected IID-scaled annualized Sharpe | 8.00100800101 |
| Selected is observed maximum | true |
| Cross-trial Sharpe standard deviation | 0.0936996156539 |
| User-supplied effective trial count | not supplied |
| Effective-count methodology | not supplied |
| Effective count verified by auditor | not supplied |

### DSR trial-count scenarios

| Count basis | Trials | Expected maximum period Sharpe | DSR | Requirement met |
|---|---:|---:|---:|---:|
| selection_eligible | 4 | 0.0985835042472 | 0.844414964164 | true |
| declared_attempts | 4 | 0.0985835042472 | 0.844414964164 | true |

### Trial-dependence evidence

| Property | Value |
|---|---:|
| Trial pairs | 6 |
| Minimum correlation | -0.706031927447 |
| Maximum correlation | 0.518670543522 |
| Mean correlation | -0.264160211205 |
| Median correlation | -0.34111373968 |
| Strongest absolute correlation | 0.706031927447 |

The classical DSR scenarios use an expected-maximum, location-only adjustment. Correlation statistics do not automatically become an effective number of independent trials, and DSR is not CSCV or PBO.

## CSCV and Probability of Backtest Overfitting

| Property | Value |
|---|---:|
| Status | eligible |
| Method | combinatorially_symmetric |
| Performance metric | period_sharpe_ratio |
| Confirmed selection metric | period_sharpe_ratio |
| Rank tie method | average |
| Winner tie policy | first_by_attempt_index |
| Partitions | 4 |
| Observations per partition | 2 |
| Exact symmetric combinations | 6 |
| Configured combination limit | 100 |
| Valid splits | 6 |
| Invalid splits | 0 |
| Probability of Backtest Overfitting | 1 |
| Maximum acceptable PBO | 0.75 |
| PBO requirement met | false |
| Probability selected OOS score is below zero | 0.166666666667 |
| Mean rank logit | -1.13299006883 |
| Median rank logit | -1.38629436112 |
| Performance-degradation slope | 7.69342693196 |
| Performance-degradation R-squared | 0.308629225279 |

### CSCV partitions

| Partition | Observations | Time range |
|---:|---:|---|
| 1 | 2 | 2026-01-01T00:00:00 to 2026-01-02T00:00:00 |
| 2 | 2 | 2026-01-05T00:00:00 to 2026-01-06T00:00:00 |
| 3 | 2 | 2026-01-07T00:00:00 to 2026-01-08T00:00:00 |
| 4 | 2 | 2026-01-09T00:00:00 to 2026-01-12T00:00:00 |

### CSCV split evidence

| Combination | Status | IS partitions | OOS partitions | IS winner | IS score | OOS score | OOS rank | Logit | Overfit |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | eligible | 1, 2 | 3, 4 | trial-002 | 0.731925054711 | 0.188982236505 | 1.5 | -0.847297860387 | true |
| 2 | eligible | 1, 3 | 2, 4 | trial-001 | 0.720576692123 | 0.285175912736 | 1 | -1.38629436112 | true |
| 3 | eligible | 1, 4 | 2, 3 | trial-002 | 0.720576692123 | 0.1127469042 | 1 | -1.38629436112 | true |
| 4 | eligible | 2, 3 | 1, 4 | trial-004 | 0.720576692123 | -1.77049473374e-17 | 1 | -1.38629436112 | true |
| 5 | eligible | 2, 4 | 1, 3 | trial-003 | 0.707106781187 | 0.0870388279778 | 1 | -1.38629436112 | true |
| 6 | eligible | 3, 4 | 1, 2 | trial-001 | 0.731925054711 | 0.339683110243 | 2 | -0.405465108108 | true |

CSCV exhaustively reuses each equal-sized half-sample in both IS and OOS roles. It audits selection-rank degradation; it is distinct from PSR and full-sample DSR.

## Parameter-neighborhood robustness

| Property | Value |
|---|---:|
| Status | eligible |
| Performance metric | period_sharpe_ratio |
| Distance metric | standardized_euclidean |
| Confirmed selection metric | period_sharpe_ratio |
| Parameter scales | lookback=5 |
| Maximum distance | 3 |
| Required neighbors | 2 |
| In-radius neighbors | 2 |
| Duplicate selected configurations | none |
| Maximum acceptable absolute Sharpe difference | 1 |
| Required acceptable-neighbor fraction | 0.5 |
| Observed acceptable-neighbor fraction | 1 |
| Neighbor-fraction requirement met | true |
| Selected is local maximum | true |
| Maximum degradation | 0.21112653571 |
| Maximum improvement | 0 |
| Steepest absolute change per distance | 0.0873832016652 |

### Local neighbors

| Attempt | Trial ID | Distance | Changed parameters | Period Sharpe | Difference | Within tolerance |
|---:|---|---:|---|---:|---:|---:|
| 2 | trial-002 | 1 | lookback | 0.416632927109 | -0.0873832016652 | true |
| 3 | trial-003 | 3 | lookback | 0.292889593065 | -0.21112653571 | true |

### One-axis sensitivities

| Parameter | One-axis neighbors | Closest lower | Lower difference | Closest upper | Upper difference | Maximum slope |
|---|---:|---|---:|---|---:|---:|
| lookback | 2 | not supplied | not supplied | trial-002 | -0.0873832016652 | 0.0873832016652 |

The neighborhood holds every unscaled parameter exactly fixed. Zero-distance duplicates are preserved separately and do not count as robustness neighbors.

## Temporal and declared-split robustness

| Property | Value |
|---|---:|
| Status | eligible |
| Performance metric | period_sharpe_ratio |
| Rank tie method | average |
| Winner tie policy | first_by_attempt_index |
| Equal windows | 4 |
| Observations per window | 2 |
| Valid windows | 4 |
| Invalid windows | 0 |
| Selected top-half fraction | 0.5 |
| Minimum acceptable top-half fraction | 0.5 |
| Top-half requirement met | true |
| Selected below-zero fraction | 0 |
| Maximum acceptable below-zero fraction | 0.5 |
| Below-zero requirement met | true |
| Selected score range | 1.97989898732 |
| Mean rank logit | 2.77555756156e-17 |
| Median rank logit | -2.77555756156e-17 |
| Distinct window winners | trial-001, trial-002, trial-003, trial-004 |

### Equal contiguous windows

| Window | Status | Time range | Selected Sharpe | Rank | Logit | Top half | Tied best | Below zero | Best trial IDs |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | eligible | 2026-01-01T00:00:00 to 2026-01-02T00:00:00 | 0.424264068712 | 3 | 0.405465108108 | true | false | false | trial-002 |
| 2 | eligible | 2026-01-05T00:00:00 to 2026-01-06T00:00:00 | 0.141421356237 | 1 | -1.38629436112 | false | false | false | trial-004 |
| 3 | eligible | 2026-01-07T00:00:00 to 2026-01-08T00:00:00 | 2.12132034356 | 4 | 1.38629436112 | true | true | false | trial-001 |
| 4 | eligible | 2026-01-09T00:00:00 to 2026-01-12T00:00:00 | 0.353553390593 | 2 | -0.405465108108 | false | false | false | trial-003 |

### Declared train/test or fold consistency

| Split | Status | IS winner | IS score | OOS score | OOS rank | OOS logit | OOS top half | Winner retained |
|---|---|---|---:|---:|---:|---:|---:|---:|
| fold-01 | eligible | trial-002 | 0.731925054711 | 0.188982236505 | 1.5 | -0.847297860387 | false | false |
| fold-02 | eligible | trial-001 | 0.731925054711 | 0.339683110243 | 2 | -0.405465108108 | false | false |

Equal windows describe subperiod rank and sign. Declared splits independently replay each supplied IS winner into its OOS set. Neither is CSCV/PBO or a formal structural-break test.

## Data-snooping controls

| Property | Value |
|---|---:|
| Status | eligible |
| Observation count | 8 |
| Selection-eligible trials | 4 |
| Benchmark ID | market |
| Replications | 100 |
| Mean block length | 2 |
| Random seed | 73 |
| Significance level | 0.05 |
| Selected trial ID | trial-001 |
| Selected mean active return | 0.00975 |
| Observed maximum mean active return | 0.00975 |
| Trials tied at observed maximum | trial-001 |
| White Reality Check p-value | 0.138613861386 |
| White Reality Check rejects null | false |
| Hansen SPA p-value | 0.128712871287 |
| Hansen SPA rejects null | false |

Method note: both tests compare the complete selection-eligible family with the shared benchmark using deterministic stationary bootstrap resamples. White centers all candidate differentials; SPA applies Hansen's consistency-based studentized recentering. Neither is calculated from winner-only evidence.

## Canonical return matrix

| Property | Value |
|---|---:|
| Return basis | simple |
| Observation count | 8 |
| Start timestamp | 2026-01-01T00:00:00 |
| End timestamp | 2026-01-12T00:00:00 |
| Exact timestamp alignment | true |
| Declared frequency | B |
| Periods per year | 252 |
| Timezone | UTC |
| Parameter schema | lookback |

## Trial evidence

| Attempt | Trial ID | Outcome | In selection | Selected | Selection score | Returns | Parameters | Source | Reason |
|---:|---|---|---:|---:|---:|---:|---|---|---|
| 1 | trial-001 | completed | true | true | 0.50401613 | true | {"lookback":5} | grid-search | not supplied |
| 2 | trial-002 | completed | true | false | 0.41663293 | true | {"lookback":10} | grid-search | not supplied |
| 3 | trial-003 | completed | true | false | 0.29288959 | true | {"lookback":20} | grid-search | not supplied |
| 4 | trial-004 | completed | true | false | 0.33303978 | true | {"lookback":40} | grid-search | not supplied |

## Declared splits

| Split ID | In-sample observations | Out-of-sample observations | In-sample range | Out-of-sample range |
|---|---:|---:|---|---|
| fold-01 | 4 | 4 | 2026-01-01T00:00:00 to 2026-01-06T00:00:00 | 2026-01-07T00:00:00 to 2026-01-12T00:00:00 |
| fold-02 | 4 | 4 | 2026-01-07T00:00:00 to 2026-01-12T00:00:00 | 2026-01-01T00:00:00 to 2026-01-06T00:00:00 |

## Shared benchmark

| Property | Value |
|---|---:|
| Benchmark ID | market |
| Return basis | simple |
| Observation count | 8 |
| Exact timestamp alignment | true |

## Input issues

| Code | Severity | Blocking | Location | Message |
|---|---|---:|---|---|
| SPLIT_MEMBERSHIP_SORTED | warning | false | examples/cscv_family_splits.csv | Split membership was normalized by split ID, role, and ascending timestamp. |

## Findings

| Code | Category | Claim | Implication | Remediation |
|---|---|---|---|---|
| DSR_INDEPENDENT_TRIALS_APPROXIMATION | methodological_risk | The primary classical DSR scenario treats every selection-eligible trial as independent. | Correlated strategy variants can make the literal trial count differ from the number of effectively independent tests; the reported correlation summary is evidence, not an automatic effective-count estimator. | Interpret the declared-attempt sensitivity and, when an independence analysis exists, supply its effective count with a methodology statement. |
| DSR_ASYMPTOTIC_PLUGIN_INFERENCE | methodological_risk | Classical DSR is an asymptotic plug-in estimate using the observed cross-trial dispersion and selected-trial moments. | Short histories, few trials, and unstable skewness or kurtosis estimates can materially change the reported probability. | Interpret DSR with the observation and trial counts shown in the report and retain independent robustness evidence. |
| DSR_SERIAL_DEPENDENCE_NOT_ADJUSTED | methodological_risk | The classical DSR standard error does not apply a HAC or other serial-dependence correction. | Serially dependent returns can make the IID-style DSR uncertainty estimate unreliable. | Interpret DSR alongside serial-dependence evidence; do not treat it as a replacement for the Part H adjustment. |
| PBO_REQUIREMENT_NOT_MET | statistical_evidence | The estimated PBO exceeds the configured maximum acceptable value. | In-sample winners rank at or below the OOS median too frequently for the stated requirement. | Treat this as adverse selection-process evidence; do not optimize strategy parameters against PBO. |
| PBO_RANK_GRANULARITY_LIMITED | methodological_risk | The CSCV universe contains ten or fewer eligible trials. | The relative ranks and logits have limited resolution. | Interpret the split-level rank distribution shown. |
| PBO_COMBINATION_RESOLUTION_LIMITED | methodological_risk | The partition count produces fewer than 100 logits. | The empirical PBO frequency is coarse. | Choose partitions from history and time structure, not to obtain a preferred PBO. |
| DECLARED_SPLITS_NOT_USED_BY_CSCV | methodological_risk | Declared external splits are preserved but not reused by CSCV. | CSCV constructs exhaustive equal-sized symmetric half-samples; external validation remains separate. |  |
| CSCV_TIME_DEPENDENCE_LIMITATION | methodological_risk | CSCV recombines contiguous partitions and does not remove serial dependence or structural breaks. | Partition size and regime coverage can affect logits. | Interpret PBO with temporal robustness evidence. |
| CSCV_NOT_A_SELECTION_OBJECTIVE | methodological_risk | PBO is an audit diagnostic, not an optimization objective. | Optimizing against PBO would overfit the diagnostic. | Freeze the search and CSCV configuration in advance. |
| PARAMETER_NEIGHBORHOOD_DEFINITION_CONDITIONAL | methodological_risk | The neighborhood is conditional on user-declared scales, radius, and fixed values for every unscaled parameter. | Different predeclared geometry can produce different plateau and cliff evidence. | Record the geometry before interpreting the selected result. |
| PARAMETER_ROBUSTNESS_NOT_A_SELECTION_OBJECTIVE | methodological_risk | Local robustness is an audit diagnostic, not a tuning objective. | Tuning against the diagnostic would reuse the same evidence. | Freeze the search and neighborhood contract in advance. |
| EXTERNAL_SPLIT_WINNER_NOT_RETAINED | statistical_evidence | The in-sample winner was not tied for best out-of-sample in 2 declared split(s). | The supplied research design shows winner instability. | Treat declared-fold performance as separate adverse evidence. |
| TEMPORAL_WINDOWS_BOUNDARY_SENSITIVE | methodological_risk | Equal contiguous windows are descriptive and sensitive to the configured count and boundaries. | They provide a limited stability view, not a formal structural-break test. | Interpret the complete window table without optimizing boundaries. |
| TEMPORAL_ROBUSTNESS_SERIAL_DEPENDENCE_UNADJUSTED | methodological_risk | Window and fold Sharpes are not HAC-adjusted. | Serial dependence can affect subperiod score interpretation. | Interpret this evidence alongside the serial diagnostics. |
| WHITE_REALITY_CHECK_NULL_NOT_REJECTED | selection_bias | White's Reality Check does not reject that the best trial lacks benchmark superiority. | The observed winner can be consistent with data-snooping variation across the tested family. | Treat superiority as unestablished under the declared bootstrap specification. |
| HANSEN_SPA_NULL_NOT_REJECTED | selection_bias | Hansen's SPA test does not reject the no-superior-alternative null. | Studentization and consistent recentering still do not establish benchmark superiority. | Treat the selected trial's superiority as statistically unestablished. |
