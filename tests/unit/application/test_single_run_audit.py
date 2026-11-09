import numpy as np
import pandas as pd

from backtest_auditor.application.single_run_audit import (
    audit_single_run,
)
from backtest_auditor.domain.assumptions import (
    BootstrapSpec,
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    FrequencyStatus,
    HACKernel,
    IssueSeverity,
    ObservationCalendarStatus,
    ReturnConvention,
    SerialDependenceStatus,
)
from backtest_auditor.domain.metadata import (
    ObservationCalendarSpec,
    ReturnConstructionSpec,
)
from backtest_auditor.domain.issues import ValidationIssue
from backtest_auditor.domain.runs import BenchmarkRun, StrategyRun
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)


def test_single_run_audit_preserves_run_id_and_connects_results() -> None:
    run = StrategyRun(
        run_id="strategy-run-001",
        returns=ReturnSeries(
            timestamps=pd.DatetimeIndex(
                [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                ]
            ),
            values=np.array([0.01, -0.02, 0.03, 0.005, 0.015]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=365),
        ),
    )

    result = audit_single_run(
        run,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
        psr_spec=ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=0.0,
            required_psr_confidence_level=0.75,
        ),
        serial_dependence_spec=SerialDependenceSpec(
            maximum_lag=1,
            significance_level=0.05,
        ),
        serial_adjustment_spec=SerialAdjustmentSpec(
            maximum_lag=1,
            kernel=HACKernel.BARTLETT,
        ),
        bootstrap_spec=BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=1_000,
            confidence_level=0.95,
            block_length=2,
            random_seed=42,
        ),
    )

    assert result.run_id == "strategy-run-001"
    assert result.sampling_assessment.status is FrequencyStatus.INFERRED_REGULAR
    assert result.sampling_assessment.annualization_eligible
    assert result.descriptive_statistics.observation_count == 5
    assert result.annualized_statistics is not None
    assert result.annualized_statistics.annualized_sharpe_ratio is not None
    assert result.distribution_statistics.sample_skewness is not None
    assert result.sharpe_uncertainty is not None
    assert result.sharpe_uncertainty.probabilistic_sharpe_ratio is not None
    assert result.track_record_length is not None
    assert result.track_record_length.confidence_requirement_met
    assert result.serial_dependence is not None
    assert not result.serial_dependence.serial_dependence_detected
    assert result.serial_adjustment is not None
    assert result.serial_adjustment.hac_confidence_requirement_met
    assert result.bootstrap is not None
    assert len(result.bootstrap.metrics) == 8
    assert [finding.code for finding in result.findings] == [
        "OBSERVATION_CALENDAR_NOT_DECLARED",
        "RETURN_CONSTRUCTION_METADATA_NOT_SUPPLIED",
    ]


def test_single_run_audit_preserves_input_issues() -> None:
    issue = ValidationIssue(
        code="TIMESTAMPS_SORTED",
        message="Input was sorted.",
        severity=IssueSeverity.WARNING,
        blocking=False,
        location="timestamp",
    )
    run = StrategyRun(
        run_id="strategy-run-002",
        returns=ReturnSeries(
            timestamps=pd.DatetimeIndex(["2026-01-01"]),
            values=np.array([0.01]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(),
        ),
    )

    result = audit_single_run(run, input_issues=(issue,))

    assert result.input_issues == (issue,)
    assert result.annualized_statistics is None


def test_complete_context_and_benchmark_flow_is_connected() -> None:
    timestamps = pd.date_range("2026-01-01", periods=4, freq="D")
    sampling = SamplingSpec(
        periods_per_year=365,
        timezone="UTC",
    )
    calendar = ObservationCalendarSpec(
        calendar_name="24/7",
        timezone="UTC",
    )
    construction = ReturnConstructionSpec(
        transaction_costs_included=True,
        fees_included=True,
        leverage_policy="unlevered",
        currency="USD",
        price_adjustment_policy="adjusted",
        data_source="point-in-time vendor",
        data_vintage="2026-08-11",
        stale_price_policy="reject carried prices after one session",
        delisting_return_policy="include terminal delisting returns",
        survivorship_bias_controlled=True,
        lookahead_bias_controlled=True,
        signal_timing="close t",
        execution_timing="open t+1",
    )
    run = StrategyRun(
        run_id="complete-context-run",
        returns=ReturnSeries(
            timestamps=timestamps,
            values=np.asarray([0.02, 0.01, -0.01, 0.03]),
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        observation_calendar=calendar,
        return_construction=construction,
        benchmark=BenchmarkRun(
            benchmark_id="market",
            returns=ReturnSeries(
                timestamps=timestamps,
                values=np.asarray([0.01, 0.0, -0.005, 0.02]),
                convention=ReturnConvention.SIMPLE,
                sampling=sampling,
            ),
            observation_calendar=calendar,
            return_construction=construction,
        ),
    )

    result = audit_single_run(run)
    codes = {finding.code for finding in result.findings}

    assert result.observation_calendar is not None
    assert result.observation_calendar.status is ObservationCalendarStatus.VERIFIED
    assert result.sampling_assessment.status is FrequencyStatus.CALENDAR_VERIFIED
    assert result.return_construction.completeness_ratio == 1.0
    assert result.benchmark_alignment is not None
    assert result.benchmark_comparison is not None
    assert result.benchmark_comparison.benchmark_id == "market"
    assert result.performance_path.cagr is not None
    assert "OBSERVATION_CALENDAR_NOT_DECLARED" not in codes
    assert "RETURN_CONSTRUCTION_METADATA_NOT_SUPPLIED" not in codes
    assert "BENCHMARK_TIMESTAMP_MISMATCH" not in codes


def test_eligible_audit_without_risk_free_rate_records_finding() -> None:
    run = StrategyRun(
        run_id="strategy-run-003",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=3,
                freq="D",
            ),
            values=np.array([0.01, -0.02, 0.03]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=365),
        ),
    )

    result = audit_single_run(run)

    assert result.annualized_statistics is not None
    assert result.annualized_statistics.annualized_sharpe_ratio is None
    assert [finding.code for finding in result.findings] == [
        "OBSERVATION_CALENDAR_NOT_DECLARED",
        "RETURN_CONSTRUCTION_METADATA_NOT_SUPPLIED",
        "SERIAL_DEPENDENCE_DIAGNOSTIC_NOT_CONFIGURED",
        "ANNUAL_RISK_FREE_RATE_NOT_SUPPLIED",
        "BOOTSTRAP_ANALYSIS_NOT_CONFIGURED",
    ]


def test_single_run_audit_records_detected_serial_dependence() -> None:
    values = np.asarray([value / 1000 for value in range(1, 31)])
    run = StrategyRun(
        run_id="serial-dependence-run",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=len(values),
                freq="D",
            ),
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=365),
        ),
    )

    result = audit_single_run(
        run,
        serial_dependence_spec=SerialDependenceSpec(
            maximum_lag=3,
            significance_level=0.05,
        ),
    )

    assert result.serial_dependence is not None
    assert result.serial_dependence.serial_dependence_detected
    assert "SERIAL_DEPENDENCE_DETECTED" in {finding.code for finding in result.findings}
    assert "SERIAL_DEPENDENCE_ADJUSTMENT_NOT_CONFIGURED" in {
        finding.code for finding in result.findings
    }


def test_single_run_audit_records_insufficient_serial_sample() -> None:
    run = StrategyRun(
        run_id="insufficient-serial-run",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=3,
                freq="D",
            ),
            values=np.asarray([0.01, 0.02, 0.03]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=365),
        ),
    )

    result = audit_single_run(
        run,
        serial_dependence_spec=SerialDependenceSpec(
            maximum_lag=3,
            significance_level=0.05,
        ),
    )

    assert result.serial_dependence is not None
    assert (
        result.serial_dependence.status
        is SerialDependenceStatus.INSUFFICIENT_OBSERVATIONS
    )
    assert "INSUFFICIENT_OBSERVATIONS_FOR_SERIAL_DEPENDENCE" in {
        finding.code for finding in result.findings
    }


def test_single_run_audit_records_zero_variance_serial_ineligibility() -> None:
    run = StrategyRun(
        run_id="zero-variance-serial-run",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=5,
                freq="D",
            ),
            values=np.asarray([0.01] * 5),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=365),
        ),
    )

    result = audit_single_run(
        run,
        serial_dependence_spec=SerialDependenceSpec(
            maximum_lag=1,
            significance_level=0.05,
        ),
    )

    assert result.serial_dependence is not None
    assert result.serial_dependence.status is SerialDependenceStatus.ZERO_VARIANCE
    assert "SERIAL_DEPENDENCE_UNDEFINED_FOR_ZERO_VARIANCE" in {
        finding.code for finding in result.findings
    }
