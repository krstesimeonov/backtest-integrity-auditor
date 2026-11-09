import math

import numpy as np
import pandas as pd

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.results import (
    PerformancePathResult,
    SamplingAssessmentResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.return_basis import to_simple_returns


def anchored_drawdown_path(
    wealth: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Wealth, running peaks and drawdowns with the starting wealth prepended.

    Element 0 is the starting wealth of 1.0 and element i is observation i-1.
    The anchor counts as the first peak, so a series that opens with a loss is
    already in drawdown at its first observation. The audited maximum drawdown
    and the web app's drawdown chart both come from here, so they cannot
    disagree.
    """

    extended_wealth = np.concatenate(([1.0], wealth))
    running_peaks = np.maximum.accumulate(extended_wealth)
    return extended_wealth, running_peaks, extended_wealth / running_peaks - 1.0


def calculate_performance_path(
    series: ReturnSeries,
    sampling: SamplingAssessmentResult,
) -> PerformancePathResult:
    """Calculate a bounded set of wealth and drawdown evidence."""

    simple_returns = to_simple_returns(series)
    with np.errstate(over="ignore", invalid="ignore"):
        wealth = np.cumprod(1.0 + simple_returns)

    if not np.all(np.isfinite(wealth)):
        # The compounded wealth path overflowed float64, so every drawdown
        # quantity derives from inf/inf = nan. Publishing nan aborts JSON
        # serialisation (allow_nan=False); every field here is nullable in the
        # published schema, so report the path as undefined instead.
        return PerformancePathResult(
            observation_count=len(simple_returns),
            return_basis=ReturnConvention.SIMPLE,
            periods_per_year=(
                sampling.periods_per_year if sampling.annualization_eligible else None
            ),
            starting_wealth=1.0,
            ending_wealth=None,
            cumulative_simple_return=None,
            cagr=None,
            maximum_drawdown=None,
            maximum_drawdown_peak_timestamp=None,
            maximum_drawdown_trough_timestamp=None,
            maximum_drawdown_recovery_timestamp=None,
            maximum_drawdown_recovered=None,
            maximum_drawdown_duration_observations=None,
            longest_time_underwater_observations=None,
            longest_time_underwater_start_timestamp=None,
            longest_time_underwater_end_timestamp=None,
        )

    extended_wealth, running_peaks, drawdowns = anchored_drawdown_path(wealth)

    trough_extended_index = int(np.argmin(drawdowns))
    maximum_drawdown = float(drawdowns[trough_extended_index])

    if maximum_drawdown == 0.0:
        peak_timestamp = series.timestamps[0]
        trough_timestamp = series.timestamps[0]
        recovery_timestamp = series.timestamps[0]
        maximum_drawdown_duration = 0
    else:
        peak_wealth = running_peaks[trough_extended_index]
        peak_candidates = np.flatnonzero(
            extended_wealth[: trough_extended_index + 1] == peak_wealth
        )
        peak_extended_index = int(peak_candidates[-1])
        peak_timestamp = (
            None
            if peak_extended_index == 0
            else series.timestamps[peak_extended_index - 1]
        )
        trough_timestamp = series.timestamps[trough_extended_index - 1]

        recovery_candidates = np.flatnonzero(
            extended_wealth[trough_extended_index + 1 :] >= peak_wealth
        )
        if recovery_candidates.size:
            recovery_extended_index = (
                trough_extended_index + 1 + int(recovery_candidates[0])
            )
            recovery_timestamp = series.timestamps[recovery_extended_index - 1]
            maximum_drawdown_duration = recovery_extended_index - peak_extended_index
        else:
            recovery_timestamp = None
            maximum_drawdown_duration = len(series.timestamps) - peak_extended_index

    (
        longest_underwater,
        underwater_start,
        underwater_end,
    ) = _longest_underwater_run(series, wealth)

    periods_per_year = (
        sampling.periods_per_year if sampling.annualization_eligible else None
    )
    ending_wealth: float | None = float(wealth[-1])
    cagr = None
    if (
        periods_per_year is not None
        and ending_wealth is not None
        and ending_wealth > 0.0
    ):
        # A short, strongly compounding sample raised to an intraday
        # periods-per-year overflows a float64 and took down the whole audit
        # with an uncaught OverflowError. cagr is already optional, so an
        # unrepresentable growth rate is reported as undefined.
        try:
            candidate = float(
                ending_wealth ** (periods_per_year / len(simple_returns)) - 1.0
            )
        except OverflowError:
            candidate = float("inf")
        cagr = candidate if math.isfinite(candidate) else None

    return PerformancePathResult(
        observation_count=len(simple_returns),
        return_basis=ReturnConvention.SIMPLE,
        periods_per_year=periods_per_year,
        starting_wealth=1.0,
        ending_wealth=ending_wealth,
        cumulative_simple_return=(
            None if ending_wealth is None else ending_wealth - 1.0
        ),
        cagr=cagr,
        maximum_drawdown=maximum_drawdown,
        maximum_drawdown_peak_timestamp=peak_timestamp,
        maximum_drawdown_trough_timestamp=trough_timestamp,
        maximum_drawdown_recovery_timestamp=recovery_timestamp,
        maximum_drawdown_recovered=(recovery_timestamp is not None),
        maximum_drawdown_duration_observations=(maximum_drawdown_duration),
        longest_time_underwater_observations=longest_underwater,
        longest_time_underwater_start_timestamp=underwater_start,
        longest_time_underwater_end_timestamp=underwater_end,
    )


def _longest_underwater_run(
    series: ReturnSeries,
    wealth: np.ndarray,
) -> tuple[int, pd.Timestamp | None, pd.Timestamp | None]:
    running_peak = 1.0
    current_start: int | None = None
    best_start: int | None = None
    best_end: int | None = None
    best_length = 0

    for index, current_wealth in enumerate(wealth):
        if current_wealth >= running_peak:
            running_peak = float(current_wealth)
            current_start = None
            continue

        if current_start is None:
            current_start = index
        current_length = index - current_start + 1
        if current_length > best_length:
            best_length = current_length
            best_start = current_start
            best_end = index

    return (
        best_length,
        None if best_start is None else series.timestamps[best_start],
        None if best_end is None else series.timestamps[best_end],
    )
