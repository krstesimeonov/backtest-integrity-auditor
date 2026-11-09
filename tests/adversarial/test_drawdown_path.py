"""Adversarial tests for statistics.performance_path (drawdown, duration, time under water, CAGR)."""

from __future__ import annotations

import numpy as np
import pytest

from .conftest import make_series, ref

from backtest_auditor.statistics.performance_path import calculate_performance_path
from backtest_auditor.statistics.sampling import assess_sampling


def _path(r, ppy=252):
    series = make_series(r, periods_per_year=ppy)
    return series, calculate_performance_path(series, assess_sampling(series))


@pytest.mark.parametrize("seed", range(40))
def test_max_drawdown_matches_plain_loop(seed):
    rng = np.random.default_rng(seed)
    r = 0.02 * rng.standard_normal(int(rng.integers(5, 400))) + 0.0005
    series, path = _path(r)
    exp = ref.drawdown_path(r)
    assert path.maximum_drawdown == pytest.approx(exp.max_drawdown, abs=1e-12), (
        f"MDD: V1={path.maximum_drawdown} loop={exp.max_drawdown}"
    )
    if exp.max_drawdown < 0:
        assert (
            path.maximum_drawdown_trough_timestamp
            == series.timestamps[exp.trough_index]
        )
        expected_peak = (
            None if exp.peak_index < 0 else series.timestamps[exp.peak_index]
        )
        assert path.maximum_drawdown_peak_timestamp == expected_peak
        if exp.recovery_index is None:
            assert path.maximum_drawdown_recovered is False
        else:
            assert (
                path.maximum_drawdown_recovery_timestamp
                == series.timestamps[exp.recovery_index]
            )
        assert path.maximum_drawdown_duration_observations == exp.duration, (
            f"duration: V1={path.maximum_drawdown_duration_observations} loop={exp.duration} "
            f"(peak idx {exp.peak_index}, recovery idx {exp.recovery_index}, n={len(r)})"
        )
    assert path.longest_time_underwater_observations == exp.longest_underwater, (
        f"TUW: V1={path.longest_time_underwater_observations} loop={exp.longest_underwater}"
    )


def test_hand_case_drawdown():
    """r = [+10%, −20%, +5%, +30%, −10%]: W = 1.1, 0.88, 0.924, 1.2012, 1.08108.
    Peak 1.1 at obs 0, trough 0.88 at obs 1 → MDD = −20 %; recovered at obs 3 (1.2012 ≥ 1.1);
    duration = 3 observations (obs 0 → obs 3); longest under water = 2 (obs 1, 2)."""
    r = np.array([0.1, -0.2, 0.05, 0.3, -0.1])
    series, path = _path(r)
    assert path.maximum_drawdown == pytest.approx(-0.2)
    assert path.maximum_drawdown_peak_timestamp == series.timestamps[0]
    assert path.maximum_drawdown_trough_timestamp == series.timestamps[1]
    assert path.maximum_drawdown_recovery_timestamp == series.timestamps[3]
    assert path.maximum_drawdown_duration_observations == 3
    assert path.longest_time_underwater_observations == 2
    assert path.ending_wealth == pytest.approx(1.1 * 0.8 * 1.05 * 1.3 * 0.9)


def test_opening_loss_is_a_drawdown_from_starting_wealth():
    """A series that starts with −5 % is already 5 % under water relative to the 1.0 anchor."""
    r = np.array([-0.05, 0.01, 0.01])
    series, path = _path(r)
    assert path.maximum_drawdown == pytest.approx(-0.05)
    assert (
        path.maximum_drawdown_peak_timestamp is None
    )  # the anchor, not an observation
    assert path.maximum_drawdown_recovered is False
    assert path.maximum_drawdown_duration_observations == 3


def test_unrecovered_drawdown_duration_runs_to_the_end():
    r = np.array([0.1, 0.1, -0.3, 0.01, 0.01, 0.01])
    series, path = _path(r)
    assert path.maximum_drawdown_recovered is False
    # peak at obs 1; remaining observations 2..5 → 4
    assert path.maximum_drawdown_duration_observations == 4
    assert path.longest_time_underwater_observations == 4


def test_cagr_matches_reference_and_is_null_without_periods():
    rng = np.random.default_rng(3)
    r = 0.01 * rng.standard_normal(500) + 0.0005
    _, path = _path(r, 252)
    assert path.cagr == pytest.approx(ref.cagr(r, 252), rel=1e-12)
    series = make_series(r, periods_per_year=None)
    path2 = calculate_performance_path(series, assess_sampling(series))
    assert path2.cagr is None


def test_total_loss_is_minus_one_and_everything_after_is_underwater():
    r = np.array([0.05, -1.0, 0.0, 0.0])
    _, path = _path(r)
    assert path.maximum_drawdown == -1.0
    assert path.ending_wealth == 0.0
    assert path.cagr is None
    assert path.longest_time_underwater_observations == 3


def test_flat_series_has_zero_drawdown_and_zero_duration():
    r = np.zeros(10)
    series, path = _path(r)
    assert path.maximum_drawdown == 0.0
    assert path.maximum_drawdown_duration_observations == 0
    assert path.longest_time_underwater_observations == 0


def test_tie_at_peak_uses_the_last_equal_peak_before_the_trough():
    """W: 1.1, 1.1 (flat), 0.99 → the peak timestamp should be the latest obs at the peak."""
    r = np.array([0.1, 0.0, -0.1])
    series, path = _path(r)
    assert path.maximum_drawdown_peak_timestamp == series.timestamps[1]
    assert path.maximum_drawdown_duration_observations == 1
