# V1.5J Golden Evidence and Release Hardening

Status: implemented in package `1.5.0`.

V1.5J closes the V1.5 Implementation Risk Engine. It does not add a comparison
level, divergence family, materiality rule, score interpretation, finding kind,
report field, or manifest field. It hardens the public V1.5I behavior and makes
the completed file-first capability independently reproducible from source and
installed artifacts.

## Why this increment exists

A deterministic example proves that one intended path currently runs. It does
not independently protect calculations, boundary cases, scalability, packaged
resources, or release archives. V1.5J adds separate evidence for each of those
failure modes:

| Release risk | V1.5J control |
|---|---|
| Silent output drift | Byte-frozen JSON/Markdown golden corpus and SHA-256 index |
| Self-confirming implementation | Manually specified independent reference expectations |
| Edge-case regression | Deterministic generated invariant/property tests |
| Unbounded runtime or memory | Explicit complete-pipeline time and memory budgets |
| Source-tree-only success | Clean installed-wheel verifier run outside the repository |
| Partial or unsafe report writes | Refuse overwrite by default and atomically commit with `--force` |
| Oversized or ambiguous inputs | Candidate, policy, upload, ZIP, and file resource limits |
| Dirty or unsafe source archive | Fail-closed archive structure, version, CRC, and content verification |

## Frozen golden corpus

`tests/fixtures/v1_5j_golden/` contains three independent file-first cases. Each
case has a reference bundle, candidate bundle, four policies, and frozen JSON
and Markdown reports. The reports omit the optional run manifest so their bytes
are stable across supported Python versions and operating systems.

| Case | Expected interpretation |
|---|---|
| `exact` | All four requested levels compare exactly; no numeric divergence is projected, so the score is honestly `not_assessed`, not a certified zero-risk score |
| `divergent` | Four complete numeric divergences produce materialities `extreme`, `material`, `below_threshold`, and `extreme`, with the independently calculated bounded score `87.5` |
| `incomplete` | Missing candidate equity evidence creates explicit gaps, high uncertainty, and a withheld score while retaining the other adverse evidence |

Regenerate or verify the corpus with:

```bash
python scripts/generate_v1_5j_golden.py
python scripts/generate_v1_5j_golden.py --check
```

The separately authored expectations in
`tests/fixtures/reference/v1_5_implementation_risk_cases.json` are not produced
by the audit service. They lock exact comparison states, threshold ratios,
family contributions, score/withholding behavior, attribution status, and
finding-kind counts.

## Generated invariants

The dependency-free property suite generates a deterministic range of complete
candidate deviations and verifies that:

- every produced score stays within 0–100;
- increasing absolute divergence never lowers the bounded score;
- materiality and scoring are symmetric in the sign of a numeric delta;
- exact agreement does not become a correctness certificate or global verdict;
- JSON and Markdown rendering are pure and byte deterministic.

These invariants supplement exact examples; they do not replace the independent
reference cases.

## Performance budgets

`benchmarks/benchmark_implementation_risk.py` exercises the complete in-memory
normalization, comparison, divergence, assessment, findings, and reporting
preparation path over four evidence levels. The release benchmark defaults to
2,000 records per level, three repetitions, a 10-second median budget, and a
512 MiB measured peak-memory budget. CI treats either budget breach as a
failure. The smaller test-suite smoke case uses 128 records per level, five
seconds, and 128 MiB to catch accidental superlinear regressions without
pretending that one machine is a universal capacity promise.

## Hardened file boundaries

- A reconciliation accepts at most 32 candidate bundles.
- Each policy JSON file/upload is limited to 1,000,000 bytes, must be UTF-8,
  finite, duplicate-key free, canonical, and—on the CLI—a regular non-symlink
  file.
- The Streamlit implementation-risk workflow rejects bundle uploads larger than
  512,000,000 bytes before materialization.
- The V1.5C adapter retains its per-entry, total-uncompressed, file-count,
  traversal, link, encryption, duplicate, and compression checks.
- CLI report output never overwrites an existing file unless `--force` is
  explicit, never aliases an input, never follows an output symlink, and is
  committed by atomic replacement. A failed commit leaves the prior report
  intact.

These are safety limits for one local process, not a multi-user quota system.

## Installed artifact and archive checks

After building a wheel, run the verifier from outside the repository with the
installed interpreter:

```bash
cd /tmp
/path/to/venv/bin/python /path/to/project/scripts/verify_v1_5_installed.py \
  --project-root /path/to/project \
  --expected-version 1.5.0
```

It requires the package to resolve outside the source tree, checks the 13
bundled V1/V1.5 schema resources, confirms the base environment does not need
optional UI/database/engine SDKs, reproduces all three golden cases, and runs
the installed CLI twice byte-for-byte.

`scripts/verify_source_archive.py` separately rejects unsafe paths, links,
encryption, duplicate entries, unsupported compression, caches, build products,
oversized members, wrong roots, incomplete candidates, CRC failures, and
package-version mismatches.

## Release boundary

Package `1.5.0` is technically release-ready, not automatically published.
Choosing a software license, public repository URL, release tag, package owner,
and publication destination remains an owner-controlled legal/operational
decision.

V1 report schema `2.5`, V1 manifest schema `1.1`, V1.5 report schema `1.0`,
V1.5 manifest schema `1.0`, and database schema `1` remain unchanged. V1.5J
adds no engine execution, broker execution, custody, persistence of V1.5
reports, live reconciliation, global pass/fail, causal proof, strategy-quality
certification, or future-performance claim.
