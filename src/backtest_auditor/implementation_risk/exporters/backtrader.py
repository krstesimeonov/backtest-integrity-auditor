"""Backtrader lifecycle recorder and deterministic D2 file exporter.

Backtrader is imported only when ``create_backtrader_audit_analyzer`` is
called inside an engine environment.  Importing the auditor itself remains
free of a Backtrader runtime dependency.
"""

from __future__ import annotations

from datetime import timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    utc_timestamp,
    write_engine_export,
)


BACKTRADER_EXPORT_FORMAT_ID = "backtest-auditor.backtrader"
BACKTRADER_TESTED_VERSION = "1.9.78.123"
BACKTRADER_ORDERS_FILE = "backtrader-orders.csv"
BACKTRADER_FILLS_FILE = "backtrader-fills.csv"
BACKTRADER_POSITIONS_FILE = "position-snapshots.csv"
BACKTRADER_PORTFOLIO_FILE = "portfolio-series.csv"

BACKTRADER_ORDERS_HEADERS = (
    "order_ref",
    "created_timestamp",
    "submitted_timestamp",
    "last_updated_timestamp",
    "instrument",
    "side",
    "quantity",
    "order_type",
    "status",
    "parent_order_ref",
    "valid_timestamp",
    "limit_price",
    "stop_price",
)
BACKTRADER_FILLS_HEADERS = (
    "fill_id",
    "order_ref",
    "timestamp",
    "instrument",
    "side",
    "quantity",
    "price",
    "commission",
)
BACKTRADER_POSITIONS_HEADERS = (
    "timestamp",
    "instrument",
    "quantity",
    "market_price",
    "market_value",
)
BACKTRADER_PORTFOLIO_HEADERS = (
    "timestamp",
    "total_equity",
    "cash",
    "gross_exposure",
    "net_exposure",
)

BACKTRADER_LEVELS = (
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


def _positive_optional(value: object, *, field: str) -> str:
    scalar = _scalar(value, field=field)
    return "" if scalar == "0" else scalar


def create_backtrader_audit_analyzer(*, source_timezone: str) -> type[Any]:
    """Create an Analyzer class that records orders, fills, and portfolios.

    Backtrader datetimes are commonly timezone-naive.  The caller must name
    the source timezone explicitly; it is attached before conversion to UTC.
    """

    engine_version = installed_engine_version("backtrader")
    if engine_version != BACKTRADER_TESTED_VERSION:
        raise ValueError(
            "Backtrader analyzer was tested only with "
            f"{BACKTRADER_TESTED_VERSION}; installed version is {engine_version}."
        )
    try:
        source_zone = ZoneInfo(source_timezone)
    except (TypeError, ZoneInfoNotFoundError) as error:
        raise ValueError(
            "source_timezone must name an installed IANA timezone."
        ) from error

    try:
        import backtrader as bt
    except ImportError as error:  # pragma: no cover - guarded by metadata check
        raise ValueError(
            "backtrader must be installed in the exporter environment."
        ) from error

    class BacktestAuditorAnalyzer(bt.Analyzer):
        """Runtime-defined analyzer to keep Backtrader an optional dependency."""

        def start(self) -> None:
            if not self.strategy.broker.p.shortcash:
                raise ValueError(
                    "Backtrader broker shortcash=False makes getcash() debit "
                    "short sales, so it is not the account's cash balance; "
                    "the audit export does not support it."
                )
            self._audit_orders: dict[int, dict[str, str]] = {}
            self._audit_fills: dict[tuple[int, int], dict[str, str]] = {}
            self._audit_positions: list[dict[str, str]] = []
            self._audit_portfolio: list[dict[str, str]] = []

        @staticmethod
        def _instrument(data: Any) -> str:
            name = str(getattr(data, "_name", "")).strip()
            if not name:
                raise ValueError(
                    "every Backtrader data feed must have a non-empty name."
                )
            return name

        @staticmethod
        def _stored_in_utc(data: Any) -> bool:
            # Backtrader converts bars to UTC itself when told the input zone
            # (``tzinput``) or when a pandas index is tz-aware; otherwise it
            # stores the naive wall time it was given.
            if getattr(data, "_tzinput", None) is not None:
                return True
            frame = getattr(getattr(data, "p", None), "dataname", None)
            return getattr(getattr(frame, "index", None), "tz", None) is not None

        def _data_timestamp(self, data: Any, value: float) -> str:
            # ``bt.num2date`` without a zone returns the stored wall time; a
            # feed's or Cerebro's ``tz`` only changes how Backtrader displays
            # it, so neither may be read and then labelled source_timezone.
            stored = bt.num2date(value)
            zone = timezone.utc if self._stored_in_utc(data) else source_zone
            return utc_timestamp(
                stored.replace(tzinfo=zone),
                field="Backtrader datetime",
            )

        def _now_timestamp(self) -> str:
            return self._data_timestamp(self.strategy.data, self.strategy.datetime[0])

        def _commission(self, order: Any, execution: Any) -> float:
            # With int2pnl (the default) BackBroker adds the short interest it
            # has already debited from cash, day by day, to the closing part's
            # commission (bbroker._execute). Only the commission is a fill cost.
            comminfo = self.strategy.broker.getcommissioninfo(order.data)
            closed = (
                comminfo.getcommission(execution.closed, execution.price)
                if execution.closed
                else 0.0
            )
            return closed + execution.openedcomm

        def notify_order(self, order: Any) -> None:
            ref = int(order.ref)
            now = self._now_timestamp()
            current = self._audit_orders.get(ref)
            if current is None:
                created = self._data_timestamp(order.data, order.created.dt)
                order_name = str(order.getordername())
                created_price = getattr(order.created, "price", 0)
                price_limit = getattr(order.created, "pricelimit", 0)
                limit_price = ""
                stop_price = ""
                if order_name == "Limit":
                    limit_price = _positive_optional(
                        created_price,
                        field="Backtrader limit price",
                    )
                elif order_name == "Stop":
                    stop_price = _positive_optional(
                        created_price,
                        field="Backtrader stop price",
                    )
                elif order_name == "StopLimit":
                    stop_price = _positive_optional(
                        created_price,
                        field="Backtrader stop price",
                    )
                    limit_price = _positive_optional(
                        price_limit,
                        field="Backtrader limit price",
                    )
                parent = getattr(order, "parent", None)
                valid = getattr(order, "valid", None)
                current = {
                    "order_ref": str(ref),
                    "created_timestamp": created,
                    "submitted_timestamp": "",
                    "last_updated_timestamp": now,
                    "instrument": self._instrument(order.data),
                    "side": "Buy" if order.isbuy() else "Sell",
                    "quantity": _scalar(
                        abs(order.created.size),
                        field="Backtrader order size",
                    ),
                    "order_type": order_name,
                    "status": str(order.getstatusname()),
                    "parent_order_ref": (
                        "" if parent is None else str(int(parent.ref))
                    ),
                    "valid_timestamp": (
                        "" if valid is None else self._data_timestamp(order.data, valid)
                    ),
                    "limit_price": limit_price,
                    "stop_price": stop_price,
                }
                self._audit_orders[ref] = current
            status = str(order.getstatusname())
            current["status"] = status
            current["last_updated_timestamp"] = now
            if status == "Submitted" and current["submitted_timestamp"] == "":
                # The broker submits inside the next() that creates the order;
                # the notification only arrives with the next cycle, so "now"
                # is a bar late, and later than a cheat-on-close fill, which
                # Backtrader dates at the creation bar.
                current["submitted_timestamp"] = current["created_timestamp"]

            for index, execution in enumerate(order.executed.exbits):
                key = (ref, index)
                if key in self._audit_fills:
                    continue
                size = execution.size
                if size == 0:
                    continue
                self._audit_fills[key] = {
                    "fill_id": f"{ref}-{index + 1}",
                    "order_ref": str(ref),
                    "timestamp": self._data_timestamp(order.data, execution.dt),
                    "instrument": self._instrument(order.data),
                    "side": "Buy" if size > 0 else "Sell",
                    "quantity": _scalar(
                        abs(size),
                        field="Backtrader execution size",
                    ),
                    "price": _scalar(
                        execution.price,
                        field="Backtrader execution price",
                    ),
                    "commission": _scalar(
                        self._commission(order, execution),
                        field="Backtrader execution commission",
                    ),
                }

        def next(self) -> None:
            timestamp = self._now_timestamp()
            gross_exposure = 0.0
            net_exposure = 0.0
            for data in sorted(self.strategy.datas, key=self._instrument):
                instrument = self._instrument(data)
                position = self.strategy.getposition(data)
                quantity = position.size
                market_price = data.close[0]
                multiplier = self.strategy.broker.getcommissioninfo(data).p.mult
                market_value = quantity * market_price * multiplier
                gross_exposure += abs(float(market_value))
                net_exposure += float(market_value)
                self._audit_positions.append(
                    {
                        "timestamp": timestamp,
                        "instrument": instrument,
                        "quantity": _scalar(
                            quantity,
                            field="Backtrader position size",
                        ),
                        "market_price": _scalar(
                            market_price,
                            field="Backtrader close",
                        ),
                        "market_value": _scalar(
                            market_value,
                            field="Backtrader market value",
                        ),
                    }
                )
            self._audit_portfolio.append(
                {
                    "timestamp": timestamp,
                    "total_equity": _scalar(
                        self.strategy.broker.getvalue(),
                        field="Backtrader broker value",
                    ),
                    "cash": _scalar(
                        self.strategy.broker.getcash(),
                        field="Backtrader broker cash",
                    ),
                    "gross_exposure": _scalar(
                        gross_exposure,
                        field="Backtrader gross exposure",
                    ),
                    "net_exposure": _scalar(
                        net_exposure,
                        field="Backtrader net exposure",
                    ),
                }
            )

        def get_analysis(self) -> dict[str, object]:
            return {
                "engine_version": engine_version,
                "orders": tuple(
                    self._audit_orders[key] for key in sorted(self._audit_orders)
                ),
                "fills": tuple(
                    self._audit_fills[key] for key in sorted(self._audit_fills)
                ),
                "positions": tuple(
                    sorted(
                        self._audit_positions,
                        key=lambda row: (row["timestamp"], row["instrument"]),
                    )
                ),
                "portfolio": tuple(
                    sorted(self._audit_portfolio, key=lambda row: row["timestamp"])
                ),
            }

    return BacktestAuditorAnalyzer


def _analysis_rows(
    analysis: dict[str, object],
    key: str,
    headers: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    value = analysis.get(key)
    if not isinstance(value, tuple):
        raise ValueError(f"Backtrader analysis {key!r} must be a tuple.")
    rows: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != set(headers):
            raise ValueError(
                f"Backtrader analysis {key!r} rows do not match the D2 contract."
            )
        if any(not isinstance(item, str) for item in row.values()):
            raise ValueError(f"Backtrader analysis {key!r} values must be strings.")
        rows.append(dict(row))
    return tuple(rows)


def export_backtrader_analysis(
    analyzer: Any,
    destination: str | Path,
    *,
    run_id: str,
    base_currency: str,
    overwrite: bool = False,
) -> Path:
    """Write the output of the D2 Backtrader audit analyzer."""

    if not hasattr(analyzer, "get_analysis"):
        raise ValueError("analyzer must expose get_analysis().")
    analysis = analyzer.get_analysis()
    if not isinstance(analysis, dict):
        raise ValueError("Backtrader analyzer result must be a dictionary.")
    engine_version = analysis.get("engine_version")
    if engine_version != BACKTRADER_TESTED_VERSION:
        raise ValueError("Backtrader analyzer version does not match D2.")
    orders = _analysis_rows(analysis, "orders", BACKTRADER_ORDERS_HEADERS)
    fills = _analysis_rows(analysis, "fills", BACKTRADER_FILLS_HEADERS)
    positions = _analysis_rows(
        analysis,
        "positions",
        BACKTRADER_POSITIONS_HEADERS,
    )
    portfolio = _analysis_rows(
        analysis,
        "portfolio",
        BACKTRADER_PORTFOLIO_HEADERS,
    )
    if not portfolio:
        raise ValueError("Backtrader analysis must contain portfolio snapshots.")

    payloads = (
        adapter_metadata_payload(base_currency),
        EngineExportPayload(
            BACKTRADER_ORDERS_FILE,
            "orders",
            "text/csv",
            canonical_csv_bytes(BACKTRADER_ORDERS_HEADERS, orders),
        ),
        EngineExportPayload(
            BACKTRADER_FILLS_FILE,
            "fills",
            "text/csv",
            canonical_csv_bytes(BACKTRADER_FILLS_HEADERS, fills),
        ),
        EngineExportPayload(
            BACKTRADER_POSITIONS_FILE,
            "positions",
            "text/csv",
            canonical_csv_bytes(BACKTRADER_POSITIONS_HEADERS, positions),
        ),
        EngineExportPayload(
            BACKTRADER_PORTFOLIO_FILE,
            "portfolio",
            "text/csv",
            canonical_csv_bytes(BACKTRADER_PORTFOLIO_HEADERS, portfolio),
        ),
    )
    return write_engine_export(
        run_id=run_id,
        engine=SupportedEngine.BACKTRADER,
        engine_version=engine_version,
        export_format_id=BACKTRADER_EXPORT_FORMAT_ID,
        declared_levels=BACKTRADER_LEVELS,
        payloads=payloads,
        destination=destination,
        overwrite=overwrite,
    )
