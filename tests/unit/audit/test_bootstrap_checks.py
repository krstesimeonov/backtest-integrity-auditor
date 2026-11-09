import numpy as np
import pandas as pd

from backtest_auditor.application.single_run_audit import audit_single_run
from backtest_auditor.domain.assumptions import (
    BootstrapSpec,
    SerialAdjustmentSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    BootstrapMetric,
    HACKernel,
    ReturnConvention,
)
from backtest_auditor.domain.runs import StrategyRun
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)


def _run(values: list[float]) -> StrategyRun:
    return StrategyRun(
        run_id="bootstrap-finding-run",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=len(values),
                freq="D",
            ),
            values=np.asarray(values),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=12),
        ),
    )


def _spec(
    *,
    replications: int = 100,
    block_length: int = 2,
    random_seed: int = 7,
) -> BootstrapSpec:
    return BootstrapSpec(
        method=BootstrapMethod.MOVING_BLOCK,
        interval_method=BootstrapIntervalMethod.PERCENTILE,
        replications=replications,
        confidence_level=0.9,
        block_length=block_length,
        random_seed=random_seed,
    )


def test_regular_audit_records_unconfigured_bootstrap() -> None:
    result = audit_single_run(_run([0.01, -0.02, 0.03, 0.005]))

    assert "BOOTSTRAP_ANALYSIS_NOT_CONFIGURED" in {
        finding.code for finding in result.findings
    }


def test_low_replications_and_unit_blocks_are_separate_findings() -> None:
    result = audit_single_run(
        _run([0.01, -0.02, 0.03, 0.005]),
        bootstrap_spec=_spec(
            replications=20,
            block_length=1,
        ),
    )
    codes = {finding.code for finding in result.findings}

    assert "LOW_BOOTSTRAP_REPLICATION_COUNT" in codes
    assert "BOOTSTRAP_BLOCK_LENGTH_ONE" in codes


def test_ineligible_block_length_produces_structured_finding() -> None:
    result = audit_single_run(
        _run([0.01, -0.02, 0.03, 0.005]),
        bootstrap_spec=_spec(block_length=4),
    )

    assert "BOOTSTRAP_BLOCK_LENGTH_NOT_BELOW_SAMPLE_SIZE" in {
        finding.code for finding in result.findings
    }


def test_dropped_hac_replications_are_counted_and_flagged() -> None:
    result = audit_single_run(
        _run([-0.02, -0.02, -0.02, -0.02, -0.02, 0.01, 0.03]),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
        serial_adjustment_spec=SerialAdjustmentSpec(
            maximum_lag=2,
            kernel=HACKernel.BARTLETT,
        ),
        bootstrap_spec=_spec(
            replications=200,
            block_length=2,
            random_seed=7,
        ),
    )

    assert result.bootstrap is not None
    hac_metric = next(
        metric
        for metric in result.bootstrap.metrics
        if metric.metric is BootstrapMetric.HAC_ADJUSTED_ANNUALIZED_SHARPE_RATIO
    )

    assert hac_metric.attempted_replications == 200
    assert hac_metric.successful_replications == 157
    assert "BOOTSTRAP_REPLICATIONS_DROPPED" in {
        finding.code for finding in result.findings
    }
