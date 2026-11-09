import numpy as np
from numpy.typing import NDArray

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import ReturnSeries


def to_simple_returns(
    series: ReturnSeries,
) -> NDArray[np.float64]:
    """Return period-by-period simple returns for statistical use."""

    if series.convention is ReturnConvention.SIMPLE:
        return series.values

    return np.expm1(series.values)


def annual_to_period_rate(
    annual_rate: float,
    periods_per_year: int,
) -> float:
    """Convert an effective annual simple rate to one observation period.

    The single definition of this conversion. It was previously written out
    three times -- in family_metrics, annualized and deflated_sharpe -- so a
    correction to one would have silently left the other two behind, and two
    sections of the same report could disagree about the risk-free rate.

    expm1/log1p rather than (1 + r) ** (1 / p) - 1: mathematically identical,
    but accurate for the small rates that dominate here.
    """

    return float(np.expm1(np.log1p(annual_rate) / periods_per_year))
