import numpy as np


def has_zero_sample_variation(values: np.ndarray) -> bool:
    """Return whether every supplied observation is bit-identical.

    Exact comparisons against ``0.0`` cannot be used to detect a constant
    return series. ``np.std([0.001] * 10, ddof=1)`` is ``2.29e-19`` rather
    than ``0.0``: ``0.001`` has no exact binary representation, so centring
    the sample leaves a non-zero rounding residue. A guard written as
    ``std != 0.0`` therefore admits a constant series and divides by that
    residue, which is how a flat return stream acquires an annualized Sharpe
    ratio of ``7.3e16``.

    The predicate is structural rather than tolerance based. It is true only
    when the sample spans a single value, which is precisely the documented
    condition "all supplied returns have zero sample variation". No genuinely
    varying series can satisfy it, so no published statistic changes for any
    input that was previously handled correctly.
    """

    return values.size > 0 and bool(np.ptp(values) == 0.0)


def columns_with_zero_sample_variation(values: np.ndarray) -> np.ndarray:
    """Column-wise :func:`has_zero_sample_variation` for observations x trials.

    Experiment-family scores are computed for every trial at once, once per
    CSCV split, so a per-column Python loop would run hundreds of thousands of
    times. This is the same structural test, vectorized, and agrees with the
    scalar form column by column, including an empty column being not flat.
    """

    if values.shape[0] == 0:
        return np.zeros(values.shape[1], dtype=bool)
    return np.ptp(values, axis=0) == 0.0
