Adapter `backtest-auditor.bt` 1.0.0, tested engine versions: 1.2.0.

| Level | Availability | Origin | Adapter's explanation |
|---|---|---|---|
| `strategy_specification` | unsupported | none | An executed bt result does not serialize the complete Algo stack canonically. |
| `market_data` | unsupported | none | Valuation prices in snapshots do not constitute an auditable market-data history. |
| `signal` | unsupported | none | bt Result does not expose strategy signals as a stable result table. |
| `order` | always | deterministic_derivation | Each executed bt transaction produces one synthetic filled order. |
| `fill` | always | engine_export | Result.get_transactions supplies timestamp, security, quantity, and price. |
| `trade` | unsupported | none | bt does not freeze one universal transaction-to-trade grouping convention. |
| `position` | always | engine_export | Executed strategy position histories map to quantity snapshots. |
| `cash` | always | engine_export | The executed strategy cash series maps to base-currency balances. |
| `cost` | always | engine_export | Strategy fee history maps to timestamp-level commission impacts. |
| `equity` | always | engine_export | Strategy values, cash, positions, and prices map to equity points. |
| `return` | always | deterministic_derivation | Returns are the period changes in bt's flow-adjusted strategy price series. |
