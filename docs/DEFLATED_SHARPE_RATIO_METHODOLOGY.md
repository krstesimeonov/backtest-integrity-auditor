# Deflated Sharpe Ratio Methodology

Part M implements the classical expected-maximum, location-only Deflated
Sharpe Ratio for a canonical Experiment-Family. It answers whether the selected
maximum observed Sharpe remains exceptional after a stated strategy search. It
does not answer whether the strategy will perform out of sample.

## Configuration contract

The base configuration is all-or-nothing:

| Choice | Supported value |
|---|---|
| Method | `classic_expected_maximum` |
| Trial-count policy | `selection_eligible` |
| Annual risk-free rate | Finite effective annual simple rate greater than `-1` |
| Required confidence | Finite value strictly between `0.5` and `1.0` |

The annual risk-free rate is converted to the equivalent period rate using the
manifest's explicit positive `periods_per_year`. No annualization scale is
inferred.

An optional effective independent-trial count requires both a positive integer
and a non-empty methodology statement. It cannot exceed the selection-eligible
trial count. The auditor reports this count as user-supplied and does not claim
to verify the external independence analysis.

## Evidence gate

Classical winner DSR is calculated only when:

- the complete search history is declared and documented;
- at least two completed trials are included in selection;
- at least four exactly aligned observations exist;
- `periods_per_year` is explicitly positive;
- every selection-eligible trial has a finite period Sharpe;
- the selected trial is the observed maximum Sharpe in the selection set;
- selected-trial skewness and Pearson kurtosis are available; and
- the higher-moment Sharpe variance adjustment is finite and positive.

Ties at the observed maximum are accepted. Failed attempts remain in the
declared-attempt scenario count but never receive fabricated return curves or
Sharpe estimates. Completed exclusions retain real Sharpe evidence but do not
enter the selection-eligible cross-trial dispersion.

## Calculation

All log-return inputs are converted period by period to simple returns. For
each completed trial, period Sharpe is the period mean excess return divided by
sample volatility.

Let `sigma_SR` be the sample standard deviation of all selection-eligible
period Sharpe estimates. For trial count `N`, Euler–Mascheroni constant `gamma`,
and standard-normal quantile `Phi_inverse`:

```text
E[max Z] ≈
    (1 - gamma) * Phi_inverse(1 - 1/N)
    + gamma * Phi_inverse(1 - 1/(N * e))

SR_benchmark = sigma_SR * E[max Z]
```

For the selected period Sharpe `SR`, `n` observations, finite-sample-corrected
sample skewness `gamma3`, and sample Pearson kurtosis `gamma4`:

```text
A = 1 - gamma3 * SR + ((gamma4 - 1) / 4) * SR**2
SE(SR) = sqrt(A / (n - 1))
DSR = Phi((SR - SR_benchmark) / SE(SR))
```

The confidence requirement is met when `DSR >= required_confidence_level`.
All calculations use period Sharpe. IID-scaled annualized Sharpe values are
reported only as labeled views.

## Trial-count scenarios

| Basis | Interpretation |
|---|---|
| `selection_eligible` | Primary classical scenario; treats each trial in the declared selection set as independent |
| `declared_attempts` | Conservative sensitivity that uses every declared attempt count, including documented failures and exclusions |
| `user_supplied_effective` | Optional scenario conditional on a supplied count and methodology; never auditor-verified |

The declared-attempt scenario keeps the selection-eligible `sigma_SR`. It is a
search-count sensitivity, not a claim that failed trials had measurable Sharpe
ratios.

## Dependence evidence and limitations

Part M calculates the minimum, maximum, mean, median, and strongest absolute
pairwise Pearson return correlation among selection-eligible canonical simple
return series. These statistics show dependence evidence but do not uniquely
identify the effective number of independent statistical tests. No correlation
threshold, clustering algorithm, or spectral estimator is silently selected.

The implemented method is the classical location-only DSR. It does not apply a
location-scale maximum-distribution adjustment, HAC correction, structural-
break correction, or resampled family-selection procedure. Its selected-trial
standard error is an asymptotic plug-in estimate and can be unstable with short
histories or uncertain higher moments.

DSR, PSR, and CSCV/PBO remain distinct:

- PSR evaluates one observed Sharpe against an explicit benchmark.
- DSR changes the benchmark to reflect an expected search maximum.
- CSCV/PBO measures how often in-sample selection ranks poorly out of sample
  across symmetric time partitions.

No one of these methods substitutes for the others.

## Result statuses

| Status | Meaning |
|---|---|
| `eligible` | Every evidence gate passed and named DSR scenarios were calculated |
| `family_ineligible` | Search completeness, trial count, or observation count is insufficient |
| `periods_per_year_unavailable` | The configured annual risk-free rate cannot be converted to the observation period |
| `incomplete_trial_sharpe_distribution` | At least one selection-eligible Sharpe is undefined |
| `selected_trial_not_maximum_sharpe` | The selected trial is not the observed Sharpe maximum in the selection set |
| `selected_return_moments_unavailable` | Selected skewness or Pearson kurtosis cannot be estimated |
| `non_positive_sharpe_variance_adjustment` | The classical plug-in Sharpe standard error is undefined |
| `invalid_effective_trial_count` | The supplied effective count exceeds the documented selection set |

## Research basis

- Bailey and López de Prado, *The Deflated Sharpe Ratio: Correcting for
  Selection Bias, Backtest Overfitting and Non-Normality* (2014):
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- López de Prado and Porcu, *The Deflated Sharpe Ratio: A Unified Framework for
  Search-Adjusted Performance Inference*:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7198158
