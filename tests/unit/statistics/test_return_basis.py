import math

import numpy as np
import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.return_basis import (
    annual_to_period_rate,
    to_simple_returns,
)


def test_period_rate_compounds_back_to_the_annual_rate() -> None:
    """The defining property: compounding the period rate must recover the year.

    This is the check that was missing. The conversion was written out three
    separate times, and flipping the `/` to a `*` in any of them left the whole
    suite green. A round-trip assertion cannot be satisfied by a wrong operator,
    so it catches the mutation without pinning a magic constant.
    """

    for annual in (0.0, 0.001, 0.04, 0.15, 1.0):
        for periods in (1, 12, 52, 252, 365):
            period = annual_to_period_rate(annual, periods)
            assert (1.0 + period) ** periods == pytest.approx(1.0 + annual, rel=1e-12)


def test_period_rate_known_value() -> None:
    """4 % a year over 252 trading days is 0.0156 % a day, not 1 960 556 %."""

    assert annual_to_period_rate(0.04, 252) == pytest.approx(
        0.00015564986279132913,
        rel=1e-15,
    )


def test_multiplying_instead_of_dividing_is_caught() -> None:
    """Pin the mutation explicitly, so the failure names itself.

    `* periods_per_year` turns a 4 % annual rate into 19 605.56 per period.
    """

    wrong = float(np.expm1(np.log1p(0.04) * 252))
    assert wrong > 19_000
    assert annual_to_period_rate(0.04, 252) != pytest.approx(wrong)


def test_zero_rate_is_zero_in_every_period() -> None:
    """The case that hides the bug: 0 % converts to 0 % under / and under *.

    Most of the project's own examples use --annual-risk-free-rate 0.0, which
    is one reason the duplicated formula went unnoticed for so long.
    """

    assert annual_to_period_rate(0.0, 252) == 0.0
    assert float(np.expm1(np.log1p(0.0) * 252)) == 0.0


def test_conversion_has_exactly_one_definition() -> None:
    """Guard the de-duplication itself.

    The formula previously appeared in family_metrics.py, annualized.py and
    deflated_sharpe.py. Identical then, but a correction to one would have
    silently left the others behind and two sections of the same report could
    have disagreed about the risk-free rate.
    """

    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "src" / "backtest_auditor"
    hits = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "expm1(np.log1p(" in path.read_text()
    ]

    assert hits == ["statistics/return_basis.py"], hits


def test_to_simple_returns_is_unchanged() -> None:
    series = ReturnSeries(
        timestamps=np.array(["2026-01-01", "2026-01-02"], dtype="datetime64[ns]"),
        values=np.asarray([0.01, -0.02]),
        convention=ReturnConvention.LOG,
        sampling=SamplingSpec(declared_frequency=None, periods_per_year=None),
    )

    assert to_simple_returns(series) == pytest.approx(
        [math.expm1(0.01), math.expm1(-0.02)]
    )
