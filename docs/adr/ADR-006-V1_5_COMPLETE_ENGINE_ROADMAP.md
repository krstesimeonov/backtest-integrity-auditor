# ADR-006: Complete Engine Roadmap and Preserve Asymmetric Evidence

Status: accepted for V1.5D3.

## Decision

Add QuantConnect LEAN and NautilusTrader through the existing D1 verified file
boundary. The complete D3 registry contains exactly one fail-closed mapper for
each accepted roadmap engine in frozen order. The two engines keep asymmetric
capabilities; a shared registry does not force identical evidence.

LEAN consumes completed local result and order-event JSON. NautilusTrader
consumes the four documented post-run report tables. Engine SDKs remain on the
producer side. The base auditor imports neither SDK.

## Consequences

- LEAN engine version provenance is producer-declared because its result JSON
  omits the NuGet version; the limitation is retained as a warning.
- LEAN positions and returns are deterministic derivations from fills and
  equity respectively. Cash and canonical trade grouping remain unavailable.
- NautilusTrader trades retain `position_id` grouping, positions are
  quantity-only report-event snapshots, and account totals remain cash rather
  than equity. Equity and returns remain unavailable.
- Empty documented reports remain available-empty. Missing payloads are fatal.
- Complete-roadmap conformance requires one exact tested version per engine and
  rejects permissive undisclosed or untested version policy.

## Rejected alternatives

- Running engines inside the auditor would violate the read-only boundary.
- Treating LEAN result charts as market data or Nautilus account cash as equity
  would overstate the evidence.
- Deriving Nautilus returns from cash or inventing trade/fill links would hide
  accounting and grouping assumptions.
- A global import-time plugin registry would make installed behavior and test
  order non-deterministic.
