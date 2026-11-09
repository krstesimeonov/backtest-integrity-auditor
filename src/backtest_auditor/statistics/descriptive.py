import math

import numpy as np

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.results import (
    DescriptiveStatisticsResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation


def calculate_descriptive_statistics(
    series: ReturnSeries,
) -> DescriptiveStatisticsResult:
    values = series.values
    observation_count = len(values)

    with np.errstate(over="ignore", invalid="ignore"):
        mean_return = _finite_or_none(float(np.mean(values)))

    if observation_count < 2:
        sample_volatility = None
    elif has_zero_sample_variation(values):
        # The sample standard deviation of a constant series is exactly zero;
        # np.std returns a rounding residue (2.3e-19 for a constant 0.001).
        # Publishing the residue also silently disables every downstream
        # `== 0.0` zero-variance gate, so normalise it here at the source.
        sample_volatility = 0.0
    else:
        with np.errstate(over="ignore", invalid="ignore"):
            sample_volatility = _finite_or_none(float(np.std(values, ddof=1)))

    minimum_return = float(np.min(values))
    maximum_return = float(np.max(values))

    cumulative_simple_return = _calculate_cumulative_simple_return(
        values,
        series.convention,
    )

    return DescriptiveStatisticsResult(
        observation_count=observation_count,
        start_timestamp=series.timestamps[0],
        end_timestamp=series.timestamps[-1],
        mean_return=mean_return,
        sample_volatility=sample_volatility,
        minimum_return=minimum_return,
        maximum_return=maximum_return,
        cumulative_simple_return=cumulative_simple_return,
        return_convention=series.convention,
    )


def _finite_or_none(value: float) -> float | None:
    """Report an unrepresentable aggregate as undefined rather than inf/nan.

    json.dumps uses allow_nan=False, so a single inf anywhere in the report
    aborts serialisation of every other section that computed correctly. All
    of these fields are nullable in the published schema.
    """

    return value if math.isfinite(value) else None


def _calculate_cumulative_simple_return(
    values: np.ndarray,
    convention: ReturnConvention,
) -> float | None:
    if convention is ReturnConvention.SIMPLE:
        if np.any(values == -1.0):
            return -1.0

        cumulative_log_growth = np.sum(np.log1p(values))

    else:
        cumulative_log_growth = np.sum(values)

    # Summed log growth above ~709.78 overflows float64 to inf, which then
    # reaches json.dumps(allow_nan=False) and aborts the whole report with an
    # uncaught ValueError. bootstrap.py already guards the identical
    # computation this way; the field is nullable in the published schema.
    with np.errstate(over="ignore", invalid="ignore"):
        result = float(np.expm1(cumulative_log_growth))
    return result if math.isfinite(result) else None
