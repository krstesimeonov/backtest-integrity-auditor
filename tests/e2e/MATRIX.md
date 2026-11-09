# E2E adapter matrix — engine × check

Re-run: `.venv/bin/pytest tests/e2e -q` (environment: `requirements-adapters.txt`). Strategy, reference and
tolerances: `strategy_spec.md`. Each cell names the test that decides it; "after `<sha>`" means the adapter needed
that fix on this branch first.

| Engine (pinned) | runs natively → export → adapter | bundle validates (schema 1.0) | fills: count, side, qty, price, UTC time | fees | round trips (incl. the short) | final equity | risk run completes (report 1.0 valid) | correct run: no defect named | look-ahead flagged (adverse) |
|---|---|---|---|---|---|---|---|---|---|
| vectorbt 1.1.0 | pass | pass | pass | pass | pass (trade level) | pass | pass | pass | pass |
| bt 1.2.0 | pass | pass | pass | pass (per-timestamp, unlinked by design) | pass (from fills) | pass | pass | pass (A) | pass |
| Backtrader 1.9.78.123 | pass, after `a309470` | pass | pass | pass | pass (from fills) | pass | pass | pass | pass |
| QuantConnect LEAN 2.5.17999 (source `278fcb3`) | pass, after `9b9b072` `9535748` `6b708c5` `3f264fc` | pass | pass | pass | pass (from fills) | pass | pass | pass | pass |
| NautilusTrader 1.231.0 | pass, after `49b4486` | pass | pass | pass | pass (trade level) | pass (final cash, B) | pass | pass (C) | xfail (D) |

Extra variant, not part of the specification:

| Engine (pinned) | runs natively → export → adapter | fills, fees, final equity | correct run: no defect named |
|---|---|---|---|
| Backtrader 1.9.78.123 with `broker.set_coc(True)` | pass, after `a309470` | pass | xfail (E) |

## Adversarial pass (fresh subagent, `test_adversarial_adapters.py`)

It tried to make each adapter emit a bundle the package accepts but that mis-states the strategy. It found 8 ways;
each reproducer was committed as a strict xfail (`e60b329`), and each fix flipped it to pass. All 12 now pass;
a refusal (`ValueError` / `EngineAdapterError`) counts as a fix.

| Engine | Accepted, but the bundle said | Fix |
|---|---|---|
| Backtrader 1.9.78.123 | rows 4–5 h off with a feed `tz`, `Cerebro(tz)` or a tz-aware index | stored bar time, labelled UTC or `source_timezone` (`eb946f1`) |
| NautilusTrader 1.231.0 | HEDGING: −100 (short) while the account was flat | refuse overlapping positions (`deb65d6`) |
| Backtrader 1.9.78.123 | `shortcash=False`: cash off by 19,318 | refuse that broker mode (`9d6fe74`) |
| Backtrader 1.9.78.123 | short interest booked again as a −75.10 commission | fill commission without folded interest (`e66733b`) |
| bt 1.2.0 | same-bar close+reopen: 4 of 6 fills dropped; sell 100 + buy 150 as one buy of 50 | refuse when bar fees ≠ `commission_fn` on net transactions (`697b365`) |
| LEAN 2.5.17999 | fee rebate −0.35 booked as a 0.35 charge | keep the sign (`0a6ad5e`) |
| Backtrader 1.9.78.123, bt 1.2.0 | futures value without the multiplier (91.13 for 4,556.50) | multiply (`322fcff`, `07a106a`) |
| LEAN 2.5.17999 | filled order last updated 20 min before its fill | latest of lastUpdate/lastFill/canceled time (`afa7b80`) |

Correctly mapped or refused already: vectorbt both directions with slippage and percentage fees; negative fees in
vectorbt, bt, Backtrader and Nautilus (refused); bt one-bar flip; Backtrader partial fills; Backtrader DST
fall-back hourly bars (refused); Nautilus NETTING close/reopen/partial close; no adapter substitutes an order, limit,
average or previous-close price for the executed price. Not fixed: a zero-fee bt run cannot reveal netted
executions; a Nautilus one-order flip (long 100, sell 200) is refused by the account-report duplicate check, which
is arguably a false refusal.

## Test that decides each column

`test_<engine>.py::` runs natively → export → adapter: the `correct`/`lookahead` fixtures (any error fails every
test) · schema: `test_bundle_validates_against_schema_1_0` (`harness.write_and_validate`: jsonschema on
`manifest.json`, then ZIP and directory read back equal) · fills: `test_fills_match_reference` · fees:
`test_fees_match_reference` · round trips: `test_round_trips_match_reference` (trade level where the adapter has one,
else `harness.assert_fills_imply_round_trips`) · final equity: `test_final_equity_matches_reference` · risk run and
no defect: `test_implementation_risk_names_no_defect` · look-ahead: `test_lookahead_defect_is_flagged`.

Levels compared in the risk run (reference = bundle built from `reference.py`, candidate = engine bundle):
vectorbt fill, trade, position, cash, cost, equity, return · bt and Backtrader fill, position, cash, cost, equity,
return · LEAN fill, position (per fill), cost, equity and return (at LEAN's own chart instants) · Nautilus fill,
trade, cash (margin balance), cost.

## Notes

- **A — bt's virtual first row.** bt prepends a row one calendar day before the data to hold the initial capital,
  and the adapter maps it as position/cash/equity evidence at 2024-01-01T21:00Z. The reference carries the same
  initial capital there (`reference_artifacts(prestart=…)`), so the row is compared, not skipped. Against an engine
  without such a row it would show up as one-sided evidence.
- **B — Nautilus has no equity level.** The D3 adapter maps cash (account report) but not equity or returns. The
  strategy ends flat, so final cash = final equity = 99,844.00. The account is MARGIN (a CASH account rejects the
  short sale), whose balance does not debit open-position notional, so the cash level is compared with a
  reference margin balance built from the reference trade list (`test_margin_balances_match_reference_realized_balance`).
- **C — exact agreement has no score.** Backtrader, LEAN and Nautilus match the reference exactly on every measured
  field. V1.5H builds observations only from records that differ, so it reports `implementation_risk_score: null`
  with uncertainty `not_assessed`, not 0. The harness accepts that only with no adverse findings, no evidence gaps,
  nothing withheld and zero observations.
- **D — xfail, nautilus_trader 1.231.0.** The Nautilus bundle has no fixed-grid level (no equity or return, and cash
  rows only at account events), so the one-bar look-ahead makes every fill, cost, trade and balance row one-sided.
  The report gives four `evidence_gap` findings and no `adverse` one. The shift is still visible, and
  `test_lookahead_defect_is_visible_as_one_sided_evidence` passes: 10 reference-only and 10 candidate-only fills,
  `IMPLEMENTATION_FAMILY_EVIDENCE_IMPAIRED`, and final cash 99,750.00 against 99,844.00.
- **E — xfail, backtrader 1.9.78.123 under cheat-on-close.** The fill is dated at bar t, but BackBroker books it in
  the next cycle, after the audit analyzer has recorded bar t's position, cash and value. At every fill bar, the
  bundle's snapshots are the pre-fill state: position off by 100, cash by price×100+fee, equity by the fee. The
  risk run flags it (adverse). Fixing it means re-dating coc snapshots or refusing coc runs.
- **Nautilus positions** are derived per positions-report row at its last update, so a strategy whose round trips
  all close yields only zero-quantity snapshots at the exits (`test_position_evidence_is_round_trip_closes_only`).
  Holdings are checked through fills and trades instead.
- **LEAN** ran locally without Docker: source `278fcb3` (master when NuGet 2.5.17999 was published), built with a
  user-local .NET 10 SDK. The test maps LEAN's own result files, checked in verbatim (`data/lean/`); regenerate them
  with `lean/run_lean.py`. A source build reports v2.5.0.0, so the `2.5.17999` passed to the exporter is a
  declaration based on that commit (docs/history/w3-j12/ASSUMPTIONS.md J9).
