"""N14 (1.5.2): a header mismatch says which column is missing or unexpected.

The adversarial suite checks the engine adapters (one shared reader for all
five engines). The canonical bundle's own CSV readers raised the same unnamed
"CSV header does not match" error and are covered here, with the helper both
use.
"""

import pytest

from backtest_auditor.implementation_risk.adapters.csv_contracts import (
    EQUITY,
    TRADE_FILLS_HEADERS,
    decode_csv,
    decode_trade_fills,
)
from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
    describe_name_difference,
)


def _header(names) -> bytes:
    return (",".join(names) + "\n").encode("utf-8")


@pytest.mark.parametrize("column", EQUITY.headers)
def test_bundle_csv_missing_column_is_named(column):
    supplied = [name for name in EQUITY.headers if name != column]
    with pytest.raises(BundleContractError) as caught:
        decode_csv(EQUITY, _header(supplied))
    error = caught.value
    assert error.code is BundleErrorCode.HEADER_MISMATCH
    assert error.field == column
    assert f"missing column {column!r}" in error.message


def test_bundle_csv_unexpected_and_reordered_columns_are_described():
    with pytest.raises(BundleContractError) as caught:
        decode_csv(EQUITY, _header([*EQUITY.headers, "note"]))
    assert caught.value.field == "note"
    assert "unexpected column 'note'" in caught.value.message

    with pytest.raises(BundleContractError) as caught:
        decode_csv(EQUITY, _header(reversed(EQUITY.headers)))
    assert caught.value.field is None
    assert "columns are duplicated or out of order" in caught.value.message


def test_trade_fill_header_mismatch_is_named():
    with pytest.raises(BundleContractError) as caught:
        decode_trade_fills(_header(TRADE_FILLS_HEADERS[:1]))
    assert caught.value.field == "fill_id"
    assert "missing column 'fill_id'" in caught.value.message


def test_describe_name_difference_lists_every_name_in_contract_order():
    description, field = describe_name_difference(
        ("a", "b", "c"), ("c", "x", "y"), noun="key"
    )
    assert description == "missing keys 'a', 'b'; unexpected keys 'x', 'y'"
    assert field == "a"
