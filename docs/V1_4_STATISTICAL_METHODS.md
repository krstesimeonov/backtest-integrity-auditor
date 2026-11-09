# V1.4 Statistical Methods and Additive Evidence

## Scope and invariants

V1.4 adds statistical and domain evidence to the existing file-first auditor.
Every method is opt-in and records its complete configuration. The increment
does not run a strategy, infer trades, select parameters, place orders, connect
to a new broker, or alter custody or money movement.

The architectural boundary is unchanged:

- ingestion validates files and constructs immutable domain objects;
- statistics consume domain objects and never read files or render reports;
- the application layer coordinates calculations and findings;
- reporting serializes completed typed results; and
- optional persistence stores immutable completed reports and canonical series.

Package `1.4.0` emits report schema `2.5` and audit-run-manifest schema `1.1`.
Legacy report `2.4` and manifest `1.0` schemas remain loadable for consumers of
stored earlier audits. Database schema remains `1`.

## Serial-dependence extension

Configure the complete diagnostic with `--serial-max-lag h` and
`--serial-significance-level alpha`. V1.4 retains the sample ACF and Ljung–Box
test and adds the following evidence.

### Partial autocorrelation

For each lag `k = 1, ..., h`, the implementation regresses the globally
mean-centered return at time `t` on its first `k` lags and records the
coefficient on lag `k`. Rank-deficient lag regressions are omitted rather than
assigned a fabricated value. PACF is descriptive and its finite-sample behavior
depends on the estimator and sample length.

### ACF reference bound

The two-sided large-sample white-noise reference is

```text
z_(1 - alpha / 2) / sqrt(n)
```

It is not a simultaneous band and is not used as a replacement for Ljung–Box.

### Mean long-run variance and effective observations

Using the configured ACF truncation,

```text
LRV ratio = 1 + 2 * sum[(1 - k/n) * rho_k], k = 1,...,h
mean effective observations = n / LRV ratio
```

The effective count is emitted only for a finite positive ratio. It is a
variance-equivalence diagnostic, not additional data; negative dependence can
make it exceed `n`.

### Median-sign runs test

Observations equal to the sample median are removed. The remaining signs form a
Wald–Wolfowitz runs statistic with the standard normal approximation and a
continuity correction. The correction moves `|R - E|` toward zero by one half
and never past it, so `R = E` gives `z = 0` and `p = 1` (1.5.2; earlier releases
added one half when `R = E`). Results are withheld when fewer than two usable signs
remain, only one sign is present, or the asymptotic variance is non-positive.
This test detects ordering patterns that may not appear as linear ACF.

### Lo–MacKinlay variance ratios

For every horizon `q = 2, ..., h`, the report compares the unbiased overlapping
`q`-period variance with `q` times the one-period variance. It uses the
heteroskedasticity-robust Lo–MacKinlay variance estimator. A finite positive
robust variance is required for the z-statistic and two-sided p-value:

```text
theta(q) = sum_{j=1..q-1} (2 (q - j) / q)**2 * delta(j)
delta(j) = n * sum_t e_t**2 e_(t-j)**2 / (sum_t e_t**2)**2,   e_t = r_t - mean
robust standard error = sqrt(theta(q) / n)
z(q) = (VR(q) - 1) / sqrt(theta(q) / n),   p = erfc(|z| / sqrt(2))
```

`theta(q)` is the asymptotic variance of `sqrt(n) (VR(q) - 1)`. Before 1.5.2 the
standard error was `sqrt(theta(q))`, so z was too small by `sqrt(n)` and the test
practically never rejected (finding N18).

Variance-ratio rejection is evidence against the random-walk variance scaling
at that horizon. Non-rejection does not prove IID returns or rule out nonlinear
dependence. The implementation follows [Lo and MacKinlay (1988)](https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/8729.pdf).

## Stationary-bootstrap intervals

V1.4 adds `--bootstrap-method stationary` alongside `moving_block`. With mean
block length `L`, the initial index is uniform over the `n` observations. Each
subsequent index restarts uniformly with probability `1/L`; otherwise it moves
to the next source observation with circular wraparound. The output length is
always exactly `n`.

Both resamplers use the existing deterministic percentile-interval pipeline.
The random seed, replication count, confidence level, method, and block length
are mandatory. A block length of one is equivalent to IID resampling and emits
a warning. No automatic block selector or block-length uncertainty adjustment
is claimed. The method follows [Politis and Romano (1994)](https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870).

## Downside, tail, and drawdown statistics

The pair `--minimum-acceptable-period-return tau` and
`--tail-confidence-level c` configures all advanced risk metrics. Canonical
simple returns are denoted by `r_t`.

### Downside deviation and Sortino

```text
downside deviation = sqrt(mean(min(r_t - tau, 0)^2))
period Sortino = mean(r_t - tau) / downside deviation
annualized Sortino = period Sortino * sqrt(periods per year)
```

The target is a period return, not an annual target. Annualized Sortino is
withheld unless the existing sampling contract is annualization-eligible.
Zero downside deviation produces an explicitly undefined ratio, never infinity.
The target/downside framing follows [Sortino and Price](https://research.rug.nl/files/604914965/DOWNSIDE_RISK_Capturing_what_s_at_stake.pdf).

### Omega

The equal-weight empirical Omega ratio at target `tau` is

```text
sum(max(r_t - tau, 0)) / sum(max(tau - r_t, 0))
```

It is undefined when the denominator is zero. This empirical discrete form is
consistent with the threshold-based measure introduced by [Keating and
Shadwick](https://oxfordstrat.com/coasdfASD32/uploads/2016/03/A-Universal-Performance-Measure.pdf).

### Historical VaR and expected shortfall

Returns are converted to losses `l_t = -r_t`. Historical VaR uses NumPy's
equal-weight `inverted_cdf` empirical quantile at `c`. Expected shortfall
integrates the equal-weight empirical loss quantile over the worst `1-c` tail;
when the tail boundary cuts through an observation, it includes the exact
fractional observation weight. No normal, Student-t, or other parametric loss
distribution is fitted. The tail-loss interpretation is aligned with
[Rockafellar and Uryasev](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=267256).

### Calmar and Ulcer Index

Calmar is CAGR divided by the absolute maximum drawdown. It is undefined when
CAGR is unavailable or maximum drawdown is zero. Ulcer Index is the root mean
square of drawdowns from the running wealth peak, including the virtual initial
wealth of one. Both are path-dependent and therefore remain distinct from the
return-distribution metrics.

## Time-varying risk-free evidence

`--risk-free-csv` accepts one canonical return per strategy timestamp. Exact
timestamp equality is required. On eligibility, V1.4 reports mean and
cumulative risk-free return, mean and sample volatility of period excess
returns, period excess Sharpe, and an annualized excess Sharpe when the existing
sampling contract permits it.

This is intentionally additive. It does not silently replace the scalar annual
risk-free assumptions supplied to legacy Sharpe, PSR, MinTRL, HAC, DSR, CSCV,
parameter, or temporal methods. Those methods retain their published V1.0–V1.3
semantics. A future change that makes a time-varying series the common risk-free
contract would require an explicit method and schema decision.

## Gross-to-net cost drag

`--gross-returns-csv` requires exact alignment with the audited net strategy
returns. Period drag is `gross_t - net_t`. The report includes mean period drag,
arithmetic annualized drag when eligible, cumulative gross and net returns,
their terminal cumulative-return difference, and counts of positive and
negative drag periods.

A negative drag period means net exceeds gross; it emits a reconciliation
finding because it may reflect rebates, inconsistent valuation, or mislabeled
cost bases. The auditor does not infer transactions or reconstruct commissions.

## Declared-regime slices

`--regimes-csv` accepts exactly one non-empty categorical label for every
strategy timestamp. Labels are sorted deterministically for reporting. Each
slice reports count, mean period return, sample volatility, compounded return,
and period excess Sharpe when an exactly aligned risk-free series is also
available.

Regimes are externally declared evidence. The auditor performs no hidden-state,
clustering, change-point, or look-ahead-safe regime inference. Slice statistics
are descriptive and do not correct for selection or multiple testing.

## Benchmark alpha inference

With an exactly aligned benchmark, `--benchmark-alpha-hac-max-lag h` and
`--benchmark-alpha-confidence-level c` fit

```text
strategy_t = alpha + beta * benchmark_t + error_t
```

by OLS. The two-parameter sandwich covariance uses Bartlett weights
`1 - k/(h+1)` through lag `h`. The report includes period alpha, beta, HAC
standard error, normal test statistic, two-sided p-value, confidence interval,
and the declared-confidence rejection decision.

The method is withheld for a missing/misaligned benchmark, too few observations,
singular design, or non-positive alpha variance. It makes no factor-model,
conditional-alpha, small-sample-t, bandwidth-selection, or causal-skill claim.
The covariance construction follows the HAC principle of [Newey and West](https://www.nber.org/papers/t0055).

## White Reality Check and Hansen SPA

Experiment-Family mode requires all four `--data-snooping-*` arguments and an
exactly aligned shared benchmark. The tested universe is every completed trial
declared eligible for the original selection. Complete-family structural
eligibility is mandatory; failed trials retain provenance but receive no
fabricated return curve.

For each trial `k`, the loss differential is represented as active return
`d_(t,k) = strategy_(t,k) - benchmark_t`. White Reality Check uses

```text
T_RC = max(0, max_k sqrt(n) * mean(d_k))
```

and a stationary-bootstrap distribution centered by each observed trial mean.
The implementation follows [White (2000)](https://users.ssc.wisc.edu/~behansen/718/White2000.pdf).

Hansen SPA studentizes each mean with a long-run standard deviation estimated
from the stationary-bootstrap distribution. Consistent recentering suppresses
clearly inferior alternatives using the `sqrt(2 log log n)` threshold. The
implementation reports the consistent SPA p-value described by [Hansen
(2005)](https://www.tandfonline.com/doi/abs/10.1198/073500105000000063).

Both Monte Carlo p-values use the finite-replication correction
`(exceedances + 1)/(replications + 1)`. The complete seed and bootstrap
configuration enter the run manifest. Rejection supports superiority over the
declared benchmark within the supplied family and assumptions; it does not
establish future performance, economic capacity, or freedom from omitted trials.

## Input and compatibility summary

| Evidence | Required contract | Main withholding condition |
|---|---|---|
| Serial extension | lag and significance | lag not below sample size or zero variance |
| Stationary bootstrap | method, percentile, replications, confidence, mean block, seed | irregular sampling, sample too short, block not below sample |
| Advanced risk | target and tail confidence | ratios may be undefined at zero downside/drawdown |
| Risk-free series | timestamped returns | any timestamp mismatch |
| Gross returns | timestamped returns | any timestamp mismatch |
| Regimes | timestamp and non-empty label | any timestamp mismatch |
| HAC alpha | aligned benchmark, lag, confidence | missing/misaligned benchmark, small/singular sample, non-positive variance |
| White/SPA | complete eligible family, shared benchmark, stationary-bootstrap spec | incomplete family, missing benchmark, insufficient or degenerate evidence |

All unavailable states remain typed in report schema `2.5`; inputs are never
silently dropped to force a calculation.
