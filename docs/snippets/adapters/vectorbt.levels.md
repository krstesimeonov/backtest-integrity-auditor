Adapter `backtest-auditor.vectorbt` 1.0.0, tested engine versions: 1.1.0.

| Level | Availability | Origin | Adapter's explanation |
|---|---|---|---|
| `strategy_specification` | unsupported | none | Portfolio exports do not retain a complete canonical strategy specification. |
| `market_data` | unsupported | none | D2 exports the valuation close only inside position snapshots, not a market-data history. |
| `signal` | unsupported | none | Portfolio objects do not reliably retain the original signal arrays and semantics. |
| `order` | always | deterministic_derivation | vectorbt order records are filled orders; canonical filled orders are reconstructed one-to-one. |
| `fill` | always | engine_export | Each vectorbt filled-order record maps to one canonical fill. |
| `trade` | always | engine_export | vectorbt position records map to canonical trades using vectorbt position grouping. |
| `position` | always | engine_export | Portfolio assets, close, and asset value form quantity snapshots. |
| `cash` | always | engine_export | Portfolio cash series maps to base-currency balances. |
| `cost` | always | engine_export | Filled-order fee values map to commission P&L impacts. |
| `equity` | always | engine_export | Portfolio value, cash, and asset value map to equity points. |
| `return` | always | engine_export | Portfolio returns map from the second timestamp onward. |
