# FAQ and honest limits

## Does `supported_under_stated_assumptions` mean my strategy works?

No. It means the evidence you configured did not contradict the claim under
the assumptions listed next to it. It never certifies skill, profit or future
performance, and it can sit next to `fragile` or `insufficient_evidence` on
other dimensions.

## Why is there no overall score or pass/fail?

Because a strong dimension cannot make up for a weak one. A long track record
does not repair an undeclared look-ahead control, and a high Sharpe ratio does
not repair an incomplete trial family. The evidence profile's
`overall_status` must be `null` (evidence-profile schema 1.0, embedded in
report schema 2.5), and consumers must not build a hidden aggregate from the
dimensions.

The implementation-risk audit does compute a bounded score per candidate, but
only from divergences it measured under your thresholds. By default it
withholds the score when something was measured but the evidence is incomplete
(the assessment policy's `require_complete_evidence_for_score`). When nothing
could be measured at all, there is no score and the uncertainty is
`not_assessed`: that happens both when every measured field agrees exactly and
when no record could be paired, and the findings tell the two apart.

## Why does it refuse my file instead of fixing it?

Repairing input silently is how audit tools hide errors. The auditor rejects
or flags what it cannot interpret unambiguously: a simple return below −1, a
mean absolute return that suggests percent units, an auxiliary series whose
timestamps do not match exactly (it never inner-joins), an export from an
untested engine version. The error names what to change.

## Why is my Sharpe ratio "undefined"?

Because nothing was annualized or no risk-free rate was stated. Pass
`--periods-per-year` and `--annual-risk-free-rate` explicitly; the auditor
never assumes 252 periods per year or a zero rate (see
[Getting started](getting-started.md)).

## Can it detect look-ahead bias or overfitting in my backtest?

Only within limits that matter:

- A **single-run audit** sees returns, not code. It records whether you
  declared look-ahead and survivorship controls; it cannot check them.
- An **experiment-family audit** measures selection risk (Deflated Sharpe
  Ratio, CSCV/PBO, Reality Check/SPA) over the trials you supply. Trials that
  were run but left out cannot be accounted for.
- An **implementation-risk audit** shows look-ahead as divergence from a
  reference that does not have it. In the example notebooks, a one-bar
  look-ahead produces adverse findings for vectorbt, bt, Backtrader and LEAN;
  for NautilusTrader, whose export has no equity or return level, it shows up
  only as one-sided records.

## Is the reference in an implementation-risk audit the correct answer?

No. It is a declared baseline. A divergence says two implementations differ
beyond your threshold, not which one is right; attribution hypotheses are
co-occurrence, not cause.

## Which engines and versions are supported?

vectorbt 1.1.0, bt 1.2.0, Backtrader 1.9.78.123, NautilusTrader 1.231.0 and
QuantConnect LEAN 2.5.17999 (declared, since LEAN's result files do not
contain a version). Each exporter refuses any other version: the mappings
depend on the exact column names and conventions that were tested. Each how-to
guide lists the limits that affect its engine.

## Does it work on live or paper-trading results?

Partly. The IBKR Flex import turns a broker's time-weighted returns into a
series the single-run audit can read. Questions about a live trade log (is
there an edge, where does it come from, is it decaying) belong to layers 5
and 6 of the [six layers](concepts.md), which this package does not cover.

## How is the package itself tested?

The repository's test suite (`pytest`) includes golden JSON and Markdown
reports, independent hand-calculable numerical reference data, deterministic
property tests, adversarial test suites written against the statistics, and
installed-wheel and source-archive checks; see
[Numerical reference and benchmarks](NUMERICAL_REFERENCE_AND_BENCHMARKS.md)
and [V1.5J release hardening](V1_5J_RELEASE_HARDENING.md). Four documented
choices remain strict expected failures in that suite, each with its reason
recorded next to it: the DSR uses the `ddof=1` cross-trial variance (F01);
percentile-bootstrap Sharpe intervals can cover below the nominal 95 % on a
given seed set (F02); one missing exchange holiday makes a weekday-calendar
series ineligible for annualization (F05); the Lo (2002) effective sample size
can exceed n under negative autocorrelation (F07).

## Is it on PyPI? What is the licence?

Not yet, and the licence is not decided. Until it is, the package metadata
carries the classifier `Private :: Do Not Upload`, which makes PyPI reject an
upload. Install from a checkout of the repository.

## Which Python versions?

Python 3.11 or newer (`requires-python = ">=3.11"`). NautilusTrader 1.231.0
needs 3.12 or newer.

## How do I cite it?

Use the repository's `CITATION.cff`.

## How do I report a security problem?

See `SECURITY.md` in the repository: privately, not in a public issue.
