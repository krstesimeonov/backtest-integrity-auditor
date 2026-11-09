import argparse

import pytest

from backtest_auditor import cli


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (cli._declared_frequency, "not-a-frequency"),
        (cli._positive_integer, "abc"),
        (cli._positive_integer, "0"),
        (cli._integer_at_least_two, "abc"),
        (cli._integer_at_least_two, "1"),
        (cli._even_integer_at_least_two, "3"),
        (cli._non_negative_integer, "abc"),
        (cli._non_negative_integer, "-1"),
        (cli._annual_risk_free_rate, "abc"),
        (cli._annual_risk_free_rate, "-1"),
        (cli._finite_number, "abc"),
        (cli._finite_number, "nan"),
        (cli._confidence_level_above_half, "0.5"),
        (cli._probability, "1"),
        (cli._inclusive_probability, "1.1"),
        (cli._positive_finite_number, "0"),
        (cli._non_negative_finite_number, "-0.1"),
        (cli._parameter_scale, "lookback"),
        (cli._parameter_scale, "lookback=0"),
        (cli._explicit_boolean, "yes"),
        (cli._audit_timestamp, "not-a-timestamp"),
        (cli._audit_timestamp, "2026-08-12T12:00:00"),
        (cli._non_empty_text, "   "),
    ],
)
def test_cli_argument_validators_reject_invalid_values(
    validator,
    value: str,
) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        validator(value)


def test_cli_argument_validators_normalize_valid_boundary_values() -> None:
    assert cli._positive_integer("2") == 2
    assert cli._integer_at_least_two("2") == 2
    assert cli._even_integer_at_least_two("4") == 4
    assert cli._non_negative_integer("0") == 0
    assert cli._annual_risk_free_rate("-0.5") == -0.5
    assert cli._finite_number("1.5") == 1.5
    assert cli._confidence_level_above_half("0.95") == 0.95
    assert cli._probability("0.5") == 0.5
    assert cli._inclusive_probability("0") == 0.0
    assert cli._positive_finite_number("0.1") == 0.1
    assert cli._non_negative_finite_number("0") == 0.0
    assert cli._explicit_boolean("TRUE") is True
    assert cli._explicit_boolean("false") is False
    assert cli._non_empty_text("  evidence  ") == "evidence"
