# E2E toy strategy — defined once

Every `tests/e2e/test_<engine>.py` implements exactly this strategy natively in
its engine. `tests/e2e/reference.py` computes the expected result
independently (pandas, numpy and `decimal` only; it imports neither
`backtest_auditor` nor any engine). `python tests/e2e/reference.py` prints the
tables below.

## Market data

- One synthetic equity, instrument id `SYN`, currency USD.
- 400 daily bars, one per weekday from 2024-01-02 (no holidays; the market is
  synthetic).
- Seed `20261062`, `numpy.random.default_rng`: log returns N(0.0004, 0.015)
  (first set to 0), open gaps N(0, 0.004), high/low wicks |N(0, 0.005)|. Close
  starts at 100.00. All prices are rounded to cents; high ≥ max(open, close),
  low ≤ min(open, close).
- **Bar timestamp = the session close instant, 16:00 America/New_York, in
  UTC**: 21:00Z in EST, 20:00Z in EDT. The series crosses three DST changes, so
  an adapter that shifts time zones or ignores DST changes fill timestamps.
- The bars are checked in as `tests/e2e/data/syn_daily.csv`; tests read that
  file, and `python tests/e2e/reference.py --write-prices` regenerates it from
  the seed. Engines receive these floats; the reference reads the same file as
  exact decimals.

## Rules

1. Signal on each bar's close: `SMA20 > SMA50` → +1 (long), else 0 (flat).
   Before bar 50 the slow average is undefined and the signal is 0. The first
   defined state is flat, so a state rule ("long while fast > slow") and an
   event rule ("enter on the cross up, exit on the cross down") give the same
   trades. The two averages never come closer than 0.0656, so no engine's
   rounding can flip a signal.
2. **Deliberate short period:** for signal sessions 2025-02-06 … 2025-03-05
   (inclusive) the signal is overridden to −1. The moving-average signal is
   flat from 2025-01-23 to 2025-04-11, so the short never meets a long.
3. **Execution lag of one bar:** the position held at bar *t* is
   `100 × signal(t−1)` shares. A change is one market order for the
   difference, filled at the **close of bar *t*** and stamped with bar *t*'s
   timestamp (every engine supports "act at today's close on yesterday's
   signal"). Each order is ±100 shares, never a reversal.
4. **Fee:** a fixed USD 1.00 commission per fill, deducted from cash.
5. Initial cash USD 100,000.00; no interest, borrow fee, slippage, dividends or
   margin cost. Equity at bar *t* = cash + position × close(*t*).
6. The strategy ends flat (last fill 2025-06-03), so final equity = final cash.

## Expected trade list (`lag=1`, the specification)

| # | timestamp (UTC) | side | qty | price | fee |
|---|---|---|---:|---:|---:|
| 1 | 2024-03-25 20:00 | buy | 100 | 89.51 | 1.00 |
| 2 | 2024-06-19 20:00 | sell | 100 | 97.33 | 1.00 |
| 3 | 2024-08-12 20:00 | buy | 100 | 101.88 | 1.00 |
| 4 | 2024-09-25 20:00 | sell | 100 | 94.88 | 1.00 |
| 5 | 2024-11-11 21:00 | buy | 100 | 97.56 | 1.00 |
| 6 | 2025-01-24 21:00 | sell | 100 | 94.96 | 1.00 |
| 7 | 2025-02-07 21:00 | sell | 100 | 96.59 | 1.00 |
| 8 | 2025-03-07 21:00 | buy | 100 | 91.56 | 1.00 |
| 9 | 2025-04-15 20:00 | buy | 100 | 102.53 | 1.00 |
| 10 | 2025-06-03 20:00 | sell | 100 | 97.82 | 1.00 |

Round trips (P&L net of both fees): long +780.00, long −702.00, long −262.00,
**short +501.00** (entry 96.59, exit 91.56), long −473.00.
**Final equity: USD 99,844.00.**

## Injected defect: look-ahead (`lag=0`)

The position at bar *t* follows `signal(t)`: the signal is shifted one bar, so
the strategy trades on the close it has not yet seen. Every fill moves one bar
earlier (first buy 2024-03-22 at 91.24); final equity USD 99,750.00. Each engine
test runs this variant through the same adapter and asserts that the
implementation-risk report flags it.

## Tolerances

| Check | Tolerance | Why |
|---|---|---|
| fill count, sides, quantities, timestamps | exact | integers, cents, UTC instants |
| fill price, fee | ±0.000001 USD | engines carry float64; cents survive float round-trips exactly |
| final equity (or final cash), trade P&L | ±0.000001 USD | ~20 float additions on 1e5 cannot reach 1e-6 |

## Implementation-risk policy (`harness.implementation_risk`)

Reference run = a canonical bundle built from `reference.py` alone; candidate
= the engine's adapted bundle. Every level is aligned semantically
(timestamp, instrument, side…). Materiality thresholds (absolute; extreme at
10×): fill quantity 0.5, fill price 0.005, cost 0.005, position quantity 0.5,
trade quantity 0.5, trade realized P&L 0.01, cash 0.01, equity 0.01, return
1e-8. They sit far above float noise and far below the smallest effect of a
one-bar shift (a price move of at least a cent on 100 shares).

- **Correct strategy:** every compared level has only matched records (no
  one-sided or ambiguous record), no `adverse` and no `evidence_gap` finding,
  nothing withheld, and either a computed score below 1 or, when every measured
  field matches exactly, no score with uncertainty `not_assessed` (V1.5H's
  intended reading of exact agreement; MATRIX.md note C).
- **Look-ahead variant:** at least one `adverse` finding (NautilusTrader: strict
  xfail, its bundle has no fixed-grid level; MATRIX.md note D).

Levels compared per engine follow each adapter's documented evidence
(`docs/V1_5D2…`, `docs/V1_5D3…`); positions and cash are sampled per bar or per
fill to match that documentation (`reference_artifacts(positions_at=…,
cash_at=…)`). The test files list their levels.
