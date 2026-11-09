"""N13 (1.5.2): canonical decimals keep every supplied digit.

normalize_decimal used Decimal.normalize() under the default 28-digit context,
which rounds; it now strips trailing zeros only. These cases pin both halves:
nothing is rounded, and the canonical spelling is unchanged otherwise.
"""

from decimal import Decimal, localcontext

import pytest

from backtest_auditor.implementation_risk.domain.validation import normalize_decimal


@pytest.mark.parametrize(
    "supplied",
    [
        "123456789012.123456789012345678",  # 30 significant digits
        "-0.000000000000000000000000000000123456789012345678901234567891",
        "1" * 60,
        "9.99999999999999999999999999999",
    ],
)
def test_more_than_28_significant_digits_survive_exactly(supplied):
    value = normalize_decimal(supplied, field="value")
    assert value == Decimal(supplied)  # Decimal comparison is exact
    assert value.as_tuple().digits == Decimal(supplied).as_tuple().digits


@pytest.mark.parametrize(
    ("supplied", "canonical"),
    [
        ("1.2300", "1.23"),
        ("100", "1E+2"),
        ("0.000", "0"),
        ("-0", "0"),
        (Decimal("5.000000000000000000000000000000000"), "5"),
        (7, "7"),
    ],
)
def test_trailing_zeros_are_still_stripped(supplied, canonical):
    assert str(normalize_decimal(supplied, field="value")) == canonical


def test_the_result_does_not_depend_on_the_callers_context():
    supplied = "123456789012.123456789012345678"
    with localcontext() as context:
        context.prec = 6
        narrow = normalize_decimal(supplied, field="value")
    assert narrow == Decimal(supplied)
