"""Is the edge decaying? Rolling expectancy, CUSUM, Page–Hinkley and an SPRT.

Set-up (all pre-specified before the monitored trades are looked at):

* Reference window: the first R trades in exit order (default max(30, T//3)).
  μ0, σ0 = their mean and SD; SR0 = μ0/σ0. Without a positive SR0 there is
  no edge to lose and the detectors are not run.
* Monitored trades t = R+1..T are standardised: z_t = (x_t - μ0) / σ0.
  "Edge gone" means E[z] = -δ, with δ = SR0 by default (the whole edge).

Detectors on z (alarm = first t whose statistic crosses its threshold):

* CUSUM (lower):  S_t = max(0, S_{t-1} - z_t - δ/2).
* Page–Hinkley (decrease), self-starting: m_t = Σ (z_s - z̄_s + δ/2) with the
  running mean z̄_s, M_t = max(0, m_1..m_t), statistic M_t - m_t.
  CUSUM and Page–Hinkley thresholds h are set by Monte Carlo so that, if
  trades are i.i.d. normal with no change, the probability of any alarm over
  the monitored trades is ``false_alarm_probability`` — including the error
  of estimating μ0 and σ0 from R trades. (Siegmund's ARL formula ignores that
  estimation error, which inflates false alarms; see DESIGN.md.)
* SPRT (Wald), H0: E[z] = 0 vs H1: E[z] = -δ, log-likelihood increment
  -δ·z_t - δ²/2, thresholds A = ln((1-β)/α), B = ln(β/(1-α)). Crossing A is
  the decay alarm; crossing B accepts "intact" and restarts the test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backtest_auditor.edge_audit.metrics import Interval, percentile_interval
from backtest_auditor.statistics.resampling import stationary_bootstrap_indices

MINIMUM_REFERENCE_TRADES = 30
MINIMUM_MONITORED_TRADES = 30


@dataclass(frozen=True, slots=True)
class DetectorResult:
    name: str
    threshold: float
    parameters: dict[str, float]
    alarm_trade_number: int | None
    alarm_exit_time: str | None
    statistic_at_alarm: float | None
    max_statistic: float
    extra: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecayResult:
    status: str
    reason: str | None
    trade_count: int
    reference_trades: int
    monitored_trades: int
    reference_mean: float | None
    reference_std: float | None
    reference_sharpe: float | None
    shift_sigma: float | None
    shift_source: str
    false_alarm_probability: float
    calibration_draws: int
    rolling_window: int
    rolling_expectancy: tuple[float, ...]
    monitored_minus_reference: Interval | None
    detectors: tuple[DetectorResult, ...]


def rolling_expectancy(pnl: NDArray[np.float64], window: int) -> NDArray[np.float64]:
    """Mean of each run of ``window`` consecutive trades (exit order)."""

    if pnl.size < window:
        return np.zeros(0, dtype=np.float64)
    cumulative = np.concatenate(([0.0], np.cumsum(pnl)))
    return (cumulative[window:] - cumulative[:-window]) / window


def cusum_lower(z: NDArray[np.float64], k: float) -> NDArray[np.float64]:
    """Lower one-sided CUSUM path along the last axis.

    [HAND-WRITE] Two lines in a loop: S = max(0, S - z_t - k). Then explain
    why S is the largest drop of the walk Σ(z + k) below its running maximum.
    """

    z = np.asarray(z, dtype=np.float64)
    path = np.empty_like(z)
    state = np.zeros(z.shape[:-1])
    for t in range(z.shape[-1]):
        state = np.maximum(0.0, state - z[..., t] - k)
        path[..., t] = state
    return path


def page_hinkley_decrease(z: NDArray[np.float64], delta: float) -> NDArray[np.float64]:
    """Page–Hinkley statistic for a decrease in mean, along the last axis.

    [HAND-WRITE] Compare with cusum_lower: the only difference is that the
    running mean z̄_t replaces the reference mean 0.
    """

    z = np.asarray(z, dtype=np.float64)
    path = np.empty_like(z)
    total = np.zeros(z.shape[:-1])
    cumulative = np.zeros(z.shape[:-1])
    peak = np.zeros(z.shape[:-1])
    for t in range(z.shape[-1]):
        total = total + z[..., t]
        running_mean = total / (t + 1)
        cumulative = cumulative + z[..., t] - running_mean + delta
        peak = np.maximum(peak, cumulative)
        path[..., t] = peak - cumulative
    return path


def sprt_decay(
    z: NDArray[np.float64], delta: float, alpha: float, beta: float
) -> tuple[int | None, NDArray[np.float64], int]:
    """Wald SPRT for 'edge gone' with restart on acceptance of 'intact'.

    Returns (0-based alarm index or None, log-likelihood-ratio path, number of
    'intact' decisions before the alarm or the end).

    [HAND-WRITE] Derive the increment log[φ(z+δ)/φ(z)] = -δz - δ²/2 and the
    thresholds from Wald's inequalities.
    """

    upper = math.log((1.0 - beta) / alpha)
    lower = math.log(beta / (1.0 - alpha))
    path = np.empty(z.size, dtype=np.float64)
    llr = 0.0
    accepted = 0
    for t, value in enumerate(np.asarray(z, dtype=np.float64)):
        llr += -delta * value - delta * delta / 2.0
        path[t] = llr
        if llr >= upper:
            return t, path[: t + 1], accepted
        if llr <= lower:
            accepted += 1
            llr = 0.0
    return None, path, accepted


def first_crossing(path: NDArray[np.float64], threshold: float) -> int | None:
    hits = np.flatnonzero(path > threshold)
    return int(hits[0]) if hits.size else None


def calibrate_threshold(
    detector: str,
    *,
    reference_trades: int,
    monitored_trades: int,
    drift: float,
    false_alarm_probability: float,
    draws: int,
    seed: int,
) -> float:
    """Threshold h with P(alarm anywhere in the monitored trades) = target.

    Simulates i.i.d. N(0, 1) trades (the scale and level cancel after
    standardisation), re-estimates μ0 and σ0 from R reference trades in every
    draw, runs the detector on the monitored trades and returns the
    (1 - target) quantile of the path maxima.
    """

    rng = np.random.default_rng(seed)
    reference = rng.standard_normal((draws, reference_trades))
    monitored = rng.standard_normal((draws, monitored_trades))
    mean = reference.mean(axis=1, keepdims=True)
    std = reference.std(axis=1, ddof=1, keepdims=True)
    z = (monitored - mean) / std
    if detector == "cusum":
        maxima = cusum_lower(z, drift).max(axis=1)
    elif detector == "page_hinkley":
        maxima = page_hinkley_decrease(z, drift).max(axis=1)
    else:
        raise ValueError(f"unknown detector {detector!r}")
    return float(np.quantile(maxima, 1.0 - false_alarm_probability))


def analyse_decay(
    pnl: NDArray[np.float64],
    exit_times: tuple[str, ...],
    *,
    reference_trades: int | None,
    shift_sigma: float | None,
    false_alarm_probability: float,
    sprt_alpha: float,
    sprt_beta: float,
    calibration_draws: int,
    rolling_window: int | None,
    bootstrap_replications: int,
    mean_block_length: int,
    confidence_level: float,
    seed: int,
) -> DecayResult:
    count = int(pnl.size)
    window = rolling_window or min(50, max(10, count // 5))
    rolling = tuple(float(value) for value in rolling_expectancy(pnl, window))
    reference = reference_trades or max(MINIMUM_REFERENCE_TRADES, count // 3)
    monitored = count - reference
    base: dict[str, Any] = {
        "trade_count": count,
        "reference_trades": reference,
        "monitored_trades": max(monitored, 0),
        "false_alarm_probability": false_alarm_probability,
        "calibration_draws": calibration_draws,
        "rolling_window": window,
        "rolling_expectancy": rolling,
        "shift_source": "declared" if shift_sigma is not None else "reference_sharpe",
    }
    if reference < MINIMUM_REFERENCE_TRADES or monitored < MINIMUM_MONITORED_TRADES:
        return DecayResult(
            status="unavailable",
            reason=(
                f"{count} trades: need >= {MINIMUM_REFERENCE_TRADES} reference and "
                f">= {MINIMUM_MONITORED_TRADES} monitored trades"
            ),
            reference_mean=None,
            reference_std=None,
            reference_sharpe=None,
            shift_sigma=shift_sigma,
            monitored_minus_reference=None,
            detectors=(),
            **base,
        )

    head, tail = pnl[:reference], pnl[reference:]
    mu0 = float(np.mean(head))
    sigma0 = float(np.std(head, ddof=1))
    seeds = np.random.SeedSequence(seed).spawn(4)
    difference = _two_sample_difference(
        head,
        tail,
        replications=bootstrap_replications,
        mean_block_length=mean_block_length,
        confidence_level=confidence_level,
        seed=int(seeds[0].generate_state(1)[0]),
    )
    if sigma0 == 0.0 or mu0 <= 0.0:
        return DecayResult(
            status="no_reference_edge",
            reason=(
                "the reference window has no positive expectancy, so there is "
                "no edge whose loss could be detected"
            ),
            reference_mean=mu0,
            reference_std=sigma0,
            reference_sharpe=(mu0 / sigma0) if sigma0 > 0.0 else None,
            shift_sigma=shift_sigma,
            monitored_minus_reference=difference,
            detectors=(),
            **base,
        )

    reference_sharpe = mu0 / sigma0
    delta = shift_sigma if shift_sigma is not None else reference_sharpe
    z = (tail - mu0) / sigma0
    drift = delta / 2.0
    detectors = []
    for name, function, child in (
        ("cusum", cusum_lower, seeds[1]),
        ("page_hinkley", page_hinkley_decrease, seeds[2]),
    ):
        threshold = calibrate_threshold(
            name,
            reference_trades=reference,
            monitored_trades=monitored,
            drift=drift,
            false_alarm_probability=false_alarm_probability,
            draws=calibration_draws,
            seed=int(child.generate_state(1)[0]),
        )
        path = function(z, drift)
        alarm = first_crossing(path, threshold)
        detectors.append(
            DetectorResult(
                name=name,
                threshold=threshold,
                parameters={"drift_allowance": drift},
                alarm_trade_number=None if alarm is None else reference + alarm + 1,
                alarm_exit_time=None
                if alarm is None
                else exit_times[reference + alarm],
                statistic_at_alarm=None if alarm is None else float(path[alarm]),
                max_statistic=float(np.max(path)),
            )
        )
    alarm, llr_path, accepted = sprt_decay(z, delta, sprt_alpha, sprt_beta)
    detectors.append(
        DetectorResult(
            name="sprt",
            threshold=math.log((1.0 - sprt_beta) / sprt_alpha),
            parameters={
                "alpha": sprt_alpha,
                "beta": sprt_beta,
                "lower_threshold": math.log(sprt_beta / (1.0 - sprt_alpha)),
            },
            alarm_trade_number=None if alarm is None else reference + alarm + 1,
            alarm_exit_time=None if alarm is None else exit_times[reference + alarm],
            statistic_at_alarm=None if alarm is None else float(llr_path[alarm]),
            max_statistic=float(np.max(llr_path)),
            extra={"intact_decisions": float(accepted)},
        )
    )
    return DecayResult(
        status="computed",
        reason=None,
        reference_mean=mu0,
        reference_std=sigma0,
        reference_sharpe=reference_sharpe,
        shift_sigma=delta,
        monitored_minus_reference=difference,
        detectors=tuple(detectors),
        **base,
    )


def _two_sample_difference(
    head: NDArray[np.float64],
    tail: NDArray[np.float64],
    *,
    replications: int,
    mean_block_length: int,
    confidence_level: float,
    seed: int,
) -> Interval:
    """mean(monitored) - mean(reference), each part resampled on its own."""

    rng = np.random.default_rng(seed)
    draws = np.empty(replications, dtype=np.float64)
    for replicate in range(replications):
        first = stationary_bootstrap_indices(
            head.size, mean_block_length=mean_block_length, rng=rng
        )
        second = stationary_bootstrap_indices(
            tail.size, mean_block_length=mean_block_length, rng=rng
        )
        draws[replicate] = float(np.mean(tail[second]) - np.mean(head[first]))
    return percentile_interval(
        float(np.mean(tail) - np.mean(head)), draws, confidence_level=confidence_level
    )
