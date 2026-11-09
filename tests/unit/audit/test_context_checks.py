from dataclasses import replace

from backtest_auditor.audit.context_checks import (
    generate_benchmark_findings,
    generate_benchmark_comparability_findings,
    generate_calendar_findings,
    generate_performance_path_findings,
    generate_return_construction_findings,
)
from backtest_auditor.audit.methodology import assess_return_construction
from backtest_auditor.domain.enums import (
    BenchmarkAlignmentStatus,
    ObservationCalendarSource,
    ObservationCalendarStatus,
    ReturnConvention,
    SeriesRole,
)
from backtest_auditor.domain.metadata import ReturnConstructionSpec
from backtest_auditor.domain.results import (
    BenchmarkAlignmentResult,
    BenchmarkComparisonResult,
    ObservationCalendarAssessmentResult,
    PerformancePathResult,
)


def _complete_spec(**overrides) -> ReturnConstructionSpec:
    values = {
        "transaction_costs_included": True,
        "fees_included": True,
        "leverage_policy": "unlevered",
        "currency": "USD",
        "price_adjustment_policy": "adjusted",
        "data_source": "point-in-time vendor",
        "data_vintage": "2026-08-11",
        "stale_price_policy": "reject carried prices after one session",
        "delisting_return_policy": "include terminal delisting returns",
        "survivorship_bias_controlled": True,
        "lookahead_bias_controlled": True,
        "signal_timing": "close t",
        "execution_timing": "open t+1",
    }
    values.update(overrides)
    return ReturnConstructionSpec(**values)


def test_complete_return_construction_has_no_findings() -> None:
    assessment = assess_return_construction(
        _complete_spec(),
        role=SeriesRole.STRATEGY,
    )

    assert generate_return_construction_findings(assessment) == ()


def test_failed_bias_declarations_are_not_treated_as_missing() -> None:
    assessment = assess_return_construction(
        _complete_spec(
            survivorship_bias_controlled=False,
            lookahead_bias_controlled=False,
        ),
        role=SeriesRole.STRATEGY,
    )
    codes = {
        finding.code for finding in generate_return_construction_findings(assessment)
    }

    assert codes == {
        "SURVIVORSHIP_BIAS_CONTROL_FAILED",
        "LOOKAHEAD_BIAS_CONTROL_FAILED",
    }


def test_currency_and_cost_basis_mismatches_are_separate_findings() -> None:
    strategy = assess_return_construction(
        _complete_spec(),
        role=SeriesRole.STRATEGY,
    )
    benchmark = assess_return_construction(
        _complete_spec(
            transaction_costs_included=False,
            fees_included=False,
            currency="EUR",
        ),
        role=SeriesRole.BENCHMARK,
    )

    codes = {
        finding.code
        for finding in generate_benchmark_comparability_findings(
            strategy,
            benchmark,
        )
    }

    assert codes == {
        "BENCHMARK_CURRENCY_MISMATCH",
        "BENCHMARK_COST_BASIS_MISMATCH",
    }


def test_calendar_findings_cover_missing_timezone_and_each_unverified_status() -> None:
    assert {
        item.code
        for item in generate_calendar_findings(None, role=SeriesRole.BENCHMARK)
    } == {"BENCHMARK_OBSERVATION_CALENDAR_NOT_DECLARED"}

    expected = {
        ObservationCalendarStatus.DECLARED_UNVERIFIED: (
            "OBSERVATION_CALENDAR_UNVERIFIED"
        ),
        ObservationCalendarStatus.MISMATCH: "OBSERVATION_CALENDAR_MISMATCH",
        ObservationCalendarStatus.INTRADAY_UNSUPPORTED: (
            "INTRADAY_CALENDAR_VERIFICATION_UNSUPPORTED"
        ),
    }
    for status, status_code in expected.items():
        assessment = ObservationCalendarAssessmentResult(
            status=status,
            calendar_name="XNYS",
            source=ObservationCalendarSource.DECLARATION_ONLY,
            calendar_timezone="America/New_York",
            timestamp_timezone=None,
            observation_count=3,
            observed_session_count=3,
            expected_session_count=None,
            missing_session_dates=(),
            unexpected_session_dates=(),
        )
        codes = {
            item.code
            for item in generate_calendar_findings(
                assessment,
                role=SeriesRole.STRATEGY,
            )
        }
        assert codes == {"TIMESTAMP_TIMEZONE_NOT_DECLARED", status_code}


def test_partial_return_construction_reports_every_missing_evidence_group() -> None:
    assessment = assess_return_construction(
        ReturnConstructionSpec(transaction_costs_included=True),
        role=SeriesRole.BENCHMARK,
    )

    codes = {item.code for item in generate_return_construction_findings(assessment)}

    assert codes == {
        "BENCHMARK_RETURN_COST_BASIS_INCOMPLETE",
        "BENCHMARK_LEVERAGE_POLICY_NOT_DECLARED",
        "BENCHMARK_RETURN_CURRENCY_NOT_DECLARED",
        "BENCHMARK_PRICE_ADJUSTMENT_POLICY_NOT_DECLARED",
        "BENCHMARK_DATA_PROVENANCE_INCOMPLETE",
        "BENCHMARK_STALE_PRICE_POLICY_NOT_DECLARED",
        "BENCHMARK_DELISTING_RETURN_POLICY_NOT_DECLARED",
        "BENCHMARK_SURVIVORSHIP_BIAS_CONTROL_NOT_DECLARED",
        "BENCHMARK_LOOKAHEAD_BIAS_CONTROL_NOT_DECLARED",
        "BENCHMARK_SIGNAL_EXECUTION_TIMING_INCOMPLETE",
    }


def test_path_findings_preserve_total_loss_and_undefined_cagr() -> None:
    result = PerformancePathResult(
        observation_count=2,
        return_basis=ReturnConvention.SIMPLE,
        periods_per_year=365,
        starting_wealth=1.0,
        ending_wealth=0.0,
        cumulative_simple_return=-1.0,
        cagr=None,
        maximum_drawdown=-1.0,
        maximum_drawdown_peak_timestamp=None,
        maximum_drawdown_trough_timestamp=None,  # type: ignore[arg-type]
        maximum_drawdown_recovery_timestamp=None,
        maximum_drawdown_recovered=False,
        maximum_drawdown_duration_observations=1,
        longest_time_underwater_observations=1,
        longest_time_underwater_start_timestamp=None,
        longest_time_underwater_end_timestamp=None,
    )

    assert {item.code for item in generate_performance_path_findings(result)} == {
        "CAGR_UNDEFINED_FOR_NON_POSITIVE_WEALTH",
        "TOTAL_WEALTH_LOSS_OBSERVED",
    }


def test_benchmark_findings_cover_alignment_and_undefined_relative_statistics() -> None:
    mismatch = BenchmarkAlignmentResult(
        status=BenchmarkAlignmentStatus.TIMESTAMP_MISMATCH,
        strategy_observation_count=2,
        benchmark_observation_count=2,
        aligned_observation_count=1,
        strategy_only_timestamps=("2026-01-01",),
        benchmark_only_timestamps=("2026-01-02",),
    )
    assert {item.code for item in generate_benchmark_findings(mismatch, None)} == {
        "BENCHMARK_TIMESTAMP_MISMATCH"
    }

    aligned = BenchmarkAlignmentResult(
        status=BenchmarkAlignmentStatus.ELIGIBLE,
        strategy_observation_count=2,
        benchmark_observation_count=2,
        aligned_observation_count=2,
        strategy_only_timestamps=(),
        benchmark_only_timestamps=(),
    )
    short = BenchmarkComparisonResult(
        benchmark_id="market",
        observation_count=1,
        return_basis=ReturnConvention.SIMPLE,
        periods_per_year=None,
        strategy_cumulative_simple_return=0.0,
        benchmark_cumulative_simple_return=-1.0,
        relative_wealth_return=None,
        mean_period_active_return=0.0,
        period_tracking_error=None,
        annualized_tracking_error=None,
        period_information_ratio=None,
        annualized_information_ratio=None,
        return_correlation=None,
        beta=None,
        period_arithmetic_alpha=None,
        annualized_arithmetic_alpha=None,
    )
    assert {item.code for item in generate_benchmark_findings(aligned, short)} == {
        "INSUFFICIENT_OBSERVATIONS_FOR_BENCHMARK_STATISTICS",
        "RELATIVE_WEALTH_UNDEFINED",
    }

    zero_variance = replace(
        short,
        observation_count=2,
        relative_wealth_return=0.0,
        period_tracking_error=0.0,
    )
    assert {
        item.code for item in generate_benchmark_findings(aligned, zero_variance)
    } == {"ZERO_ACTIVE_RETURN_VOLATILITY", "ZERO_BENCHMARK_VARIANCE"}
