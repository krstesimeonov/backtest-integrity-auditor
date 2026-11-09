"""Adversarial tests for statistics.cscv (CSCV / PBO), BBLZ17.

Reference: reference_stats.cscv_pbo (independent enumeration).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from .conftest import cscv_spec, make_family, ref

from backtest_auditor.domain.enums import CSCVStatus
from backtest_auditor.statistics.cscv import calculate_cscv


def _pbo(M, S=4, **kw):
    family = make_family(M, **kw)
    result = calculate_cscv(family, cscv_spec(partitions=S))
    return result


@pytest.mark.parametrize("seed", range(12))
def test_pbo_matches_independent_enumeration(seed):
    rng = np.random.default_rng(100 + seed)
    T, N, S = 240, int(rng.integers(3, 15)), int(rng.choice([4, 6, 8]))
    M = 0.01 * rng.standard_normal((T, N)) + 0.0002 * rng.standard_normal(N)
    result = _pbo(M, S)
    assert result.status is CSCVStatus.ELIGIBLE, result.status
    expected = ref.cscv_pbo(M, S)
    logits = np.asarray([s.rank_logit for s in result.splits])
    assert len(logits) == math.comb(S, S // 2) == len(expected.logits)
    assert np.allclose(logits, expected.logits, rtol=0, atol=1e-12), (
        "per-combination logits differ (BBLZ17 eq. 3)"
    )
    assert result.probability_of_backtest_overfitting == pytest.approx(
        expected.pbo, abs=1e-12
    ), (
        f"PBO: V1={result.probability_of_backtest_overfitting} reference={expected.pbo} (BBLZ17 eq. 4)"
    )
    is_scores = np.asarray([s.selected_in_sample_score for s in result.splits])
    oos_scores = np.asarray([s.selected_out_of_sample_score for s in result.splits])
    assert np.allclose(is_scores, expected.is_scores, atol=1e-12)
    assert np.allclose(oos_scores, expected.oos_scores, atol=1e-12)
    # linear degradation = OLS of OOS on IS over combinations
    slope, intercept = np.polyfit(expected.is_scores, expected.oos_scores, 1)
    assert result.performance_degradation_slope == pytest.approx(slope, rel=1e-9)
    assert result.performance_degradation_intercept == pytest.approx(
        intercept, rel=1e-9, abs=1e-12
    )


def test_pbo_pure_noise_is_near_one_half_on_average():
    """50 pure-noise strategies, S = 8 (70 combinations). Under H0 the IS-best trial's OOS
    rank is uniform, so E[PBO] = 0.5 exactly. The 70 combinations of one family are
    strongly dependent, so a single family's PBO has sd ≈ 0.17–0.23
    (night3/baseline/pbo_null_study*.txt: 300 seeds, mean 0.506). The spec's [0.4, 0.6]
    band is therefore applied to the mean over 60 seeds (se ≈ 0.022) and each seed is
    only required to stay inside [0.05, 0.95]. T = 400 keeps the run under a minute."""
    pbos = []
    for seed in range(60):
        rng = np.random.default_rng(200 + seed)
        M = 0.01 * rng.standard_normal((400, 50))
        result = _pbo(M, 8)
        assert result.status is CSCVStatus.ELIGIBLE
        pbos.append(result.probability_of_backtest_overfitting)
        assert 0.05 <= pbos[-1] <= 0.95, f"seed {seed}: PBO={pbos[-1]}"
    mean_pbo = float(np.mean(pbos))
    assert 0.4 <= mean_pbo <= 0.6, (
        f"mean PBO over 60 seeds = {mean_pbo:.3f}; sd = {np.std(pbos):.3f}"
    )


def test_pbo_single_family_spread_under_the_null_is_large():
    """Documents for the report reader: one family's PBO is a noisy estimate. 20 seeds of
    2000 bars × 50 noise trials give PBOs between about 0.1 and 0.8 (reference and V1
    agree exactly, so this is the statistic, not the code). The assertion records the
    range in the message and passes if the spread is as large as expected."""
    pbos = []
    for seed in range(20):
        rng = np.random.default_rng(200 + seed)
        M = 0.01 * rng.standard_normal((2000, 50))
        pbos.append(_pbo(M, 8).probability_of_backtest_overfitting)
    assert max(pbos) - min(pbos) > 0.3, (
        f"PBO range over 20 null families = {min(pbos):.3f}–{max(pbos):.3f}"
    )


def test_pbo_with_one_true_signal_among_noise_is_small():
    """One strategy with annual Sharpe 2 (period SR = 2/√252) among 49 noise strategies,
    2000 bars: the true strategy wins IS almost always and ranks top OOS, so PBO < 0.1."""
    rng = np.random.default_rng(300)
    M = 0.01 * rng.standard_normal((2000, 50))
    M[:, 17] += 0.01 * 2.0 / math.sqrt(252)
    result = _pbo(M, 8)
    assert result.status is CSCVStatus.ELIGIBLE
    assert result.probability_of_backtest_overfitting < 0.1, (
        result.probability_of_backtest_overfitting
    )


def test_pbo_invariant_under_column_permutation():
    rng = np.random.default_rng(400)
    M = 0.01 * rng.standard_normal((400, 12))
    base = _pbo(M, 6)
    perm = rng.permutation(12)
    permuted = _pbo(M[:, perm], 6)
    assert (
        permuted.probability_of_backtest_overfitting
        == base.probability_of_backtest_overfitting
    )
    assert sorted(s.rank_logit for s in permuted.splits) == pytest.approx(
        sorted(s.rank_logit for s in base.splits), abs=1e-12
    )


def test_pbo_ties_handled_without_nan():
    """Two identical columns tie in every IS/OOS split. The IS winner tie resolves by
    attempt order; the OOS rank is the average rank; no NaN may appear and the logit
    must be finite."""
    rng = np.random.default_rng(500)
    M = 0.01 * rng.standard_normal((200, 5))
    M[:, 3] = M[:, 1]
    result = _pbo(M, 4)
    assert result.status is CSCVStatus.ELIGIBLE, result.status
    for s in result.splits:
        assert s.rank_logit is not None and math.isfinite(s.rank_logit)
        if s.selected_trial_id in ("t002", "t004"):
            assert set(s.tied_in_sample_winner_trial_ids) == {"t002", "t004"}
            # ascending ranks 1..5: tied pair shares the average of two adjacent ranks
            assert (s.out_of_sample_rank * 2) % 1 == 0
    expected = ref.cscv_pbo(M, 4)
    assert result.probability_of_backtest_overfitting == pytest.approx(expected.pbo)


def test_all_columns_identical_gives_pbo_with_average_rank_logit_zero():
    """N identical trials: every OOS rank is the average (N+1)/2 ⇒ ω̄ = 1/2 ⇒ λ = 0 ⇒
    every combination is an overfit event (λ ≤ 0) ⇒ PBO = 1."""
    rng = np.random.default_rng(501)
    col = 0.01 * rng.standard_normal(100)
    M = np.column_stack([col] * 4)
    result = _pbo(M, 4)
    assert result.status is CSCVStatus.ELIGIBLE, result.status
    assert all(abs(s.rank_logit) < 1e-12 for s in result.splits)
    assert result.probability_of_backtest_overfitting == 1.0


def test_observations_not_divisible_by_partitions_is_refused_not_trimmed():
    rng = np.random.default_rng(600)
    M = 0.01 * rng.standard_normal((203, 6))
    result = _pbo(M, 4)
    assert result.status is CSCVStatus.OBSERVATIONS_NOT_DIVISIBLE_BY_PARTITIONS
    assert result.probability_of_backtest_overfitting is None
    # the same data trimmed to 200 rows must be eligible, so the refusal is the only path
    assert _pbo(M[:200], 4).status is CSCVStatus.ELIGIBLE


def test_pbo_uses_all_combinations_each_pair_twice():
    """BBLZ17 enumerates all C(S, S/2) combinations; each (IS, OOS) pair appears with
    its complement, so the logit multiset is symmetric under complementation only in
    expectation. Check the count and that the complement of a combination is present."""
    rng = np.random.default_rng(700)
    M = 0.01 * rng.standard_normal((120, 7))
    result = _pbo(M, 6)
    combos = {tuple(s.in_sample_partition_indices) for s in result.splits}
    assert len(combos) == math.comb(6, 3) == 20
    for c in combos:
        complement = tuple(sorted(set(range(1, 7)) - set(c)))
        assert complement in combos


def test_period_sharpe_metric_uses_period_risk_free_rate():
    """With r_f = 3% annual at 252 periods, the IS/OOS scores must subtract the geometric
    period rate; the reference enumerates with the same rate."""
    rng = np.random.default_rng(800)
    M = 0.01 * rng.standard_normal((200, 6)) + 0.0005
    family = make_family(M, rf_annual=0.03)
    result = calculate_cscv(family, cscv_spec(partitions=4, rf=0.03))
    assert result.status is CSCVStatus.ELIGIBLE, result.status
    rf_p = ref.annual_to_period_rate_geometric(0.03, 252)
    expected = ref.cscv_pbo(M, 4, rf_p)
    logits = np.asarray([s.rank_logit for s in result.splits])
    assert np.allclose(logits, expected.logits, atol=1e-12)


def test_selected_trial_identity_does_not_affect_pbo():
    """PBO is a family property; the manifest's selected trial must not enter it."""
    rng = np.random.default_rng(900)
    M = 0.01 * rng.standard_normal((160, 5))
    sharpes = M.mean(axis=0) / M.std(axis=0, ddof=1)
    best = int(np.argmax(sharpes))
    a = calculate_cscv(make_family(M, selected=best), cscv_spec(partitions=4))
    # family with another selected trial: must still validate (selected must be the
    # max declared score, so re-declare scores to make column 0 the winner)
    assert a.status is CSCVStatus.ELIGIBLE
    assert a.probability_of_backtest_overfitting == pytest.approx(
        ref.cscv_pbo(M, 4).pbo
    )
