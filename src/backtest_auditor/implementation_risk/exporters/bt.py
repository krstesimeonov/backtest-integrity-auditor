"""Deterministic exporter for executed bt 1.2.0 results."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_auditor.implementation_risk.adapters.engine_csv import (
    canonical_csv_bytes,
    canonical_decimal,
)
from backtest_auditor.implementation_risk.domain import (
    ComparisonLevel,
    EngineExportPayload,
    SupportedEngine,
)
from backtest_auditor.implementation_risk.exporters.common import (
    adapter_metadata_payload,
    installed_engine_version,
    require_datetime_index,
    require_frame,
    require_series,
    utc_timestamp,
    write_engine_export,
)


BT_EXPORT_FORMAT_ID = "backtest-auditor.bt"
BT_TESTED_VERSION = "1.2.0"
BT_TRANSACTIONS_FILE = "bt-transactions.csv"
BT_POSITIONS_FILE = "position-snapshots.csv"
BT_PORTFOLIO_FILE = "portfolio-series.csv"

BT_TRANSACTIONS_HEADERS = (
    "transaction_id",
    "timestamp",
    "instrument",
    "quantity",
    "price",
)
BT_POSITIONS_HEADERS = (
    "timestamp",
    "instrument",
    "quantity",
    "market_price",
    "market_value",
)
BT_PORTFOLIO_HEADERS = (
    "timestamp",
    "total_equity",
    "cash",
    "gross_exposure",
    "net_exposure",
    "fees",
    "return",
)

BT_LEVELS = (
    ComparisonLevel.ORDER,
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)


def _scalar(value: object, *, field: str) -> str:
    try:
        return canonical_decimal(value)
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error


def _optional_scalar(value: object, *, field: str) -> str:
    if pd.isna(value):
        return ""
    return _scalar(value, field=field)


def _select_backtest(result: Any, strategy_name: str | None) -> tuple[str, Any]:
    backtests = getattr(result, "backtests", None)
    if not isinstance(backtests, dict) or not backtests:
        raise ValueError("result.backtests must contain an executed bt backtest.")
    if strategy_name is None:
        if len(backtests) != 1:
            raise ValueError(
                "strategy_name is required when a bt Result contains multiple backtests."
            )
        selected = next(iter(backtests))
    else:
        selected = strategy_name
    if selected not in backtests:
        raise ValueError(f"bt result contains no strategy {selected!r}.")
    return selected, backtests[selected]


def _require_unnetted_executions(
    transactions: pd.DataFrame,
    fees: pd.Series,
    strategy: Any,
) -> None:
    """Refuse a run whose fees show executions that bt netted away.

    bt keeps no execution log: ``Result.get_transactions()`` is the change in
    position between bars. Several executions on one bar (a close and a
    re-open, a partial reversal) collapse into their net, or vanish, while bt
    still charged the commission of each. Then a bar's fee differs from the
    strategy's own commission function applied to that bar's net
    transactions, and the export cannot state the run truthfully.
    """

    commission = getattr(strategy, "commission_fn", None)
    if not callable(commission):
        raise ValueError("bt strategy.commission_fn must be callable.")
    expected: dict[Any, float] = {}
    for (timestamp, security), row in transactions.iterrows():
        child = strategy.children.get(security)
        multiplier = float(getattr(child, "multiplier", 1.0) or 1.0)
        expected[timestamp] = expected.get(timestamp, 0.0) + float(
            commission(row["quantity"], row["price"] * multiplier)
        )
    for timestamp, fee in fees.items():
        if not math.isclose(
            float(fee), expected.get(timestamp, 0.0), rel_tol=1e-9, abs_tol=1e-9
        ):
            raise ValueError(
                f"bt charged {float(fee)} in fees at {timestamp} but its net "
                "transactions there cost "
                f"{expected.get(timestamp, 0.0)}: bt netted several executions "
                "on one bar, which this export cannot represent."
            )


def export_bt_result(
    result: Any,
    destination: str | Path,
    *,
    run_id: str,
    base_currency: str,
    strategy_name: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Export one already executed bt backtest from a ``bt.Result``."""

    engine_version = installed_engine_version("bt")
    if engine_version != BT_TESTED_VERSION:
        raise ValueError(
            f"bt exporter was tested only with {BT_TESTED_VERSION}; "
            f"installed version is {engine_version}."
        )
    selected_name, backtest = _select_backtest(result, strategy_name)
    strategy = getattr(backtest, "strategy", None)
    if strategy is None:
        raise ValueError("selected bt backtest has no executed strategy.")

    try:
        transactions = result.get_transactions(selected_name)
    except Exception as error:
        raise ValueError("bt transactions could not be exported.") from error
    if not isinstance(transactions, pd.DataFrame):
        raise ValueError("bt Result.get_transactions() must return a DataFrame.")
    if tuple(str(column) for column in transactions.columns) != (
        "price",
        "quantity",
    ):
        raise ValueError("bt transaction columns do not match version 1.2.0.")
    if not isinstance(transactions.index, pd.MultiIndex) or tuple(
        transactions.index.names
    ) != ("Date", "Security"):
        raise ValueError(
            "bt transactions must use the documented Date/Security MultiIndex."
        )

    positions = require_frame(strategy.positions, field="bt strategy.positions")
    values = require_series(strategy.values, field="bt strategy.values")
    cash = require_series(strategy.cash, field="bt strategy.cash")
    prices = require_frame(backtest.data, field="bt backtest.data")
    normalized_prices = require_series(
        strategy.prices,
        field="bt strategy.prices",
    )
    fees = require_series(strategy.data["fees"], field="bt strategy fees")
    index = require_datetime_index(values, field="bt strategy.values")
    for name, value in (
        ("positions", positions),
        ("data", prices),
        ("cash", cash),
        ("prices", normalized_prices),
        ("fees", fees),
    ):
        if not value.index.equals(index):
            raise ValueError(f"bt {name} index must equal the strategy value index.")
    if set(str(column) for column in positions.columns) != set(
        str(column) for column in prices.columns
    ):
        raise ValueError("bt position and market-price instruments must match.")

    raw_transactions: list[tuple[str, str, str, str]] = []
    for row_number, (index_value, row) in enumerate(
        transactions.iterrows(),
        start=2,
    ):
        timestamp, instrument = index_value
        raw_transactions.append(
            (
                utc_timestamp(timestamp, field=f"transaction row {row_number} Date"),
                str(instrument),
                _scalar(row["quantity"], field="quantity"),
                _scalar(row["price"], field="price"),
            )
        )
    raw_transactions.sort()
    _require_unnetted_executions(transactions, fees, strategy)
    transaction_rows = [
        {
            "transaction_id": f"{index:08d}",
            "timestamp": timestamp,
            "instrument": instrument,
            "quantity": quantity,
            "price": price,
        }
        for index, (timestamp, instrument, quantity, price) in enumerate(
            raw_transactions,
            start=1,
        )
    ]

    position_rows = []
    portfolio_rows = []
    period_returns = normalized_prices.pct_change(fill_method=None)
    for timestamp in index:
        gross_exposure = 0.0
        net_exposure = 0.0
        for raw_instrument in sorted(positions.columns, key=str):
            instrument = str(raw_instrument)
            quantity = positions.loc[timestamp, raw_instrument]
            market_price = prices.loc[timestamp, raw_instrument]
            if pd.isna(market_price):
                if float(quantity) != 0.0:
                    raise ValueError(
                        f"bt has a non-zero {instrument!r} position without a price."
                    )
                market_value = 0.0
            else:
                child = strategy.children.get(raw_instrument)
                multiplier = getattr(child, "multiplier", 1.0)
                market_value = quantity * market_price * multiplier
                gross_exposure += abs(float(market_value))
                net_exposure += float(market_value)
            position_rows.append(
                {
                    "timestamp": utc_timestamp(timestamp, field="position timestamp"),
                    "instrument": instrument,
                    "quantity": _scalar(quantity, field="position quantity"),
                    "market_price": _optional_scalar(
                        market_price,
                        field="market price",
                    ),
                    "market_value": _scalar(market_value, field="market value"),
                }
            )
        period_return = period_returns.loc[timestamp]
        portfolio_rows.append(
            {
                "timestamp": utc_timestamp(timestamp, field="portfolio timestamp"),
                "total_equity": _scalar(values.loc[timestamp], field="value"),
                "cash": _scalar(cash.loc[timestamp], field="cash"),
                "gross_exposure": _scalar(gross_exposure, field="gross exposure"),
                "net_exposure": _scalar(net_exposure, field="net exposure"),
                "fees": _scalar(fees.loc[timestamp], field="fees"),
                "return": _optional_scalar(period_return, field="return"),
            }
        )

    payloads = (
        adapter_metadata_payload(base_currency),
        EngineExportPayload(
            BT_TRANSACTIONS_FILE,
            "transactions",
            "text/csv",
            canonical_csv_bytes(BT_TRANSACTIONS_HEADERS, transaction_rows),
        ),
        EngineExportPayload(
            BT_POSITIONS_FILE,
            "positions",
            "text/csv",
            canonical_csv_bytes(BT_POSITIONS_HEADERS, position_rows),
        ),
        EngineExportPayload(
            BT_PORTFOLIO_FILE,
            "portfolio",
            "text/csv",
            canonical_csv_bytes(BT_PORTFOLIO_HEADERS, portfolio_rows),
        ),
    )
    return write_engine_export(
        run_id=run_id,
        engine=SupportedEngine.BT,
        engine_version=engine_version,
        export_format_id=BT_EXPORT_FORMAT_ID,
        declared_levels=BT_LEVELS,
        payloads=payloads,
        destination=destination,
        overwrite=overwrite,
    )
