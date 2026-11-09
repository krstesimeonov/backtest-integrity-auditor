# ADR-001: Add V1.5 as an Export-Only Capability Boundary

- Status: Accepted
- Date: 2026-08-15
- Decision owners: project owner and architecture implementation

## Context

The completed V1 package audits statistical evidence from return series and
experiment families. V1.5 must compare implementations across backtesting
engines without corrupting V1's frozen statistical domain or coupling the
package to engine runtimes.

Three designs were considered:

1. Add order, fill, position, and reconciliation objects to the existing V1
   `domain` package.
2. Create a separately deployed service for V1.5.
3. Add a new capability boundary inside the existing modular monolith.

Engine execution inside the auditor and export-only ingestion were also
compared.

## Decision

Use `backtest_auditor.implementation_risk` as a capability boundary inside the
existing distribution. Its domain is standard-library-only. Later application,
adapter, and reporting modules may depend inward on that domain; the domain
cannot depend outward on engines, files, databases, UI frameworks, or reports.

V1.5 consumes exported engine evidence. It does not execute engines. One
declared reference run is compared independently with one or more candidates.
Evidence availability is assessed per comparison level, with no implied
hierarchy and no silent repair.

## Why

- A separate service adds deployment, API, observability, and consistency cost
  before a multi-user scaling need exists.
- Expanding V1's statistical domain with execution artifacts would mix two
  bounded problems and make the V1 public contracts harder to preserve.
- Export-only evidence keeps audits reproducible and prevents engine SDKs from
  determining the domain model.
- Reference-to-candidates reporting is deterministic and easier to interpret
  than an all-pairs matrix.
- Independent level eligibility preserves partial evidence without claiming
  unsupported causal attribution.

## Consequences

Positive:

- V1 schemas and statistical semantics remain unchanged.
- Engine adapters can evolve independently behind canonical contracts.
- The same reconciliation core can compare different engines, versions, or
  configurations.
- Missing low-level evidence does not erase valid high-level comparisons.

Costs:

- Users or external tooling must export runs before reconciliation.
- Concrete adapters must accurately document each engine's semantics.
- Agreement between engines still cannot prove correctness.
- Root-cause attribution will remain unavailable when upstream artifacts are
  missing.

## Rejected alternatives

**Microservice now:** rejected because there is one codebase, one owner, one
local workflow, and no independent scaling or deployment requirement.

**Execute every engine inside V1.5:** rejected because it couples dependency
versions, environments, data access, and user strategy code to the auditor.

**Treat the reference as ground truth:** rejected because engine choice does
not establish correctness. The reference supplies direction, not authority.

**Require a complete artifact stack:** rejected because many engines export
only returns or trades. Typed partial evidence is more honest than rejecting
all useful comparisons.

## Revisit conditions

Reconsider an optional external runner only when users repeatedly require
automated export and the runner can produce the same canonical file contract.
Reconsider service extraction only when deployment, security, ownership, or
scaling requirements become independently measurable.
