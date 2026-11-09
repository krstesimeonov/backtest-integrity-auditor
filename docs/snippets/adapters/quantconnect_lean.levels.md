Adapter `backtest-auditor.quantconnect-lean` 1.0.0, tested engine versions: 2.5.17999.

| Level | Availability | Origin | Adapter's explanation |
|---|---|---|---|
| `strategy_specification` | unsupported | none | Local result files do not retain a complete canonical algorithm specification. |
| `market_data` | unsupported | none | Result charts are not the exact market-data stream consumed by the algorithm. |
| `signal` | unsupported | none | Insights and custom charts do not establish canonical signal semantics. |
| `order` | always | engine_export | The official local result Orders collection supplies final order records. |
| `fill` | always | engine_export | Non-zero fill quantities in the official order-events file map one-to-one. |
| `trade` | unsupported | none | D3 does not promote LEAN closed-trade grouping to a universal canonical grouping. |
| `position` | always | deterministic_derivation | Net instrument quantities are accumulated from the ordered fill stream. |
| `cash` | unsupported | none | The standard local result does not provide a complete cash-balance history. |
| `cost` | always | engine_export | Order-event fees map to fill-linked commission impacts. |
| `equity` | always | engine_export | The built-in Strategy Equity chart supplies total portfolio value. |
| `return` | always | deterministic_derivation | Simple returns are calculated from consecutive Strategy Equity points. |
