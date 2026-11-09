import math
from typing import Any

import numpy as np

from backtest_auditor.domain.assumptions import BootstrapSpec
from backtest_auditor.domain.enums import (
    BootstrapMethod,
    BootstrapMetric,
    BootstrapMetricStatus,
    BootstrapStatus,
    FrequencyStatus,
    HACKernel,
    ReturnConvention,
)
from backtest_auditor.domain.results import (
    AnnualizedStatisticsResult,
    BootstrapMetricResult,
    BootstrapResult,
    SamplingAssessmentResult,
    SerialAdjustmentResult,
)
from backtest_auditor.domain.series import ReturnSeries
from backtest_auditor.statistics.degeneracy import has_zero_sample_variation
from backtest_auditor.statistics.return_basis import (
    to_simple_returns,
)
from backtest_auditor.statistics.resampling import stationary_bootstrap_indices
from backtest_auditor.statistics.serial_adjustment import (
    calculate_bartlett_hac_ratio,
)

_REGULAR_SAMPLING_STATUSES = {
    FrequencyStatus.DECLARED,
    FrequencyStatus.INFERRED_REGULAR,
    FrequencyStatus.CALENDAR_VERIFIED,
}

_METRIC_ORDER = (
    BootstrapMetric.PERIOD_MEAN_RETURN,
    BootstrapMetric.PERIOD_SAMPLE_VOLATILITY,
    BootstrapMetric.FIXED_HORIZON_CUMULATIVE_SIMPLE_RETURN,
    BootstrapMetric.ANNUALIZED_ARITHMETIC_MEAN_RETURN,
    BootstrapMetric.IID_ANNUALIZED_SAMPLE_VOLATILITY,
    BootstrapMetric.PERIOD_SHARPE_RATIO,
    BootstrapMetric.IID_ANNUALIZED_SHARPE_RATIO,
    BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO,
)


def calculate_bootstrap_confidence_intervals(
    series: ReturnSeries,
    sampling: SamplingAssessmentResult,
    annualized: AnnualizedStatisticsResult | None,
    serial_adjustment: SerialAdjustmentResult | None,
    *,
    spec: BootstrapSpec | None = None,
) -> BootstrapResult | None:
    """Calculate deterministic block-bootstrap percentile intervals."""

    if spec is None:
        return None

    values = to_simple_returns(series)
    observation_count = int(values.size)
    lower_quantile = (1.0 - spec.confidence_level) / 2.0
    upper_quantile = 1.0 - lower_quantile

    common: dict[str, Any] = {
        "observation_count": observation_count,
        "return_basis": ReturnConvention.SIMPLE,
        "method": spec.method,
        "interval_method": spec.interval_method,
        "replications": spec.replications,
        "confidence_level": spec.confidence_level,
        "lower_quantile": lower_quantile,
        "upper_quantile": upper_quantile,
        "block_length": spec.block_length,
        "random_seed": spec.random_seed,
        "periods_per_year": (
            None if annualized is None else annualized.periods_per_year
        ),
        "hac_maximum_lag": (
            None if serial_adjustment is None else serial_adjustment.maximum_lag
        ),
        "hac_kernel": (None if serial_adjustment is None else serial_adjustment.kernel),
    }

    if sampling.status not in _REGULAR_SAMPLING_STATUSES:
        return BootstrapResult(
            status=BootstrapStatus.SAMPLING_INELIGIBLE,
            overlapping_block_count=None,
            blocks_per_replication=None,
            metrics=(),
            **common,
        )

    if observation_count < 2:
        return BootstrapResult(
            status=BootstrapStatus.INSUFFICIENT_OBSERVATIONS,
            overlapping_block_count=None,
            blocks_per_replication=None,
            metrics=(),
            **common,
        )

    if spec.block_length >= observation_count:
        return BootstrapResult(
            status=(BootstrapStatus.BLOCK_LENGTH_NOT_BELOW_OBSERVATION_COUNT),
            overlapping_block_count=None,
            blocks_per_replication=None,
            metrics=(),
            **common,
        )

    blocks_per_replication = (
        math.ceil(observation_count / spec.block_length)
        if spec.method is BootstrapMethod.MOVING_BLOCK
        else None
    )
    overlapping_block_count = (
        observation_count - spec.block_length + 1
        if spec.method is BootstrapMethod.MOVING_BLOCK
        else None
    )

    point_estimates = _point_estimates(
        values,
        annualized=annualized,
        serial_adjustment=serial_adjustment,
    )
    distributions: dict[BootstrapMetric, list[float]] = {
        metric: [] for metric in _METRIC_ORDER
    }
    attempted_replications = {metric: 0 for metric in _METRIC_ORDER}

    random_generator = np.random.default_rng(spec.random_seed)
    for _ in range(spec.replications):
        if spec.method is BootstrapMethod.MOVING_BLOCK:
            if blocks_per_replication is None:
                raise AssertionError("moving-block count must be available")
            resample = _moving_block_resample(
                values,
                block_length=spec.block_length,
                blocks_per_replication=blocks_per_replication,
                random_generator=random_generator,
            )
        else:
            indices = stationary_bootstrap_indices(
                observation_count,
                mean_block_length=spec.block_length,
                rng=random_generator,
            )
            resample = values[indices]
        replicate_estimates = _replicate_estimates(
            resample,
            annualized=annualized,
            serial_adjustment=serial_adjustment,
        )

        for metric in _METRIC_ORDER:
            if point_estimates[metric] is None:
                continue

            attempted_replications[metric] += 1
            estimate = replicate_estimates[metric]
            if estimate is not None and math.isfinite(estimate):
                distributions[metric].append(estimate)

    metrics = tuple(
        _metric_result(
            metric,
            point_estimate=point_estimates[metric],
            distribution=distributions[metric],
            attempted_replications=attempted_replications[metric],
            lower_quantile=lower_quantile,
            upper_quantile=upper_quantile,
        )
        for metric in _METRIC_ORDER
    )

    return BootstrapResult(
        status=BootstrapStatus.ELIGIBLE,
        overlapping_block_count=overlapping_block_count,
        blocks_per_replication=blocks_per_replication,
        metrics=metrics,
        **common,
    )


def _moving_block_resample(
    values: np.ndarray,
    *,
    block_length: int,
    blocks_per_replication: int,
    random_generator: np.random.Generator,
) -> np.ndarray:
    maximum_start = values.size - block_length
    starts = random_generator.integers(
        0,
        maximum_start + 1,
        size=blocks_per_replication,
    )
    blocks = [values[start : start + block_length] for start in starts]
    return np.concatenate(blocks)[: values.size]


def _point_estimates(
    values: np.ndarray,
    *,
    annualized: AnnualizedStatisticsResult | None,
    serial_adjustment: SerialAdjustmentResult | None,
) -> dict[BootstrapMetric, float | None]:
    mean_return = float(np.mean(values))
    degenerate = has_zero_sample_variation(values)
    sample_volatility = 0.0 if degenerate else float(np.std(values, ddof=1))

    estimates: dict[BootstrapMetric, float | None] = {
        BootstrapMetric.PERIOD_MEAN_RETURN: mean_return,
        BootstrapMetric.PERIOD_SAMPLE_VOLATILITY: sample_volatility,
        BootstrapMetric.FIXED_HORIZON_CUMULATIVE_SIMPLE_RETURN: (
            _cumulative_simple_return(values)
        ),
        BootstrapMetric.ANNUALIZED_ARITHMETIC_MEAN_RETURN: None,
        BootstrapMetric.IID_ANNUALIZED_SAMPLE_VOLATILITY: None,
        BootstrapMetric.PERIOD_SHARPE_RATIO: None,
        BootstrapMetric.IID_ANNUALIZED_SHARPE_RATIO: None,
        BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO: None,
    }

    if annualized is not None:
        estimates[BootstrapMetric.ANNUALIZED_ARITHMETIC_MEAN_RETURN] = (
            annualized.annualized_arithmetic_mean_return
        )
        estimates[BootstrapMetric.IID_ANNUALIZED_SAMPLE_VOLATILITY] = (
            annualized.annualized_sample_volatility
        )

        if annualized.annualized_sharpe_ratio is not None:
            estimates[BootstrapMetric.PERIOD_SHARPE_RATIO] = (
                annualized.annualized_sharpe_ratio
                / math.sqrt(annualized.periods_per_year)
            )
            estimates[BootstrapMetric.IID_ANNUALIZED_SHARPE_RATIO] = (
                annualized.annualized_sharpe_ratio
            )

    if (
        serial_adjustment is not None
        and serial_adjustment.hac_adjusted_annualized_sharpe_ratio is not None
    ):
        estimates[BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO] = (
            serial_adjustment.hac_adjusted_annualized_sharpe_ratio
        )

    return estimates


def _replicate_estimates(
    values: np.ndarray,
    *,
    annualized: AnnualizedStatisticsResult | None,
    serial_adjustment: SerialAdjustmentResult | None,
) -> dict[BootstrapMetric, float | None]:
    mean_return = float(np.mean(values))
    # A moving-block replicate can draw a run of identical returns even from a
    # varying series. np.std then leaves a rounding residue (2.29e-19 for ten
    # copies of 0.001) that the `<= 0.0` gate below admitted, publishing a
    # Sharpe near 4e15 and an interval upper bound near 7e16. Normalised at the
    # source, as the point estimate already is.
    sample_volatility = (
        0.0 if has_zero_sample_variation(values) else float(np.std(values, ddof=1))
    )

    estimates: dict[BootstrapMetric, float | None] = {
        BootstrapMetric.PERIOD_MEAN_RETURN: mean_return,
        BootstrapMetric.PERIOD_SAMPLE_VOLATILITY: sample_volatility,
        BootstrapMetric.FIXED_HORIZON_CUMULATIVE_SIMPLE_RETURN: (
            _cumulative_simple_return(values)
        ),
        BootstrapMetric.ANNUALIZED_ARITHMETIC_MEAN_RETURN: None,
        BootstrapMetric.IID_ANNUALIZED_SAMPLE_VOLATILITY: None,
        BootstrapMetric.PERIOD_SHARPE_RATIO: None,
        BootstrapMetric.IID_ANNUALIZED_SHARPE_RATIO: None,
        BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO: None,
    }

    if annualized is None:
        return estimates

    periods_per_year = annualized.periods_per_year
    iid_factor = math.sqrt(periods_per_year)
    estimates[BootstrapMetric.ANNUALIZED_ARITHMETIC_MEAN_RETURN] = (
        mean_return * periods_per_year
    )
    estimates[BootstrapMetric.IID_ANNUALIZED_SAMPLE_VOLATILITY] = (
        sample_volatility * iid_factor
    )

    if annualized.period_risk_free_rate is None or sample_volatility <= 0.0:
        return estimates

    period_sharpe = (mean_return - annualized.period_risk_free_rate) / sample_volatility
    estimates[BootstrapMetric.PERIOD_SHARPE_RATIO] = period_sharpe
    estimates[BootstrapMetric.IID_ANNUALIZED_SHARPE_RATIO] = period_sharpe * iid_factor

    if (
        serial_adjustment is None
        or serial_adjustment.hac_adjusted_annualized_sharpe_ratio is None
        or serial_adjustment.kernel is not HACKernel.BARTLETT
        or serial_adjustment.maximum_lag >= values.size
    ):
        return estimates

    _, long_run_variance_ratio = calculate_bartlett_hac_ratio(
        values,
        maximum_lag=serial_adjustment.maximum_lag,
    )
    if math.isfinite(long_run_variance_ratio) and long_run_variance_ratio > 0.0:
        estimates[BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO] = (
            period_sharpe * math.sqrt(periods_per_year / long_run_variance_ratio)
        )

    return estimates


def _cumulative_simple_return(values: np.ndarray) -> float | None:
    if np.any(values == -1.0):
        return -1.0

    with np.errstate(over="ignore", invalid="ignore"):
        result = float(np.expm1(np.sum(np.log1p(values))))

    return result if math.isfinite(result) else None


def _metric_result(
    metric: BootstrapMetric,
    *,
    point_estimate: float | None,
    distribution: list[float],
    attempted_replications: int,
    lower_quantile: float,
    upper_quantile: float,
) -> BootstrapMetricResult:
    if point_estimate is None or not math.isfinite(point_estimate):
        return BootstrapMetricResult(
            metric=metric,
            status=BootstrapMetricStatus.POINT_ESTIMATE_UNAVAILABLE,
            point_estimate=None,
            lower_bound=None,
            upper_bound=None,
            bootstrap_standard_error=None,
            attempted_replications=0,
            successful_replications=0,
        )

    successful_replications = len(distribution)
    if successful_replications < 2:
        return BootstrapMetricResult(
            metric=metric,
            status=(BootstrapMetricStatus.INSUFFICIENT_VALID_REPLICATIONS),
            point_estimate=point_estimate,
            lower_bound=None,
            upper_bound=None,
            bootstrap_standard_error=None,
            attempted_replications=attempted_replications,
            successful_replications=successful_replications,
        )

    bootstrap_values = np.asarray(distribution, dtype=np.float64)
    lower_bound, upper_bound = np.quantile(
        bootstrap_values,
        [lower_quantile, upper_quantile],
        method="linear",
    )

    return BootstrapMetricResult(
        metric=metric,
        status=BootstrapMetricStatus.ELIGIBLE,
        point_estimate=point_estimate,
        lower_bound=float(lower_bound),
        upper_bound=float(upper_bound),
        bootstrap_standard_error=float(np.std(bootstrap_values, ddof=1)),
        attempted_replications=attempted_replications,
        successful_replications=successful_replications,
    )
