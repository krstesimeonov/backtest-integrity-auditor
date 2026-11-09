import math

import numpy as np
import pytest

from backtest_auditor.statistics.family_metrics import period_sharpe_scores


def _column(*values: float) -> np.ndarray:
    return np.asarray(values, dtype=np.float64).reshape(-1, 1)


def test_period_sharpe_matches_the_closed_form_with_a_nonzero_risk_free_rate() -> None:
    # [0.01, 0.03]: mean 0.02, sample sd sqrt((0.01^2 + 0.01^2) / 1) = 0.01 sqrt 2.
    # (0.02 - 0.005) / (0.01 sqrt 2) = 1.5 / sqrt 2.
    scores = period_sharpe_scores(
        _column(0.01, 0.03),
        period_risk_free_rate_value=0.005,
    )

    assert scores[0] == pytest.approx(1.5 / math.sqrt(2))


def test_period_sharpe_is_zero_when_the_risk_free_rate_equals_the_mean() -> None:
    # (mean - r) / sd vanishes at r = mean whatever the volatility.
    values = np.asarray(
        [[0.01, 0.00], [0.03, 0.04], [0.02, -0.01], [0.00, 0.05]],
        dtype=np.float64,
    )
    for column, mean in enumerate(values.mean(axis=0)):
        scores = period_sharpe_scores(values, period_risk_free_rate_value=float(mean))
        assert scores[column] == pytest.approx(0.0, abs=1e-12)


def test_period_sharpe_falls_strictly_as_the_risk_free_rate_rises() -> None:
    values = _column(0.01, 0.03, -0.02, 0.04)
    scores = [
        float(period_sharpe_scores(values, period_risk_free_rate_value=rate)[0])
        for rate in (-0.01, 0.0, 0.005, 0.01, 0.02)
    ]

    assert all(later < earlier for earlier, later in zip(scores, scores[1:]))


def test_period_sharpe_divides_by_a_volatility_of_exactly_one() -> None:
    # [0, 1, 2]: mean 1, sample variance ((-1)^2 + 0^2 + 1^2) / 2 = 1, so sd = 1
    # and the Sharpe is (1 - r) / 1.
    values = _column(0.0, 1.0, 2.0)

    assert period_sharpe_scores(values, period_risk_free_rate_value=0.0)[0] == 1.0
    assert period_sharpe_scores(values, period_risk_free_rate_value=0.5)[0] == 0.5


def test_period_sharpe_is_undefined_only_for_the_zero_volatility_column() -> None:
    values = np.asarray(
        [[0.01, 0.01], [0.01, 0.03], [0.01, 0.02]],
        dtype=np.float64,
    )
    scores = period_sharpe_scores(values, period_risk_free_rate_value=0.0)

    assert not math.isfinite(scores[0])
    # [0.01, 0.03, 0.02]: mean 0.02, sample sd sqrt((0.01^2 + 0.01^2 + 0) / 2) = 0.01.
    assert scores[1] == pytest.approx(2.0)
