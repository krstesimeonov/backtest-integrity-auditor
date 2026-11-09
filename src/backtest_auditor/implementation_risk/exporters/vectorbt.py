"""Deterministic exporter for one-column vectorbt 1.1.0 portfolios."""

from __future__ import annotations

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
    require_series,
    utc_timestamp,
    write_engine_export,
)


VECTORBT_EXPORT_FORMAT_ID = "backtest-auditor.vectorbt"
VECTORBT_TESTED_VERSION = "1.1.0"
VECTORBT_ORDERS_FILE = "vectorbt-orders.csv"
VECTORBT_TRADES_FILE = "vectorbt-positions.csv"
VECTORBT_POSITIONS_FILE = "position-snapshots.csv"
VECTORBT_PORTFOLIO_FILE = "portfolio-series.csv"

VECTORBT_ORDERS_HEADERS = (
    "order_id",
    "instrument",
    "timestamp",
    "size",
    "price",
    "fees",
    "side",
)
VECTORBT_TRADES_HEADERS = (
    "position_id",
    "instrument",
    "size",
    "entry_timestamp",
    "avg_entry_price",
    "entry_fees",
    "exit_timestamp",
    "avg_exit_price",
    "exit_fees",
    "pnl",
    "return",
    "direction",
    "status",
)
VECTORBT_POSITIONS_HEADERS = (
    "timestamp",
    "instrument",
    "quantity",
    "market_price",
    "market_value",
)
VECTORBT_PORTFOLIO_HEADERS = (
    "timestamp",
    "total_equity",
    "cash",
    "gross_exposure",
    "net_exposure",
    "return",
)

VECTORBT_LEVELS = (
    ComparisonLevel.ORDER,
    ComparisonLevel.FILL,
    ComparisonLevel.TRADE,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)


def _readable_records(value: object, *, field: str) -> pd.DataFrame:
    records = getattr(value, "records_readable", None)
    if not isinstance(records, pd.DataFrame):
        raise ValueError(f"portfolio.{field}.records_readable must be a DataFrame.")
    return records


def _require_columns(
    frame: pd.DataFrame,
    expected: tuple[str, ...],
    *,
    field: str,
) -> None:
    if tuple(str(column) for column in frame.columns) != expected:
        raise ValueError(f"{field} columns do not match vectorbt 1.1.0.")


def _scalar(value: object, *, field: str) -> str:
    try:
        return canonical_decimal(value)
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error


def export_vectorbt_portfolio(
    portfolio: Any,
    destination: str | Path,
    *,
    run_id: str,
    instrument_id: str,
    base_currency: str,
    overwrite: bool = False,
) -> Path:
    """Export an executed one-column vectorbt portfolio without rerunning it.

    The explicit ``instrument_id`` avoids trusting vectorbt's display label,
    which can be the integer column ``0`` even when the source Series had a
    name.  Multi-column portfolios must first be grouped/exported separately;
    this prevents accidental aggregation of independent cash books.
    """

    engine_version = installed_engine_version("vectorbt")
    if engine_version != VECTORBT_TESTED_VERSION:
        raise ValueError(
            "vectorbt exporter was tested only with "
            f"{VECTORBT_TESTED_VERSION}; installed version is {engine_version}."
        )
    if not isinstance(instrument_id, str) or not instrument_id.strip():
        raise ValueError("instrument_id must be a non-empty string.")
    instrument = instrument_id.strip()

    wrapper = getattr(portfolio, "wrapper", None)
    if wrapper is None or getattr(wrapper, "ndim", None) != 1:
        raise ValueError(
            "vectorbt D2 export requires a one-column, ungrouped portfolio."
        )

    orders = _readable_records(getattr(portfolio, "orders", None), field="orders")
    trades = _readable_records(
        getattr(portfolio, "positions", None),
        field="positions",
    )
    _require_columns(
        orders,
        ("Order Id", "Column", "Timestamp", "Size", "Price", "Fees", "Side"),
        field="orders",
    )
    _require_columns(
        trades,
        (
            "Position Id",
            "Column",
            "Size",
            "Entry Timestamp",
            "Avg Entry Price",
            "Entry Fees",
            "Exit Timestamp",
            "Avg Exit Price",
            "Exit Fees",
            "PnL",
            "Return",
            "Direction",
            "Status",
        ),
        field="positions",
    )

    close = require_series(getattr(portfolio, "close", None), field="portfolio.close")
    value = require_series(portfolio.value(), field="portfolio.value()")
    cash = require_series(portfolio.cash(), field="portfolio.cash()")
    assets = require_series(portfolio.assets(), field="portfolio.assets()")
    asset_value = require_series(
        portfolio.asset_value(),
        field="portfolio.asset_value()",
    )
    returns = require_series(portfolio.returns(), field="portfolio.returns()")
    index = require_datetime_index(value, field="portfolio.value()")
    for name, series in (
        ("close", close),
        ("cash", cash),
        ("assets", assets),
        ("asset_value", asset_value),
        ("returns", returns),
    ):
        if not series.index.equals(index):
            raise ValueError(
                f"portfolio.{name} index must equal portfolio.value index."
            )

    order_rows = []
    for row_number, (_, row) in enumerate(orders.iterrows(), start=2):
        side = str(row["Side"])
        if side not in {"Buy", "Sell"}:
            raise ValueError(f"orders row {row_number} has unsupported Side {side!r}.")
        order_rows.append(
            {
                "order_id": str(int(row["Order Id"])),
                "instrument": instrument,
                "timestamp": utc_timestamp(
                    row["Timestamp"],
                    field=f"orders row {row_number} Timestamp",
                ),
                "size": _scalar(row["Size"], field="Size"),
                "price": _scalar(row["Price"], field="Price"),
                "fees": _scalar(row["Fees"], field="Fees"),
                "side": side,
            }
        )

    trade_rows = []
    for row_number, (_, row) in enumerate(trades.iterrows(), start=2):
        direction = str(row["Direction"])
        status = str(row["Status"])
        if direction not in {"Long", "Short"}:
            raise ValueError(
                f"positions row {row_number} has unsupported Direction {direction!r}."
            )
        if status not in {"Open", "Closed"}:
            raise ValueError(
                f"positions row {row_number} has unsupported Status {status!r}."
            )
        trade_rows.append(
            {
                "position_id": str(int(row["Position Id"])),
                "instrument": instrument,
                "size": _scalar(row["Size"], field="Size"),
                "entry_timestamp": utc_timestamp(
                    row["Entry Timestamp"],
                    field=f"positions row {row_number} Entry Timestamp",
                ),
                "avg_entry_price": _scalar(
                    row["Avg Entry Price"],
                    field="Avg Entry Price",
                ),
                "entry_fees": _scalar(row["Entry Fees"], field="Entry Fees"),
                "exit_timestamp": utc_timestamp(
                    row["Exit Timestamp"],
                    field=f"positions row {row_number} Exit Timestamp",
                ),
                "avg_exit_price": _scalar(
                    row["Avg Exit Price"],
                    field="Avg Exit Price",
                ),
                "exit_fees": _scalar(row["Exit Fees"], field="Exit Fees"),
                "pnl": _scalar(row["PnL"], field="PnL"),
                "return": _scalar(row["Return"], field="Return"),
                "direction": direction,
                "status": status,
            }
        )

    position_rows = []
    portfolio_rows = []
    for timestamp in index:
        stamp = utc_timestamp(timestamp, field="portfolio timestamp")
        quantity = assets.loc[timestamp]
        market_value = asset_value.loc[timestamp]
        position_rows.append(
            {
                "timestamp": stamp,
                "instrument": instrument,
                "quantity": _scalar(quantity, field="asset quantity"),
                "market_price": _scalar(close.loc[timestamp], field="close"),
                "market_value": _scalar(market_value, field="asset value"),
            }
        )
        portfolio_rows.append(
            {
                "timestamp": stamp,
                "total_equity": _scalar(value.loc[timestamp], field="value"),
                "cash": _scalar(cash.loc[timestamp], field="cash"),
                "gross_exposure": _scalar(
                    abs(market_value),
                    field="gross exposure",
                ),
                "net_exposure": _scalar(market_value, field="net exposure"),
                "return": _scalar(returns.loc[timestamp], field="return"),
            }
        )

    payloads = (
        adapter_metadata_payload(base_currency),
        EngineExportPayload(
            VECTORBT_ORDERS_FILE,
            "orders",
            "text/csv",
            canonical_csv_bytes(VECTORBT_ORDERS_HEADERS, order_rows),
        ),
        EngineExportPayload(
            VECTORBT_TRADES_FILE,
            "trades",
            "text/csv",
            canonical_csv_bytes(VECTORBT_TRADES_HEADERS, trade_rows),
        ),
        EngineExportPayload(
            VECTORBT_POSITIONS_FILE,
            "positions",
            "text/csv",
            canonical_csv_bytes(VECTORBT_POSITIONS_HEADERS, position_rows),
        ),
        EngineExportPayload(
            VECTORBT_PORTFOLIO_FILE,
            "portfolio",
            "text/csv",
            canonical_csv_bytes(VECTORBT_PORTFOLIO_HEADERS, portfolio_rows),
        ),
    )
    return write_engine_export(
        run_id=run_id,
        engine=SupportedEngine.VECTORBT,
        engine_version=engine_version,
        export_format_id=VECTORBT_EXPORT_FORMAT_ID,
        declared_levels=VECTORBT_LEVELS,
        payloads=payloads,
        destination=destination,
        overwrite=overwrite,
    )
