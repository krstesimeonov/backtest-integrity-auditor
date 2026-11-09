from datetime import date

import pytest

from backtest_auditor.audit.methodology import (
    assess_return_construction,
)
from backtest_auditor.domain.enums import (
    LeveragePolicy,
    PriceAdjustmentPolicy,
    ReturnCostBasis,
    SeriesRole,
)
from backtest_auditor.domain.metadata import (
    ObservationCalendarSpec,
    ReturnConstructionSpec,
)


def test_observation_calendar_spec_preserves_ordered_dates() -> None:
    dates = (date(2026, 1, 2), date(2026, 1, 5))

    spec = ObservationCalendarSpec(
        calendar_name=" XNYS ",
        timezone="America/New_York",
        expected_session_dates=dates,
    )

    assert spec.calendar_name == "XNYS"
    assert spec.expected_session_dates == dates


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"calendar_name": "", "timezone": "UTC"}, "calendar_name"),
        ({"calendar_name": "XNYS", "timezone": "Mars/Olympus"}, "IANA"),
        (
            {
                "calendar_name": "XNYS",
                "timezone": "UTC",
                "expected_session_dates": (
                    date(2026, 1, 5),
                    date(2026, 1, 2),
                ),
            },
            "increasing",
        ),
    ],
)
def test_observation_calendar_spec_rejects_invalid_contracts(
    kwargs: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ObservationCalendarSpec(**kwargs)


def test_return_construction_normalizes_and_assesses_complete_spec() -> None:
    spec = ReturnConstructionSpec(
        transaction_costs_included=True,
        fees_included=True,
        leverage_policy="dynamic",
        currency="usd",
        price_adjustment_policy="adjusted",
        data_source=" point-in-time vendor ",
        data_vintage="2026-08-11",
        stale_price_policy="reject carried prices",
        delisting_return_policy="include terminal returns",
        survivorship_bias_controlled=True,
        lookahead_bias_controlled=True,
        signal_timing="close t",
        execution_timing="open t+1",
    )

    result = assess_return_construction(
        spec,
        role=SeriesRole.STRATEGY,
    )

    assert spec.currency == "USD"
    assert spec.leverage_policy is LeveragePolicy.DYNAMIC
    assert spec.price_adjustment_policy is PriceAdjustmentPolicy.ADJUSTED
    assert result.declared_field_count == 13
    assert result.completeness_ratio == 1.0
    assert result.cost_basis is ReturnCostBasis.NET_OF_ALL_DECLARED_COSTS


@pytest.mark.parametrize("currency", ["US", "USDD", "12A"])
def test_return_construction_rejects_invalid_currency(
    currency: str,
) -> None:
    with pytest.raises(ValueError, match="three-letter"):
        ReturnConstructionSpec(currency=currency)


def test_partial_cost_declaration_is_not_silently_classified() -> None:
    result = assess_return_construction(
        ReturnConstructionSpec(transaction_costs_included=True),
        role=SeriesRole.BENCHMARK,
    )

    assert result.cost_basis is ReturnCostBasis.PARTIALLY_DECLARED
    assert result.role is SeriesRole.BENCHMARK


def test_missing_return_construction_remains_typed() -> None:
    result = assess_return_construction(None, role=SeriesRole.STRATEGY)

    assert not result.supplied
    assert result.required_field_count == 13
    assert result.cost_basis is ReturnCostBasis.UNDECLARED
