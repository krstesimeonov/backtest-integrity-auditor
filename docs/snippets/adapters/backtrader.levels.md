Adapter `backtest-auditor.backtrader` 1.0.0, tested engine versions: 1.9.78.123.

| Level | Availability | Origin | Adapter's explanation |
|---|---|---|---|
| `strategy_specification` | unsupported | none | The analyzer does not serialize arbitrary Strategy Python code and parameters. |
| `market_data` | unsupported | none | Snapshot close prices are valuation evidence, not a complete data-feed export. |
| `signal` | unsupported | none | Backtrader strategies do not share one stable signal representation. |
| `order` | always | engine_export | Analyzer order notifications preserve final lifecycle state and timestamps. |
| `fill` | always | engine_export | OrderExecutionBit values map one-to-one to canonical fills. |
| `trade` | unsupported | none | Backtrader trade grouping may depend on tradeid and strategy conventions not frozen in D2. |
| `position` | always | engine_export | Analyzer snapshots preserve per-feed position quantity and close valuation. |
| `cash` | always | engine_export | Broker cash snapshots map to base-currency balances. |
| `cost` | always | engine_export | Execution-bit commissions map to fill-linked P&L impacts. |
| `equity` | always | engine_export | Broker value, cash, and recorded position exposure map to equity points. |
| `return` | always | deterministic_derivation | Simple returns are derived from consecutive broker equity snapshots. |
