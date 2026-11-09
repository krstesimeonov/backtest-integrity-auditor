#!/usr/bin/env python3
"""Leave-one-out error of interpolating the threshold table along each axis.

For every interior grid point, the stored threshold is predicted from its two
neighbours along one axis (twice the real grid spacing, so this overstates
the error of the audit's interpolation) by linear interpolation of either the
threshold h or log h, in the audit's coordinates (1/√R, ln δ or ln w, ln N,
ln α). Prints the root-mean-square and largest relative errors. The audit
interpolates log h (decay.threshold).

    .venv/bin/python docs/edge_audit/calibration/interpolation_loo.py
"""

from __future__ import annotations

import itertools

import numpy as np

from backtest_auditor.edge_audit.decay import DETECTORS, threshold_table


def coordinates(table, name: str, axis: int) -> np.ndarray:
    if axis == 0:
        return 1.0 / np.sqrt(table.reference_trades)
    if axis == 1:
        return np.log(table.parameters[name])
    if axis == 2:
        return np.log(table.horizons)
    return np.log(table.alphas)


def leave_one_out(name: str, axis: int, logarithm: bool) -> tuple[float, float, int]:
    table = threshold_table()
    values = table.values[name]
    x = coordinates(table, name, axis)
    errors = []
    for index in itertools.product(*[range(size) for size in values.shape]):
        i = index[axis]
        if i == 0 or i == values.shape[axis] - 1:
            continue
        below, above = list(index), list(index)
        below[axis], above[axis] = i - 1, i + 1
        y0, y1, y2 = values[tuple(below)], values[index], values[tuple(above)]
        if not np.all(np.isfinite([y0, y1, y2])):
            continue
        weight = (x[i] - x[i - 1]) / (x[i + 1] - x[i - 1])
        if logarithm:
            predicted = np.exp((1 - weight) * np.log(y0) + weight * np.log(y2))
        else:
            predicted = (1 - weight) * y0 + weight * y2
        errors.append(predicted / y1 - 1.0)
    errors_array = np.array(errors)
    return (
        float(np.sqrt(np.mean(errors_array**2))),
        float(np.max(np.abs(errors_array))),
        errors_array.size,
    )


def main() -> None:
    axes = ("R (1/√R)", "δ or w (ln)", "N (ln)", "α (ln)")
    print("detector | axis | interior points | rms h | rms log h | max h | max log h")
    for name in DETECTORS:
        for axis, label in enumerate(axes):
            rms_h, max_h, count = leave_one_out(name, axis, False)
            rms_log, max_log, _ = leave_one_out(name, axis, True)
            print(
                f"{name} | {label} | {count} | {100 * rms_h:.1f} % | {100 * rms_log:.1f} % | "
                f"{100 * max_h:.1f} % | {100 * max_log:.1f} %"
            )


if __name__ == "__main__":
    main()
