"""Deterministic exporter for completed QuantConnect LEAN local results.

The exporter reads the two files written by LEAN after a local backtest.  It
does not start LEAN, import a .NET bridge, or infer evidence absent from those
files.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

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
    utc_timestamp,
    write_engine_export,
)


QUANTCONNECT_LEAN_EXPORT_FORMAT_ID = "backtest-auditor.quantconnect-lean"
QUANTCONNECT_LEAN_TESTED_VERSION = "2.5.17999"
QUANTCONNECT_LEAN_ORDERS_FILE = "lean-orders.csv"
QUANTCONNECT_LEAN_FILLS_FILE = "lean-fills.csv"
QUANTCONNECT_LEAN_PORTFOLIO_FILE = "portfolio-series.csv"

QUANTCONNECT_LEAN_ORDERS_HEADERS = (
    "order_id",
    "instrument",
    "created_at",
    "last_updated_at",
    "quantity",
    "side",
    "type",
    "time_in_force",
    "status",
    "limit_price",
    "stop_price",
)
QUANTCONNECT_LEAN_FILLS_HEADERS = (
    "fill_id",
    "order_id",
    "instrument",
    "timestamp",
    "side",
    "quantity",
    "price",
    "currency",
    "fee_amount",
    "fee_currency",
)
QUANTCONNECT_LEAN_PORTFOLIO_HEADERS = (
    "timestamp",
    "total_equity",
)

QUANTCONNECT_LEAN_LEVELS = (
    ComparisonLevel.ORDER,
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)

_ORDER_TYPES = {
    0: "Market",
    1: "Limit",
    2: "StopMarket",
    3: "StopLimit",
    4: "MarketOnOpen",
    5: "MarketOnClose",
    6: "OptionExercise",
    7: "LimitIfTouched",
    8: "ComboMarket",
    9: "ComboLimit",
    10: "ComboLegLimit",
    11: "TrailingStop",
}
_ORDER_STATUSES = {
    0: "New",
    1: "Submitted",
    2: "PartiallyFilled",
    3: "Filled",
    5: "Canceled",
    6: "None",
    7: "Invalid",
    8: "CancelPending",
    9: "UpdateSubmitted",
}
_ORDER_DIRECTIONS = {0: "Buy", 1: "Sell", 2: "Hold"}


def _invalid(message: str) -> NoReturn:
    raise ValueError(f"invalid QuantConnect LEAN result: {message}")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _invalid(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _nonfinite(value: str) -> NoReturn:
    _invalid(f"non-finite JSON number {value!r}")


def _load_json(path: str | Path, *, field: str) -> object:
    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as error:
        raise ValueError(f"{field} could not be read.") from error
    if len(data) > 64 * 1024 * 1024:
        raise ValueError(f"{field} exceeds the 64 MiB exporter limit.")
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_nonfinite,
            parse_float=Decimal,
            parse_int=Decimal,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field} must be valid UTF-8 JSON.") from error


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be a JSON object.")
    return value


def _pick(
    value: Mapping[str, Any],
    *names: str,
    field: str,
    required: bool = True,
) -> Any:
    present = [name for name in names if name in value]
    if len(present) > 1:
        raise ValueError(f"{field} is ambiguous.")
    if not present:
        if required:
            raise ValueError(f"{field} is missing.")
        return None
    return value[present[0]]


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text.")
    return value.strip()


def _timestamp(value: object, *, field: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field} must not be a boolean.")
    if isinstance(value, (int, float, Decimal)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError(f"{field} is not a valid Unix timestamp.") from error
        return utc_timestamp(parsed, field=field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 or Unix timestamp.")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{field} is not a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must disclose its UTC offset.")
    return utc_timestamp(parsed, field=field)


def _decimal(value: object, *, field: str, positive: bool = False) -> str:
    try:
        normalized = Decimal(canonical_decimal(value))
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error
    if positive and normalized <= 0:
        raise ValueError(f"{field} must be positive.")
    return canonical_decimal(normalized)


def _optional_decimal(value: object, *, field: str) -> str:
    if value is None or value == "":
        return ""
    return _decimal(value, field=field)


def _enum(
    value: object,
    numeric: Mapping[int, str],
    *,
    field: str,
) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field} is invalid.")
    if isinstance(value, Decimal) and value == value.to_integral_value():
        value = int(value)
    if isinstance(value, int):
        if value not in numeric:
            raise ValueError(f"{field} numeric value is unsupported.")
        return numeric[value]
    text = _text(value, field=field)
    for candidate in numeric.values():
        if text.casefold() == candidate.casefold():
            return candidate
    raise ValueError(f"{field} value is unsupported.")


def _instrument(value: object, *, field: str) -> str:
    if isinstance(value, str):
        return _text(value, field=field)
    symbol = _mapping(value, field=field)
    return _text(
        _pick(symbol, "value", "Value", field=f"{field}.value"),
        field=field,
    )


def _time_in_force(order: Mapping[str, Any]) -> str:
    properties = _pick(
        order,
        "properties",
        "Properties",
        field="order.properties",
        required=False,
    )
    if properties is None:
        return "Custom"
    values = _mapping(properties, field="order.properties")
    raw = _pick(
        values,
        "timeInForce",
        "TimeInForce",
        "$type",
        field="order.properties.timeInForce",
        required=False,
    )
    if raw is None:
        return "Custom"
    if isinstance(raw, Mapping):
        # LEAN 2.5 serializes TimeInForce as an object: {"$type": "...Day..."}
        # for every kind except GoodTilCanceled, which its converter writes as
        # {} because that is its reader's default (TimeInForceJsonConverter).
        type_name = raw.get("$type")
        if type_name is None:
            return "GTC" if not raw else "Custom"
        raw = type_name
    name = _text(raw, field="order.properties.timeInForce")
    folded = name.casefold()
    if "goodtilcanceled" in folded or folded in {"gtc", "good_til_canceled"}:
        return "GTC"
    if "immediateorcancel" in folded or folded == "ioc":
        return "IOC"
    if "day" in folded:
        return "Day"
    return "Custom"


def _event_id(value: object) -> str:
    """An order event's identity.

    LEAN 2.5's SerializedOrderEvent.Id is text,
    ``"<algorithmId>-<orderId>-<orderEventId>"``; numeric identities keep
    their canonical decimal spelling.
    """

    if isinstance(value, str):
        return _text(value, field="order event id")
    return _decimal(value, field="order event id")


def _order_time(order: Mapping[str, Any]) -> str:
    """The order's creation instant.

    LEAN 2.5 serializes ``time`` and also ``createdTime``, which is an alias of
    the same property (``Order.CreatedTime => Time``), so every real result
    carries both. Equal values are one fact; different values stay ambiguous.
    """

    present = [name for name in ("time", "Time", "createdTime") if name in order]
    if not present:
        raise ValueError("order time is missing.")
    instants = {_timestamp(order[name], field="order time") for name in present}
    if len(instants) > 1:
        raise ValueError("order time is ambiguous.")
    return instants.pop()


def _order_last_update(order: Mapping[str, Any]) -> str:
    """The latest lifecycle instant LEAN recorded for an order.

    LEAN omits ``lastUpdateTime`` for an order that was never updated but
    writes ``lastFillTime`` (and ``canceledTime``), so a filled order is last
    updated at its fill, not at its creation.
    """

    instants = [
        _timestamp(order[name], field=f"order {name}")
        for name in (
            "lastUpdateTime",
            "LastUpdateTime",
            "lastFillTime",
            "LastFillTime",
            "canceledTime",
            "CanceledTime",
        )
        if order.get(name) not in (None, "")
    ]
    return max(instants, default="")


def _results_root(value: object) -> Mapping[str, Any]:
    root = _mapping(value, field="result file")
    nested = _pick(
        root,
        "results",
        "Results",
        field="results",
        required=False,
    )
    return root if nested is None else _mapping(nested, field="results")


def _orders(value: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = _pick(value, "orders", "Orders", field="orders")
    if isinstance(raw, Mapping):
        ordered = sorted(raw.items(), key=lambda item: str(item[0]))
        return tuple(_mapping(item, field="order") for _, item in ordered)
    if isinstance(raw, list):
        return tuple(_mapping(item, field="order") for item in raw)
    raise ValueError("orders must be a JSON object or array.")


def _order_events(value: object) -> tuple[Mapping[str, Any], ...]:
    raw: object = value
    if isinstance(raw, Mapping):
        nested = _pick(
            raw,
            "orderEvents",
            "OrderEvents",
            field="orderEvents",
            required=False,
        )
        if nested is not None:
            raw = nested
        elif all(isinstance(item, list) for item in raw.values()):
            raw = [item for key in sorted(raw, key=str) for item in raw[key]]
    if not isinstance(raw, list):
        raise ValueError("order-events file must contain a JSON array.")
    return tuple(_mapping(item, field="order event") for item in raw)


def _fee(event: Mapping[str, Any]) -> tuple[str, str]:
    flat_amount = _pick(
        event,
        "orderFeeAmount",
        "OrderFeeAmount",
        field="order event fee amount",
        required=False,
    )
    flat_currency = _pick(
        event,
        "orderFeeCurrency",
        "OrderFeeCurrency",
        field="order event fee currency",
        required=False,
    )
    if flat_amount is not None:
        return (
            _decimal(flat_amount, field="order event fee amount"),
            _text(flat_currency, field="order event fee currency"),
        )
    order_fee = _pick(
        event,
        "orderFee",
        "OrderFee",
        field="order event fee",
        required=False,
    )
    if order_fee is None:
        return "0", ""
    fee_object = _mapping(order_fee, field="order event fee")
    cash = _pick(
        fee_object,
        "value",
        "Value",
        field="order event fee value",
        required=False,
    )
    if cash is None:
        return "0", ""
    cash_object = _mapping(cash, field="order event fee value")
    amount = _pick(cash_object, "amount", "Amount", field="fee amount")
    currency = _pick(cash_object, "currency", "Currency", field="fee currency")
    return _decimal(amount, field="fee amount"), _text(currency, field="fee currency")


def _equity_point(value: object, *, index: int) -> tuple[object, object]:
    """One Strategy Equity value as ``(time, equity)``.

    LEAN 2.5 samples equity into a CandlestickSeries and writes each point as
    ``[time, open, high, low, close]`` (CandlestickJsonConverter); the equity
    at the sample time is the close. ChartPoint series are written as
    ``[time, value]``; ``{"x", "y"}`` objects are the older ChartPoint form.
    """

    if isinstance(value, list):
        if len(value) == 5:
            return value[0], value[4]
        if len(value) == 2:
            return value[0], value[1]
        raise ValueError(
            f"equity point {index} must be [time, value] or "
            "[time, open, high, low, close]."
        )
    point = _mapping(value, field=f"equity point {index}")
    return (
        _pick(point, "x", "X", field="equity point x"),
        _pick(point, "y", "Y", field="equity point y"),
    )


def _equity_points(results: Mapping[str, Any]) -> list[dict[str, str]]:
    charts = _mapping(
        _pick(results, "charts", "Charts", field="charts"),
        field="charts",
    )
    strategy = _mapping(
        _pick(
            charts,
            "Strategy Equity",
            field="charts.Strategy Equity",
        ),
        field="charts.Strategy Equity",
    )
    series = _mapping(
        _pick(strategy, "series", "Series", field="Strategy Equity.series"),
        field="Strategy Equity.series",
    )
    equity = _mapping(
        _pick(series, "Equity", field="Strategy Equity.Equity"),
        field="Strategy Equity.Equity",
    )
    raw_values = _pick(equity, "values", "Values", field="Equity.values")
    if not isinstance(raw_values, list) or not raw_values:
        raise ValueError("Strategy Equity / Equity must contain at least one point.")
    rows: list[dict[str, str]] = []
    for index, point_value in enumerate(raw_values, start=1):
        time_value, equity_value = _equity_point(point_value, index=index)
        rows.append(
            {
                "timestamp": _timestamp(time_value, field="equity point x"),
                "total_equity": _decimal(equity_value, field="equity point y"),
            }
        )
    rows.sort(key=lambda row: row["timestamp"])
    timestamps = [row["timestamp"] for row in rows]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("Strategy Equity timestamps must be unique.")
    return rows


def export_quantconnect_lean_results(
    result_file: str | Path,
    order_events_file: str | Path,
    destination: str | Path,
    *,
    run_id: str,
    base_currency: str,
    engine_version: str,
    overwrite: bool = False,
) -> Path:
    """Export completed official LEAN local result files.

    ``engine_version`` is producer-declared because LEAN's result JSON does not
    include the NuGet package version.  Only the exact conformance-tested
    version is accepted.
    """

    if engine_version != QUANTCONNECT_LEAN_TESTED_VERSION:
        raise ValueError(
            "QuantConnect LEAN exporter was tested only with "
            f"{QUANTCONNECT_LEAN_TESTED_VERSION}; declared version is "
            f"{engine_version}."
        )
    results = _results_root(_load_json(result_file, field="result_file"))
    raw_orders = _orders(results)
    raw_events = _order_events(_load_json(order_events_file, field="order_events_file"))

    order_rows: list[dict[str, str]] = []
    order_instruments: dict[str, str] = {}
    for index, order in enumerate(raw_orders, start=1):
        raw_id = _pick(order, "id", "Id", field=f"order {index} id")
        order_id = _decimal(raw_id, field=f"order {index} id")
        if Decimal(order_id) != Decimal(order_id).to_integral_value():
            raise ValueError(f"order {index} id must be an integer.")
        instrument = _instrument(
            _pick(order, "symbol", "Symbol", field=f"order {index} symbol"),
            field=f"order {index} symbol",
        )
        quantity = Decimal(
            _decimal(
                _pick(order, "quantity", "Quantity", field="order quantity"),
                field="order quantity",
            )
        )
        if quantity == 0:
            raise ValueError("LEAN orders must have non-zero quantity.")
        direction = _pick(
            order,
            "direction",
            "Direction",
            field="order direction",
            required=False,
        )
        side = (
            _enum(direction, _ORDER_DIRECTIONS, field="order direction")
            if direction is not None
            else ("Buy" if quantity > 0 else "Sell")
        )
        created = _order_time(order)
        order_rows.append(
            {
                "order_id": order_id,
                "instrument": instrument,
                "created_at": created,
                "last_updated_at": _order_last_update(order),
                "quantity": canonical_decimal(quantity.copy_abs()),
                "side": side,
                "type": _enum(
                    _pick(order, "type", "Type", field="order type"),
                    _ORDER_TYPES,
                    field="order type",
                ),
                "time_in_force": _time_in_force(order),
                "status": _enum(
                    _pick(order, "status", "Status", field="order status"),
                    _ORDER_STATUSES,
                    field="order status",
                ),
                "limit_price": _optional_decimal(
                    _pick(
                        order,
                        "limitPrice",
                        "LimitPrice",
                        field="order limit price",
                        required=False,
                    ),
                    field="order limit price",
                ),
                "stop_price": _optional_decimal(
                    _pick(
                        order,
                        "stopPrice",
                        "StopPrice",
                        field="order stop price",
                        required=False,
                    ),
                    field="order stop price",
                ),
            }
        )
        if order_id in order_instruments:
            raise ValueError("LEAN order IDs must be unique.")
        order_instruments[order_id] = instrument
    order_rows.sort(key=lambda row: (row["created_at"], row["order_id"]))

    fill_rows: list[dict[str, str]] = []
    sequence_by_order: dict[str, int] = {}
    for index, event in enumerate(raw_events, start=1):
        raw_quantity = Decimal(
            _decimal(
                _pick(
                    event,
                    "fillQuantity",
                    "FillQuantity",
                    field=f"order event {index} fillQuantity",
                ),
                field=f"order event {index} fillQuantity",
            )
        )
        if raw_quantity == 0:
            continue
        order_id = _decimal(
            _pick(event, "orderId", "OrderId", field="order event orderId"),
            field="order event orderId",
        )
        if order_id not in order_instruments:
            raise ValueError("a fill event references an unknown LEAN order.")
        sequence_by_order[order_id] = sequence_by_order.get(order_id, 0) + 1
        event_id = _pick(
            event,
            "id",
            "Id",
            field="order event id",
            required=False,
        )
        fill_id = (
            _event_id(event_id)
            if event_id is not None
            else f"{order_id}-{sequence_by_order[order_id]:08d}"
        )
        direction = _pick(
            event,
            "direction",
            "Direction",
            field="order event direction",
            required=False,
        )
        side = (
            _enum(direction, _ORDER_DIRECTIONS, field="order event direction")
            if direction is not None
            else ("Buy" if raw_quantity > 0 else "Sell")
        )
        event_currency = _pick(
            event,
            "fillPriceCurrency",
            "FillPriceCurrency",
            field="order event fillPriceCurrency",
            required=False,
        )
        currency = (
            base_currency
            if event_currency in {None, ""}
            else _text(event_currency, field="order event fillPriceCurrency")
        )
        fee_amount, fee_currency = _fee(event)
        if Decimal(fee_amount) != 0 and not fee_currency:
            raise ValueError("a non-zero LEAN order fee must disclose its currency.")
        fill_rows.append(
            {
                "fill_id": fill_id,
                "order_id": order_id,
                "instrument": order_instruments[order_id],
                "timestamp": _timestamp(
                    _pick(
                        event,
                        "utcTime",
                        "UtcTime",
                        "time",
                        "Time",
                        field="order event time",
                    ),
                    field="order event time",
                ),
                "side": side,
                "quantity": canonical_decimal(raw_quantity.copy_abs()),
                "price": _decimal(
                    _pick(
                        event,
                        "fillPrice",
                        "FillPrice",
                        field="order event fillPrice",
                    ),
                    field="order event fillPrice",
                    positive=True,
                ),
                "currency": currency,
                # Signed as LEAN reports it: positive is a charge, negative a
                # rebate that LEAN credits to cash (OrderFee.ApplyToPortfolio).
                "fee_amount": fee_amount,
                "fee_currency": fee_currency,
            }
        )
    fill_rows.sort(key=lambda row: (row["timestamp"], row["fill_id"]))
    fill_ids = [row["fill_id"] for row in fill_rows]
    if len(fill_ids) != len(set(fill_ids)):
        raise ValueError("LEAN fill IDs must be unique.")

    portfolio_rows = _equity_points(results)
    payloads = (
        adapter_metadata_payload(base_currency),
        EngineExportPayload(
            QUANTCONNECT_LEAN_ORDERS_FILE,
            "orders",
            "text/csv",
            canonical_csv_bytes(QUANTCONNECT_LEAN_ORDERS_HEADERS, order_rows),
        ),
        EngineExportPayload(
            QUANTCONNECT_LEAN_FILLS_FILE,
            "fills",
            "text/csv",
            canonical_csv_bytes(QUANTCONNECT_LEAN_FILLS_HEADERS, fill_rows),
        ),
        EngineExportPayload(
            QUANTCONNECT_LEAN_PORTFOLIO_FILE,
            "portfolio",
            "text/csv",
            canonical_csv_bytes(
                QUANTCONNECT_LEAN_PORTFOLIO_HEADERS,
                portfolio_rows,
            ),
        ),
    )
    return write_engine_export(
        run_id=run_id,
        engine=SupportedEngine.QUANTCONNECT_LEAN,
        engine_version=engine_version,
        export_format_id=QUANTCONNECT_LEAN_EXPORT_FORMAT_ID,
        declared_levels=QUANTCONNECT_LEAN_LEVELS,
        payloads=payloads,
        destination=destination,
        overwrite=overwrite,
    )


__all__ = ["export_quantconnect_lean_results"]
