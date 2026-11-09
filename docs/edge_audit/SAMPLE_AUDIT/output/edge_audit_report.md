# Edge Audit

Trades: `trades.csv` (sha256 `56ec93fe207c47f2…`, 420 closed trades, 2025-01-06T14:30:00+00:00 → 2026-02-25T19:00:00+00:00). Prices: `prices.csv`.
Declared trials: **12**. Confidence level: 95%. Seed: 20261103. Report schema `edge-audit-report/1.1`, package 1.6.0.

## Verdict

**no evidence of edge** — DSR 0.7113 < 0.95 at 12 declared trial(s).

| Question | Answer |
|---|---|
| Is there evidence of an edge? | No. DSR 0.711 at 12 declared trial(s) is below 0.95. Expectancy 5.07 [0.65, 9.45] USD per trade (95 % interval) over 420 trades. If the per-trade Sharpe ratio stayed at 0.109, about 931 trades would be needed. |
| Where does it come from? | holding: not distinguishable from random (p = 0.8416 for adding P&L); entry timing: adds P&L (significant) (p = 0.0005 for adding P&L); exit timing: not distinguishable from random (p = 0.3698 for adding P&L); sizing: sizing neither adds nor costs P&L detectably (permutation p = 0.0560); holding period: expectancy does not differ detectably across terciles (p = 0.5177); volatility regime: expectancy does not differ detectably across terciles (p = 0.0900). |
| Is it decaying? | Decay alarm: rolling_expectancy at trade #344, page_hinkley at trade #367. Each detector allows a 5.0% chance of a false alarm within 1,000 monitored trades if nothing changes, for i.i.d. normal trades (null `iid_normal`). Expectancy after the first 140 trades minus before: -7.17 [-17.03, 2.31] USD. |
| How sensitive is it to costs? | Break-even at 4.64 [0.60, 8.78] bps of notional added per round trip (fees already paid: 3.00 bps). |

## 1. Performance (net of logged fees)

Intervals: 95% percentile bootstrap over trades (2000 resamples, mean block length 1).

| Metric | Value [interval] |
|---|---|
| Expectancy per trade (USD) | 5.07 [0.65, 9.45] |
| Profit factor | 1.342 [1.037, 1.746] |
| Win rate | 0.543 [0.498, 0.590] |
| Total net P&L | 2'127.57 |
| Total fees | 1'374.44 |
| Average win / average loss | 36.61 / -32.39 |
| Mean net return per trade | 6.28 bps |
| Median holding period | 46.00 h |
| Most trades open at once | 8 |
| Lag-1 autocorrelation of trade P&L | 0.070 (Ljung-Box p = 0.0768) |

## 2. Luck or skill

| Quantity | Value |
|---|---|
| Sharpe ratio per trade (SR) | 0.1086 |
| t = SR·√T | 2.225 (one-sided p = 0.0133) |
| Trades per year (trade clock) | 369.5 |
| Annualised SR (trade clock) | 2.085 |
| Skewness / Pearson kurtosis | 0.140 / 4.187 |
| SE of SR: under H0 (1/√(T-1)) / plug-in (V1) | 0.0489 / 0.0487 |
| PSR vs SR* = 0 (V1, plug-in SE) | 0.9871 |
| Declared trials N | 12 |
| Cross-trial SD of SR (null default) | 0.0489 |
| Expected max SR of N skill-less trials | 0.0813 |
| **DSR (verdict; SE under H0)** | **0.7113** |
| DSR, classical plug-in SE (V1) | 0.7119 |
| MinTRL vs SR* = 0 (V1, plug-in SE; trades; before the 30-trade floor) | 230 |
| Trades needed for the verdict DSR ≥ 0.95 at this SR | 931 |

## 3. Where the P&L comes from: timing

Window mode `day` (days in UTC); 420 trades with price coverage; 2000 random-time draws per test. Gross P&L of these trades: 3'502.01 USD.

| Component | Total | Share of gross | Mean per trade [interval] | p (adds) | p (costs) | Finding |
|---|---|---|---|---|---|---|
| holding | -826.91 | -23.6% | -1.97 [-5.91, 2.00] | 0.8416 | 0.1589 | not distinguishable from random |
| entry timing | 5'148.76 | 147.0% | 12.26 [10.82, 13.80] | 0.0005 | 1.0000 | adds P&L (significant) |
| exit timing | 96.29 | 2.7% | 0.23 [-1.34, 1.71] | 0.3698 | 0.6307 | not distinguishable from random |
| execution | -916.13 | -26.2% | -2.18 [-2.27, -2.09] | n/a | n/a | costs P&L |

## 4. Holding period and volatility regime

*holding period* (source: trade_log; 420 of 420 trades have a value); permutation p = 0.5177 for 'expectancy differs across terciles'.

| Tercile | Trades | Range | Expectancy [interval] | Win rate |
|---|---|---|---|---|
| short | 140 | 18 – 26.5 | 1.85 [-4.06, 7.74] | 50.7% |
| medium | 140 | 26.5 – 50.5 | 8.37 [-0.67, 16.37] | 58.6% |
| long | 140 | 50.5 – 101.5 | 4.99 [-3.07, 13.64] | 53.6% |

*volatility regime* (source: price file: SD of log changes over the 50 bars before entry; 419 of 420 trades have a value); permutation p = 0.0900 for 'expectancy differs across terciles'.

| Tercile | Trades | Range | Expectancy [interval] | Win rate |
|---|---|---|---|---|
| low | 140 | 0.0007191 – 0.000927 | 10.20 [2.89, 17.26] | 57.1% |
| mid | 140 | 0.0009274 – 0.001022 | -1.83 [-9.72, 5.60] | 51.4% |
| high | 139 | 0.001023 – 0.001272 | 6.69 [-1.44, 15.02] | 54.0% |

## 5. Cost sensitivity

Unit: bps of entry notional per round trip, on top of logged fees. Mean notional 10'907.58 USD; fees already paid 3.00 bps; gross edge can carry 7.64 bps in total.

Break-even added cost: **4.64 [0.60, 8.78] bps**. No evidence of edge at the logged costs, so none to lose.

| Added cost (bps) | Expectancy [interval] | DSR | Verdict |
|---|---|---|---|
| 0.00 | 5.07 [0.65, 9.45] | 0.7113 | no evidence of edge |
| 1.00 | 3.97 [-0.45, 8.37] | 0.5310 | no evidence of edge |
| 2.00 | 2.88 [-1.55, 7.32] | 0.3441 | no evidence of edge |
| 4.64 | -0.00 [-4.42, 4.46] | 0.0480 | no evidence of edge |
| 5.00 | -0.39 [-4.80, 4.07] | 0.0333 | no evidence of edge |
| 10.00 | -5.84 [-10.31, -1.31] | 0.0000 | no evidence of edge |
| 20.00 | -16.75 [-21.34, -12.08] | 0.0000 | no evidence of edge |
| 50.00 | -49.47 [-54.49, -44.40] | 0.0000 | no evidence of edge |

## 6. Decay

Rolling expectancy, 50-trade window (min -18.53, max 23.11, last -4.81):

`▆▆▅▆▅▅▆▆▆▇▆▆▆▆▅▆▆▅▆▇▇▇████▇█▇▆▆▆▅▅▅▅▅▆▆▆▇▅▄▄▃▂▂▁▁▂▃▃▂▂▂▂▂▂▂▃`

Reference: first 140 trades, mean 9.84, SD 49.35, SR 0.1994. Shift to detect δ = 0.1994 SD (reference sharpe). Monitored: 280 trades.

False-alarm budget: α = 5.0% per detector within a horizon of 1,000 monitored trades. Thresholds from edge-audit-decay-thresholds/1: 40,000 simulated paths per cell, seed 20261102, calibrated under the null `iid_normal`: i.i.d. normal trades without a change; reference mean and SD re-estimated from the R reference trades in every simulated path. Serially dependent or fat-tailed trades raise the false-alarm rate above α (docs/edge_audit/CALIBRATION.md).

| Detector | Threshold | Calibrated α within N trades | False-alarm chance over the monitored trades | Alarm at trade # | Alarm exit time | Max statistic |
|---|---|---|---|---|---|---|
| rolling_expectancy | 3.914 | 5.0% within 1,000 (iid_normal) | 1.4% | 344 | 2025-12-08T16:00:00+00:00 | 4.064 |
| cusum | 65.773 | 5.0% within 1,000 (iid_normal) | < 0.5% | n/a | — | 43.419 |
| page_hinkley | 28.472 | 5.0% within 1,000 (iid_normal) | 0.8% | 367 | 2026-01-01T20:00:00+00:00 | 36.630 |
| mixture_sprt | 10.653 | 5.0% within 1,000 (iid_normal) | < 0.5% | n/a | — | 2.485 |

Rolling-expectancy alarm level: the 50-trade average P&L below -17.48 USD.

Monitored minus reference expectancy: -7.17 [-17.03, 2.31] USD.

## 7. Position sizing

| Quantity | Value [interval] |
|---|---|
| Actual expectancy | 5.07 [0.65, 9.45] |
| Fixed-size expectancy (mean notional 10'907.58) | 6.85 [2.55, 11.22] |
| Sizing contribution per trade | -1.79 [-3.45, -0.15] |
| Sizing contribution, total | -751.30 |
| Correlation of notional and net return | -0.095 |
| Permutation p (two-sided) | 0.0560 |
| Fixed-size DSR / verdict | 0.9203 / no evidence of edge |

Finding: sizing neither adds nor costs P&L detectably. The finding uses the permutation test, exact if sizes are unrelated to outcomes; the bootstrap interval describes the estimate's uncertainty without that assumption, so the two can disagree near the 5 % line.

## Warnings

- Up to 8 trades were open at once; overlapping trades share market moves, so they are less independent than their count suggests.

## Method notes

Methods, assumptions and failure cases: `docs/edge_audit/DESIGN.md`. The verdict uses no random numbers; every interval and p-value is reproducible from the seed above.
