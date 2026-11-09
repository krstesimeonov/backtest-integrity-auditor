# V4 Edge Audit — design (version 1.1)

Status: implemented in `src/backtest_auditor/edge_audit/`, tested in `tests/edge_audit/`.
Every number in the worked examples below is recomputed by
`tests/edge_audit/test_edge_audit_design_examples.py`.

## 0. What V4 answers

Quant Integrity audits a strategy in six layers: statistical claims (V1), implementation
correctness (V1.5), simulation realism (V2), portfolio risk (V3), **realised performance
(V4, this document)** and live edge health (V5). V1–V3 look at a backtest. V4 looks at what
actually happened: a log of closed trades. It answers four questions, in this order:

1. **Is there evidence of an edge?** One pre-specified test (§3.2), deflated for the number of
   strategy variants the trader tried (`--trials N`).
2. **Where does it come from?** Entry timing, exit timing, holding (direction), execution
   (§3.3); holding period and volatility regime (§3.4); position sizing (§3.7).
3. **Is it decaying?** Rolling expectancy, CUSUM, Page–Hinkley and a sequential test (§3.6).
4. **How sensitive is it to costs?** Expectancy versus extra cost per trade, break-even cost,
   and the cost at which the statistical evidence disappears (§3.5).

Command: `edge-audit run trades.csv --trials N [--prices prices.csv] [--out DIR]`.
Until `pyproject.toml` gets the line `edge-audit = "backtest_auditor.edge_audit.cli:main"`
under `[project.scripts]` (outside this job's paths), run it as
`python -m backtest_auditor.edge_audit run …`; a test runs an equivalent of the wrapper pip
would install. Output: `edge_audit_report.json` and `edge_audit_report.md` with identical content.

Not in scope for 1.x: open positions and partial fills (close them in the log), several
account currencies (convert first), portfolio-level overlap (V3), live monitoring (V5; the
decay detectors here are its retrospective prototype).

## 1. Inputs

Both inputs are CSV (UTF-8, comma separated, double quotes, read strictly: an unclosed quote
or a line break inside a field is an error) with a header row. An optional
first line `# schema: <id>` pins the version; a file declaring any other version is refused.
Without the line the file is read as 1.0 and the report says so
(`input.trades.schema_declared_in_file = false`). Rows with no content are skipped; every row
must have as many fields as the header.

Timestamps: `YYYY-MM-DDTHH:MM[:SS[.fffffffff]]` (a space may replace the `T`) followed by
`Z` or an offset `+hh:mm` / `+hhmm`, for example `2025-01-02T14:30:00Z`. Nothing else is
accepted: a naive time would silently shift trades across day boundaries, and a layout such
as `03/04/2025` means different dates in different countries.

### 1.1 `edge-audit-trades/1.0` — closed trades, one row each

| Column | Req. | Type / unit | Rule |
|---|---|---|---|
| `instrument` | yes | text | non-empty; must match the price file's names for timing analysis |
| `side` | yes | `long` / `short` (any case) | |
| `quantity` | yes | number > 0 | units or contracts, unsigned |
| `entry_time` | yes | timestamp as above, **with offset** | naive or non-ISO times are rejected |
| `entry_price` | yes | number > 0 | average fill price |
| `exit_time` | yes | timestamp as above, with offset | `exit_time >= entry_time` |
| `exit_price` | yes | number > 0 | average fill price |
| `fees` | yes | number >= 0, account currency | all explicit costs of the round trip (commission, exchange, financing). Slippage is already in the fill prices |
| `trade_id` | no | text | unique; default `L<line>` |
| `multiplier` | no | number > 0, default 1 | contract multiplier (ES = 50) |
| `currency` | no | text | if present, one value for the whole file |
| `entry_volatility` | no | number >= 0 | the trader's own regime measure at entry; if present it is used for §3.4 instead of the price file |

Any other column is an error (a typo such as `fee` must not become "fees are zero").
Validation collects **every** problem with the physical CSV line number (blank lines and
quoted line breaks counted) and stops before any statistics (`InputValidationError`; CLI exit
code 2; codes such as `invalid_side`, `naive_entry_time`, `invalid_entry_time`,
`exit_before_entry`, `duplicate_trade_id`, `duplicate_column`, `wrong_field_count`,
`mixed_currency`).

Derived per trade (k = side · quantity · multiplier, side = ±1):

| Quantity | Definition |
|---|---|
| gross P&L | k · (exit_price − entry_price) |
| net P&L | gross P&L − fees |
| notional | quantity · multiplier · entry_price |
| net return | net P&L / notional |
| holding period | exit_time − entry_time |

Trades are sorted by (exit_time, entry_time, trade_id): exit order is when P&L was
realised, the time axis of every sequential method.

### 1.2 `edge-audit-prices/1.0` — optional, for §3.3 and §3.4

Columns `instrument, timestamp, price` (timestamp with offset, price > 0, no duplicate
timestamp per instrument). Bars, mid quotes or trade prices at any regular or irregular
spacing. "The bar in force at time t" is the last price with timestamp <= t.

### 1.3 Versioning

The 1.0 reader rejects unknown columns and any other declared version, so a file written for a
later schema is refused rather than misread. Any added, renamed or removed column, and any
change of meaning or unit, is a new schema id (1.1 for an added optional column, 2.0 for the
rest) with its own reader. The report schema follows the same rule: `report_schema.py` closes
every object (`additionalProperties: false`), so a field added to the report but not to the
schema fails the tests.

## 2. Output: `edge-audit-report/1.1`

Full JSON Schema: [`edge-audit-report-1.1.schema.json`](edge-audit-report-1.1.schema.json)
(generated from `report_schema.py`; a test keeps them identical). Top level:

| Key | Content |
|---|---|
| `schema`, `generated_by` | `edge-audit-report/1.1`; package name and version |
| `input` | file names, SHA-256 of each input, schema ids, row count |
| `settings` | every choice that can change a number (seed, resamples, trials, windows, thresholds) |
| `verdict` | `edge` ∈ {`evidence_of_edge`, `no_evidence_of_edge`, `insufficient_data`}, the test, its DSR |
| `answers` | the four questions above, one sentence each, generated from the numbers |
| `performance` | counts, totals, expectancy / profit factor / win rate with intervals, payoff, holding, overlap, serial dependence |
| `luck_vs_skill` | SR per trade, t, PSR, DSR (verdict and classical), expected max SR, MinTRL, trades needed |
| `timing` | per component: total, share, mean per trade with interval, randomisation p-values, finding; counterfactual quantiles |
| `conditional` | `holding_period` and `volatility_regime` tercile tables with permutation p-values |
| `costs` | cost curve, break-even with interval, gross break-even, fees paid, cost at which evidence is lost |
| `decay` | reference window, rolling expectancy, false-alarm budget α, horizon N, calibration null and table; one entry per detector (status, threshold, α, N, null, alarm trade, time) |
| `sizing` | actual vs fixed-size expectancy, sizing contribution with interval, permutation p, fixed-size verdict |
| `warnings` | data conditions that weaken a method (overlap, serial dependence, few trades, exclusions) |

An *interval* object is `{point, lower, upper, confidence_level, standard_error,
replications, valid_replications, upper_unbounded, point_unbounded}` (`point_unbounded`: a
profit factor with no losing trade at all). Undefined numbers are `null`, never
`NaN`. No wall-clock time is written: the same inputs and settings give byte-identical
files (tested).

## 3. Methods

Notation: T trades, x_i net P&L of trade i, x̄ its mean, s its SD (ddof = 1),
SR = x̄ / s the per-trade Sharpe ratio, Φ the standard normal CDF, z_q = Φ⁻¹(q).

### 3.1 Trade-level bootstrap intervals: expectancy, profit factor, win rate

**Intuition.** The log is one draw of the trader's luck. Re-drawing T trades with
replacement from the log many times shows how much the three headline numbers would move
if a different but equally likely set of trades had happened.

**Example.** P&L = 120, −80, 50, −40, 0, 150, −60, 30. Expectancy 21.25; profit factor
350 / 180 = 1.944; win rate 4/8 = 0.5 (the zero trade is not a win). One resample, indices
(5, 0, 0, 3, 7, 1, 5, 2): 150, 120, 120, −40, 30, −80, 150, 50, mean 62.5. With 10,000
resamples (seed 1) the 95 % intervals are: expectancy [−31.25, 76.25], profit factor
[0.238, unbounded], win rate [0.125, 0.875]. Eight trades say almost nothing.

**Formula.** For b = 1..B draw indices I_b (V1's `stationary_bootstrap_indices`; mean block
length 1 = i.i.d.), compute θ*_b = θ(x[I_b]). Interval: the α/2 and 1 − α/2 quantiles of
θ* with linear interpolation (V1's convention). Profit factor PF = Σ x⁺ / Σ |x⁻|; a resample
without a losing trade has PF = +∞, which is kept, so an upper end can be unbounded.

**Assumptions.** Trades are exchangeable (i.i.d.). With `--block-length L > 1` runs of
consecutive trades are kept together (stationary bootstrap) for serial dependence.

**Failure cases.** Percentile intervals can under-cover, more so with few trades and for ratio
statistics (V1 finding F02 in `FINDINGS_DISPOSITION.md`: a Sharpe-ratio interval with n = 500
covered 92.6 % on its test's seeds, 94.3 % pooled); the report warns below 100 trades. Overlapping trades share
market moves, so they are less independent than T suggests (the report prints the maximum
number open at once). A single huge trade dominates both the point estimate and the
interval; the profit factor's upper end is often unbounded below ~50 trades.

### 3.2 Luck versus skill: t = SR·√T, DSR at a declared trial count, MinTRL

**Intuition.** A positive average can be luck. The t-statistic measures how many standard
errors the average is above zero. If the trader tried N variants and kept the best, the best
one's t is inflated even with no skill at all; the Deflated Sharpe Ratio (DSR) raises the bar
to the Sharpe ratio the best of N skill-less variants would show on average.

**Example.** SR = 0.1 per trade over T = 400 trades: t = 0.1 · √400 = 2.0 (one-sided p
0.0231 with 399 degrees of freedom). At 200 trades a year that is SR_annual = 0.1 · √200 =
1.414 over 2 years, and t = 1.414 · √2 = 2.0 again. One variant (N = 1): DSR = Φ(0.1·√399) =
0.9771 ≥ 0.95, evidence. Ten variants (N = 10): the expected maximum of 10 standard normals is
e₁₀ = 1.5746, the standard error under H0 is 1/√399 = 0.05006, so the bar is
SR* = 1.5746 · 0.05006 = 0.0788 and DSR = Φ((0.1 − 0.0788)/0.05006) = Φ(0.4229) = 0.6638:
no evidence. At SR = 0.1 the verdict needs 272 trades with N = 1 and 1,038 with N = 10.

**Formula.**
* t = x̄ / (s/√T) = SR·√T exactly; with annualised SR, t = SR_annual·√years.
* Expected maximum (V1, `_expected_maximum_standard_normal`):
  e_N = (1 − γ)·z_{1−1/N} + γ·z_{1−1/(N·e)}, γ = 0.5772 (Euler–Mascheroni), e₁ = 0.
* Cross-trial spread of SR: σ_N = 1/√(T−1) by default — the SD of a skill-less trial's SR
  estimate — or `--trial-sharpe-std` if the trader knows it. Bar: SR* = σ_N · e_N.
* **Verdict:** DSR = Φ((SR − SR*) / SE₀), SE₀ = 1/√(T−1) (the SE of SR *under H0*), computed
  by V1's `_calculate_scenario` with V1's SR. Evidence iff T ≥ 30 and DSR ≥ 0.95
  (`--confidence`).
* Reported for comparison, exactly as V1 and Bailey & López de Prado compute it: PSR and the
  classical DSR with the plug-in SE = √((1 − g₃·SR + (g₄ − 1)/4·SR²)/(T − 1)), g₃ skewness,
  g₄ Pearson kurtosis of the trade P&L.
* MinTRL (V1): 1 + V·(z_{0.95}/SR)² with the plug-in V. Trades needed for the verdict,
  never below the 30-trade minimum: with one trial or a declared σ (a fixed bar SR*), V1's
  MinTRL with V = 1 against SR*; with N > 1 and the default σ_N the bar e_N/√(T−1) shrinks as
  T grows, which V1's MinTRL does not model, so T* = 1 + ((z_{0.95} + e_N)/SR)² (solve
  SR·√(T−1) − e_N = z for T; computed here, not in V1).
* All of this runs on a "trade clock": V1 sees a regular series with one period per trade
  (P&L divided by a constant so the values sit in V1's return domain; every quantity above
  is scale-free, so nothing changes).

**Why the verdict uses SE₀ and not the plug-in SE.** The first calibration run (§5) failed:
on 500 fat-tailed noise logs the classical DSR fired on 41 (band 13–38). On 4,000 more logs,
used for the diagnosis: plug-in 6.22 %, Student t 5.30 %, SE₀ 5.37 % at a nominal 5 %. With
fat tails the sample skewness moves with the sample SR (correlation 0.45 on the 500 logs), so
the plug-in SE shrinks exactly when SR is high by luck; under H0 (SR = 0) the variance
adjustment is 1 whatever g₃ and g₄ are. Run only after the change, on seeds never used
before: 4,000 held-out logs, SE₀ 197 (4.9 %) and plug-in 230 (5.75 %); the SPEC's 500-seed
scenario on a fresh block, SE₀ 32 (6.4 %, 95 % interval 4.4–8.9 %) and plug-in 38 (7.6 %).
(Re-run: `docs/edge_audit/job/evidence/fpr_diagnosis.py`; the tests
`test_a_extended_verdict_calibration_on_4000_held_out_seeds` and
`test_a_noise_logs_on_500_fresh_seeds`.)

**Assumptions.** Trades i.i.d. with finite variance; T large enough for the normal
approximation (≥ 30 enforced); N counts every variant whose result the trader saw before
choosing this one, including discarded parameter sets; trials are independent (correlated
trials make the effective N smaller: then pass a smaller N and say why).

**Failure cases.** An under-declared N (the most common and the most damaging). With N > 1
the DSR rule is conservative for independent trials: on best-of-10 noise strategies it
fired on 2 of 300 (0.7 %), not 5 %, while the undeflated test fired on 42 % (§5); an exact max-of-N test (Šidák) is an exercise in
LEARNING.md. Serial dependence makes SE₀ too small (the report runs V1's Ljung–Box and warns).
Trade-clock annualisation treats trades as periods; with overlapping trades it overstates
the annual SR.

### 3.3 Timing decomposition: entry vs exit vs holding vs execution

**Intuition.** Replace the actual entry time with a random time in a window and keep
everything else: the P&L lost on average is what the entry timing earned. Do the same for
exits. What remains when both times are random is the directional call (holding); the
difference between fills and the prices in force is execution.

**Example** (the unit test's numbers). Long 10 units. Day 1 bars 100, 98, 101, 103 (mean
100.5); day 2 bars 104, 106, 105, 109 (mean 106). Entry fill 98.2 at the 98 bar, exit fill
104.9 at the 105 bar. Gross P&L 10·(104.9 − 98.2) = 67. Holding 10·(106 − 100.5) = 55;
entry timing 10·(100.5 − 98) = 25; exit timing 10·(105 − 106) = −10; execution
10·((98 − 98.2) + (104.9 − 105)) = −3. 55 + 25 − 10 − 3 = 67.

**Formula.** With k = side·quantity·multiplier, fills P_e, P_x, bars in force B_e, B_x and
window means Ē_e, Ē_x:

    gross = k(Ē_x − Ē_e)  holding
          + k(Ē_e − B_e)  entry timing
          + k(B_x − Ē_x)  exit timing
          + k[(B_e − P_e) + (P_x − B_x)]  execution          (exact identity)

Windows, `--timing-window day` (default; days in `--day-timezone`): W_e = the entry day's
bars up to the bar in force at exit; W_x = the exit day's bars from the bar in force at
entry. `--timing-window holding`: W_e = W_x = the bars in force during the trade.
Tests: entry — draw a uniform bar in W_e for every trade, keep actual exits, total P&L at bar
prices; repeat `--timing-draws` times; p = (1 + #{draw ≥ actual})/(draws + 1). Exit — the
same with W_x. Holding — flip each trade's holding component's sign at random (H0: direction
independent of the move). Each component also gets a bootstrap interval of its mean.
A component "adds P&L" if its p < 0.05, "costs P&L" if the opposite tail's p < 0.05.

**Assumptions.** Under H0 the actual entry (exit) time is like a uniform draw from its window;
bars are dense enough that "a random time" is "a random bar"; prices in the file are the ones
the trader could have traded at (mid or last).

**Failure cases.** Holding mode credits a trend inside the trade to timing and has holding
≡ 0 by construction (reported as such). Day mode with strategies that may only enter at the
open makes "a random time in the day" an impossible counterfactual — choose windows that
match the decision rule. The holding test's null is "direction independent of the move, moves
symmetric": a long-biased book in a rising market shows "holding adds P&L" that is market
drift (beta), not skill — the adversarial review measured 20 of 20 flagged at a drift of about
0.4 % a day, 1 of 5 at 10 % a year with 1,000 trades. Trades are excluded and counted
(`timing.excluded`) when the instrument has no prices, when no bar exists at or before the
entry, or, in day mode, when the bar in force at entry or exit comes from an earlier day
(entered or exited before that day's first bar: the actual time could never be a draw, and
the overnight gap would be credited to timing). Days are calendar days in `--day-timezone`;
where clocks jump at midnight the day starts at the first instant that exists. Intraday trades
in day mode can draw an exit before the entry in the joint counterfactual; the identity is
unaffected (it uses expectations), the "random entry and exit" quantiles are.

### 3.4 Holding period and volatility regime (terciles)

**Intuition.** An edge that lives only in short trades, or only in calm markets, is a
different business from one that is everywhere. Split the trades into thirds and compare.

**Example.** Holding hours 1, 2, 3, 10, 11, 12, 40, 50, 60 with P&L −1, 0, −2, 1, 2, 0, 5,
4, 6: tercile means −1, 1, 5; grand mean 1.667; between-tercile sum of squares
3·[(−1 − 1.667)² + (1 − 1.667)² + (5 − 1.667)²] = 56.0. Shuffling the labels many times shows
how often a split this uneven appears by chance.

**Formula.** Labels by rank: label_i = ⌊3·rank_i / T⌋ (ties in exit order), so groups differ
in size by at most one. Statistic S = Σ_g n_g (x̄_g − x̄)²; p = (1 + #{S_perm ≥ S})/(B + 1)
over B label permutations. Per tercile: expectancy with a bootstrap interval, win rate.
Volatility at entry: SD of log price changes over the `--vol-lookback-bars` bars strictly
before the entry time, or the `entry_volatility` column if present.

**Assumptions.** Exchangeability of trades across terciles under H0. At least 10 trades per
tercile (otherwise "unavailable").

**Failure cases.** Cut points use the whole sample, so tercile membership is descriptive, not
tradable. Holding period is chosen by the strategy (a stop-loss makes losers short): a
holding-period effect is often the exit rule, not a regime. Two splits are tested, so one
p < 0.05 among them is weaker than it looks.

### 3.5 Fee and slippage sensitivity

**Intuition.** Costs scale with notional; an edge measured in basis points of notional can be
eaten by a few basis points of extra slippage. The curve shows how fast.

**Example.** Three trades with net P&L 3, −1, 4 and notional 1,000, 2,000, 3,000: mean net 2,
mean notional 2,000, break-even added cost 2 / 2,000 = 0.001 = 10 bps. Expectancy at c bps
added: 2 − 0.2·c.

**Formula.** net_i(c) = net_i − c·10⁻⁴·notional_i; expectancy(c) = x̄ − c·10⁻⁴·N̄ (a line);
break-even c* = x̄ / N̄ · 10⁴ bps (interval: the same bootstrap resamples as the expectancy,
ratio of resampled means); gross break-even = mean gross / N̄ · 10⁴ = c* + fees already paid;
"evidence lost at" = the smallest c (bisection to 0.001 bps) where the §3.2 verdict stops
being evidence.

**Assumptions.** Extra costs are proportional to entry notional; trades would have happened
anyway at the higher cost (no change in behaviour).

**Failure cases.** Fixed per-trade costs (per-ticket fees) are not proportional; read the
curve at the average notional. Capacity effects (impact grows with size) make the true curve
bend down. The ratio-of-means break-even is not the mean of per-trade returns (they differ
when size and return are related: §3.7).

### 3.6 Decay: rolling expectancy, CUSUM, Page–Hinkley, mixture SPRT

**Intuition.** Use the first part of the log to learn what the edge looked like, then watch
the rest for a drop. The rolling expectancy compares the last w trades with the reference;
CUSUM accumulates evidence of a drop and forgets evidence of no drop; Page–Hinkley does the
same against the running mean instead of the reference mean; the mixture SPRT weighs "edge
intact" against "edge down by some amount" over all monitored trades. Every detector has a
false-alarm budget: had nothing changed, the chance of any alarm within the horizon is α.

**Example.** Standardised trades z = −1, −1, 0.5, −2 with allowance k = 0.25: CUSUM
S = 0.75, 1.5, 0.75, 2.5. Mixture SPRT with τ = 0.5 after the 4 trades (S = −3.5,
a = 4 + 1/0.25 = 8): log Λ = ln 2 − ½ ln 2 + 3.5²/16 + ln Φ(3.5/√8) = 0.998, below Ville's
5 % bound ln 20 = 2.996 (valid when μ₀ and σ₀ are known). Siegmund's
approximation gives an average run of 142 trades between false alarms for k = 0.25, h = 5 —
but that ignores the error in the estimated reference (below).

**Formula.** Reference = first R trades (default max(30, ⌊T/3⌋)): μ₀, σ₀, SR₀ = μ₀/σ₀; no
positive SR₀ → no edge to lose, detectors not run. Monitored trades: z_t = (x_t − μ₀)/σ₀,
t = 1..M. Shift to detect δ = SR₀ (the whole edge) or `--decay-shift`.
* Rolling expectancy over w = min(50, max(10, ⌊T/5⌋)) trades (`--rolling-window`): the series
  is reported for the whole log; the alarm statistic is D_t = −(z_{t−w+1} + … + z_t)/√w for
  t ≥ w, i.e. an alarm when the w-trade average P&L falls below μ₀ − h·σ₀/√w (reported in
  currency as `alarm_level_mean_pnl`).
* CUSUM: S_t = max(0, S_{t−1} − z_t − δ/2); alarm when S_t > h.
* Page–Hinkley: m_t = Σ_{s≤t}(z_s − z̄_s + δ/2) with the running mean z̄_s; alarm when
  max(0, m_1..m_t) − m_t > λ.
* Mixture SPRT: log Λ_t = ln 2 − ½ ln(1 + tδ²) + S_t²/(2a_t) + ln Φ(−S_t/√a_t), S_t = Σ_{s≤t} z_s,
  a_t = t + 1/δ²: the likelihood ratio of "down by θ" against "intact", averaged over
  θ ~ half-normal(scale δ), so every drop counts, not only δ. One test over the horizon, no
  restarts. Alarm when log Λ_t > h. With μ₀, σ₀ known, Λ is a martingale under "intact" and
  Ville's inequality gives P(sup Λ ≥ 1/α) ≤ α at any horizon; with them estimated it does
  not hold, so h is simulated like the others.
* Thresholds: one table, `decay_thresholds.py`, generated by
  `python -m backtest_auditor.edge_audit.decay_calibration --write`. Each cell is the (1 − α)
  quantile of the largest statistic within N monitored trades over 40,000 paths simulated under
  the calibration null `iid_normal`: i.i.d. normal trades without a change, the reference mean
  and SD re-drawn in every path from their exact distributions for R trades (mean ~ N(0, 1/R),
  (R − 1)·SD² ~ χ²(R − 1)). Grid: α ∈ {0.005, 0.01, 0.02, 0.05, 0.1, 0.2}, N ∈ {30, …, 10,000}
  (17 values), R ∈ {30, 50, 75, 100, 150, 200, 300, 400, 600, 1,000, 1,500, 3,000, 6,000, ∞}, δ ∈ {0.02, …, 2}
  (12 values), w ∈ {10, …, 100} (8 values). The logarithm of a threshold is interpolated
  multilinearly in (ln α, ln N, 1/√R, ln δ or ln w): thresholds grow roughly exponentially along
  these axes, and leave-one-out on the table shows log-thresholds interpolate with less error
  where it matters (CUSUM and mixture SPRT; `calibration/interpolation_loo.txt`). A grid point
  returns the stored value exactly.
* α (`--decay-false-alarm`, default 5 %, 0.5–20 %) and N (`--decay-horizon`, default 1,000,
  30–10,000) are inputs. The horizon used is max(N, M): the budget always covers every
  monitored trade. When M < N each detector also reports the false-alarm chance over the M
  trades it saw (`false_alarm_probability_over_monitored`, from the same table).
* Reported per detector: status (or why not run: δ, w, R or N outside the table), threshold,
  α, N, the calibration null, alarm trade and exit time, largest statistic.

**Assumptions.** Under "intact" the trades are i.i.d. with constant variance and normal tails
(the table's null); the reference window is representative.

**Failure cases.** Measured in `CALIBRATION.md` (2,000 logs per cell): with serially dependent
trades (AR(1), φ = 0.3, t(3) shocks) the false alarms within N = 1,000 trades are
17.4–48.5 % instead of 5 %, with fat tails (Student t, 3 degrees of freedom)
7.0–14.4 %; the report says which null the thresholds assume and warns when the
trades are serially dependent. A volatility change looks like a mean change to all four.
Page–Hinkley compares each trade with the running mean of the monitored trades, so it cannot
see a drop that starts with the first monitored trade. Detection is slow when the edge is
small: with SR 0.3 → 0 after 100 of 400 monitored trades, CUSUM's median delay was
110.5 trades (§5, scenario c). A short reference makes μ₀ uncertain and the honest thresholds
large: in the sample audit (140 reference trades, SR₀ 0.20, 280 monitored, horizon 1,000) the
CUSUM threshold is 65.8, against 28.8 from Siegmund's formula with μ₀ and σ₀ known (5 % over
the same 1,000 trades, taking false alarms as a Poisson stream: ARL₀ = −1,000 / ln 0.95).

**Why not formula thresholds, and what happened to Wald's SPRT.** Version 1.0 ran Wald's SPRT
(A = ln((1−β)/α), restart after every "intact"). Its no-change false alarms were 13.2 % over
400 monitored trades and 47.5 % over 4,000 (`CALIBRATION.md`, Table C): each restart is a fresh
chance to cross A, and the estimated reference adds a common shift the formula ignores. The
same two effects break Siegmund's CUSUM formula, Ville's bound and a per-window 5 % limit on
the same simulated logs (Table D). The fix is one rule for all four detectors: simulate the detector under
the stated null with the reference re-estimated, over the stated horizon.

### 3.7 Position-sizing contribution: fixed-size counterfactual

**Intuition.** Keep each trade's return but give every trade the same size. If the trader's
sizing carried information, the fixed-size P&L is worse; if sizes were arbitrary, it is the
same on average.

**Example.** Notional 1,000, 3,000, 1,000, 3,000 with net returns −1 %, +1 %, −1 %, +1 %:
actual P&L −10, 30, −10, 30 (mean 10). At the mean notional 2,000: −20, 20, −20, 20 (mean 0).
All of the edge (10 per trade) is sizing: big positions went into the winners.

**Formula.** fixed_i = r_i·N̄; sizing contribution = x̄ − mean(fixed) = mean((N_i − N̄)·r_i),
exactly the population covariance of notional and return. Interval: bootstrap (N̄
recomputed in every resample). Test: permute notionals across trades; p = (1 + #{|c_perm| ≥
|c|})/(B + 1). The §3.2 verdict is also run on the fixed-size series.

**Assumptions.** Under H0 size is exchangeable across trades; a trade's return does not
depend on its size (no market impact).

**Failure cases.** Size that grows with account equity creates a contribution from the
equity path, not from information. Notional also moves with the price level (a trending
instrument). With impact, big trades have worse returns and sizing looks harmful.

## 4. Verdict and answers

The verdict is §3.2's test alone; it uses no random numbers (the seed changes intervals and
p-values, never the verdict — tested). `insufficient_data` when T < 30, the P&L has no
variation, or fewer than 4 trades. The `answers` sentences are generated from the numbers:
evidence (DSR, expectancy interval, trades needed), source (timing components, sizing,
terciles), decay (alarms, monitored-minus-reference interval), costs (break-even, evidence
lost).

## 5. Calibration

Known-truth scenarios (SPEC a–e) are in `tests/edge_audit/test_edge_audit_scenarios.py`
with acceptance bands fixed before the first run; the measured numbers are in
`TEST_RESULTS.txt` (job folder) and `docs/edge_audit/job/evidence/scenario_results.json`:
(a) false-positive rate on 500 noise logs — on a block of seeds never run before the verdict
changed, and, after the fact, on the original seeds 0–499 whose failure caused the change —
and on 4,000 held-out logs; best-of-10 selection; (b) entry alpha attributed to entry;
(c) detection delay distribution of the decay detectors and their no-change false-alarm rates
(1.0: the CUSUM and Page–Hinkley bands pre-registered, the SPRT and Page–Hinkley detection
floors added after the second run as regression guards; 1.1: the band applies to all four
detectors at a 400-trade horizon, and the detection floors for the calibrated detectors were
written before their first run); (d) break-even recovery and interval coverage; (e) the
fixed-size counterfactual removing the sizing contribution.

The decay detectors' own calibration (1.1) is documented in `CALIBRATION.md`: false alarms
under three nulls at N = 100, 400, 1,000 and 4,000 before and after the table, detection
delays, where the old SPRT's false alarms came from, and what formula thresholds do on the
same logs. `tests/edge_audit/test_edge_audit_detector_calibration.py` requires every detector's
no-change false-alarm rate to be within ±1.5 percentage points of α = 5 % at N = 400 and
1,000 under the i.i.d. normal null (4,000 logs each) and prints the rates under the other two
nulls; `tests/edge_audit/test_edge_audit_threshold_table.py` fails if a threshold changes
without the table being regenerated.

## 6. Reuse of V1 (imported, never copied)

| V4 use | V1 function |
|---|---|
| per-trade SR used by the verdict, annualised SR | `statistics.annualized.calculate_annualized_statistics` (via `statistics.sampling.assess_sampling`) |
| skewness, kurtosis | `statistics.distribution.calculate_distribution_statistics` |
| plug-in SE, PSR | `statistics.sharpe_uncertainty.calculate_sharpe_uncertainty` |
| MinTRL; the verdict's trades needed with one trial or a declared σ | `statistics.track_record.calculate_track_record_length` (and its `MINIMUM_MOMENT_OBSERVATIONS`) |
| DSR (verdict and classical), expected maximum | `statistics.deflated_sharpe._calculate_scenario` |
| bootstrap index paths | `statistics.resampling.stationary_bootstrap_indices` |
| percentile interval and bootstrap SE (finite resamples) | `statistics.bootstrap._metric_result` |
| Ljung–Box, lag-1 autocorrelation | `statistics.serial_dependence.calculate_serial_dependence` |
| validation issue type | `domain.issues.ValidationIssue`, `InputValidationError` |

Computed in `edge_audit` because V1 has no equivalent: t = SR·√T (a teaching identity, tested
against V1's SR); the SE under H0 and the default spread σ_N = 1/√(T−1) (§3.2); the verdict's
trades needed for N > 1 with the default σ_N; the percentile interval of a profit factor whose
resamples include +∞ (V1 drops non-finite resamples); everything in §3.3–§3.7, which has no V1
counterpart. Tests fail if `skill.py` stops calling the V1 functions above (spies in
`test_edge_audit_statistics.py`).

`_calculate_scenario` and `_metric_result` are private in V1;
`report_v3/scripts/s06a_dsr_direction.py` already imports their sibling
`_expected_maximum_standard_normal` the same way. Making them public is a small V1 change left
to Krste.

## 7. Changelog

* 1.1 (2026-11-03): decay detectors calibrated by one simulated threshold table for a stated
  false-alarm budget α over a stated horizon N (new inputs `--decay-horizon`; `--decay-false-alarm`
  now 0.5–20 %); a calibrated rolling-expectancy alarm; Wald's SPRT replaced by the mixture
  SPRT; `--sprt-alpha`, `--sprt-beta` and `--calibration-draws` removed; every detector reports
  its α, N and calibration null; report schema `edge-audit-report/1.1`; a warning when serially
  dependent trades make the decay false alarms exceed α (§3.6, `CALIBRATION.md`).
* 1.0 (2026-11-02): first version. Verdict DSR uses the null SE after the first calibration
  run (§3.2). After the adversarial review: strict ISO 8601 timestamps and physical line
  numbers (§1), day boundaries safe across clock changes and trades priced by an earlier
  session excluded from timing (§3.3), trades needed floored at 30 (§3.2).
