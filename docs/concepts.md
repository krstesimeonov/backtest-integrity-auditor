# Concepts

## The six layers of backtest integrity

A backtest result can be wrong in more than one place, and each place needs
different evidence. The project separates six layers:

| # | Layer | The question it answers | In this package today |
|---|---|---|---|
| 1 | Statistical claims | Do the reported returns support the claimed performance once sampling, non-normality, serial dependence and the number of trials are accounted for? | **Yes**: single-run and experiment-family audits |
| 2 | Implementation correctness | Does the engine's simulation do what the strategy specification says, compared record by record with a declared reference? | **Yes**: the cross-engine implementation-risk audit |
| 3 | Simulation realism | Are fills, costs, slippage and market impact plausible for the traded size and venue? | No |
| 4 | Portfolio risk | How does the strategy behave inside a portfolio: exposures, concentration, correlation to other holdings? | No |
| 5 | Realised performance | From a live trade log, is there evidence of an edge, where does it come from, is it decaying? | No |
| 6 | Live edge health | Is a running strategy still behaving as its backtest said it would? | No |

Layers 3 to 6 are outside this package. Nothing it reports should be read as
evidence about them. The IBKR Flex import (layer-1 input, not layer 5) only
turns broker statements into a return series that the layer-1 audit can read.

## Layer 1: statistical claims

Two audit modes read results that already exist; the package never runs a
backtest and never places an order.

**Single-run audit** (`backtest-auditor <returns.csv>`): one timestamped return
series. Configured explicitly, it reports sampling and annualization
eligibility, Sharpe ratio and its higher-moment standard error, the
Probabilistic Sharpe Ratio (PSR) and minimum track-record length, ACF/PACF,
Ljung–Box, runs and variance-ratio diagnostics, Bartlett-HAC adjustments,
moving-block and stationary bootstrap intervals, drawdown and tail risk,
benchmark-relative evidence with HAC alpha inference, gross-to-net cost drag,
and slices by externally declared regimes.

**Experiment-family audit** (`backtest-auditor family ...`): every trial that
was run to pick a strategy, with its parameters and returns. It reports the
Deflated Sharpe Ratio (DSR) with trial-count sensitivities, CSCV and the
Probability of Backtest Overfitting (PBO), White's Reality Check and Hansen's
SPA test over the complete family, parameter-neighbourhood and temporal
robustness. Its value depends entirely on the family being complete: trials
that were run but not supplied cannot be accounted for.

Both modes end in the same **dimensioned evidence profile**: each dimension
(input integrity, statistical evidence, serial robustness, multiple testing,
reproducibility, …) gets its own status: `supported_under_stated_assumptions`,
`fragile`, `insufficient_evidence` or `ineligible`. There is no total score,
no global pass, and no rule by which one strong dimension offsets a weak one.

## Layer 2: implementation correctness

The implementation-risk audit compares the evidence of one **reference** run
with one or more **candidate** runs of the same strategy, for example a pandas
reimplementation against a vectorbt backtest, or vectorbt against LEAN. The
reference is a declared baseline, never ground truth.

1. **Export.** An optional exporter reads a completed run of vectorbt 1.1.0,
   bt 1.2.0, Backtrader 1.9.78.123, QuantConnect LEAN 2.5.17999 (its local
   result files) or NautilusTrader 1.231.0 and writes an export envelope. Each
   exporter refuses any other engine version (for LEAN, the version you
   declare, since there is no SDK to inspect).
2. **Map.** An adapter turns the export into the engine-neutral **canonical
   bundle 1.0** (JSON specification plus CSV tables, as a directory or a
   deterministic ZIP, with SHA-256 identities). What an engine does not
   provide is recorded as unavailable, never filled in.
3. **Normalize.** An explicit plan maps instruments, currencies, timestamps
   and frequencies; nothing is guessed and no observation is resampled.
4. **Align and compare** each requested level (order, fill, trade, position,
   cash, cost, equity, return …) by source IDs or by economic identity.
5. **Measure** divergence per declared field in four families: transaction
   cost, sizing, accounting, return.
6. **Assess** materiality against explicit thresholds and family weights; by
   default a bounded score is withheld when the evidence is incomplete, and
   there is none when nothing could be measured.
7. **Report** in implementation-risk report schema 1.0 with its own manifest.
   Attribution ("a cost difference may explain an accounting difference") is
   co-occurrence only: a hypothesis to investigate, not a cause.

Equal returns do not prove equal orders, and a level that one engine does not
export cannot be compared. The [how-to guides](how-to/vectorbt.md) list which
levels each adapter provides.

## Evidence first

Three rules run through both layers:

- **No silent defaults for the choices that decide a conclusion.** No default
  risk-free rate, no assumed 252 periods per year, no inferred audit time or
  Git revision, no guessed instrument mapping. Two documented defaults remain:
  returns are read as simple returns unless `--return-convention log` is
  passed, and the sampling frequency is inferred from the timestamps and
  checked against a declared one.
- **Unavailable is not zero.** A missing input, an ineligible method or an
  unexported level is reported as such, with the evidence that would close it.
- **Reports can identify their inputs.** With an audit identity declared
  (`--audit-id`, `--audit-timestamp`, `--git-commit`), a report carries a
  manifest with raw-file, normalized-data, configuration and manifest SHA-256
  identities, method and dependency versions, and seeds. Reports are
  deterministic for the same inputs and environment; the manifest hash changes
  with the environment by design.

## What the package does not claim

- A `supported_under_stated_assumptions` status does not certify skill, profit
  or future performance. It says the configured evidence did not contradict
  the claim under the assumptions listed next to it.
- It cannot see your code. A single-run audit cannot detect look-ahead bias,
  survivorship bias or a data error in the returns it is given; it records
  whether you *declared* controls for them. Look-ahead in an implementation
  shows up only as divergence from a reference that does not have it.
- A SHA-256 identifies bytes; it is not a signature and does not prove an
  export is truthful.
- Implementation-risk findings are measurements against a declared reference
  under explicit thresholds, not verdicts, and attribution is not causation.
- Adapters are tested against one version of each engine and refuse others.
- Layers 3 to 6 above are not covered.
