import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import PairedSeriesStatus, ReturnConvention
from backtest_auditor.domain.series import RegimeSeries, ReturnSeries, SamplingSpec
from backtest_auditor.statistics.additive_domain import (
    calculate_gross_net_cost_drag,
    calculate_regime_analysis,
    calculate_risk_free_series_evidence,
)
from backtest_auditor.statistics.sampling import assess_sampling


def _series(values: list[float], *, start: str = "2026-01-01") -> ReturnSeries:
    return ReturnSeries(
        timestamps=pd.date_range(start, periods=len(values), freq="D"),
        values=np.asarray(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency="D", periods_per_year=4),
    )


def test_time_varying_risk_free_and_gross_net_evidence_match_references() -> None:
    net = _series([0.02, -0.01, 0.03, 0.00])
    risk_free = _series([0.001, 0.001, 0.002, 0.001])
    gross = _series([0.025, -0.005, 0.035, 0.002])
    sampling = assess_sampling(net)

    rf = calculate_risk_free_series_evidence(net, risk_free, sampling)
    drag = calculate_gross_net_cost_drag(net, gross, sampling)

    assert rf is not None and drag is not None
    assert rf.alignment.status is PairedSeriesStatus.ELIGIBLE
    assert rf.mean_period_risk_free_return == pytest.approx(0.00125)
    assert rf.mean_period_excess_return == pytest.approx(0.00875)
    assert rf.period_excess_sharpe_ratio is not None
    assert rf.annualized_excess_sharpe_ratio == pytest.approx(
        2.0 * rf.period_excess_sharpe_ratio
    )
    assert drag.mean_period_cost_drag == pytest.approx(0.00425)
    assert drag.annualized_arithmetic_cost_drag == pytest.approx(0.017)
    assert drag.periods_with_positive_cost_drag == 4
    assert drag.periods_with_negative_cost_drag == 0


def test_additive_evidence_requires_exact_timestamp_alignment() -> None:
    strategy = _series([0.01, 0.02, 0.03])
    shifted = _series([0.0, 0.0, 0.0], start="2026-01-02")
    sampling = assess_sampling(strategy)

    rf = calculate_risk_free_series_evidence(strategy, shifted, sampling)
    drag = calculate_gross_net_cost_drag(strategy, shifted, sampling)
    regimes = calculate_regime_analysis(
        strategy,
        RegimeSeries(shifted.timestamps, ("a", "b", "c")),
    )

    assert rf is not None and drag is not None and regimes is not None
    assert rf.alignment.status is PairedSeriesStatus.TIMESTAMP_MISMATCH
    assert rf.mean_period_excess_return is None
    assert drag.alignment.aligned_observation_count == 2
    assert drag.mean_period_cost_drag is None
    assert regimes.status is PairedSeriesStatus.TIMESTAMP_MISMATCH
    assert regimes.slices == ()


def test_declared_regime_slices_use_aligned_risk_free_returns() -> None:
    strategy = _series([0.02, -0.01, 0.03, 0.01])
    risk_free = _series([0.001, 0.001, 0.001, 0.001])
    regimes = RegimeSeries(
        strategy.timestamps, ("risk-on", "risk-off", "risk-on", "risk-off")
    )

    result = calculate_regime_analysis(strategy, regimes, risk_free=risk_free)

    assert result is not None
    assert result.status is PairedSeriesStatus.ELIGIBLE
    assert [item.regime for item in result.slices] == ["risk-off", "risk-on"]
    assert [item.observation_count for item in result.slices] == [2, 2]
    assert all(item.period_sharpe_ratio is not None for item in result.slices)


def test_additive_series_are_optional() -> None:
    strategy = _series([0.01, 0.02])
    sampling = assess_sampling(strategy)

    assert calculate_risk_free_series_evidence(strategy, None, sampling) is None
    assert calculate_gross_net_cost_drag(strategy, None, sampling) is None
    assert calculate_regime_analysis(strategy, None) is None
