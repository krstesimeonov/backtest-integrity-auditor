"""N13 follow-up (1.5.2): sums and sign changes of canonical decimals are exact.

Keeping every supplied digit in normalize_decimal (8fade30) exposed arithmetic
that still rounded to the default 28 digits: the bundle's fill-chain check
summed fill quantities with ``+=``, so a FILLED order of a 30-digit quantity was
rejected as "fills exceed order quantity" (1.5.1 accepted it after silently
rounding both sides), and the Lean and NautilusTrader adapters rounded the
position quantities they accumulate or negate. Found by the W2-J6 adversarial
review; each test fails on 8fade30 and passes on the fix.
"""

from __future__ import annotations

import csv
import dataclasses
import io
from decimal import Decimal, DefaultContext

import pytest

from .test_v15_bundle_and_adapters import (
    _adapt,
    _rich_bundle,
    bt_case,
    lean_case,
    nautilus_case,
)

from backtest_auditor.implementation_risk.domain.validation import (
    exact_add,
    normalize_decimal,
)

Q = Decimal("123456789012.123456789012345678")  # 30 significant digits
PART = Decimal(
    "61728394506.061728394506172839"
)  # Q = PART + PART exactly; 29 digits each


def _single_fill_order(bundle):
    fills_by_order: dict[str, list] = {}
    for fill in bundle.fills:
        fills_by_order.setdefault(fill.order_id, []).append(fill)
    order = next(
        o
        for o in bundle.orders
        if o.status.name == "FILLED" and len(fills_by_order.get(o.order_id, [])) == 1
    )
    return order, fills_by_order[order.order_id][0]


def _with_quantities(bundle, order, fill, order_quantity, fill_quantities):
    """The bundle with `order` set to `order_quantity`, filled by fills of
    `fill_quantities` (the first replaces `fill`, the rest are added copies)."""

    orders = tuple(
        dataclasses.replace(o, quantity=order_quantity) if o is order else o
        for o in bundle.orders
    )
    extra = tuple(
        dataclasses.replace(fill, fill_id=f"{fill.fill_id}-part{index}", quantity=q)
        for index, q in enumerate(fill_quantities[1:], start=2)
    )
    fills = (
        tuple(
            dataclasses.replace(f, quantity=fill_quantities[0]) if f is fill else f
            for f in bundle.fills
        )
        + extra
    )
    # the bundle requires fills in canonical (timestamp, fill_id) order
    fills = tuple(sorted(fills, key=lambda item: (item.timestamp, item.fill_id)))
    return dataclasses.replace(bundle, orders=orders, fills=fills)


def test_a_30_digit_order_filled_by_one_fill_is_accepted_exactly():
    bundle = _rich_bundle(engine_version="1.0")
    order, fill = _single_fill_order(bundle)
    accepted = _with_quantities(bundle, order, fill, Q, [Q])
    stored = next(o for o in accepted.orders if o.order_id == order.order_id)
    assert stored.quantity == Q and str(stored.quantity) == str(Q)


def test_a_30_digit_order_filled_by_split_fills_is_accepted():
    bundle = _rich_bundle(engine_version="1.0")
    order, fill = _single_fill_order(bundle)
    # PART + PART in the default context rounds to 28 digits; exactly it is Q.
    assert PART + PART != Q and exact_add(PART, PART) == Q
    accepted = _with_quantities(bundle, order, fill, Q, [PART, PART])
    filled = [f.quantity for f in accepted.fills if f.order_id == order.order_id]
    assert filled == [PART, PART]


def test_an_overfill_in_the_30th_digit_is_still_rejected():
    bundle = _rich_bundle(engine_version="1.0")
    order, fill = _single_fill_order(bundle)
    with pytest.raises(ValueError, match="fills exceed order quantity"):
        _with_quantities(bundle, order, fill, Q, [Q + Decimal("1E-18")])


def test_the_lean_adapter_maps_a_30_digit_filled_order_and_position_exactly(tmp_path):
    case = lean_case()
    fills = [row for row in case.payloads["lean-fills.csv"].rows if row[0] != "12"]
    fills[0] = (*fills[0][:5], str(Q), *fills[0][6:])
    orders = list(case.payloads["lean-orders.csv"].rows)
    orders[0] = (*orders[0][:4], str(Q), *orders[0][5:])
    payloads = dict(case.payloads)
    payloads["lean-fills.csv"] = dataclasses.replace(
        case.payloads["lean-fills.csv"], rows=tuple(fills)
    )
    payloads["lean-orders.csv"] = dataclasses.replace(
        case.payloads["lean-orders.csv"], rows=tuple(orders)
    )
    _envelope, result = _adapt(tmp_path, dataclasses.replace(case, payloads=payloads))
    assert result.artifacts.orders[0].quantity == Q
    assert result.artifacts.positions[0].quantity == Q


def test_the_nautilus_adapter_keeps_a_30_digit_short_position_exact(tmp_path):
    case = nautilus_case()
    name = next(path for path in case.payloads if "position" in path)
    payload = case.payloads[name]
    rows = [list(row) for row in payload.rows]
    side = payload.headers.index("side")
    target = next(i for i, row in enumerate(rows) if row[side] == "SHORT")
    for column in ("quantity", "peak_quantity"):
        rows[target][payload.headers.index(column)] = str(Q)
    payloads = dict(case.payloads)
    payloads[name] = dataclasses.replace(payload, rows=tuple(tuple(r) for r in rows))
    _envelope, result = _adapt(tmp_path, dataclasses.replace(case, payloads=payloads))
    quantities = [p.quantity for p in result.artifacts.positions]
    # -Q would round to 28 digits in the default context; copy_negate does not.
    assert Q.copy_negate() in quantities, [str(q) for q in quantities]


def test_short_values_normalize_exactly_as_in_the_default_context():
    """Up to 28 digits normalize_decimal is DefaultContext.normalize, exponent
    limits included: 1E-1000000 stays a subnormal value, as in 1.5.1."""

    for text in ("1E-1000000", "1.2300", "100", "-0.000", "9" * 28, "0.0000001"):
        assert (
            normalize_decimal(text, field="value")
            == Decimal(text).normalize(DefaultContext)
            or Decimal(text) == 0
        )
    assert str(normalize_decimal("1E-1000000", field="value")) == "1E-1000000"


def test_exact_add_does_not_round_to_the_callers_precision():
    bigger = exact_add(Q, Decimal("1E-30"))
    assert str(bigger) == "123456789012.123456789012345678000000000001"
    assert exact_add(bigger, Decimal("-1E-30")) == Q
    assert str(exact_add(Q, Decimal(0))) == str(Q)
    assert str(exact_add(Q.copy_negate(), Q)) == "0E-18"


# Second follow-up (W2-J6, third review): abs() and unary minus also round to
# the context's 28 digits; copy_abs / copy_negate do not. And exact_add is
# bounded: a sum needing more than 100 significant digits is rejected.

FEE = Decimal(
    "1234567890.12345678901234567891"
)  # 30 significant digits, no trailing zero


def _replace_rows(case, key, edit):
    payload = case.payloads[key]
    rows = [list(row) for row in payload.rows]
    edit(payload.headers, rows)
    payloads = dict(case.payloads)
    payloads[key] = dataclasses.replace(payload, rows=tuple(tuple(r) for r in rows))
    return dataclasses.replace(case, payloads=payloads)


def test_the_bt_adapter_keeps_30_digit_buy_and_sell_quantities_exact(tmp_path):
    def edit(headers, rows):
        quantity = headers.index("quantity")
        rows[0][quantity] = str(Q + 10)  # a BUY
        rows[2][quantity] = "-" + str(Q)  # a SELL

    case = _replace_rows(bt_case(), "bt-transactions.csv", edit)
    _envelope, result = _adapt(tmp_path, case)
    fills = {str(f.quantity) for f in result.artifacts.fills}
    orders = {str(o.quantity) for o in result.artifacts.orders}
    assert {str(Q), str(Q + 10)} <= fills and {str(Q), str(Q + 10)} <= orders


@pytest.mark.parametrize(
    ("factory", "key"),
    [(lean_case, "lean-fills.csv"), (nautilus_case, None)],
    ids=["lean", "nautilus"],
)
def test_a_30_digit_fee_becomes_an_exact_negative_cost(tmp_path, factory, key):
    case = factory()
    key = key or next(path for path in case.payloads if "fill" in path)

    def edit(headers, rows):
        rows[0][headers.index("fee_amount")] = str(FEE)

    _envelope, result = _adapt(tmp_path, _replace_rows(case, key, edit))
    impacts = {str(c.pnl_impact) for c in result.artifacts.costs}
    assert str(FEE.copy_negate()) in impacts, impacts


def test_the_lean_exporter_keeps_30_digit_quantities_and_fees(tmp_path):
    from backtest_auditor.implementation_risk.exporters.quantconnect_lean import (
        QUANTCONNECT_LEAN_TESTED_VERSION,
        export_quantconnect_lean_results,
    )

    result = (
        '{"Orders": {"1": {"id": 1, "symbol": {"value": "AAPL"}, '
        '"time": "2026-01-02T14:30:00Z", "lastUpdateTime": "2026-01-02T14:31:00Z", '
        f'"quantity": -{Q}, "direction": 1, "type": 0, "status": 3, '
        '"properties": {"timeInForce": "DayTimeInForce"}}}, '
        '"Charts": {"Strategy Equity": {"Series": {"Equity": {"Values": '
        '[{"x": 1767364200, "y": 1000}, {"x": 1767450600, "y": 1020}]}}}}}'
    )
    events = (
        '[{"id": 11, "orderId": 1, "utcTime": "2026-01-02T14:31:00Z", "status": 3, '
        f'"direction": 1, "fillPrice": 100, "fillPriceCurrency": "USD", "fillQuantity": -{Q}, '
        f'"orderFeeAmount": -{FEE}, "orderFeeCurrency": "USD"}}]'
    )
    (tmp_path / "result.json").write_text(result, encoding="utf-8")
    (tmp_path / "events.json").write_text(events, encoding="utf-8")
    directory = export_quantconnect_lean_results(
        tmp_path / "result.json",
        tmp_path / "events.json",
        tmp_path / "export",
        run_id="lean-30-digits",
        base_currency="USD",
        engine_version=QUANTCONNECT_LEAN_TESTED_VERSION,
    )
    exported = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(directory.rglob("*.csv"))
    )
    # The fee keeps LEAN's sign since wave3/adapter-e2e (0a6ad5e: a negative
    # orderFeeAmount is a rebate); this test pins its 30 digits.
    assert f",{Q}," in exported and f",-{FEE}," in exported
    # Each file on its own (W5-J1 adversarial finding 4): the joined text above
    # still held Q from the fills when the orders row was rounded.
    tables = {
        path.name: list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
        for path in directory.rglob("*.csv")
    }
    assert [row["quantity"] for row in tables["lean-orders.csv"]] == [str(Q)]
    assert [row["quantity"] for row in tables["lean-fills.csv"]] == [str(Q)]
    assert [row["fee_amount"] for row in tables["lean-fills.csv"]] == [f"-{FEE}"]


def test_exact_add_rejects_rather_than_rounds_a_sum_wider_than_100_digits():
    exact = exact_add(Decimal("1E+49"), Decimal("1E-50"))  # exactly 100 digits
    assert str(exact) == "1" + "0" * 49 + "." + "0" * 49 + "1"
    with pytest.raises(ValueError, match="rejected rather than rounded"):
        exact_add(Decimal("1E+60"), Decimal("1E-60"))


def test_a_bundle_whose_fill_sum_needs_more_than_100_digits_is_rejected():
    bundle = _rich_bundle(engine_version="1.0")
    order, fill = _single_fill_order(bundle)
    with pytest.raises(ValueError, match="rejected rather than rounded"):
        _with_quantities(
            bundle, order, fill, Decimal("1E+60"), [Decimal("1E+60"), Decimal("1E-60")]
        )
