"""Is the edge decaying? Rolling expectancy, CUSUM, Page–Hinkley and a mixture SPRT.

Set-up (all pre-specified before the monitored trades are looked at):

* Reference window: the first R trades in exit order (default max(30, T//3)).
  μ0, σ0 = their mean and SD; SR0 = μ0/σ0. Without a positive SR0 there is
  no edge to lose and the detectors are not run.
* Monitored trades t = R+1..T are standardised: z_t = (x_t - μ0) / σ0.
  "Edge gone" means E[z] = -δ, with δ = SR0 by default (the whole edge).
* False-alarm budget: α over a horizon of N monitored trades (audit inputs,
  defaults 0.05 and 1,000). The horizon used is max(N, M) for M monitored
  trades, so the budget always covers every trade the detectors look at.

Detectors on z (alarm = first t whose statistic exceeds its threshold):

* Rolling expectancy: D_t = -(z_{t-w+1} + ... + z_t)/√w once w trades are
  monitored (the w-trade average P&L falls below μ0 - h·σ0/√w).
* CUSUM (lower):  S_t = max(0, S_{t-1} - z_t - δ/2).
* Page–Hinkley (decrease), self-starting: m_t = Σ (z_s - z̄_s + δ/2) with the
  running mean z̄_s, M_t = max(0, m_1..m_t), statistic M_t - m_t.
* Mixture SPRT: log Λ_t, the likelihood ratio of "edge down by θ" against
  "intact", averaged over θ ~ half-normal(scale δ) - the composite
  alternative "down by some θ > 0", tested once over the horizon, no restarts.
  With μ0 and σ0 known, Λ is a martingale under "intact" and Ville's
  inequality bounds P(Λ ever ≥ 1/α) by α at any horizon; with the reference
  estimated the bound fails, so the threshold is simulated like the others.

Every threshold comes from one table (``decay_thresholds.py``) simulated once
under the calibration null - i.i.d. normal trades without a change, the
reference mean and SD re-estimated from R trades in every path - over a grid
of (α, N, R, δ or w) and interpolated (``threshold``). Regenerate it with
``python -m backtest_auditor.edge_audit.decay_calibration --write``.
J9's Wald SPRT (``sprt_decay``) is kept for the exercises and the before/after
study but no longer runs in the audit: see docs/edge_audit/CALIBRATION.md.
"""

from __future__ import annotations

import hashlib
import importlib
import itertools
import math
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.special import log_ndtr

from backtest_auditor.edge_audit.metrics import Interval, percentile_interval
from backtest_auditor.statistics.resampling import stationary_bootstrap_indices

MINIMUM_REFERENCE_TRADES = 30
MINIMUM_MONITORED_TRADES = 30
DEFAULT_HORIZON = 1000
DETECTORS = ("rolling_expectancy", "cusum", "page_hinkley", "mixture_sprt")
CALIBRATION_NULL = "iid_normal"
TABLE_MODULE = "backtest_auditor.edge_audit.decay_thresholds"
CALIBRATION_NULL_TEXT = (
    "i.i.d. normal trades without a change; reference mean and SD re-estimated "
    "from the R reference trades in every simulated path"
)


@dataclass(frozen=True, slots=True)
class DetectorResult:
    name: str
    status: str
    reason: str | None
    threshold: float | None
    parameters: dict[str, float]
    false_alarm_probability: float
    horizon: int
    calibration_null: str
    false_alarm_probability_over_monitored: float | None
    alarm_trade_number: int | None
    alarm_exit_time: str | None
    statistic_at_alarm: float | None
    max_statistic: float | None
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
    horizon_requested: int
    horizon: int
    calibration_null: str
    calibration_table: str
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


def rolling_drop(z: NDArray[np.float64], window: int) -> NDArray[np.float64]:
    """Standardised drop of the last ``window`` values, along the last axis.

    D_t = -(z_{t-w+1} + ... + z_t)/√w; -inf until ``window`` values exist.
    Under "intact" with μ0, σ0 known each D_t is N(0, 1).
    """

    z = np.asarray(z, dtype=np.float64)
    path = np.full(z.shape, -np.inf)
    if z.shape[-1] >= window:
        cumulative = np.cumsum(z, axis=-1)
        sums = cumulative[..., window - 1 :].copy()
        sums[..., 1:] -= cumulative[..., : z.shape[-1] - window]
        path[..., window - 1 :] = -sums / math.sqrt(window)
    return path


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


def mixture_sprt_log_lr(z: NDArray[np.float64], tau: float) -> NDArray[np.float64]:
    """log Λ_t of the one-sided normal-mixture SPRT, along the last axis.

    Λ_t = ∫_0^∞ Π_{s≤t} φ(z_s + θ)/φ(z_s) · π(θ) dθ with π half-normal of
    scale τ. With S_t = Σ_{s≤t} z_s and a_t = t + 1/τ²:
    Λ_t = 2 (1 + tτ²)^(-1/2) exp(S_t²/(2a_t)) Φ(-S_t/√a_t).

    [HAND-WRITE] Complete the square in θ to get the closed form; then check
    it against a numerical integral for one (S_t, t).
    """

    z = np.asarray(z, dtype=np.float64)
    total = np.cumsum(z, axis=-1)
    count = np.arange(1, z.shape[-1] + 1, dtype=np.float64)
    precision = count + 1.0 / (tau * tau)
    return (
        math.log(2.0)
        - 0.5 * np.log1p(count * tau * tau)
        + total * total / (2.0 * precision)
        + log_ndtr(-total / np.sqrt(precision))
    )


def detector_statistic(
    name: str, z: NDArray[np.float64], parameter: float
) -> NDArray[np.float64]:
    """The statistic path of detector ``name`` (the audit and the table both call this).

    ``parameter`` is the window w for the rolling expectancy and the shift δ
    for the others (CUSUM and Page–Hinkley allow δ/2, the mixture scale is δ).
    """

    if name == "rolling_expectancy":
        return rolling_drop(z, int(parameter))
    if name == "cusum":
        return cusum_lower(z, parameter / 2.0)
    if name == "page_hinkley":
        return page_hinkley_decrease(z, parameter / 2.0)
    if name == "mixture_sprt":
        return mixture_sprt_log_lr(z, parameter)
    raise ValueError(f"unknown detector {name!r}")


def sprt_decay(
    z: NDArray[np.float64], delta: float, alpha: float, beta: float
) -> tuple[int | None, NDArray[np.float64], int]:
    """Wald SPRT for 'edge gone' with restart on acceptance of 'intact'.

    Returns (0-based alarm index or None, log-likelihood-ratio path, number of
    'intact' decisions before the alarm or the end).

    Retired from the audit (version 1.1): every restart is a fresh chance of a
    false alarm, so over 400 monitored trades it alarmed far more often than
    α; see docs/edge_audit/CALIBRATION.md. Kept for the exercise.

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


# --- the threshold table -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ThresholdTable:
    alphas: NDArray[np.float64]
    horizons: NDArray[np.float64]
    reference_trades: NDArray[np.float64]
    parameters: dict[str, NDArray[np.float64]]
    values: dict[str, NDArray[np.float64]]
    description: str


def table_content_sha256(
    alphas: tuple[float, ...],
    horizons: tuple[int, ...],
    reference_trades: tuple[float, ...],
    parameters: dict[str, tuple[float, ...]],
    blocks: dict[str, str],
) -> str:
    """Hash of the grids and the threshold text as stored; an edited number changes it."""

    grids = (
        tuple(alphas),
        tuple(horizons),
        tuple(reference_trades),
        tuple(sorted((name, tuple(values)) for name, values in parameters.items())),
    )
    digest = hashlib.sha256(repr(grids).encode("utf-8"))
    for name in sorted(blocks):
        digest.update(name.encode("utf-8"))
        digest.update(" ".join(blocks[name].split()).encode("utf-8"))
    return digest.hexdigest()


@cache
def threshold_table() -> ThresholdTable:
    """Parse ``decay_thresholds.py``; refuse a table whose numbers were edited."""

    module = importlib.import_module(TABLE_MODULE)
    content = table_content_sha256(
        module.ALPHAS,
        module.HORIZONS,
        module.REFERENCE_TRADES,
        module.PARAMETERS,
        module.THRESHOLDS,
    )
    if content != module.CONTENT_SHA256:
        raise RuntimeError(
            "decay_thresholds.py was edited by hand (content hash mismatch); "
            "regenerate it: python -m backtest_auditor.edge_audit.decay_calibration --write"
        )
    alphas = np.array(module.ALPHAS, dtype=np.float64)
    horizons = np.array(module.HORIZONS, dtype=np.float64)
    reference = np.array(module.REFERENCE_TRADES, dtype=np.float64)
    parameters = {
        name: np.array(values, dtype=np.float64)
        for name, values in module.PARAMETERS.items()
    }
    values = {}
    for name in DETECTORS:
        flat = np.array(module.THRESHOLDS[name].split(), dtype=np.float64)
        values[name] = flat.reshape(
            reference.size, parameters[name].size, horizons.size, alphas.size
        )
    return ThresholdTable(
        alphas=alphas,
        horizons=horizons,
        reference_trades=reference,
        parameters=parameters,
        values=values,
        description=(
            f"{module.TABLE_ID}: {module.PATHS:,} simulated paths per cell, "
            f"seed {module.SEED}"
        ),
    )


def _locate(grid: NDArray[np.float64], value: float) -> tuple[int, float]:
    """(i, w) with value = (1 - w)·grid[i] + w·grid[i + 1]; grid ascending."""

    index = int(np.searchsorted(grid, value, side="right")) - 1
    index = min(max(index, 0), grid.size - 2)
    weight = (value - grid[index]) / (grid[index + 1] - grid[index])
    return index, float(weight)


def table_range_problem(
    name: str,
    *,
    alpha: float,
    horizon: float,
    reference_trades: float,
    parameter: float,
) -> str | None:
    """Why (α, N, R, parameter) is outside the table, or None."""

    table = threshold_table()
    grid = table.parameters[name]
    label = "window" if name == "rolling_expectancy" else "shift δ"
    if not table.alphas[0] <= alpha <= table.alphas[-1]:
        return f"α = {alpha:g} is outside the table ({table.alphas[0]:g}-{table.alphas[-1]:g})"
    if not table.horizons[0] <= horizon <= table.horizons[-1]:
        return (
            f"a horizon of {horizon:,.0f} trades is outside the table "
            f"({table.horizons[0]:,.0f}-{table.horizons[-1]:,.0f})"
        )
    if reference_trades < table.reference_trades[0]:
        return f"{reference_trades:,.0f} reference trades: the table starts at {table.reference_trades[0]:,.0f}"
    if not grid[0] <= parameter <= grid[-1]:
        return (
            f"{label} {parameter:.4g} is outside the table ({grid[0]:g}-{grid[-1]:g})"
        )
    return None


def threshold(
    name: str,
    *,
    alpha: float,
    horizon: float,
    reference_trades: float,
    parameter: float,
) -> float:
    """Table threshold for P(alarm within ``horizon`` monitored trades) = α.

    Multilinear interpolation of the log-threshold in (log α, log N, 1/√R,
    log parameter); R may be ``inf`` (μ0 and σ0 known). Thresholds grow
    roughly exponentially along these axes, so interpolating their logs
    roughly halves the error of interpolating them directly (leave-one-out on
    the table; CALIBRATION.md). A grid point returns the stored number
    exactly. NaN where the table has no value (a rolling window longer than
    the horizon).
    """

    problem = table_range_problem(
        name,
        alpha=alpha,
        horizon=horizon,
        reference_trades=reference_trades,
        parameter=parameter,
    )
    if problem is not None:
        raise ValueError(problem)
    table = threshold_table()
    # 1/√R decreases with R; the grid is reversed so that it ascends.
    inverse_root = 1.0 / np.sqrt(table.reference_trades[::-1])
    r_index, r_weight = _locate(inverse_root, 1.0 / math.sqrt(reference_trades))
    r_index = table.reference_trades.size - 2 - r_index
    r_weight = 1.0 - r_weight
    p_index, p_weight = _locate(np.log(table.parameters[name]), math.log(parameter))
    n_index, n_weight = _locate(np.log(table.horizons), math.log(horizon))
    a_index, a_weight = _locate(np.log(table.alphas), math.log(alpha))
    values = table.values[name]
    corners = []
    for corner in itertools.product((0, 1), repeat=4):
        weight = 1.0
        for bit, axis_weight in zip(
            corner, (r_weight, p_weight, n_weight, a_weight), strict=True
        ):
            weight *= axis_weight if bit else 1.0 - axis_weight
        if weight == 0.0:
            continue
        value = float(
            values[
                r_index + corner[0],
                p_index + corner[1],
                n_index + corner[2],
                a_index + corner[3],
            ]
        )
        corners.append((weight, value))
    if len(corners) == 1:
        return corners[0][1]
    if not all(math.isfinite(value) for _, value in corners):
        return math.nan
    return math.exp(sum(weight * math.log(value) for weight, value in corners))


def false_alarm_probability_at(
    name: str,
    *,
    level: float,
    horizon: float,
    reference_trades: float,
    parameter: float,
) -> tuple[float | None, bool]:
    """(α', below) with threshold(α', horizon) = level.

    ``below`` is True when the level lies above the table's threshold for its
    smallest α: then α' is reported as that α and is an upper bound. α' is None
    when the table has no value there (a rolling window close to the horizon).
    """

    table = threshold_table()
    levels = np.array(
        [
            threshold(
                name,
                alpha=float(alpha),
                horizon=horizon,
                reference_trades=reference_trades,
                parameter=parameter,
            )
            for alpha in table.alphas
        ]
    )
    if not np.all(np.isfinite(levels)):
        return None, False
    if level > levels[0]:
        return float(table.alphas[0]), True
    if level <= levels[-1]:
        # Not reached when horizon <= the horizon ``level`` was set for:
        # thresholds grow with the horizon.
        return float(table.alphas[-1]), False
    index = int(np.flatnonzero(levels >= level)[-1])
    weight = (levels[index] - level) / (levels[index] - levels[index + 1])
    log_alpha = (1.0 - weight) * math.log(table.alphas[index]) + weight * math.log(
        table.alphas[index + 1]
    )
    return math.exp(log_alpha), False


# --- the audit step ----------------------------------------------------------------


def analyse_decay(
    pnl: NDArray[np.float64],
    exit_times: tuple[str, ...],
    *,
    reference_trades: int | None,
    shift_sigma: float | None,
    false_alarm_probability: float,
    horizon: int,
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
    used_horizon = max(horizon, monitored)
    base: dict[str, Any] = {
        "trade_count": count,
        "reference_trades": reference,
        "monitored_trades": max(monitored, 0),
        "false_alarm_probability": false_alarm_probability,
        "horizon_requested": horizon,
        "horizon": used_horizon,
        "calibration_null": CALIBRATION_NULL,
        "calibration_table": threshold_table().description,
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
    detectors = tuple(
        _run_detector(
            name,
            z,
            parameter=float(window) if name == "rolling_expectancy" else delta,
            false_alarm_probability=false_alarm_probability,
            horizon=used_horizon,
            reference_trades=reference,
            mu0=mu0,
            sigma0=sigma0,
            exit_times=exit_times,
        )
        for name in DETECTORS
    )
    return DecayResult(
        status="computed",
        reason=None,
        reference_mean=mu0,
        reference_std=sigma0,
        reference_sharpe=reference_sharpe,
        shift_sigma=delta,
        monitored_minus_reference=difference,
        detectors=detectors,
        **base,
    )


def _run_detector(
    name: str,
    z: NDArray[np.float64],
    *,
    parameter: float,
    false_alarm_probability: float,
    horizon: int,
    reference_trades: int,
    mu0: float,
    sigma0: float,
    exit_times: tuple[str, ...],
) -> DetectorResult:
    if name == "rolling_expectancy":
        parameters = {"window": parameter}
    elif name == "mixture_sprt":
        parameters = {"shift_sigma": parameter, "mixing_scale": parameter}
    else:
        parameters = {"shift_sigma": parameter, "drift_allowance": parameter / 2.0}
    common: dict[str, Any] = {
        "name": name,
        "parameters": parameters,
        "false_alarm_probability": false_alarm_probability,
        "horizon": horizon,
        "calibration_null": CALIBRATION_NULL,
    }
    reason = table_range_problem(
        name,
        alpha=false_alarm_probability,
        horizon=horizon,
        reference_trades=reference_trades,
        parameter=parameter,
    )
    level = math.nan
    if reason is None and name == "rolling_expectancy" and z.size < parameter:
        reason = (
            f"{z.size} monitored trades, fewer than the {parameter:.0f}-trade window"
        )
    if reason is None:
        level = threshold(
            name,
            alpha=false_alarm_probability,
            horizon=horizon,
            reference_trades=reference_trades,
            parameter=parameter,
        )
        if not math.isfinite(level):
            reason = "the table has no threshold for this window and horizon"
    if reason is not None:
        return DetectorResult(
            status="unavailable",
            reason=reason,
            threshold=None,
            false_alarm_probability_over_monitored=None,
            alarm_trade_number=None,
            alarm_exit_time=None,
            statistic_at_alarm=None,
            max_statistic=None,
            **common,
        )
    path = detector_statistic(name, z, parameter)
    alarm = first_crossing(path, level)
    offset = len(exit_times) - z.size
    extra: dict[str, float] = {}
    if z.size >= horizon:
        over_monitored: float | None = false_alarm_probability
    else:
        over_monitored, below = false_alarm_probability_at(
            name,
            level=level,
            horizon=max(float(z.size), float(threshold_table().horizons[0])),
            reference_trades=reference_trades,
            parameter=parameter,
        )
        if below:
            extra["false_alarm_over_monitored_is_upper_bound"] = 1.0
    if name == "rolling_expectancy":
        extra["alarm_level_mean_pnl"] = mu0 - level * sigma0 / math.sqrt(parameter)
    if name == "mixture_sprt":
        extra["ville_threshold_known_reference"] = math.log(
            1.0 / false_alarm_probability
        )
    return DetectorResult(
        status="computed",
        reason=None,
        threshold=level,
        false_alarm_probability_over_monitored=over_monitored,
        alarm_trade_number=None if alarm is None else offset + alarm + 1,
        alarm_exit_time=None if alarm is None else exit_times[offset + alarm],
        statistic_at_alarm=None if alarm is None else float(path[alarm]),
        max_statistic=float(np.max(path)),
        extra=extra,
        **common,
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
