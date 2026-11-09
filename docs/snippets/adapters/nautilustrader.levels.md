Adapter `backtest-auditor.nautilustrader` 1.0.0, tested engine versions: 1.231.0.

| Level | Availability | Origin | Adapter's explanation |
|---|---|---|---|
| `strategy_specification` | unsupported | none | Post-run reports do not retain a complete canonical strategy configuration. |
| `market_data` | unsupported | none | Report tables do not contain the exact market-data event history. |
| `signal` | unsupported | none | Strategy signals are not part of the documented report set. |
| `order` | always | engine_export | The orders report maps final lifecycle, quantity, type, and time-in-force fields. |
| `fill` | always | engine_export | The fills report supplies one row per OrderFilled event. |
| `trade` | always | engine_export | Position and snapshot report rows retain engine-native position grouping and realized P&L. |
| `position` | always | deterministic_derivation | Instrument net quantities are summed at each reported position update timestamp. |
| `cash` | always | engine_export | One account report supplies timestamped balances by currency. |
| `cost` | always | engine_export | Per-fill commissions map to fill-linked commission impacts. |
| `equity` | unsupported | none | Account balances are not promoted to portfolio equity without valuation evidence. |
| `return` | unsupported | none | The documented report set does not expose a timestamped portfolio return series. |
