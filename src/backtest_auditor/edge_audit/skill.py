"""Luck versus skill: t = SR·√T, PSR, DSR at a declared trial count, MinTRL.

Computed by V1 code (imported):

* SR       — :func:`backtest_auditor.statistics.annualized.calculate_annualized_statistics`
  (per-trade SR = V1's annualised SR / √periods; the verdict uses this value)
* moments  — :func:`backtest_auditor.statistics.distribution.calculate_distribution_statistics`
* PSR, plug-in SE — :func:`backtest_auditor.statistics.sharpe_uncertainty.calculate_sharpe_uncertainty`
* MinTRL   — :func:`backtest_auditor.statistics.track_record.calculate_track_record_length`
  (also for the verdict's "trades needed" when N = 1 or the spread is declared)
* expected maximum and both DSRs — :func:`backtest_auditor.statistics.deflated_sharpe._calculate_scenario`
  (the per-scenario core of V1's family DSR; a single trade log has a declared
  trial count but not the other trials' returns, so the family wrapper cannot
  be used).

Computed here: t = SR·√T (a teaching identity; a test checks it against V1's
SR), the standard error under H0 and the default cross-trial spread
1/√(T-1) (design choices, ASSUMPTIONS A5/A6), and the verdict's "trades
needed" when N > 1 with that default spread — not in V1, because the DSR bar
then shrinks as T grows and V1's MinTRL assumes a fixed benchmark.

Two DSR numbers are reported. ``dsr_plug_in`` is the classical DSR exactly as V1
computes it: the Sharpe-ratio standard error uses the *observed* SR, skewness
and kurtosis. ``dsr`` — the verdict — evaluates the standard error under the
null hypothesis being tested (a skill-less strategy, SR = 0), where V1's
variance adjustment 1 - g3·SR + (g4-1)/4·SR² equals 1, so SE0 = 1/√(T-1).
Both go through V1's ``_calculate_scenario``; only the SE argument differs.
Why: with fat-tailed trade P&L the sample skewness rises and falls with the
sample SR (correlation 0.45 on the calibration logs), so the plug-in SE
shrinks exactly when SR is high by luck. On 4,000 fat-tailed noise logs the
plug-in test fired 6.2 % of the time at a 5 % level, the null-SE test 5.4 %;
on 4,000 held-out logs 5.75 % and 4.9 % (230 and 197 of 4,000)
(docs/edge_audit/job/evidence/fpr_diagnosis.py and the scenario tests).

V1 works on a regular "period" series. The adapter here makes one period =
one closed trade (a synthetic one-second clock, so V1's regularity check
passes; the timestamps carry no meaning) and divides the P&L by a positive
constant so the values sit inside V1's simple-return domain (> -1). Sharpe
ratio, skewness, kurtosis, PSR, DSR and MinTRL are all invariant to that
scale, so nothing is approximated by it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy import stats as scipy_stats

from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    DSRTrialCountBasis,
    FrequencyStatus,
    ReturnConvention,
)
from backtest_auditor.domain.results import SharpeUncertaintyResult
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import calculate_annualized_statistics
from backtest_auditor.statistics.deflated_sharpe import _calculate_scenario
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.distribution import (
    calculate_distribution_statistics,
)
from backtest_auditor.statistics.sampling import assess_sampling
from backtest_auditor.statistics.sharpe_uncertainty import (
    calculate_sharpe_uncertainty,
)
from backtest_auditor.statistics.track_record import (
    MINIMUM_MOMENT_OBSERVATIONS,
    calculate_track_record_length,
)

#: Pre-specified floor below which no verdict other than "insufficient data"
#: is issued: the normal approximations behind PSR/DSR need it.
MINIMUM_TRADES_FOR_VERDICT = 30

EVIDENCE = "evidence_of_edge"
NO_EVIDENCE = "no_evidence_of_edge"
INSUFFICIENT = "insufficient_data"

_TRADE_CLOCK_START = pd.Timestamp("2000-01-01", tz="UTC")


@dataclass(frozen=True, slots=True)
class LuckVsSkill:
    trade_count: int
    span_years: float
    trades_per_year: float
    periods_per_year: int
    mean: float
    standard_deviation: float | None
    sharpe_per_trade: float | None
    t_statistic: float | None
    t_p_value_one_sided: float | None
    annualized_sharpe: float | None
    sample_skewness: float | None
    sample_pearson_kurtosis: float | None
    sharpe_variance_adjustment: float | None
    sharpe_standard_error: float | None
    null_standard_error: float | None
    psr_vs_zero: float | None
    declared_trials: int
    trial_sharpe_std: float | None
    trial_sharpe_std_source: str
    expected_max_standard_normal: float | None
    expected_max_sharpe_per_trade: float | None
    dsr: float | None
    dsr_test_statistic: float | None
    dsr_plug_in: float | None
    confidence_level: float
    min_track_record_trades: int | None
    deflated_min_track_record_trades: int | None
    verdict: str
    verdict_reason: str


def sharpe_t_statistic(values: NDArray[np.float64]) -> tuple[float, float] | None:
    """Per-trade Sharpe ratio and its t-statistic, t = SR·√T.

    [HAND-WRITE] Show on paper that SR·√T is *exactly* the one-sample
    t-statistic mean / (s/√T) when SR uses the same s (ddof=1), and that with
    an annualised SR the same number is SR_annual·√years.
    """

    if values.size < 2 or has_zero_sample_variation(values):
        return None
    sharpe = float(np.mean(values) / np.std(values, ddof=1))
    return sharpe, sharpe * math.sqrt(values.size)


def null_trial_sharpe_std(trade_count: int) -> float:
    """Cross-trial SD of per-trade Sharpe ratios when no trial has skill.

    Under H0 each trial's SR estimate is ~N(0, 1/(T-1)) (V1's SE with the
    variance adjustment equal to 1 at SR = 0), so the trials' SRs spread by
    1/√(T-1). This is the default when the user declares N but not the spread.

    [HAND-WRITE] Derive it from V1's SE formula at SR = 0.
    """

    return 1.0 / math.sqrt(trade_count - 1)


def deflated_min_track_record(
    sharpe: float,
    variance_adjustment: float,
    expected_max_standard_normal: float,
    confidence_level: float,
) -> int | None:
    """Trades needed for DSR >= confidence if the per-trade SR stays as observed.

    With the null spread 1/√(T-1) the DSR benchmark itself shrinks as T grows,
    so V1's MinTRL (fixed benchmark) does not apply directly. Solving
    SR·√(T-1) - e_N = z·√V for T gives T* = 1 + ((z·√V + e_N)/SR)². With
    N = 1 (e_N = 0) this is V1's MinTRL against SR* = 0.

    The verdict's DSR uses the null SE, i.e. V = 1; pass the plug-in V to get
    the classical (plug-in) version.

    [HAND-WRITE] Do the algebra from DSR = Φ((SR - e_N/√(T-1)) / √(V/(T-1))).
    """

    if sharpe <= 0.0 or variance_adjustment <= 0.0:
        return None
    z = NormalDist().inv_cdf(confidence_level)
    root = (z * math.sqrt(variance_adjustment) + expected_max_standard_normal) / sharpe
    return max(MINIMUM_MOMENT_OBSERVATIONS, math.ceil(1.0 + root * root))


def trade_clock_series(
    values: NDArray[np.float64], periods_per_year: int
) -> ReturnSeries:
    """Wrap per-trade values as a V1 ReturnSeries (one period = one trade)."""

    largest = float(np.max(np.abs(values)))
    scale = 2.0 * largest if largest > 0.0 else 1.0
    timestamps = pd.date_range(
        _TRADE_CLOCK_START, periods=values.size, freq="s", unit="ns"
    )
    return ReturnSeries(
        timestamps=timestamps,
        values=np.asarray(values, dtype=np.float64) / scale,
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(
            status=FrequencyStatus.DECLARED,
            declared_frequency="s",
            periods_per_year=periods_per_year,
        ),
        name="trade_clock",
    )


def assess_luck_vs_skill(
    values: NDArray[np.float64],
    *,
    span_years: float,
    declared_trials: int,
    confidence_level: float = 0.95,
    trial_sharpe_std: float | None = None,
) -> LuckVsSkill:
    """Primary edge test: DSR (null SE) at the declared trial count >= confidence.

    The verdict is pre-specified and depends on nothing random (no bootstrap,
    no seed), so its false-positive rate can be calibrated on its own.
    """

    if declared_trials < 1:
        raise ValueError("declared_trials must be at least 1.")
    if trial_sharpe_std is not None and not (
        math.isfinite(trial_sharpe_std) and trial_sharpe_std >= 0.0
    ):
        raise ValueError("trial_sharpe_std must be finite and non-negative.")
    trade_count = int(values.size)
    trades_per_year = (
        trade_count / span_years if span_years > 0.0 else float(trade_count)
    )
    periods_per_year = max(1, int(round(trades_per_year)))
    mean = float(np.mean(values))
    flat = has_zero_sample_variation(values)
    standard_deviation = (
        None if trade_count < 2 else 0.0 if flat else float(np.std(values, ddof=1))
    )
    empty: dict[str, Any] = {
        "trade_count": trade_count,
        "span_years": span_years,
        "trades_per_year": trades_per_year,
        "periods_per_year": periods_per_year,
        "mean": mean,
        "standard_deviation": standard_deviation,
        "declared_trials": declared_trials,
        "confidence_level": confidence_level,
        "trial_sharpe_std_source": (
            "null_default" if trial_sharpe_std is None else "declared"
        ),
    }
    if trade_count < 4 or flat:
        return _without_sharpe(
            empty,
            reason=(
                f"{trade_count} trade(s); at least 4 are needed for moments"
                if trade_count < 4
                else "all trades have the same net P&L"
            ),
        )

    sharpe, t_statistic = sharpe_t_statistic(values)  # type: ignore[misc]
    t_p_value = float(scipy_stats.t.sf(t_statistic, df=trade_count - 1))

    series = trade_clock_series(values, periods_per_year)
    sampling = assess_sampling(series)
    annualized = calculate_annualized_statistics(
        series, sampling, sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0)
    )
    distribution = calculate_distribution_statistics(series)
    psr_spec = ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=0.0,
        required_psr_confidence_level=confidence_level,
    )
    uncertainty = calculate_sharpe_uncertainty(
        annualized, distribution, psr_spec=psr_spec
    )
    track_record = calculate_track_record_length(uncertainty, psr_spec=psr_spec)

    # The verdict uses V1's SR. ``sharpe`` (local, for t = SR·√T) is the same
    # number up to rounding; V1 returns no uncertainty only for < 4 or flat
    # trades, which were handled above.
    selected = sharpe if uncertainty is None else uncertainty.period_sharpe_ratio
    sigma = (
        trial_sharpe_std
        if trial_sharpe_std is not None
        else null_trial_sharpe_std(trade_count)
    )
    common: dict[str, Any] = dict(
        empty,
        sharpe_per_trade=selected,
        t_statistic=t_statistic,
        t_p_value_one_sided=t_p_value,
        annualized_sharpe=(
            None if annualized is None else annualized.annualized_sharpe_ratio
        ),
        sample_skewness=distribution.sample_skewness,
        sample_pearson_kurtosis=distribution.sample_pearson_kurtosis,
        trial_sharpe_std=sigma,
        min_track_record_trades=(
            None if track_record is None else track_record.minimum_required_observations
        ),
    )
    null_se = 1.0 / math.sqrt(trade_count - 1)
    plug_in_se = (
        None if uncertainty is None else uncertainty.period_sharpe_standard_error
    )
    scenario_options: dict[str, Any] = dict(
        basis=DSRTrialCountBasis.DECLARED_ATTEMPTS,
        trial_count=declared_trials,
        cross_trial_standard_deviation=sigma,
        selected_period_sharpe_ratio=selected,
        square_root_of_periods=math.sqrt(periods_per_year),
        required_confidence_level=confidence_level,
    )
    scenario = _calculate_scenario(
        **scenario_options, selected_period_standard_error=null_se
    )
    plug_in = (
        None
        if plug_in_se is None
        else _calculate_scenario(
            **scenario_options, selected_period_standard_error=plug_in_se
        )
    )
    if trial_sharpe_std is None and declared_trials > 1:
        needed = deflated_min_track_record(
            selected, 1.0, scenario.expected_maximum_standard_normal, confidence_level
        )
    else:
        # Fixed bar (0 with one trial, or σ·e_N with a declared σ): V1's MinTRL.
        needed = _fixed_benchmark_track_record(
            selected,
            trade_count,
            periods_per_year,
            scenario.expected_maximum_period_sharpe_ratio,
            null_se,
            scenario.deflated_sharpe_ratio,
            confidence_level,
        )
    if needed is not None:
        needed = max(MINIMUM_TRADES_FOR_VERDICT, needed)

    if trade_count < MINIMUM_TRADES_FOR_VERDICT:
        verdict, reason = (
            INSUFFICIENT,
            f"{trade_count} trades; the pre-specified minimum for a verdict is "
            f"{MINIMUM_TRADES_FOR_VERDICT}",
        )
    elif scenario.deflated_sharpe_ratio >= confidence_level:
        verdict, reason = (
            EVIDENCE,
            f"DSR {scenario.deflated_sharpe_ratio:.4f} >= {confidence_level:g} "
            f"at {declared_trials} declared trial(s)",
        )
    else:
        verdict, reason = (
            NO_EVIDENCE,
            f"DSR {scenario.deflated_sharpe_ratio:.4f} < {confidence_level:g} "
            f"at {declared_trials} declared trial(s)",
        )

    return LuckVsSkill(
        **common,
        sharpe_variance_adjustment=(
            None if uncertainty is None else uncertainty.sharpe_variance_adjustment
        ),
        sharpe_standard_error=plug_in_se,
        null_standard_error=null_se,
        psr_vs_zero=None
        if uncertainty is None
        else uncertainty.probabilistic_sharpe_ratio,
        expected_max_standard_normal=scenario.expected_maximum_standard_normal,
        expected_max_sharpe_per_trade=scenario.expected_maximum_period_sharpe_ratio,
        dsr=scenario.deflated_sharpe_ratio,
        dsr_test_statistic=scenario.test_statistic,
        dsr_plug_in=None if plug_in is None else plug_in.deflated_sharpe_ratio,
        deflated_min_track_record_trades=needed,
        verdict=verdict,
        verdict_reason=reason,
    )


def _fixed_benchmark_track_record(
    sharpe: float,
    trade_count: int,
    periods_per_year: int,
    benchmark: float,
    null_se: float,
    dsr: float,
    confidence_level: float,
) -> int | None:
    """Trades needed against a declared (fixed) DSR benchmark: V1's MinTRL.

    The verdict's SE is the null SE (variance adjustment 1), so V1's MinTRL
    is fed an uncertainty result carrying that variance adjustment.
    """

    root = math.sqrt(periods_per_year)
    spec = ProbabilisticSharpeRatioSpec(
        benchmark_annualized_sharpe_ratio=benchmark * root,
        required_psr_confidence_level=confidence_level,
    )
    uncertainty = SharpeUncertaintyResult(
        observation_count=trade_count,
        periods_per_year=periods_per_year,
        period_sharpe_ratio=sharpe,
        annualized_sharpe_ratio=sharpe * root,
        sharpe_variance_adjustment=1.0,
        period_sharpe_standard_error=null_se,
        annualized_sharpe_standard_error=null_se * root,
        benchmark_period_sharpe_ratio=benchmark,
        benchmark_annualized_sharpe_ratio=benchmark * root,
        probabilistic_sharpe_ratio=dsr,
    )
    result = calculate_track_record_length(uncertainty, psr_spec=spec)
    return None if result is None else result.minimum_required_observations


def _without_sharpe(fields: dict[str, Any], *, reason: str) -> LuckVsSkill:
    return LuckVsSkill(
        **fields,
        sharpe_per_trade=None,
        t_statistic=None,
        t_p_value_one_sided=None,
        annualized_sharpe=None,
        sample_skewness=None,
        sample_pearson_kurtosis=None,
        sharpe_variance_adjustment=None,
        sharpe_standard_error=None,
        null_standard_error=None,
        psr_vs_zero=None,
        trial_sharpe_std=None,
        expected_max_standard_normal=None,
        expected_max_sharpe_per_trade=None,
        dsr=None,
        dsr_test_statistic=None,
        dsr_plug_in=None,
        min_track_record_trades=None,
        deflated_min_track_record_trades=None,
        verdict=INSUFFICIENT,
        verdict_reason=reason,
    )
