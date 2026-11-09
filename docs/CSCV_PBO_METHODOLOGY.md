# CSCV and Probability of Backtest Overfitting Methodology

Part N implements Algorithm 2.3 from Bailey, Borwein, López de Prado, and Zhu,
*The Probability of Backtest Overfitting*. It audits the strategy-selection
process represented by a complete aligned Experiment-Family matrix. It does not
train a model or certify future profitability.

## Eligibility and explicit configuration

The calculation requires:

- complete declared search history;
- at least two completed, selection-eligible trials;
- at least four exactly aligned observations;
- a maximize selection rule;
- explicit confirmation that the manifest selection metric is period Sharpe;
- a positive `periods_per_year` declaration;
- an even partition count `S`;
- `T` exactly divisible by `S` and at least two observations per half-sample;
- an explicit annual simple risk-free rate, tie policies, maximum combination
  count, and maximum acceptable PBO.

Only `period_sharpe_ratio`, average OOS ranks, and first-by-attempt-index IS tie
resolution are currently supported. Every choice is still explicit so later
extensions cannot silently change an existing audit.

## Calculation

Let `M` be the `T × N` matrix of simple returns for the `N`
selection-eligible trials. Log-return inputs are converted period by period.
The annual simple risk-free rate is converted to an equivalent period rate.

1. Divide the rows of `M` into `S` consecutive, disjoint, equal partitions.
2. Enumerate all `C(S, S/2)` choices of `S/2` partitions.
3. Join each choice in time order as the IS half and its complement as OOS.
4. Recalculate the period Sharpe ratio of every trial on each half.
5. Select the maximum IS Sharpe. Preserve every tied ID and choose the earliest
   canonical `attempt_index` when several trials tie.
6. Rank OOS Sharpes from worst (`1`) to best (`N`) with average tie ranks, and
   observe the OOS rank of the IS-selected trial.
7. Calculate relative rank and logit:

```text
omega = OOS rank / (N + 1)
lambda = log(omega / (1 - omega))
```

8. Calculate PBO as the proportion of logits where `lambda <= 0`. This matches
   the reference implementation and counts a median logit as an overfit event.

Every complementary half appears in both roles. The output is deterministic;
there is no random seed and no sampled approximation.

## Additional evidence

Each split preserves partition memberships, selected trial, tied winners,
IS/OOS scores, OOS rank, relative rank, logit, and overfit/below-zero flags. The
family result also reports PBO, its configured requirement, selected OOS
below-zero frequency, mean/median logits, and the OLS intercept, slope, and
R-squared for selected OOS Sharpe regressed on selected IS Sharpe. The
regression describes performance degradation; it is not causal.

## Evidence-preserving failure policy

The auditor does not silently trim observations, sample fewer combinations,
remove zero-volatility trials, drop invalid splits, reuse external folds as
CSCV, or infer that a similarly named metric is period Sharpe. Each condition
returns a typed status. If split metrics are incomplete, attempted splits and
unavailable trial IDs remain visible while aggregates remain undefined.

## Interpretation boundaries

PBO is a relative-rank diagnostic. A high value can arise among several
similarly skilled strategies; a low value cannot repair bad prices, look-ahead,
survivorship bias, unrealistic costs, or a non-representative regime. Few
trials give coarse ranks, few combinations give coarse tail frequencies, and
strong time dependence can make partition choice material.

PSR compares one Sharpe estimate with a benchmark. DSR compares the selected
full-sample Sharpe with an expected search maximum. CSCV/PBO measures how often
IS selection degrades in complementary OOS samples. These are complementary,
not interchangeable. PBO must not become a strategy-search objective.

## References

- Bailey, D. H., Borwein, J. M., López de Prado, M., and Zhu, Q. J., *The
  Probability of Backtest Overfitting*:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- `pypbo` reference implementation used to cross-check rank, relative-rank,
  logit, and `lambda <= 0` behavior:
  https://github.com/esvhd/pypbo/blob/master/pypbo/pbo.py
