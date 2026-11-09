# Parameter and Temporal Robustness Methodology

Part O adds two explicitly configured diagnostics to the canonical
Experiment-Family audit. They reuse the complete aligned trial matrix but answer
questions different from full-sample DSR and CSCV/PBO:

1. parameter-neighborhood robustness asks whether nearby *tested*
   configurations form a plateau or a cliff around the selected trial;
2. temporal robustness asks whether the selected trial's score and cross-trial
   rank are consistent across equal contiguous windows, and separately replays
   each supplied train/test or fold selection.

Both methods currently support a maximize rule whose manifest metric is
explicitly confirmed as `period_sharpe_ratio`. Every score is recalculated from
canonical simple returns. Log-return matrices are converted observation by
observation first.

## Shared eligibility and score

The family must have complete declared search history, at least two completed
selection-eligible trials, at least four aligned observations, a positive
`periods_per_year`, a maximize selection direction, and an exact metric-name
match. There is no default risk-free rate. An effective annual simple rate is
converted to the equivalent period rate:

```text
period risk-free rate =
    (1 + annual risk-free rate) ** (1 / periods_per_year) - 1

period Sharpe =
    mean(simple returns - period risk-free rate)
    / sample standard deviation(simple returns)
```

A zero-volatility score is undefined. The auditor never deletes the affected
trial, neighbor, window, or split to finish an aggregate calculation.

## Explicit parameter neighborhood

For each scaled numeric parameter `j`, the user supplies a positive finite
scale `s_j`. For candidate configuration `x` and selected configuration `x*`,
the standardized Euclidean distance is:

```text
d(x, x*) = sqrt(sum_j(((x_j - x*_j) / s_j) ** 2))
```

A tested selection-eligible trial is a neighbor only when:

- every unscaled parameter exactly equals the selected value;
- `0 < d(x, x*) <= maximum_distance`.

The rule makes the neighborhood reproducible and prevents categorical or
otherwise unscaled dimensions from changing silently. A scale name must exist
in the manifest and be numeric and non-boolean for every selection-eligible
trial. Equal parameter configurations have distance zero. They are preserved as
duplicates, not counted as independent neighbors.

For every neighbor, the report preserves distance, changed dimensions,
recalculated period Sharpe, score difference from the selected trial, and
whether the absolute score difference is within the explicit tolerance. The
aggregate view reports:

- acceptable-neighbor count and fraction;
- the explicit fraction requirement and whether it is met;
- whether the selected trial is a local maximum;
- neighbor minimum, maximum, and mean scores;
- maximum degradation and improvement relative to the selected score;
- steepest absolute score change per standardized distance;
- one-axis lower, upper, and slope evidence where tested points exist.

The minimum-neighbor requirement is enforced before aggregate interpretation.
The auditor returns `insufficient_neighbors` instead of widening the radius.
If any in-radius neighbor score is undefined, it returns
`incomplete_neighbor_metrics` and preserves that trial ID rather than computing
a favorable fraction from the remainder.

Complete CLI configuration:

```text
--parameter-robustness-metric period_sharpe_ratio
--parameter-selection-metric-name period_sharpe_ratio
--parameter-annual-risk-free-rate 0.03
--parameter-distance-metric standardized_euclidean
--parameter-scale lookback=5
--parameter-scale threshold=0.1
--parameter-maximum-distance 1.5
--parameter-minimum-neighbors 2
--parameter-maximum-score-difference 0.10
--parameter-minimum-acceptable-neighbor-fraction 0.75
```

Repeated scales must follow manifest parameter-name order. The neighborhood is
a conditional sensitivity diagnostic, not a formal hypothesis test or a rule
for choosing new parameters. Its result can change with the predeclared scales,
radius, available search grid, and fixed unscaled dimensions.

## Equal-window temporal view

The auditor partitions the aligned observation history into the explicit number
of equal contiguous windows. The total observation count must divide the window
count exactly, and every window must contain at least two observations. No
remainder is trimmed.

In each window it recalculates every selection-eligible trial's period Sharpe.
The report preserves the selected trial's score, one-based ascending average
rank, relative rank, rank logit, top-half flag, tied-best flag, below-zero flag,
and every tied-best trial ID:

```text
relative rank = average rank / (eligible trial count + 1)
rank logit = log(relative rank / (1 - relative rank))
top half = rank logit > 0
```

The strict `> 0` boundary means a median-ranked trial is not classified as top
half. Aggregate evidence includes selected-score mean, sample standard
deviation, minimum, maximum, and range; top-half, tied-best, and below-zero
fractions; mean and median rank logits; distinct window winners; and the two
explicit requirement decisions.

If any eligible trial has an undefined score in any window, the report preserves
all windows and unavailable trial IDs but does not calculate partial temporal
fractions.

Complete CLI configuration:

```text
--temporal-robustness-metric period_sharpe_ratio
--temporal-selection-metric-name period_sharpe_ratio
--temporal-annual-risk-free-rate 0.03
--temporal-windows 4
--temporal-rank-tie-method average
--temporal-winner-tie-policy first_by_attempt_index
--temporal-minimum-acceptable-top-half-fraction 0.75
--temporal-maximum-acceptable-below-zero-fraction 0.25
```

## Declared train/test and fold consistency

When canonical split metadata exists, temporal robustness also evaluates each
declared split without changing the equal-window result. For every split it:

1. calculates all eligible-trial IS Sharpes;
2. selects the highest IS score, preserving ties and resolving them by attempt
   order;
3. evaluates that same trial's OOS score, average rank, relative rank, logit,
   top-half flag, below-zero flag, and tied-best retention.

A declared split with fewer than two observations in either role or any
undefined eligible-trial score is retained with
`performance_metric_unavailable`. Invalid external splits do not invalidate
otherwise complete equal-window evidence. This separation preserves the
research design and prevents external folds from being silently repurposed as
CSCV partitions.

## Interpretation boundaries

- Parameter robustness, equal windows, external folds, DSR, and CSCV/PBO are
  separate report objects and findings.
- Equal windows are a limited descriptive stability view, not an Andrews-style
  formal structural-break test.
- Subperiod Sharpes are not HAC-adjusted. Interpret them alongside the serial
  dependence and adjustment diagnostics.
- Parameter scales, the radius, the window count, thresholds, and tie rules
  must be chosen for the audit question, not optimized until the report looks
  favorable.
- None of these diagnostics proves skill or future profitability.

The complete-trial-universe principle is consistent with Sullivan, Timmermann,
and White's data-snooping analysis. The temporal limitation is stated explicitly
because formal unknown-break inference, such as Andrews' parameter-instability
tests, has a different model and null distribution. Primary references:

- Ryan Sullivan, Allan Timmermann, and Halbert White, “Data-Snooping,
  Technical Trading Rule Performance, and the Bootstrap,” *Journal of
  Finance* 54(5), 1999, DOI `10.1111/0022-1082.00163`.
- Donald W. K. Andrews, “Tests for Parameter Instability and Structural Change
  with Unknown Change Point,” *Econometrica* 61(4), 1993, pp. 821–856.
- Bailey, Borwein, López de Prado, and Zhu, “The Probability of Backtest
  Overfitting,” 2015, for the distinct CSCV/PBO method documented separately.
