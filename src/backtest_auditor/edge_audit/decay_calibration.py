"""The decay-detector threshold table: simulation, grid, generation and checks.

One command regenerates the table the audit reads (``decay_thresholds.py``):

    python -m backtest_auditor.edge_audit.decay_calibration --write [--workers 4]

``--spot-check`` re-simulates a few cells (seconds) and compares them with the
stored table; ``--check`` regenerates the whole table in memory and compares
(as long as ``--write``). Every cell is the (1 - α) quantile of the largest
detector statistic within the first N monitored trades over ``PATHS`` paths
simulated under the calibration null: i.i.d. normal trades without a change,
whose reference mean and SD are re-estimated from R trades in every path.
"""

from __future__ import annotations

import argparse
import importlib
import math
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from itertools import pairwise
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.stats import chi2

from backtest_auditor.edge_audit.decay import (
    CALIBRATION_NULL,
    DETECTORS,
    detector_statistic,
    table_content_sha256,
)

TABLE_ID = "edge-audit-decay-thresholds/1"
NULL = CALIBRATION_NULL
SEED = 20261102
PATHS = 40_000
CHUNK = 2_500
BLOCK = 500
ALPHAS = (0.005, 0.01, 0.02, 0.05, 0.1, 0.2)
HORIZONS = (
    30,
    50,
    75,
    100,
    150,
    200,
    300,
    400,
    500,
    700,
    1000,
    1500,
    2000,
    3000,
    4000,
    6000,
    10000,
)
REFERENCE_TRADES = (
    30.0,
    50.0,
    75.0,
    100.0,
    150.0,
    200.0,
    300.0,
    400.0,
    600.0,
    1000.0,
    1500.0,
    3000.0,
    6000.0,
    math.inf,
)
SHIFTS = (0.02, 0.03, 0.05, 0.07, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1.0, 2.0)
WINDOWS = (10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0)
PARAMETERS = {
    "rolling_expectancy": WINDOWS,
    "cusum": SHIFTS,
    "page_hinkley": SHIFTS,
    "mixture_sprt": SHIFTS,
}
TABLE_PATH = Path(__file__).resolve().parent / "decay_thresholds.py"
REGENERATE = "python -m backtest_auditor.edge_audit.decay_calibration --write"


def reference_estimates(
    reference_trades: float, size: int, seed: int, chunk: int
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Mean and SD of R i.i.d. N(0, 1) reference trades, drawn exactly.

    For normal trades the sample mean is N(0, 1/R) and (R - 1)·SD² is χ²(R - 1),
    independently. The same two uniforms drive every R (common random numbers
    across the R grid). R = inf means μ0 and σ0 known: mean 0, SD 1.
    """

    rng = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(chunk, 0)))
    normal = rng.standard_normal(size)
    uniform = np.maximum(rng.random(size), np.finfo(np.float64).tiny)
    if math.isinf(reference_trades):
        return np.zeros(size), np.ones(size)
    freedom = reference_trades - 1.0
    mean = normal / math.sqrt(reference_trades)
    std = np.sqrt(chi2.ppf(uniform, freedom) / freedom)
    return mean, std


def monitored_draws(
    size: int, length: int, seed: int, chunk: int
) -> NDArray[np.float64]:
    """N(0, 1) trades, (size, length), Fortran order, in blocks of BLOCK steps.

    Each block has its own seed, so the first n steps are the same whatever
    the longest horizon requested (cheap spot checks of short horizons).
    """

    out = np.empty((size, length), dtype=np.float64, order="F")
    for block, start in enumerate(range(0, length, BLOCK)):
        rng = np.random.default_rng(
            np.random.SeedSequence(seed, spawn_key=(chunk, 1 + block))
        )
        values = rng.standard_normal((size, BLOCK))
        stop = min(start + BLOCK, length)
        out[:, start:stop] = values[:, : stop - start]
    return out


def running_maxima(
    path: NDArray[np.float64], horizons: NDArray[np.int64]
) -> NDArray[np.float64]:
    """Largest value of each row within the first h steps, for every h."""

    edges = np.concatenate(([0], horizons))
    blocks = np.stack([path[:, a:b].max(axis=1) for a, b in pairwise(edges)], axis=1)
    return np.maximum.accumulate(blocks, axis=1)


def simulate_null_maxima(
    detector: str,
    *,
    reference_trades: float,
    parameters: Sequence[float],
    horizons: Sequence[int],
    paths: int,
    seed: int,
) -> NDArray[np.float64]:
    """Largest detector statistic within each horizon, under the calibration null.

    Returns an array (len(parameters), paths, len(horizons)). In every path:
    draw the reference mean and SD of R normal trades, draw the monitored
    trades, standardise them with the reference estimates exactly as the audit
    does, run the detector and keep the running maximum of its statistic. The
    threshold for α at horizon N is the (1 - α) quantile over paths.

    [HAND-WRITE] Write the plain version: a loop over paths that draws R
    reference trades and N monitored trades, standardises, calls
    ``detector_statistic`` and records the maximum. Then explain why the
    reference has to be re-drawn in every path (what goes wrong at N = 4,000
    if μ0 and σ0 are treated as known).
    """

    horizon_array = np.array(sorted(horizons), dtype=np.int64)
    longest = int(horizon_array[-1])
    maxima = np.empty((len(parameters), paths, horizon_array.size))
    for chunk, start in enumerate(range(0, paths, CHUNK)):
        size = min(CHUNK, paths - start)
        mean, std = reference_estimates(reference_trades, size, seed, chunk)
        trades = monitored_draws(size, longest, seed, chunk)
        z = np.asfortranarray((trades - mean[:, None]) / std[:, None])
        for index, parameter in enumerate(parameters):
            path = detector_statistic(detector, z, parameter)
            maxima[index, start : start + size] = running_maxima(path, horizon_array)
    return maxima


def thresholds_from_maxima(
    maxima: NDArray[np.float64], alphas: Sequence[float]
) -> NDArray[np.float64]:
    """(parameters, paths, horizons) maxima -> (parameters, horizons, alphas) thresholds."""

    with np.errstate(invalid="ignore"):  # -inf maxima: rolling window > horizon
        levels = np.quantile(maxima, 1.0 - np.asarray(alphas), axis=1)
    return np.moveaxis(levels, 0, -1)


def build_cells(
    task: tuple[str, float, tuple[int, ...], int],
) -> NDArray[np.float64]:
    """Thresholds (parameters, horizons, alphas) of one detector at one R."""

    detector, reference_trades, horizons, paths = task
    parameters = PARAMETERS[detector]
    maxima = simulate_null_maxima(
        detector,
        reference_trades=reference_trades,
        parameters=parameters,
        horizons=horizons,
        paths=paths,
        seed=SEED,
    )
    levels = thresholds_from_maxima(maxima, ALPHAS)
    if detector == "rolling_expectancy":
        for index, window in enumerate(parameters):
            short = np.array(horizons) < window
            levels[index, short, :] = np.nan
    return levels


def _cached_cells(
    task: tuple[str, float, tuple[int, ...], int], cache: str | None
) -> NDArray[np.float64]:
    """build_cells, saved to / loaded from ``cache`` (cells are deterministic)."""

    if cache is None:
        return build_cells(task)
    detector, reference, horizons, paths = task
    path = Path(cache) / f"{detector}_R{reference}_P{paths}_N{horizons[-1]}.npy"
    if path.is_file():
        return np.load(path)
    levels = build_cells(task)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, levels)
    return levels


def _cached_task(
    item: tuple[tuple[str, float, tuple[int, ...], int], str | None],
) -> NDArray[np.float64]:
    return _cached_cells(*item)


def build_table(
    workers: int, paths: int = PATHS, cache: str | None = None
) -> dict[str, NDArray[np.float64]]:
    # The slowest cells first, so the pool is not left waiting on one task.
    order = {"mixture_sprt": 0, "page_hinkley": 1, "cusum": 2, "rolling_expectancy": 3}
    tasks = sorted(
        (
            (detector, reference, HORIZONS, paths)
            for detector in DETECTORS
            for reference in REFERENCE_TRADES
        ),
        key=lambda task: order[task[0]],
    )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        cells = list(pool.map(_cached_task, [(task, cache) for task in tasks]))
    table: dict[str, NDArray[np.float64]] = {}
    for detector in DETECTORS:
        table[detector] = np.stack(
            [
                cell
                for task, cell in zip(tasks, cells, strict=True)
                if task[0] == detector
            ]
        )
    return table


def format_value(value: float) -> str:
    return "nan" if math.isnan(value) else f"{value:.6g}"


def render_blocks(table: dict[str, NDArray[np.float64]]) -> dict[str, str]:
    """One text line per (R, parameter, N), the α values across."""

    blocks = {}
    for detector in DETECTORS:
        values = table[detector]
        lines = [
            " ".join(format_value(float(value)) for value in values[r, p, n])
            for r in range(values.shape[0])
            for p in range(values.shape[1])
            for n in range(values.shape[2])
        ]
        blocks[detector] = "\n" + "\n".join(lines) + "\n"
    return blocks


def _exploded(name: str, values: Sequence[float]) -> list[str]:
    items = ["math.inf" if math.isinf(value) else repr(value) for value in values]
    return [f"{name} = (", *[f"    {item}," for item in items], ")"]


def render_module(
    table: dict[str, NDArray[np.float64]], seconds: float, paths: int = PATHS
) -> str:
    blocks = render_blocks(table)
    content = table_content_sha256(
        ALPHAS, HORIZONS, REFERENCE_TRADES, PARAMETERS, blocks
    )
    parameter_lines = []
    for name, values in PARAMETERS.items():
        parameter_lines += [
            f'    "{name}": (',
            *[f"        {v!r}," for v in values],
            "    ),",
        ]
    parts = [
        f'"""Decay-detector thresholds. GENERATED by `{REGENERATE}`;',
        "do not edit (the audit refuses a table whose content hash does not match).",
        "",
        "THRESHOLDS[detector] holds one line per (R, parameter, N), in the order of",
        "REFERENCE_TRADES, PARAMETERS[detector] and HORIZONS; each line gives the",
        "threshold for every α in ALPHAS. Under the calibration null (NULL) the",
        "probability of any alarm within the first N monitored trades is α, up to",
        f"Monte Carlo error over PATHS paths. Generation took {seconds:.0f} s.",
        '"""',
        "",
        "import math",
        "",
        f'TABLE_ID = "{TABLE_ID}"',
        f'NULL = "{NULL}"',
        f"SEED = {SEED}",
        f"PATHS = {paths}",
        *_exploded("ALPHAS", ALPHAS),
        *_exploded("HORIZONS", HORIZONS),
        *_exploded("REFERENCE_TRADES", REFERENCE_TRADES),
        "PARAMETERS = {",
        *parameter_lines,
        "}",
        f'CONTENT_SHA256 = "{content}"',
        "THRESHOLDS = {",
    ]
    for detector in DETECTORS:
        parts.append(f'    "{detector}": """{blocks[detector]}""",')
    parts.append("}")
    return "\n".join(parts) + "\n"


def stored_values() -> dict[str, NDArray[np.float64]]:
    from backtest_auditor.edge_audit.decay import threshold_table

    return threshold_table().values


def stored_paths() -> int:
    from backtest_auditor.edge_audit.decay import TABLE_MODULE

    return int(importlib.import_module(TABLE_MODULE).PATHS)


def spot_check(
    cells: Sequence[tuple[str, float]], horizons: Sequence[int]
) -> list[str]:
    """Re-simulate (detector, R) cells at short horizons; list every mismatch.

    The draws of the first n steps do not depend on the longest horizon, so a
    cell recomputed for horizons <= n must equal the stored text exactly.
    """

    stored = stored_values()
    paths = stored_paths()
    columns = [HORIZONS.index(h) for h in horizons]
    problems = []
    for detector, reference in cells:
        levels = thresholds_from_maxima(
            simulate_null_maxima(
                detector,
                reference_trades=reference,
                parameters=PARAMETERS[detector],
                horizons=horizons,
                paths=paths,
                seed=SEED,
            ),
            ALPHAS,
        )
        if detector == "rolling_expectancy":
            for index, window in enumerate(PARAMETERS[detector]):
                levels[index, np.array(horizons) < window, :] = np.nan
        r = REFERENCE_TRADES.index(reference)
        for p in range(len(PARAMETERS[detector])):
            for column, n in enumerate(columns):
                for a in range(len(ALPHAS)):
                    fresh = format_value(float(levels[p, column, a]))
                    kept = format_value(float(stored[detector][r, p, n, a]))
                    if fresh != kept:
                        problems.append(
                            f"{detector} R={reference} parameter={PARAMETERS[detector][p]} "
                            f"N={HORIZONS[n]} alpha={ALPHAS[a]}: table {kept}, simulation {fresh}"
                        )
    return problems


SPOT_CELLS = (
    ("rolling_expectancy", 200.0),
    ("cusum", 50.0),
    ("cusum", math.inf),
    ("page_hinkley", 400.0),
    ("mixture_sprt", 100.0),
)
SPOT_HORIZONS = (30, 50, 75, 100, 150, 200, 300, 400)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backtest_auditor.edge_audit.decay_calibration",
        description="Regenerate or check the decay-detector threshold table.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--write", action="store_true", help=f"rewrite {TABLE_PATH.name}"
    )
    action.add_argument("--check", action="store_true", help="regenerate and compare")
    action.add_argument(
        "--spot-check", action="store_true", help="re-simulate a few cells"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--cache",
        help="directory for finished cells, so an interrupted --write resumes",
    )
    parser.add_argument(
        "--paths",
        type=int,
        default=PATHS,
        help=f"paths per cell (default {PATHS:,}; the tests require the default)",
    )
    args = parser.parse_args(argv)
    if args.spot_check:
        problems = spot_check(SPOT_CELLS, SPOT_HORIZONS)
        print("\n".join(problems) if problems else "spot check: every cell matches")
        return 1 if problems else 0
    started = time.time()
    paths = args.paths if args.write else stored_paths()
    table = build_table(args.workers, paths, args.cache)
    text = render_module(table, time.time() - started, paths)
    if args.write:
        TABLE_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {TABLE_PATH} in {time.time() - started:.0f} s")
        return 0
    stored = stored_values()
    fresh = render_blocks(table)
    kept = render_blocks(stored)
    same = all(fresh[name] == kept[name] for name in DETECTORS)
    print("table is current" if same else f"table is stale: run {REGENERATE}")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
