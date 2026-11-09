# Changelog

All notable changes to Backtest Integrity Auditor are recorded here.

## 1.6.0 — 2026-11-10

Minor release: what `main` ships after the wave-5 integration and three more merges
(W7-J07; MERGE_LOG.md sections 5 to 7). Against the `v1.5.2` tag (b2c5486) the public
API gains 396 objects, all in the new `backtest_auditor.edge_audit`, and loses or
changes none (griffe, static comparison). Semantic versioning makes that a minor
release, so this is 1.6.0, not a second 1.5.2. V1 and V1.5 schema versions are
unchanged (report 2.5, run manifest 1.1, canonical bundle 1.0, implementation-risk
report 1.0); the edge audit's report schema is 1.1.

- `wave5/edge-audit-calib` (W5-J14): the decay detectors read one simulated threshold
  table, and a mixture SPRT replaces the Wald SPRT (`docs/edge_audit/CALIBRATION.md`).
- `wave5/known-answer` (W5-J16): an opt-in known-answer battery, `tests/kat/` (runs
  with `KAT=1`), and `docs/kat/`.
- `wave5/learning-docs` (W5-J12): `docs/learning/`, a course on the V1 internals,
  kept out of the site.
- The five example notebooks were re-executed against 1.6.0.

The 1.5.2 entry below covers everything between the first 1.5.2 cut and this release.

## 1.5.2 — 2026-11-02

Release candidate `wave5/rc-1.5.2`: one release for what waves 1–4 produced
for this package. The first 1.5.2 cut (local tag `v1.5.2` at b2c5486,
2026-10-26, not pushed per W2-J6) is the `wave2/1.5.2-report-fix` entry below; this
candidate adds the apps on report schema 2.5, the five engine adapters end to
end, two commits held over from `test/verdict-mutation` and two wave-4 audit
patches. No public name or signature changed in what this candidate merged:
990 public module-level names before and after, none added, removed or
re-signed (`evidence/adversarial/out/api_surface_diff.txt`); the adapter fixes
add private helpers and refuse runs a bundle could not state truthfully. So the
version stays 1.5.2 rather than 1.6.0. (The first 1.5.2 cut itself added 12
module-level helpers over 1.5.1, e.g. `exact_add`, and changed no existing
name; only the presentation dataclasses' `package_version` default follows
the version. W2-J6 released that as a patch.) No schema version changes: report 2.5, run
manifest 1.1, canonical bundle 1.0, implementation-risk report 1.0.
MERGE_LOG.md records each merge and conflict; MERGE_DECISIONS.md what was
deferred and why.

### `wave5/integration` (W5-J13): release kit, V4 edge audit

The integration branch merges wave-5 branches on top of the release
candidate; MERGE_LOG.md records each merge, conflict and gate run.

- `wave5/release-kit` (W5-J6, merge 74aa2c3): MkDocs site (`mkdocs.yml`,
  `docs/`), five executed engine notebooks (`examples/notebooks/`), the README
  rewrite, `CONTRIBUTING.md`, `SECURITY.md`, `CITATION.cff`, `LICENSE_MEMO.md`,
  the CI workflow, and one install extra per engine plus `docs`. Its `src/`
  changes are docstrings and typing only (`scripts/check_typing_only.py`). The
  how-to notes on 1.5.2 adapter limits that wave 3 fixed are deleted (b3b76a6).
- `wave5/edge-audit` (W5-J9, merge 541943f): new subpackage
  `backtest_auditor.edge_audit` (V4 Edge Audit: realised trade log to evidence
  of edge, timing and sizing sources, decay, cost sensitivity), with
  `tests/edge_audit/` and `docs/edge_audit/`. No console script is added.
- Public API: no existing public object changed or was removed (griffe:
  0 breaking changes, 0 removed objects; `logs/api/api_diff_rc_to_integration.txt`).
  326 public objects were added, all in `backtest_auditor.edge_audit`. The
  version stays 1.5.2, because the integration rule bumps it only when an
  existing public API changes. Semantic versioning would call the addition a
  minor release (1.6.0); that choice is open.

### Packaging

- The version has one source, `backtest_auditor.PACKAGE_VERSION`:
  `pyproject.toml` declares it dynamic and setuptools reads that constant;
  `scripts/verify_source_archive.py` reads it from a source archive the same
  way and fails closed on anything else (af4c65d).

### `wave2/1.5.2-report-fix` (W2-J6): closes N18, N21, N13, N14, N15, F06, F04, F03; keeps F01, F02, F05, F07

Fix release for the open findings 1.5.1 carried as strict xfails: 8 of the 12
findings are defects and are fixed by `fix: <id> ...` commits (one each; N13 and
F06 took three); 4 are
documented conventions or method properties and stay strict xfails with their
verdicts in FINDINGS_DISPOSITION.md. No schema version changes: report 2.5,
run manifest 1.1, canonical bundle 1.0, implementation-risk report 1.0. Reports
can carry two new finding codes (PERIODS_PER_YEAR_SAMPLING_MISMATCH,
RETURN_MAGNITUDE_SUGGESTS_PERCENT_UNITS; codes are free strings in the 2.5
schema), and VARIANCE_RATIO_DEPENDENCE_DETECTED, which 1.5.1 practically never
emitted, now fires when a horizon is rejected.

#### Fixed

- N18: the Lo-MacKinlay variance-ratio z-statistic divided by sqrt(theta)
  instead of sqrt(theta / n), so it was too small by sqrt(n) and practically
  never rejected (an AR(1) with z* = 8.50 printed z = 0.27, p = 0.79); its
  two-sided p-value now keeps precision in the far tail (e1fc1cd).
- N21: the runs-test continuity correction turned R == E into a deviation of
  1/2 (z 0.38, p 0.70 instead of 0, 1) and could flip the sign of a deviation
  below 1/2; it now shrinks |R - E| toward zero without crossing it (e5667a9).
- N13: canonical decimals were rounded to 28 significant digits by
  Decimal.normalize() in the default context; every supplied digit is now
  kept, whatever the caller's context (8fade30). The sums, sign changes and
  absolute values applied to supplied quantities and fees (the bundle's
  fill-chain check, adapter positions and costs, the LEAN exporter) are exact,
  so a 30-digit filled order keeps every digit and still balances against its
  fills; a sum that would need more than 100 significant digits is rejected
  rather than rounded (5d5e5bd, 1db9494).
- N14: a CSV header mismatch (engine adapters and the bundle's own CSV
  readers) now names the missing and unexpected columns, with the first
  missing one as the error field (fd379f1).
- N15: an invalid adapter-metadata file now names the missing or unexpected
  key, and a non-object payload says so (1eaccd3).
- F06: timestamps with more than one UTC offset are a blocking issue inside
  the validation contract (INVALID_TIMESTAMP and the family, split, regime
  and session readers' own codes) instead of a pandas ValueError (b926a0f,
  1df5407); unparseable rows beside them are still reported (773d3e4).
- F04: RETURN_MAGNITUDE_SUGGESTS_PERCENT_UNITS warns when the mean absolute
  return exceeds 0.05 per period (daily or faster; scaled by the square root
  of the interval for slower sampling), and both "below -1" rejections say
  that percent values must be divided by 100 (dff4216).
- F03: PERIODS_PER_YEAR_SAMPLING_MISMATCH warns when the declared periods per
  year differ from the rate the timestamps imply by more than a factor of
  1.2 (spans of 28 days or more); the declaration is still used as given
  (b48d554).

#### Deferred (strict xfail kept; FINDINGS_DISPOSITION.md has the evidence)

- F01 (convention): the DSR uses the n - 1 cross-trial variance, the
  documented and more conservative estimator; the test expects the plug-in.
- F02 (method property): percentile moving-block intervals cover 92.6 % on the
  test's 500 seeds and 94.3 % pooled over 2,000 (nominal 95 %, n = 500); the
  arithmetic matches a reference exactly.
- F05 (design): one missing exchange holiday makes a business-day series
  ineligible for annualization; a sessions CSV is the documented route.
- F07 (convention): under negative autocorrelation the HAC effective count
  exceeds n, as Lo (2002) eq. 20 allows and the methods document states.

#### Report output

- No golden report changed: fresh output differs from the committed goldens
  by float noise only (at most 120 ULP, `notes/evidence/golden_diff_152.txt`),
  with no non-float difference. `scripts/release_contracts.py --check` still
  reports that noise on this Mac; the 8-ULP tolerance is unchanged.
- Variance-ratio z, standard errors and p-values change by a factor of
  sqrt(n) wherever `--serial-max-lag` is at least 2, and
  VARIANCE_RATIO_DEPENDENCE_DETECTED can now fire. Runs-test z and p change
  only when |R - E| <= 1/2.
- Correction to 1.5.1's note on the direction of the DSR bound. Measured on
  the sample report's own trial returns (moving-block bootstrap, blocks of 10
  sessions, `report_v3/scripts/s06a_dsr_direction.py`), the threshold at the
  raw trial count against the simulated expected maximum is at 378 trials
  3.0 % above (0.2 % to 3.0 % across block lengths: close to right or slightly
  conservative), at 1,512 trials 8.1 % above (conservative: DSRs understated)
  and at 19 trials 11.5 % below (lenient: DSRs overstated, so an upper bound
  there). 1.5.1's "23 % and 13 % too high … about right at
  19" holds only for null families' own dispersion (CONTRADICTIONS.md B,
  W2-J6 addendum); "not an upper bound" holds for the factorial grids only.

#### Tests

- `tests/test_findings_disposition.py` holds the strict xfails equal to
  FINDINGS_DISPOSITION.md's kept rows, by decorator and by the markers pytest
  applies at collection; `tests/unit/test_v152_report_consequences.py` checks
  each fix through the CLI report.
- `tests/test_contradiction_stat_bug.py` now asserts the N18 bug on 1.5.0
  and 1.5.1 (tag v1.5.1) and the corrected statistic on this branch.

### `wave2/apps-schema-2.5` (W2-J7): closes the apps' schema-2.4 pins (W1-J2 decision 2)

- `apps/api` expects report schema 2.5 and records the engine's versions
  (c359080); `apps/web` is typed against report schema 2.5 and run manifest
  1.1 (0464a28). Before, the API job failed two tests on any 1.5.x engine
  ("2 failed, 52 passed").
- The API requires the engine it runs on, `backtest-integrity-auditor>=1.5.1`
  (8e95d7c); `>=1.0.0` installed an engine the app then failed to import.
- `SCHEMA_MIGRATION.md` accounts for every 2.4 → 2.5 difference the apps meet
  (24 schema differences, nothing removed, renamed or retyped) and seven
  contract changes no schema shows (C1–C7) (9f06279, ebf1183); the apps' docs
  stop describing the 1.0.0 engine (5d5cbd4).

### `wave3/adapter-e2e` (W3-J12): 15 adapter fixes (by commit; no finding ids were assigned); adds kept findings E01, E02

End-to-end tests for the five V1.5 engine adapters, and the adapter fixes
they forced. No schema or version change (report 2.5, canonical bundle 1.0,
implementation-risk report 1.0).

#### Fixed (adapters)

- NautilusTrader: `export_nautilustrader_engine` works on a real 1.231.0
  `BacktestEngine`, whose report methods live on `engine.trader`; it failed on
  every real engine (`49b4486`).
- Backtrader: an order's submission instant is its creation bar. The audit
  analyzer stamped it one bar late, so cheat-on-close exports were rejected
  ("fills must not occur before their related orders"). The D2 Backtrader
  example is regenerated (`a309470`).
- QuantConnect LEAN: the exporter rejected every real LEAN 2.5 result file. It
  now reads LEAN's own serialization: orders carrying both `time` and
  `createdTime` (`9b9b072`), object-valued `properties.timeInForce`
  (`9535748`), text order-event ids (`6b708c5`), and the candlestick Strategy
  Equity series (`3f264fc`). The earlier LEAN fixtures used a hand-written
  shape that LEAN does not produce.
- An adversarial pass found eight ways an adapter accepted a run but
  mis-stated it; each is fixed or now refused, with a reproducer in
  `tests/e2e/test_adversarial_adapters.py`:
  - Backtrader reads the stored bar time, so a feed `tz`, `Cerebro(tz)` or a
    tz-aware index no longer shifts rows by 4–5 h (`eb946f1`); runs with
    `shortcash=False` are refused (`9d6fe74`); short interest folded into the
    closing commission by `int2pnl` is no longer booked again as a fill cost
    (`e66733b`); position value includes the contract multiplier (`322fcff`).
  - NautilusTrader refuses overlapping positions of one instrument (HEDGING or
    several strategies), whose report rows are not the net quantity
    (`deb65d6`).
  - bt refuses a run whose per-bar fees differ from its commission function
    on the net transactions, i.e. whose same-bar executions were netted away
    (`697b365`); position value includes the security multiplier (`07a106a`).
  - QuantConnect LEAN keeps a fee rebate's sign (`0a6ad5e`) and dates a filled
    order's last update at its fill (`afa7b80`).

#### Added

- `tests/e2e/`: one toy strategy (`strategy_spec.md`), an independent pandas
  reference, and one test file per engine that runs it natively (LEAN: replays its
  checked-in result files), exports and maps it, validates the bundle against schema 1.0, checks fills, fees, round
  trips and final equity, and runs the implementation-risk audit for the
  correct strategy and for an injected one-bar look-ahead. `tests/e2e/MATRIX.md`
  records engine × check.
- LEAN's own result files for that strategy (`tests/e2e/data/lean/`), from a
  local LEAN build without Docker (`tests/e2e/lean/run_lean.py`).
- `requirements-adapters.txt` pins the engine SDKs, plus `plotly==6.9.0`:
  vectorbt 1.1.0 does not import under plotly 7.

#### Known, still open

- NautilusTrader bundles have no equity or return level, so a one-bar
  look-ahead shows only as one-sided evidence (evidence gaps), never as
  adverse divergence (strict xfail).
- Backtrader with `set_coc(True)`: position, cash and equity snapshots at fill
  bars are the pre-fill state (strict xfail).
- When every measured field matches exactly, the implementation-risk score is
  null with uncertainty `not_assessed`, not 0.

- Registered when this branch was merged: the two strict xfails above are
  E01 (NautilusTrader look-ahead) and E02 (Backtrader cheat-on-close), kept
  as open limits awaiting Krste's choice in FINDINGS_DISPOSITION.md, which
  `tests/test_findings_disposition.py` requires of every strict xfail (523c493).
- The LEAN exporter keeps a 30-digit fee exact and, since `0a6ad5e`, signed:
  the N13 test now expects the signed value (523c493).

### `test/verdict-mutation`: two of its three repo-level commits

- Web: the verdict card says why a verdict is missing, and reads inputs back
  to the user (82d56f7, picked as 8040dfc).
- `docs/review/`: the verdict mutation pass (fedfb66, picked as 305ff25).
- Not picked: c4f9571 (golden check on every CI leg, pandas-2 job), held until
  `scripts/release_contracts.py --check` passes on CI's image (W4-J16, T8).

### W4-J16 (wave 4, audit resolution): closes audit items T2, T8

- T2: 1.5.1's DSR-direction note corrected with the measured readings
  (7528ce7, `tests/test_changelog_dsr_direction.py`; the bullet sits under
  "Report output" above).
- T8: the archived merge plan (`docs/history/w2-j6/MERGE_PLAN.md`) gates
  c4f9571 on the golden check and runs the new `scripts/check_local_paths.py`
  before any push (c0902ef, `tests/test_merge_plan_safety.py`).

### `wave1/reconcile-1.5.1` (W1-J2)

- Released as 1.5.1, below (its own tag `v1.5.1`, 21600b3).

## 1.5.1 — 2026-10-26

Reconciliation release. 1.5.0 was built from the archived 1.0.0, so it lacked
the review fixes made on the repository's 1.0.0 line afterwards. This release
is the 1.5.0 code with those fixes ported, one commit per original fix
(RECONCILIATION.md has the full account). No schema version changes: report
2.5, run manifest 1.1, canonical bundle 1.0, implementation-risk report 1.0.
`backtest_auditor.__version__` now exists and equals `PACKAGE_VERSION`.

### Ported fixes (original commit → port commit)

- `6d7a1f0` (#14) The golden JSON check accepts float differences up to 8 ULP
  → `afe36d4`.
- `19a2eae` Zero sample variation is detected from the data (`np.ptp == 0`),
  not by comparing a computed standard deviation with 0.0; 300 returns of
  0.001 no longer get a Sharpe of 7e16. Also applied to 1.4.0's risk-free and
  regime evidence, where a cash regime against a constant risk-free file
  printed a regime Sharpe of -4.3e15 → `9b80928`.
- `0c65eaa` The published report schemas take nullability from declarations,
  not from two examples. The 2.5 schemas are regenerated, so moving-block
  bootstrap reports, a benchmark without a calendar, CSCV-only families and
  families without methods validate again → `8c4b202`.
- `48731d1` Failures stay inside the machine-readable contract: an overflowing
  wealth path is reported as null, CSCV partitions are capped at 1024, a DST
  fold or gap is a typed blocking issue, and a render failure exits 4 with a
  JSON envelope. 1.4.0's Ulcer index and Calmar ratio are guarded the same
  way. (The manifest `date` sub-fix was already in 1.1.0.) → `ac8d6c2`.
- `0718043` Input reaches the report unchanged: timestamps must be ISO 8601,
  trial ids are read as text (`007` stays `007`), and unparseable timestamps
  are no longer also reported as duplicates. Also applied to 1.4.0's regime
  CSV reader → `8023d62`.
- `eee64e0` The evidence profile follows the facts: undeclared return
  construction is `insufficient_evidence` (it was `fragile`), a null PSR is
  reported unavailable, an ineligible serial diagnostic is `ineligible`. A
  gross/net timestamp mismatch stays adverse → `49c04fa`.
- `12aa60c` Parameter neighbourhoods no longer depend on representation
  error, and a calendar-verified series needs at least 3 observations
  → `6ab6eac`.
- `b11365c` One definition of the annual-to-period rate conversion
  → `480d586`.
- `87d9f09` Every published array has typed items; the 2.5 schemas are
  regenerated → `3b6a02b`.
- `3a9795e` A flat trial or bootstrap replicate is treated as flat in the
  family audit: no "eligible" DSR of 0.0 or PBO of 0.0 from a cash-like trial,
  no bootstrap upper bound near 4e15. Also applied to 1.4.0's Hansen SPA, where
  one flat trial turned p = 0.50 into a rejection at p = 0.002 → `810a5d1`.
- `840f499` The HAC influence variance is judged numerically → `a85c9c9`.
- `3ff09e1` pandas 2's pytz DST exceptions are caught → `e55cd9f`.
- `de3507f` One drawdown implementation (`anchored_drawdown_path`) for the
  engine and the API's drawdown chart → `7bbc1ef`.
- `19a33b5`, `d849100`, `72d3a61` (tests) Mutation-killing tests for the
  verdict modules, canonical report bytes and manifest Markdown, residue
  guards → `a960b7f`, `78a3180`, `471cbfe`.

The two `c6b0efb` items the archive also lacked are already covered in 1.5.0:
mypy is kept clear of incompatible NumPy stubs by the `numpy<2.5` and `mypy<2`
pins, and the unknown-schema-name test exists.

### Report output

- No golden report changed: fresh output differs from the committed goldens
  by float noise only (at most 120 ULP), so no fixture was regenerated.
- Output changes only for degenerate or extreme inputs: constant series,
  trials or replicates give null statistics with their typed status instead
  of values near 1e15; an overflowing wealth path gives null fields; a run
  that declares no return construction opens with `insufficient_evidence`.
- Still open: 1.4.0's gross/net, risk-free and regime sections overflow to
  `inf` when the wealth path does. The JSON report then ends with exit 4 and
  the `report_serialization_failed` envelope (1.5.0 crashed with a
  traceback), and the Markdown report prints `inf`/`nan` in those tables.
- The 2.5 report schema files are regenerated under the same version: more
  nullable objects, no field frozen to null, every array typed.

### Contradictions settled by test

- Where the statistical-test bug is: the Lo-MacKinlay variance-ratio
  z-statistic, `statistics/serial_dependence.py:257` (1.4.0 code main never
  had), is too small by sqrt(n), so the test practically never rejects.
  Ljung-Box and the HAC adjustment agree with independent references. Not
  fixed in this release (night 7's N18 stays open).
  `tests/test_contradiction_stat_bug.py`.
- Direction of the DSR bound: by Monte Carlo, the classical DSR at the raw
  trial count is about right for equicorrelated trials and strict for
  clustered trials; it is not an upper bound. On the sample report's own
  trial returns the threshold at the raw count is 23 % too high at 378 trials
  and 13 % at 1,512 (strict), and about right at 19. For skewed returns it
  sits 3-4 % low. `tests/test_dsr_direction.py`. (Wrong at 19 trials, where
  the measured DSR is lenient; corrected in 1.5.2.)

### Tests

- `tests/adversarial/`: night 3's adversarial suite and night 7's four
  additional files. Open findings are strict xfails with their ids (F01-F07,
  N13-N15, N18, N21). `requirements-dev.txt` pins statsmodels and arch for it.

## 1.5.0 — 2026-08-21

### V1.5J golden evidence and release hardening

- Freezes the V1.5 report and manifest schemas at `1.0` and adds exact,
  divergent, and incomplete cross-platform JSON/Markdown golden cases with a
  complete SHA-256 index.
- Adds independently authored reference expectations, deterministic generated
  score/materiality invariants, and complete-pipeline time and memory budgets.
- Adds a clean installed-wheel verifier for all 13 V1/V1.5 schema resources,
  three golden cases, base dependency isolation, and byte-identical CLI runs.
- Bounds candidate fanout, policy JSON files/uploads, and Streamlit bundle
  uploads; policy files must be regular UTF-8 non-symlink inputs.
- Refuses implementation-risk report overwrite by default, requires explicit
  `--force`, prevents input/output aliasing, and atomically preserves a prior
  report when commit fails.
- Adds fail-closed source-archive verification, CI/release gates, ADR-012, and
  final operator/release documentation.

### Boundaries and compatibility

- Adds no audit semantics, schema fields, global verdict, persistence, engine
  execution, broker action, live behavior, causal proof, or performance claim.
- Technical release readiness does not choose a license, publish a package,
  create a tag, or claim repository/package ownership.

## 1.5.0a11 — 2026-08-21

### V1.5I reports and operator integration

- Adds a separate implementation-risk report schema `1.0` and run-manifest
  schema `1.0`; frozen V1 report schema `2.5` and manifest schema `1.1` do not
  change.
- Runs the complete file-first V1.5 normalization, exact comparison,
  divergence, materiality, uncertainty, scoring, and attribution pipeline from
  canonical directory or ZIP bundles.
- Adds deterministic JSON and Markdown reports with per-level evidence,
  normalization changes, family materiality, explicit uncertainty, policy
  hashes, and independent findings without a global verdict.
- Adds strict JSON policy decoders, the `implementation-risk` CLI workflow, a
  matching Streamlit upload/download workflow, bundled schemas, and a complete
  deterministic example.
- Binds source and canonical bundle identities, all four policy hashes, exact
  findings, method versions, explicit audit identity, and environment metadata
  in the optional implementation-risk manifest.

### Boundaries and compatibility

- A reference remains a baseline rather than ground truth; co-occurrence
  remains an investigation hypothesis rather than causal proof.
- Adds no persistence, backtest execution, broker connection, order action,
  live monitoring, V1 schema mutation, or V1.5J release-hardening work.

## 1.5.0a10 — 2026-08-21

### V1.5H evidence-bounded materiality, attribution, and scoring

- Adds explicit per-field materiality thresholds, extreme multiples, and four
  canonical family weights with deterministic policy hashing.
- Produces bounded 0–100 implementation-risk scores from threshold-normalized
  family evidence without summing heterogeneous raw values.
- Withholds scores under incomplete evidence by default and exposes explicit
  assessment uncertainty.
- Restricts attribution to declared, evidence-complete material co-occurrence
  hypotheses; no causal proof is claimed.
- Adds typed failures, adversarial tests, deterministic examples, ADR-010, and
  operator documentation.

### Boundaries and compatibility

- Adds no reports, findings renderer, CLI, Streamlit, persistence, execution,
  broker, or live behavior and retains all frozen earlier schemas.

## 1.5.0a9 — 2026-08-21

### V1.5G implementation-divergence measurement

- Projects exact V1.5F evidence into transaction-cost, sizing, accounting, and
  return families through explicit canonical field rules.
- Preserves exact candidate-minus-reference Decimal deltas and impaired
  unavailable, one-sided, ambiguous, and non-numeric evidence.
- Links results to normalization, comparison, and measurement policy hashes;
  heterogeneous currencies, instruments, periods, and units are never summed.
- Adds stable typed errors, deterministic examples, adversarial tests, ADR-009,
  and operator documentation.

### Boundaries and compatibility

- Adds no attribution, materiality, severity, scoring, verdict, findings,
  report, CLI, Streamlit, persistence, execution, broker, or live behavior.
- Retains all frozen V1 and earlier V1.5 schema versions.

## 1.5.0a8 — 2026-08-21

### V1.5F deterministic alignment and exact comparison

- Adds immutable, canonically serialized per-level semantic/source-ID policies
  and hash-linked comparison results over V1.5E normalized evidence.
- Reports matched-equal, matched-different, reference-only, candidate-only, and
  ambiguous records without ordinal guessing; preserves all unavailable and
  available-empty states.
- Produces exact field evidence with Decimal and microsecond deltas while
  retaining engine-local IDs and lineage in source records.
- Adds adversarial tests, a deterministic executable example, ADR-008, and
  operator documentation.

### Boundaries and compatibility

- Adds no tolerance, materiality, verdict, scoring, attribution, report, UI,
  CLI, persistence, backtest execution, broker, or live-trading behavior.
- Retains V1 report schema `2.5`, audit-run-manifest schema `1.1`, database
  schema `1`, and canonical artifact/bundle/export/normalization schemas `1.0`.

## 1.5.0a7 — 2026-08-21

### V1.5E explicit cross-engine normalization

- Adds immutable reconciliation normalization plans with exact per-run
  strategy, instrument/symbol, currency, timestamp, and frequency assertions.
- Requires exhaustive one-to-one source mappings and globally consistent
  canonical instrument, strategy, and frequency identities; missing, unused,
  ambiguous, and contradictory evidence fails closed with stable typed errors.
- Supports explicit fixed microsecond clock offsets by available comparison
  level and exact fixed-duration or calendar/timezone frequency semantics.
- Preserves source-run provenance, all numerical values, and unavailable versus
  available-empty evidence; currency rules never perform FX conversion and
  frequency rules never resample observations.
- Rebuilds every normalized result through the V1.5B cross-record contracts and
  retains deterministic plan SHA-256, normalized bundle SHA-256, and canonically
  ordered change/rationale evidence.
- Adds an executable deterministic example, ADR-007, complete operator
  documentation, adversarial rule/service tests, focused strict typing, and
  release-gate integration.

### Boundaries and compatibility

- Adds no alignment, tolerance, comparison, divergence measurement,
  attribution, implementation-risk report, CLI, Streamlit, persistence,
  broker, execution, or live-reconciliation behavior.
- Retains V1 report schema `2.5`, audit-run-manifest schema `1.1`, database
  schema `1`, and canonical artifact/bundle/export schemas `1.0`.

## 1.5.0a6 — 2026-08-21

### V1.5D3 LEAN, NautilusTrader, and adapter hardening

- Adds a deterministic QuantConnect LEAN `2.5.17999` exporter for completed
  local result and order-event JSON files plus an SDK-neutral mapper for orders,
  fills, fill-derived positions, fees, equity, and equity-derived returns.
- Adds exact NautilusTrader `1.231.0` post-run report exporters and an
  SDK-neutral mapper for orders, individual fills, engine-native position
  grouping, quantity snapshots, account balances, and commissions.
- Completes the five-engine registry in frozen roadmap order and adds a
  fail-closed complete-roadmap conformance check requiring one exact tested
  version and project-namespaced adapter/format IDs per engine.
- Preserves unavailable versus available-empty evidence, deterministic
  directory/ZIP bytes, source and canonical identities, and explicit warnings
  for every semantic derivation or source limitation.
- Adds committed D3 examples, real NautilusTrader `ReportProvider` conformance,
  malformed/version/integrity tests, documentation, release gates, and clean
  base-wheel checks without engine SDKs.

## 1.5.0a5 — 2026-08-16

### V1.5D2 concrete vectorbt, bt, and Backtrader adapters

- Adds exact-version engine-side exporters for vectorbt `1.1.0`, bt `1.2.0`,
  and Backtrader `1.9.78.123`, while keeping the base auditor free of all three
  SDK dependencies.
- Maps verified engine files through SDK-neutral anti-corruption adapters into
  canonical orders, fills, trades where supported, position snapshots, cash,
  costs, equity, and returns.
- Preserves asymmetric evidence: vectorbt filled orders and bt transactions
  produce explicitly derived orders; Backtrader retains native order lifecycle
  notifications and execution bits; unsupported signal, market-data, strategy,
  and trade histories remain unavailable.
- Adds strict canonical engine CSV contracts, shared adapter metadata schema
  `1.0`, exact UTC/decimal rules, fail-closed instrument/index/version checks,
  and retained warnings for lossy but auditable mappings.
- Adds a lazy Backtrader audit analyzer with explicit source timezone, an
  explicit three-mapper D2 composition root, live conformance tests against all
  three engines, and deterministic generated examples.
- Adds the `engine-exporters` optional dependency extra, ADR-005, D2 operator
  documentation, SDK-free installed-wheel mapping checks, and live engine CI
  across Python 3.11–3.13.

### Boundaries and compatibility

- Exporters accept already executed objects and never initiate a backtest; the
  auditor itself continues to read files and never imports an engine SDK.
- Retains V1 report schema `2.5`, audit-run-manifest schema `1.1`, database
  schema `1`, and canonical artifact/bundle/export schemas `1.0`.
- Adds no cross-run alignment, comparison, attribution, report, CLI,
  Streamlit, persistence, broker integration, or live trading behavior.

## 1.5.0a4 — 2026-08-15

### V1.5D1 shared engine-adapter foundation

- Freezes the five-engine roadmap order: vectorbt, bt, Backtrader,
  QuantConnect LEAN, and NautilusTrader.
- Adds full eleven-level adapter capability descriptors with explicit
  always/conditional/unsupported availability and engine-export/derived/none
  evidence origin.
- Adds a strict common engine-export envelope with automatic source SHA-256,
  payload roles, sizes, hashes, declared levels, and explicit engine/export
  versions.
- Adds safe directory and deterministic ZIP transport, immutable verified
  payload bytes, atomic writes, traversal/symlink/archive defenses, and resource
  limits.
- Adds runtime-checkable engine reader/mapper/identity ports, an explicit
  deterministic registry, and fail-closed orchestration that revalidates run
  identity, versions, capabilities, declared levels, warning references, and
  canonical output identity.
- Separates fatal `EngineAdapterError` failures from canonically retained
  `AdapterWarning` evidence and supports namespaced engine-specific detail
  codes without leaking arbitrary mapper exceptions.
- Adds envelope schema `1.0`, a deterministic illustrative export, ADR-004,
  architecture documentation, and adversarial contract tests.

### Boundaries and compatibility

- Adds no concrete engine mapping or SDK dependency; vectorbt/bt/Backtrader
  remain D2 and LEAN/NautilusTrader remain D3.
- Retains V1 report schema `2.5`, audit-run-manifest schema `1.1`, database
  schema `1`, canonical artifact/bundle/specification schemas `1.0`, and every
  existing statistical behavior.

## 1.5.0a3 — 2026-08-15

### V1.5C hybrid file-bundle adapter

- Adds engine-neutral canonical artifact reader and writer ports plus a concrete
  `CanonicalArtifactFileBundleAdapter` for suffix-free directories and
  deterministic ZIP archives.
- Uses canonical JSON for the manifest and nested run specification, and exact
  UTF-8 CSV tables for flat artifact histories. Trade-to-fill membership uses
  a separate normalized relation table rather than JSON hidden inside CSV.
- Preserves unavailable versus available-empty evidence: unavailable levels
  have no file, while available empty tables contain their exact header and no
  data rows. Cash balances and movements remain independently available.
- Adds SHA-256, byte-size, record-count, media-type, level-availability, bundle
  identity, and schema-version declarations with strict round-trip validation.
- Adds typed fail-closed errors for malformed JSON/CSV, unsafe ZIPs, unsupported
  versions, resource limits, missing or undeclared files, integrity mismatches,
  noncanonical encodings, and domain contradictions.
- Bundles Draft 2020-12 schemas for manifest `1.0` and run specification `1.0`,
  a separate schema catalog, and a generated inspectable example bundle.

### Boundaries and compatibility

- Adds no concrete engine mapping, alignment, tolerance, comparison,
  attribution, report, CLI, Streamlit, or persistence behavior.
- Advances the package to PEP 440 prerelease `1.5.0a3` while retaining V1
  report schema `2.5`, audit-run-manifest schema `1.1`, database schema `1`,
  canonical artifact schema `1.0`, and all existing statistical behavior.

## 1.5.0a2 — 2026-08-15

### V1.5B canonical contracts

- Separates intended strategy logic from run-specific simulation assumptions,
  including typed scalar parameters, instrument identities, named model
  specifications, explicit calendars, timing, accounting, cost, shorting, and
  fractional-quantity declarations.
- Adds immutable, engine-neutral market-data, signal, order, fill, trade,
  position, cash, cost, equity, and return records. Financial values use
  `Decimal`, timestamps require timezone information and normalize to UTC, and
  runtime enum strings normalize to stable vocabulary.
- Adds canonical run-artifact bundles with schema version `1.0`, deterministic
  collection ordering and identity rules, and an evidence profile derived from
  actual artifact availability.
- Preserves `None` as unavailable and an empty tuple as available-but-empty,
  preventing omitted evidence from being interpreted as zero activity.
- Validates strategy-universe membership, instrument currencies, signal/order/
  fill lineage and timing, order-status/fill-quantity consistency, trade/fill
  links, cost references, and simulation base currency where the related
  evidence is available.

### Boundaries and compatibility

- Keeps Part B standard-library-only and free of engine parsers, comparison
  tolerances, alignment, attribution, reports, CLI, Streamlit, and persistence.
- Advances the package to PEP 440 prerelease `1.5.0a2` while retaining V1
  report schema `2.5`, audit-run-manifest schema `1.1`, database schema `1`,
  and all existing statistical behavior.

## 1.5.0a1 — 2026-08-15

### V1.5A architecture and domain foundation

- Adds `backtest_auditor.implementation_risk` as an explicit capability
  boundary inside the existing modular monolith; its domain is independent
  from V1 statistics, adapters, persistence, presentation, and reporting.
- Adds immutable exported-run references with engine identity, optional
  explicit engine version, and adapter-computed source SHA-256 provenance.
- Adds deterministic reference-to-candidates reconciliation scopes with
  eleven independently requestable comparison levels.
- Adds evidence-profile preflight with typed `eligible`,
  `reference_unavailable`, `candidate_unavailable`, and `both_unavailable`
  outcomes for every candidate/level pair.
- Rejects missing, duplicate, extra, or identity-mismatched run profiles rather
  than assessing a different scope silently.

### Boundaries and compatibility

- Freezes V1.5 as file-first and read-only: it consumes exported evidence and
  does not execute a backtest, connect to broker execution, select strategies,
  or reconstruct real trading.
- Documents comparison semantics, invariants, dependency direction, deferred
  decisions, and the remaining V1.5 roadmap in a dedicated architecture guide
  and ADR.
- Advances the package to PEP 440 prerelease `1.5.0a1` while retaining V1
  report schema `2.5`, audit-run-manifest schema `1.1`, database schema `1`,
  and every V1.4 statistical behavior.

## 1.4.0 — 2026-08-14

### Additional statistical methods

- Extends serial-dependence evidence with PACF estimates, configurable
  large-sample ACF bounds, a median-sign Wald–Wolfowitz runs test,
  Bartlett long-run variance and effective-sample-size evidence for the mean,
  and heteroskedasticity-robust Lo–MacKinlay variance-ratio tests.
- Adds deterministic circular stationary-bootstrap percentile intervals while
  retaining the existing moving-block implementation and explicit block/seed
  contract.
- Adds target-dependent Sortino, downside deviation, and Omega; empirical
  historical loss VaR and expected shortfall; and path-dependent Calmar and
  Ulcer Index evidence.
- Adds OLS benchmark alpha/beta with an explicit Bartlett-HAC bandwidth,
  two-sided p-value, and confidence interval.
- Adds family-wide White Reality Check and consistent Hansen SPA tests against
  an exactly aligned shared benchmark using deterministic stationary-bootstrap
  resampling. Winner-only or incomplete-family evidence remains ineligible.

### Additive domain evidence

- Accepts optional exactly aligned period risk-free returns, gross strategy
  returns, and externally declared regime labels in CLI and Streamlit
  Single-Run workflows.
- Reports time-varying excess-return evidence, gross-to-net cost drag, and
  descriptive declared-regime slices without silently joining timestamps or
  inferring regimes.
- Keeps time-varying risk-free evidence separate from the scalar risk-free
  assumptions of the legacy Sharpe/PSR/HAC methods, avoiding an implicit change
  to previously published statistical semantics.

### Contracts and quality

- Advances package version to `1.4.0`, report schema to `2.5`, and audit-run
  manifest schema to `1.1`; retains the `2.4` and `1.0` schemas in the bundled
  catalog for legacy report validation. Database schema remains `1`.
- Adds complete CLI, Streamlit, manifest, findings, evidence-profile,
  deterministic JSON/Markdown, schema, golden-report, numerical-reference,
  malformed-input, and boundary tests for the new evidence.
- Preserves file-first operation, engine neutrality, immutable history, and the
  prohibition on execution, custody, money movement, or trade reconstruction.

## 1.3.0 — 2026-08-14

### Read-only IBKR Activity Flex import

- Adds one anti-corruption adapter for exported Activity Flex XML/CSV statements
  and Flex Web Service v3 responses using the same canonicalization path.
- Imports only period-level Change-in-NAV `TWR`, divides the percentage by 100,
  timestamps it at statement `ToDate`, retains explicit interval bounds, and
  rejects duplicate, overlapping, invalid, or ambiguous account/model scopes.
- Adds `backtest-auditor ibkr files` and `backtest-auditor ibkr api`, plus a
  Streamlit import/download workflow. Both produce the unchanged Single-Run CSV
  contract and a deterministic import manifest.
- Hashes source bytes/names, account/model selectors, query identity, and canonical
  CSV provenance without serializing clear-text account IDs, model names, query
  IDs, or tokens.

### Credential and protocol hardening

- Accepts the API token only through
  `BACKTEST_AUDITOR_IBKR_FLEX_TOKEN`, excludes credentials from object
  representations and public errors, ignores service-returned URLs, refuses
  redirects, and bounds timeouts, response sizes, polling, and date overrides.
- Implements fixed official v3 endpoints, explicit User-Agent identification,
  credential-safe control-response parsing, terminal authentication failures,
  bounded transient retries, and a default 6.1-second request interval for the
  documented per-token rate limit.
- Rejects XML DTD/entity declarations, malformed or non-UTF-8 inputs, missing
  Change-in-NAV fields, non-finite TWR, simple returns below -100%, and more than
  10,000 source intervals.
- Preserves report schema `2.4`, audit-run-manifest schema `1.0`, database schema
  `1`, existing statistical semantics, and file-first operation. V1.3 adds no
  order execution, trade reconstruction, or broker reconciliation.

## 1.2.1 — 2026-08-14

### Persistence correctness and compatibility

- Includes package, report-schema, and manifest identity in new audit
  fingerprints while retaining idempotent recognition of existing V1.2.0
  fingerprints with matching stored versions.
- Validates report JSON, manifest consistency, normalized-series metadata,
  ISO-8601 timestamps, finite returns, identifier bounds, and duplicate series
  identities before writes and after reads.
- Rejects unknown future schema versions before creating or altering tables.
- Normalizes ordinary `postgresql://` URLs to the declared psycopg driver,
  rejects unsupported asynchronous/third-party drivers, and converts malformed
  URL or engine failures into credential-safe errors.
- Adds explicit repository lifecycle management and closes Streamlit database
  engines after each save/history interaction.

### Streamlit and release hardening

- Clears stale successful evidence before a replacement audit is validated.
- Rejects control characters and non-portable overlong browser filenames.
- Uses Streamlit's current stretch-width API when available while retaining the
  declared compatibility path for older supported Streamlit releases.
- Tests the built wheel in isolated base and `ui,postgres` environments, proving
  both optional-dependency boundaries and installed psycopg initialization.
- Preserves report schema `2.4`, manifest schema `1.0`, database schema `1`, and
  all statistical semantics.

## 1.2.0 — 2026-08-14

### Database-backed audit history

- Adds one repository contract with transactional SQLAlchemy adapters for both
  SQLite and PostgreSQL.
- Stores immutable JSON/Markdown reports, optional manifests, package/schema
  identity, and canonical normalized strategy, trial, and benchmark returns.
- Uses content fingerprints for idempotent saves and never retains original
  uploaded files or database credentials.
- Adds Streamlit save, browse, reopen, and report-download workflows while
  preserving optional, file-first operation.
- Adds schema-version checks, SQLite integration tests, PostgreSQL CI, and
  package extras for database-only and PostgreSQL installations.

## 1.1.0 — 2026-08-13

### Streamlit presentation layer

- Adds an optional local Streamlit interface for both Single-Run and
  Experiment-Family workflows.
- Supports strategy, benchmark, family, split, and authoritative-calendar file
  uploads; explicit sampling and return-methodology declarations; every V1
  statistical and robustness specification; and deterministic audit identity.
- Presents evidence dimensions, findings, and normalization issues separately,
  with downloadable deterministic JSON and Markdown reports.
- Adds a framework-neutral upload controller that calls the canonical V1
  ingestion and application services directly and discards temporary files
  after each audit.
- Adds the `ui` optional dependency and `backtest-auditor-ui` launcher while
  keeping the base CLI installation free of Streamlit.

### Hardening and compatibility

- Extends canonical manifest serialization to support authoritative calendar
  session dates, fixing the calendar-plus-manifest combination.
- Preserves report schema `2.4`, evidence-profile schema `1.0`, manifest schema
  `1.0`, CLI behavior, and all statistical semantics.
- Raises the package version to `1.1.0` and adds controller, UI, launcher,
  packaging, and installed-application tests.

## 1.0.0 — 2026-08-12

This is the completed V1 release.

### Audit capabilities

- Audits canonical timestamped return series without executing a backtest or
  connecting to a broker.
- Audits complete experiment families with explicit trial, return-matrix,
  parameter, selection, and optional fold evidence.
- Reports sampling and calendar eligibility, annualized statistics, Sharpe,
  higher moments, PSR, Minimum Track-Record Length, serial dependence,
  Bartlett-HAC estimates, moving-block bootstrap intervals, performance paths,
  and exactly aligned benchmark-relative evidence.
- Reports classical location-only DSR, exhaustive CSCV/PBO, parameter
  neighborhoods, temporal robustness, and declared-fold replay for eligible
  experiment families.
- Provides independent categorical evidence dimensions without an aggregate
  score or global pass/fail label.
- Provides optional content-hashed audit-run manifests covering raw inputs,
  normalized data, configuration, methods, seeds, warnings, dependencies, and
  environment identity.

### Release contracts

- Publishes Draft 2020-12 JSON Schemas for report schema `2.4`, evidence-profile
  schema `1.0`, and audit-run-manifest schema `1.0`.
- Ships complete deterministic JSON and Markdown golden reports, independent
  hand-calculable numerical reference data, and a deterministic large-family
  benchmark harness.
- Adds Python 3.11–3.13 CI, formatting, lint, focused static typing, 95% coverage,
  schema/golden regeneration, build, metadata, clean-install, and deterministic
  installed-CLI gates.

### Compatibility

- Package version is `1.0.0`.
- Public report schema remains `2.4`; Part Q hardens the existing Part P report
  shape and evidence semantics rather than adding a new statistical method.
- Public audit-run manifest schema remains `1.0`.
