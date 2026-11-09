#!/usr/bin/env python3
"""Before/after study of the Edge Audit decay detectors (docs/edge_audit/CALIBRATION.md).

Every simulated log is a series of per-trade P&L values with a constant edge of
SR 0.3 per trade (J9's scenario (c) value). The audit's default geometry is
used: R = N/2 reference trades followed by N monitored trades (J9's default
reference max(30, T//3) with T = 1.5 N), so N is both the number of monitored
trades and the horizon the "after" detectors are calibrated for.

* nulls (nothing changes): iid_normal, student_t3 (Student t, 3 degrees of
  freedom, unit variance), ar1_t3 (AR(1), phi = 0.3, Student-t(3) innovations,
  unit marginal variance);
* changes (normal noise): the edge halves (SR 0.3 -> 0.15) or goes to zero
  after the first N/4 monitored trades.

"before" runs J9's decay code exactly as shipped in 1c1184a (frozen copy
j9_decay.py; its Monte Carlo threshold is cached per (R, M) because J9 draws
the same 2,000 calibration paths for every log - a self-check confirms the
cached thresholds equal J9's own function bit for bit). "after" runs the
current package's analyse_decay. Both run on the same logs (same seeds).

Commands (repository root):
  .venv/bin/python docs/edge_audit/calibration/evaluate_detectors.py run before
  .venv/bin/python docs/edge_audit/calibration/evaluate_detectors.py run after
  .venv/bin/python docs/edge_audit/calibration/evaluate_detectors.py report
Options: --seeds (default 2000), --workers (default 4), --horizons.
Outputs: results_before.json / results_after.json here, figures in
docs/edge_audit/figures/, tables in tables.md here.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
FIGURES = HERE.parent / "figures"
sys.path.insert(0, str(HERE))

import j9_decay  # noqa: E402  (frozen copy of J9's decay.py)

SHARPE = 0.3
PHI = 0.3
T_DF = 3.0
AR_BURN_IN = 200
ROOT_SEED = 20261102
HORIZONS = (100, 400, 1000, 4000)
NULLS = ("iid_normal", "student_t3", "ar1_t3")
CHANGES = {"halving": 0.5, "to_zero": 0.0}
SCENARIO_CODES = {
    "iid_normal": 1,
    "student_t3": 2,
    "ar1_t3": 3,
    "halving": 4,
    "to_zero": 5,
}
# The seed run_edge_audit hands to analyse_decay with the default settings.
AUDIT_DECAY_SEED = int(
    np.random.SeedSequence(20261103).spawn(8)[4].generate_state(1)[0]
)
J9_DETECTORS = ("rolling_rule", "cusum", "page_hinkley", "sprt")
UNAVAILABLE = "unavailable"  # a detector the audit reported as not run on this log


def reference_size(horizon: int) -> int:
    return horizon // 2


def change_after(horizon: int) -> int:
    return horizon // 4


def standard_noise(kind: str, rng: np.random.Generator, size: int) -> np.ndarray:
    """Unit-variance noise of the three null shapes."""

    if kind == "iid_normal":
        return rng.standard_normal(size)
    scale = math.sqrt(T_DF / (T_DF - 2.0))
    if kind == "student_t3":
        return rng.standard_t(T_DF, size) / scale
    if kind == "ar1_t3":
        shocks = rng.standard_t(T_DF, size + AR_BURN_IN) / scale
        values = np.empty_like(shocks)
        state = 0.0
        for index, shock in enumerate(shocks):
            state = PHI * state + shock
            values[index] = state
        return values[AR_BURN_IN:] * math.sqrt(1.0 - PHI * PHI)
    raise ValueError(kind)


def simulated_pnl(scenario: str, horizon: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(
        np.random.SeedSequence([ROOT_SEED, SCENARIO_CODES[scenario], horizon, seed])
    )
    total = reference_size(horizon) + horizon
    means = np.full(total, SHARPE)
    if scenario in CHANGES:
        means[reference_size(horizon) + change_after(horizon) :] *= CHANGES[scenario]
        noise = standard_noise("iid_normal", rng, total)
    else:
        noise = standard_noise(scenario, rng, total)
    return means + noise


@functools.lru_cache(maxsize=4)
def _exit_times(count: int) -> tuple[str, ...]:
    return tuple(f"t{index}" for index in range(count))


# --- before: J9 as shipped ---------------------------------------------------------


@functools.lru_cache(maxsize=4)
def _j9_calibration_paths(
    reference_trades: int, monitored_trades: int, draws: int, seed: int
) -> np.ndarray:
    """The z draws of j9_decay.calibrate_threshold, generated exactly as it does."""

    rng = np.random.default_rng(seed)
    reference = rng.standard_normal((draws, reference_trades))
    monitored = rng.standard_normal((draws, monitored_trades))
    mean = reference.mean(axis=1, keepdims=True)
    std = reference.std(axis=1, ddof=1, keepdims=True)
    return np.asfortranarray((monitored - mean) / std)


def _j9_threshold_cached(
    detector: str,
    *,
    reference_trades: int,
    monitored_trades: int,
    drift: float,
    false_alarm_probability: float,
    draws: int,
    seed: int,
) -> float:
    z = _j9_calibration_paths(reference_trades, monitored_trades, draws, seed)
    if detector == "cusum":
        maxima = j9_decay.cusum_lower(z, drift).max(axis=1)
    elif detector == "page_hinkley":
        maxima = j9_decay.page_hinkley_decrease(z, drift).max(axis=1)
    else:
        raise ValueError(f"unknown detector {detector!r}")
    return float(np.quantile(maxima, 1.0 - false_alarm_probability))


ORIGINAL_J9_THRESHOLD = j9_decay.calibrate_threshold


def _j9_analyse(pnl: np.ndarray) -> Any:
    return j9_decay.analyse_decay(
        pnl,
        _exit_times(pnl.size),
        reference_trades=None,
        shift_sigma=None,
        false_alarm_probability=0.05,
        sprt_alpha=0.01,
        sprt_beta=0.10,
        calibration_draws=2000,
        rolling_window=None,
        bootstrap_replications=2,
        mean_block_length=1,
        confidence_level=0.95,
        seed=AUDIT_DECAY_SEED,
    )


def before_one_log(scenario: str, horizon: int, seed: int) -> dict[str, Any]:
    pnl = simulated_pnl(scenario, horizon, seed)
    reference = reference_size(horizon)
    result = _j9_analyse(pnl)
    record: dict[str, Any] = {"seed": seed, "computed": result.status == "computed"}
    # The implicit rule a reader of J9's report applies: the w-trade rolling
    # expectancy (a window ending at a monitored trade) drops below zero.
    window = result.rolling_window
    rolling = np.asarray(result.rolling_expectancy)
    first = reference + 1 - window
    below = np.flatnonzero(rolling[first:] < 0.0)
    record["rolling_rule"] = None if below.size == 0 else int(below[0]) + 1
    for item in result.detectors:
        record[item.name] = (
            None
            if item.alarm_trade_number is None
            else item.alarm_trade_number - reference
        )
        if item.name == "sprt":
            record["sprt_single_cycle"] = (
                record["sprt"] if item.extra["intact_decisions"] == 0.0 else None
            )
    # Mechanism check: the same SPRT with the true mu0, sigma0 and delta.
    z_true = (pnl[reference:] - SHARPE) / 1.0
    alarm, _, accepted = j9_decay.sprt_decay(z_true, SHARPE, 0.01, 0.10)
    record["sprt_known_parameters"] = None if alarm is None else alarm + 1
    record["sprt_known_parameters_single_cycle"] = (
        None if alarm is None or accepted > 0 else alarm + 1
    )
    return record


def _before_task(task: tuple[str, int, int, int]) -> list[dict[str, Any]]:
    j9_decay.calibrate_threshold = _j9_threshold_cached
    scenario, horizon, start, stop = task
    return [before_one_log(scenario, horizon, seed) for seed in range(start, stop)]


def check_cached_j9_thresholds(horizons: tuple[int, ...]) -> list[dict[str, Any]]:
    """The cached thresholds equal J9's own calibrate_threshold, bit for bit."""

    checks = []
    for horizon in horizons:
        reference = reference_size(horizon)
        pnl = simulated_pnl("iid_normal", horizon, 0)
        mu0 = float(np.mean(pnl[:reference]))
        sigma0 = float(np.std(pnl[:reference], ddof=1))
        drift = mu0 / sigma0 / 2.0
        seeds = np.random.SeedSequence(AUDIT_DECAY_SEED).spawn(4)
        for name, child in (("cusum", seeds[1]), ("page_hinkley", seeds[2])):
            options = dict(
                reference_trades=reference,
                monitored_trades=horizon,
                drift=drift,
                false_alarm_probability=0.05,
                draws=2000,
                seed=int(child.generate_state(1)[0]),
            )
            original = ORIGINAL_J9_THRESHOLD(name, **options)
            cached = _j9_threshold_cached(name, **options)
            checks.append(
                {
                    "horizon": horizon,
                    "detector": name,
                    "j9": original,
                    "cached": cached,
                    "identical": original == cached,
                }
            )
    return checks


# --- after: the current package ----------------------------------------------------


def after_one_log(scenario: str, horizon: int, seed: int) -> dict[str, Any]:
    from backtest_auditor.edge_audit import decay as current

    pnl = simulated_pnl(scenario, horizon, seed)
    reference = reference_size(horizon)
    result = current.analyse_decay(
        pnl,
        _exit_times(pnl.size),
        reference_trades=None,
        shift_sigma=None,
        false_alarm_probability=0.05,
        horizon=horizon,
        rolling_window=None,
        bootstrap_replications=2,
        mean_block_length=1,
        confidence_level=0.95,
        seed=AUDIT_DECAY_SEED,
    )
    record: dict[str, Any] = {"seed": seed, "computed": result.status == "computed"}
    for item in result.detectors:
        if item.status != "computed":
            record[item.name] = UNAVAILABLE
            continue
        record[item.name] = (
            None
            if item.alarm_trade_number is None
            else item.alarm_trade_number - reference
        )
    if result.status == "computed":
        record.update(
            formula_thresholds(pnl, reference, horizon, result.rolling_window)
        )
    return record


def formula_thresholds(
    pnl: np.ndarray, reference: int, horizon: int, window: int
) -> dict[str, int | None]:
    """The same statistics with textbook thresholds instead of simulated ones."""

    from scipy.stats import norm

    from backtest_auditor.edge_audit import decay as current

    head, tail = pnl[:reference], pnl[reference:]
    mu0, sigma0 = float(np.mean(head)), float(np.std(head, ddof=1))
    z = (tail - mu0) / sigma0
    delta = mu0 / sigma0
    out: dict[str, int | None] = {}

    def first(path: np.ndarray, threshold: float) -> int | None:
        hits = np.flatnonzero(path > threshold)
        return None if hits.size == 0 else int(hits[0]) + 1

    # CUSUM: Siegmund's ARL0 formula solved for 5 % over the horizon (Poisson
    # stream of alarms, ARL0 = -N / ln 0.95), as DESIGN.md section 3.6 quotes.
    k = delta / 2.0
    target = -horizon / math.log(0.95)
    out["formula_cusum_siegmund"] = first(
        current.cusum_lower(z, k), siegmund_threshold(k, target)
    )
    # Mixture SPRT: Ville's inequality, log(1/alpha) - exact for known mu0, sigma0.
    out["formula_mixture_sprt_ville"] = first(
        current.mixture_sprt_log_lr(z, delta), math.log(1.0 / 0.05)
    )
    z_known = (tail - SHARPE) / 1.0
    out["formula_mixture_sprt_ville_known_parameters"] = first(
        current.mixture_sprt_log_lr(z_known, SHARPE), math.log(1.0 / 0.05)
    )
    # Rolling expectancy: a one-sided 5 % normal threshold for each window.
    out["formula_rolling_per_window_5pct"] = first(
        current.rolling_drop(z, window), float(norm.ppf(0.95))
    )
    return out


def siegmund_threshold(k: float, target_arl: float) -> float:
    """h with Siegmund's ARL0(h) = (exp(2kb) - 2kb - 1) / (2k^2) = target, b = h + 1.166."""

    def arl(h: float) -> float:
        b = h + 1.166
        return (math.exp(2.0 * k * b) - 2.0 * k * b - 1.0) / (2.0 * k * k)

    low, high = 0.0, 1.0
    while arl(high) < target_arl:
        high *= 2.0
    for _ in range(200):
        middle = (low + high) / 2.0
        if arl(middle) < target_arl:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _after_task(task: tuple[str, int, int, int]) -> list[dict[str, Any]]:
    scenario, horizon, start, stop = task
    return [after_one_log(scenario, horizon, seed) for seed in range(start, stop)]


# --- aggregation ---------------------------------------------------------------------


def wilson(hits: int, count: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if count == 0:
        return (math.nan, math.nan)
    p = hits / count
    denominator = 1.0 + z * z / count
    centre = (p + z * z / (2.0 * count)) / denominator
    half = (
        z
        * math.sqrt(p * (1.0 - p) / count + z * z / (4.0 * count * count))
        / denominator
    )
    return (max(0.0, centre - half), min(1.0, centre + half))


def summarise(
    records: list[dict[str, Any]], scenario: str, horizon: int
) -> dict[str, Any]:
    computed = [record for record in records if record["computed"]]
    names = sorted(
        {key for record in computed for key in record} - {"seed", "computed"}
    )
    out: dict[str, Any] = {
        "logs": len(records),
        "detectors_run": len(computed),
        "detectors_not_run": len(records) - len(computed),
        "detectors": {},
    }
    for name in names:
        ran = [record for record in computed if record.get(name) != UNAVAILABLE]
        alarms = [record.get(name) for record in ran]
        if scenario in CHANGES:
            out["detectors"][name] = delay_summary(
                alarms, change_after(horizon), horizon
            )
        else:
            hits = sum(alarm is not None for alarm in alarms)
            out["detectors"][name] = {
                "logs": len(alarms),
                "false_alarms": hits,
                "rate": hits / len(alarms) if alarms else math.nan,
                "wilson95": wilson(hits, len(alarms)),
            }
        out["detectors"][name]["unavailable"] = len(computed) - len(ran)
    return out


def delay_summary(
    alarms: list[int | None], change: int, horizon: int
) -> dict[str, Any]:
    early = [alarm for alarm in alarms if alarm is not None and alarm <= change]
    rest = [alarm for alarm in alarms if alarm is None or alarm > change]
    delays = np.array(
        [math.inf if alarm is None else float(alarm - change) for alarm in rest]
    )
    detected = int(np.isfinite(delays).sum())
    summary: dict[str, Any] = {
        "logs": len(alarms),
        "alarm_before_change": len(early),
        "alarm_before_change_rate": len(early) / len(alarms),
        "detected_after_change": detected,
        "detected_rate_among_no_early_alarm": detected / len(rest)
        if rest
        else math.nan,
        "post_change_trades": horizon - change,
    }
    for label, q in (("delay_median", 50), ("delay_p90", 90)):
        value = (
            float(np.percentile(delays, q, method="inverted_cdf")) if rest else math.nan
        )
        summary[label] = None if not math.isfinite(value) else value
    return summary


def run(which: str, seeds: int, workers: int, horizons: tuple[int, ...]) -> Path:
    task_function: Callable[[tuple[str, int, int, int]], list[dict[str, Any]]]
    task_function = _before_task if which == "before" else _after_task
    scenarios = [*NULLS, *CHANGES]
    chunk = 50
    tasks = [
        (scenario, horizon, start, min(start + chunk, seeds))
        for horizon in sorted(horizons, reverse=True)
        for scenario in scenarios
        for start in range(0, seeds, chunk)
    ]
    started = time.time()
    collected: dict[tuple[str, int], list[dict[str, Any]]] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for task, records in zip(tasks, pool.map(task_function, tasks), strict=True):
            collected.setdefault((task[0], task[1]), []).extend(records)
    results: dict[str, Any] = {
        "which": which,
        "seeds_per_scenario": seeds,
        "sharpe_per_trade": SHARPE,
        "geometry": "R = N/2 reference trades, N monitored trades; changes after N/4",
        "horizons": list(horizons),
        "seconds": round(time.time() - started, 1),
        "scenarios": {},
    }
    if which == "before":
        results["cached_threshold_check"] = check_cached_j9_thresholds(horizons)
    for (scenario, horizon), records in sorted(collected.items()):
        records.sort(key=lambda record: record["seed"])
        results["scenarios"][f"{scenario}/{horizon}"] = summarise(
            records, scenario, horizon
        )
    path = HERE / f"results_{which}.json"
    path.write_text(
        json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("which", choices=("before", "after"))
    runner.add_argument("--seeds", type=int, default=2000)
    runner.add_argument("--workers", type=int, default=4)
    runner.add_argument("--horizons", default=",".join(map(str, HORIZONS)))
    commands.add_parser("report")
    args = parser.parse_args(argv)
    if args.command == "run":
        horizons = tuple(int(value) for value in args.horizons.split(","))
        path = run(args.which, args.seeds, args.workers, horizons)
        print(f"wrote {path}")
        return 0
    from report_tables import write_report  # noqa: PLC0415

    write_report(HERE, FIGURES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
