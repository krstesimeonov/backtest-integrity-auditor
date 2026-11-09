# V1 Release Checklist

Run every command from the repository root in a clean Python environment.

## Contract and quality gates

- [ ] `ruff format --check src tests scripts benchmarks`
- [ ] `ruff check src tests scripts benchmarks`
- [ ] `mypy`
- [ ] `python scripts/release_contracts.py --check`
- [ ] `python scripts/generate_v1_5c_bundle_example.py --check`
- [ ] `python scripts/generate_v1_5d1_engine_export_example.py --check`
- [ ] `python scripts/generate_v1_5d2_engine_examples.py --check`
- [ ] `python scripts/generate_v1_5d3_engine_examples.py --check`
- [ ] `python scripts/generate_v1_5e_normalization_example.py --check`
- [ ] `python scripts/generate_v1_5f_comparison_example.py --check`
- [ ] `python scripts/generate_v1_5g_divergence_example.py --check`
- [ ] `python scripts/generate_v1_5h_risk_example.py --check`
- [ ] `python scripts/generate_v1_5i_report_example.py --check`
- [ ] `python scripts/generate_v1_5j_golden.py --check`
- [ ] `python -m pytest --cov=backtest_auditor --cov-fail-under=95`
- [ ] `python benchmarks/benchmark_implementation_risk.py`
- [ ] Test the full suite on Python 3.11, 3.12, and 3.13.
- [ ] Render Single-Run, Experiment-Family, IBKR Flex Import, and Audit History
  with `streamlit.testing.v1.AppTest`.
- [ ] Import representative IBKR Flex XML and CSV exports and compare the
  canonical CSV and credential-free import manifest.
- [ ] Exercise the Flex Web Service client through mocked success, transient,
  authentication, rate-limit, redirect, and oversized-response paths. A live
  credential test is optional and must not expose or persist the token.
- [ ] Run the benchmark smoke case and inspect its eligible matrix shape.

## Distribution gates

- [ ] `python -m build`
- [ ] `python -m twine check dist/*`
- [ ] Inspect the wheel and source distribution for `py.typed`, all seven V1
  public schemas, and all six V1.5 schemas.
- [ ] Install the wheel into a clean environment without the source tree on
  `PYTHONPATH`.
- [ ] Load every public schema from the installed package.
- [ ] Import `backtest_auditor.implementation_risk` from the base wheel,
  execute a scope-preflight smoke case, and construct a canonical run-artifact
  bundle with specification, order, and fill evidence.
- [ ] Load both V1.5C schemas and round-trip the example directory plus a
  deterministic ZIP through the installed canonical bundle adapter.
- [ ] Load the V1.5D1 envelope schema; round-trip its example as a directory and
  deterministic ZIP; verify the registry/service ports without installing an
  engine SDK.
- [ ] Load the D2 adapter-metadata schema and map all three committed D2 exports
  from the base wheel without vectorbt, bt, or Backtrader installed.
- [ ] Map both committed D3 exports from the base wheel without LEAN or
  NautilusTrader installed and assert complete five-engine registry coverage.
- [ ] Normalize the committed V1.5E example with the base wheel; verify its
  plan/output identities, exact changes, unchanged numbers, and timestamps.
- [ ] Compare the committed V1.5F example with the base wheel; verify exact
  statuses, field deltas, and normalization/comparison policy hashes.
- [ ] Measure the committed V1.5G example with the base wheel; verify family
  states, exact Decimal deltas, and all three evidence-policy hashes.
- [ ] Assess the committed V1.5H example with the base wheel; verify materiality,
  bounded score, uncertainty, attribution status, and policy hash.
- [ ] Run the committed V1.5I example through the base-wheel CLI; validate the
  report and manifest against their separate schemas and confirm byte-identical
  JSON and Markdown regeneration.
- [ ] From outside the source tree, run `scripts/verify_v1_5_installed.py`
  against the base wheel and all three V1.5J golden cases.
- [ ] Install the `engine-exporters` extra, verify all four exact Python SDK
  versions on Python 3.12+, and run the live exporter/mapper conformance tests.
- [ ] Run the installed CLI twice with the same explicit audit identity and
  confirm byte-for-byte identical output.
- [ ] Install the `ui` extra and render the installed Streamlit application
  with `AppTest` outside the source tree.

## Source-archive gates

- [ ] Include only source, tests, fixtures, examples, documentation, benchmark,
  release scripts, and CI configuration.
- [ ] Exclude caches, coverage data, virtual environments, build products,
  installed metadata, and generated audit output.
- [ ] Extract the exact candidate archive into a new directory and repeat the
  contract, test, build, installation, and determinism gates there.
- [ ] Record the archive SHA-256.
- [ ] Run `scripts/verify_source_archive.py` with expected root and version
  against the exact candidate ZIP before delivery or publication.

## Owner-controlled publication decisions

- [ ] Choose and add an explicit software license before public distribution.
  No license is inferred by this repository.
- [ ] Confirm package ownership, repository URL, release tag, and publication
  destination.
- [ ] Publish only the verified wheel and source distribution built from the
  tagged source archive.
