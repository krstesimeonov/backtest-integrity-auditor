"""Zero sample variation in the 1.4.0 additive-domain evidence.

Port of 19a2eae to code that 1.0.0 did not have: a constant excess return must
be detected from the data, not from a computed standard deviation, which is a
rounding residue (about 2.8e-20 for 0.0 - 0.03/252) rather than 0.0.
"""

import numpy as np
import pandas as pd

from backtest_auditor.domain.enums import PairedSeriesStatus, ReturnConvention
from backtest_auditor.domain.series import RegimeSeries, ReturnSeries, SamplingSpec
from backtest_auditor.statistics.additive_domain import (
    calculate_regime_analysis,
    calculate_risk_free_series_evidence,
)
from backtest_auditor.statistics.sampling import assess_sampling

DAILY_RISK_FREE = 0.03 / 252


def _series(values: list[float]) -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=np.asarray(values, dtype=np.float64),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency="D", periods_per_year=365),
    )


def test_numpy_leaves_a_residue_for_this_constant_excess_return() -> None:
    excess = np.zeros(20) - DAILY_RISK_FREE
    assert float(np.std(excess, ddof=1)) != 0.0


def test_constant_excess_return_has_no_risk_free_sharpe() -> None:
    strategy = _series([0.0] * 20)
    risk_free = _series([DAILY_RISK_FREE] * 20)

    result = calculate_risk_free_series_evidence(
        strategy, risk_free, assess_sampling(strategy)
    )

    assert result is not None
    assert result.alignment.status is PairedSeriesStatus.ELIGIBLE
    assert result.period_excess_sharpe_ratio is None
    assert result.annualized_excess_sharpe_ratio is None


def test_regime_in_cash_against_a_constant_risk_free_series_has_no_sharpe() -> None:
    strategy = _series([0.01, -0.02, 0.015, 0.005] + [0.0] * 6 + [0.002, 0.004])
    risk_free = _series([DAILY_RISK_FREE] * 12)
    labels = ("risk",) * 4 + ("cash",) * 6 + ("risk",) * 2
    regimes = RegimeSeries(strategy.timestamps, labels)

    result = calculate_regime_analysis(strategy, regimes, risk_free=risk_free)

    assert result is not None
    by_regime = {item.regime: item for item in result.slices}
    assert by_regime["cash"].sample_volatility == 0.0
    assert by_regime["cash"].period_sharpe_ratio is None
    assert by_regime["risk"].period_sharpe_ratio is not None


def test_constant_non_representable_regime_returns_report_zero_volatility() -> None:
    assert float(np.std([0.001] * 10, ddof=1)) != 0.0  # the residue exists
    strategy = _series([0.001] * 10 + [0.01, -0.01, 0.02])
    regimes = RegimeSeries(strategy.timestamps, ("flat",) * 10 + ("live",) * 3)

    result = calculate_regime_analysis(strategy, regimes)

    assert result is not None
    by_regime = {item.regime: item for item in result.slices}
    assert by_regime["flat"].sample_volatility == 0.0
    assert by_regime["live"].sample_volatility is not None
    assert by_regime["live"].sample_volatility > 0.0
