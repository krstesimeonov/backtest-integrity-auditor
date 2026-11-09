# Security policy

## Supported versions

Security fixes go into the latest 1.6.x release.

## Reporting a vulnerability

Please report security problems privately, not in a public issue. Once the
repository is public and private vulnerability reporting is enabled for it,
use "Report a vulnerability" on the repository's Security tab. Include the version, the
input that triggers the problem (synthetic data only, please) and what you
expected instead.

There is no bug bounty.

## What is in scope

The package reads files and archives that you give it: return CSVs,
experiment-family inputs, IBKR Flex statements (XML or CSV), engine exports,
canonical bundle ZIPs and policy JSON. A crash is not a vulnerability by
itself; reading outside the given paths, executing code from an input, an
unbounded resource use that the documented limits should prevent
(`docs/V1_5J_RELEASE_HARDENING.md`), or leaking the IBKR Flex token is.

The IBKR Flex Web Service mode reads its token only from the environment
variable `BACKTEST_AUDITOR_IBKR_FLEX_TOKEN`; there is no command-line option
for it (`docs/IBKR_FLEX_IMPORT.md`). The package never places orders.
