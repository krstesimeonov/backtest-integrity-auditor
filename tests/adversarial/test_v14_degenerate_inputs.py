"""V1.4 evidence that only exists in 1.5.0, probed with flat (zero-variation) inputs.

A series of identical non-zero floats has no variation, so a Sharpe ratio built on
it is undefined. `np.std` of such a series is usually a ~1e-20 rounding residue
rather than 0.0, and the V1.4 risk-free and regime code only treats an exact 0.0 as
"no variation". Main fixed this pattern for the 1.0.0 modules (statistics/degeneracy.py,
19a2eae and 3a9795e); the V1.4 modules were never on main, so porting that fix
would not reach them. Finding N17 in night7/FINDINGS_1.5.0.md.

The trigger is ordinary: a strategy that sits in cash (returns exactly 0.0) during
a declared regime, audited with a constant risk-free series, which is what the
package's own examples/sample_risk_free.csv contains.
"""

import numpy as np
import pandas as pd
from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import RegimeSeries, ReturnSeries, SamplingSpec
from backtest_auditor.statistics.additive_domain import (
    calculate_regime_analysis,
    calculate_risk_free_series_evidence,
)
from backtest_auditor.statistics.sampling import assess_sampling

DAILY_RF = 0.03 / 252  # a constant risk-free series built from a 3 % annual rate


def _series(values, timestamps) -> ReturnSeries:
    return ReturnSeries(
        timestamps=timestamps,
        values=np.asarray(values, dtype=float),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency="B", periods_per_year=252),
    )


def test_cash_regime_with_a_constant_risk_free_series_has_no_sharpe():
    """Regime 'cash' has returns of exactly 0.0, so its excess return is the constant
    -DAILY_RF and its excess Sharpe is undefined (docs/V1_4_STATISTICAL_METHODS.md,
    "Declared-regime slices": period excess Sharpe; the code withholds it only when
    the excess volatility is exactly 0.0). 1.5.0 prints about -4.3e15."""
    timestamps = pd.bdate_range("2025-01-06", periods=40)
    rng = np.random.default_rng(7)
    returns = np.r_[rng.normal(0.0005, 0.01, 20), np.zeros(20)]
    labels = ("risk_on",) * 20 + ("cash",) * 20
    result = calculate_regime_analysis(
        _series(returns, timestamps),
        RegimeSeries(timestamps=timestamps, labels=labels),
        risk_free=_series(np.full(40, DAILY_RF), timestamps),
    )
    cash = next(item for item in result.slices if item.regime == "cash")
    assert cash.sample_volatility == 0.0
    assert cash.period_sharpe_ratio is None, (
        f"cash regime: excess returns all equal {-DAILY_RF!r}, yet period Sharpe = "
        f"{cash.period_sharpe_ratio!r}"
    )


def test_all_cash_strategy_against_a_constant_risk_free_series_has_no_excess_sharpe():
    """Same mechanism over the whole series: a strategy flat at 0.0 against a constant
    risk-free series has a constant excess return and an undefined excess Sharpe
    (docs/V1_4_STATISTICAL_METHODS.md, "Time-varying risk-free evidence")."""
    timestamps = pd.bdate_range("2025-01-06", periods=63)
    strategy = _series(np.zeros(63), timestamps)
    result = calculate_risk_free_series_evidence(
        strategy,
        _series(np.full(63, DAILY_RF), timestamps),
        assess_sampling(strategy),
    )
    assert result.period_excess_sharpe_ratio is None, (
        f"excess returns all equal {-DAILY_RF!r}, yet period excess Sharpe = "
        f"{result.period_excess_sharpe_ratio!r}, annualized "
        f"{result.annualized_excess_sharpe_ratio!r}"
    )
