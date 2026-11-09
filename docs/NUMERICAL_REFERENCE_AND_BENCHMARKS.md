# Numerical Reference Data and Benchmarks

V1 separates correctness references from performance measurements. A numerical
case must pass to release; an elapsed benchmark is informational because timing
depends on hardware and the Python environment.

## Independent numerical reference

`tests/fixtures/reference/independent_numerical_cases.json` contains a
hand-calculable four-return series and expected descriptive, annualized,
distribution, Sharpe-uncertainty, and path values. The expected values are
stored as data, not produced by the functions under test. The regression test
audits the series through the public application service and compares the
result with tight tolerances.

The existing method-specific tests add deterministic reference behavior for:

- classical expected-maximum, location-only Deflated Sharpe Ratio;
- exhaustive CSCV partitions, OOS ranks, logits, and PBO;
- Bartlett-HAC point estimates and Sharpe uncertainty; and
- seeded moving-block and stationary-bootstrap intervals;
- PACF, runs, long-run mean variance, effective observations, and robust
  variance-ratio boundary behavior;
- empirical Sortino/Omega/VaR/expected-shortfall and path-risk values;
- exactly aligned risk-free, gross/net, and declared-regime calculations;
- OLS alpha coefficients with Bartlett-HAC inference and typed regression
  ineligibility; and
- deterministic White Reality Check/Hansen SPA results plus complete-family,
  missing-benchmark, insufficient-sample, and degenerate-trial boundaries.

Complete report fixtures in `tests/fixtures/golden/` cover both audit modes and
all V1 report sections. The checker requires canonical JSON formatting, exact
structure and non-floating values, and floating values within eight units in
the last place (ULPs). This narrow tolerance accommodates arithmetic variation
between supported Python and numerical-library builds without masking a
methodological change. Markdown fixtures and repeated CLI output within one
environment remain byte-for-byte contracts. These fixtures are not a
substitute for the independent numerical assertions.

## Large-family benchmark

Run the deterministic benchmark from the repository root:

```bash
python benchmarks/benchmark_family_audit.py \
  --trials 128 \
  --observations 1024 \
  --repeats 3
```

The harness constructs a canonical aligned matrix with fixed deterministic
returns, runs the family application service, verifies the eligible shape, and
prints JSON containing minimum, median, and maximum wall time. Its parameters
can be reduced for a quick local check.

CI includes a smaller scalability smoke test that verifies behavior but has no
wall-time threshold. This avoids turning shared-runner noise into a correctness
failure. Release reviewers can retain benchmark output separately when they
need to compare performance across commits on the same controlled machine.
