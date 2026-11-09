import pandas as pd

from backtest_auditor.audit.checks import (
    generate_annualized_statistical_findings,
    generate_basic_statistical_findings,
    generate_sharpe_uncertainty_findings,
    generate_track_record_findings,
)
from backtest_auditor.domain.assumptions import (
    ProbabilisticSharpeRatioSpec,
)
from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.findings import FindingCategory
from backtest_auditor.domain.results import (
    AnnualizedStatisticsResult,
    DescriptiveStatisticsResult,
    DistributionStatisticsResult,
    SharpeUncertaintyResult,
    TrackRecordLengthResult,
)


def _statistics_with_volatility(
    sample_volatility: float | None,
) -> DescriptiveStatisticsResult:
    return DescriptiveStatisticsResult(
        observation_count=(1 if sample_volatility is None else 2),
        start_timestamp=pd.Timestamp("2026-01-01"),
        end_timestamp=pd.Timestamp("2026-01-02"),
        mean_return=0.01,
        sample_volatility=sample_volatility,
        minimum_return=0.0,
        maximum_return=0.02,
        cumulative_simple_return=0.0201,
        return_convention=ReturnConvention.SIMPLE,
    )


def test_single_observation_generates_insufficient_sample_finding() -> None:
    findings = generate_basic_statistical_findings(_statistics_with_volatility(None))

    assert len(findings) == 1
    assert findings[0].code == "INSUFFICIENT_OBSERVATIONS_FOR_SAMPLE_VOLATILITY"
    assert findings[0].category is FindingCategory.SAMPLE_SUFFICIENCY


def test_constant_returns_generate_zero_volatility_finding() -> None:
    findings = generate_basic_statistical_findings(_statistics_with_volatility(0.0))

    assert len(findings) == 1
    assert findings[0].code == "ZERO_SAMPLE_VOLATILITY"
    assert findings[0].category is FindingCategory.STATISTICAL_EVIDENCE


def test_varying_returns_generate_no_basic_findings() -> None:
    findings = generate_basic_statistical_findings(_statistics_with_volatility(0.01))

    assert findings == ()


def _annualized_statistics(
    annual_risk_free_rate: float | None,
) -> AnnualizedStatisticsResult:
    return AnnualizedStatisticsResult(
        periods_per_year=252,
        return_basis=ReturnConvention.SIMPLE,
        annualized_arithmetic_mean_return=0.10,
        annualized_sample_volatility=0.20,
        annual_risk_free_rate=annual_risk_free_rate,
        period_risk_free_rate=(None if annual_risk_free_rate is None else 0.0),
        annualized_sharpe_ratio=(None if annual_risk_free_rate is None else 0.5),
    )


def test_missing_risk_free_rate_generates_finding() -> None:
    findings = generate_annualized_statistical_findings(_annualized_statistics(None))

    assert [finding.code for finding in findings] == [
        "ANNUAL_RISK_FREE_RATE_NOT_SUPPLIED"
    ]
    assert findings[0].category is FindingCategory.METHODOLOGICAL_RISK


def test_supplied_risk_free_rate_generates_no_finding() -> None:
    findings = generate_annualized_statistical_findings(_annualized_statistics(0.0))

    assert findings == ()


def test_ineligible_annualization_generates_no_duplicate_finding() -> None:
    findings = generate_annualized_statistical_findings(None)

    assert findings == ()


def _distribution(
    observation_count: int = 20,
    *,
    skewness: float | None = 0.0,
    pearson_kurtosis: float | None = 3.0,
) -> DistributionStatisticsResult:
    return DistributionStatisticsResult(
        observation_count=observation_count,
        return_basis=ReturnConvention.SIMPLE,
        sample_skewness=skewness,
        sample_excess_kurtosis=(
            None if pearson_kurtosis is None else pearson_kurtosis - 3.0
        ),
        sample_pearson_kurtosis=pearson_kurtosis,
    )


def _uncertainty(
    period_standard_error: float | None = 0.2,
) -> SharpeUncertaintyResult:
    return SharpeUncertaintyResult(
        observation_count=20,
        periods_per_year=252,
        period_sharpe_ratio=0.05,
        annualized_sharpe_ratio=0.793725393,
        sharpe_variance_adjustment=1.0,
        period_sharpe_standard_error=period_standard_error,
        annualized_sharpe_standard_error=(
            None if period_standard_error is None else period_standard_error * 252**0.5
        ),
        benchmark_period_sharpe_ratio=None,
        benchmark_annualized_sharpe_ratio=None,
        probabilistic_sharpe_ratio=None,
    )


def test_missing_shape_generates_uncertainty_finding() -> None:
    findings = generate_sharpe_uncertainty_findings(
        _annualized_statistics(0.0),
        _distribution(
            observation_count=3,
            pearson_kurtosis=None,
        ),
        None,
    )

    assert [finding.code for finding in findings] == [
        "INSUFFICIENT_OBSERVATIONS_FOR_SHARPE_UNCERTAINTY"
    ]


def test_missing_psr_benchmark_generates_finding() -> None:
    findings = generate_sharpe_uncertainty_findings(
        _annualized_statistics(0.0),
        _distribution(),
        _uncertainty(),
    )

    assert [finding.code for finding in findings] == [
        "ANNUALIZED_SHARPE_BENCHMARK_NOT_SUPPLIED"
    ]
    assert findings[0].category is FindingCategory.METHODOLOGICAL_RISK


def test_supplied_psr_benchmark_generates_no_finding() -> None:
    findings = generate_sharpe_uncertainty_findings(
        _annualized_statistics(0.0),
        _distribution(),
        _uncertainty(),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0),
    )

    assert findings == ()


def test_non_positive_variance_estimate_generates_finding() -> None:
    findings = generate_sharpe_uncertainty_findings(
        _annualized_statistics(0.0),
        _distribution(),
        _uncertainty(period_standard_error=None),
        psr_spec=ProbabilisticSharpeRatioSpec(benchmark_annualized_sharpe_ratio=0.0),
    )

    assert [finding.code for finding in findings] == [
        "NON_POSITIVE_SHARPE_VARIANCE_ESTIMATE"
    ]


def _psr_uncertainty(
    *,
    period_sharpe: float = 0.10,
    benchmark_period: float = 0.05,
    psr: float = 0.90,
) -> SharpeUncertaintyResult:
    return SharpeUncertaintyResult(
        observation_count=100,
        periods_per_year=252,
        period_sharpe_ratio=period_sharpe,
        annualized_sharpe_ratio=period_sharpe * 252**0.5,
        sharpe_variance_adjustment=1.0,
        period_sharpe_standard_error=0.04,
        annualized_sharpe_standard_error=0.04 * 252**0.5,
        benchmark_period_sharpe_ratio=benchmark_period,
        benchmark_annualized_sharpe_ratio=(benchmark_period * 252**0.5),
        probabilistic_sharpe_ratio=psr,
    )


def _track_record(
    *,
    sharpe_difference: float = 0.05,
    requirement_met: bool = False,
    minimum_required_observations: int | None = 150,
    additional_observations: int | None = 50,
) -> TrackRecordLengthResult:
    return TrackRecordLengthResult(
        observation_count=100,
        periods_per_year=252,
        required_psr_confidence_level=0.95,
        observed_probabilistic_sharpe_ratio=(0.96 if requirement_met else 0.90),
        confidence_requirement_met=requirement_met,
        normal_critical_value=1.6448536269514715,
        observed_period_sharpe_difference=sharpe_difference,
        minimum_track_record_length_observations=(
            None
            if minimum_required_observations is None
            else float(minimum_required_observations) - 0.2
        ),
        minimum_required_observations=(minimum_required_observations),
        minimum_track_record_length_years=(
            None
            if minimum_required_observations is None
            else (minimum_required_observations - 0.2) / 252
        ),
        additional_observations_required=additional_observations,
        observations_above_minimum=(5 if requirement_met else 0),
    )


def test_missing_psr_confidence_level_generates_finding() -> None:
    uncertainty = _psr_uncertainty()
    findings = generate_track_record_findings(
        uncertainty,
        None,
        psr_spec=ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=(
                uncertainty.benchmark_annualized_sharpe_ratio
            )
        ),
    )

    assert [finding.code for finding in findings] == [
        "PSR_CONFIDENCE_LEVEL_NOT_SUPPLIED"
    ]
    assert findings[0].category is FindingCategory.METHODOLOGICAL_RISK


def test_sharpe_not_above_benchmark_generates_finding() -> None:
    findings = generate_track_record_findings(
        _psr_uncertainty(period_sharpe=0.04),
        _track_record(
            sharpe_difference=-0.01,
            minimum_required_observations=None,
            additional_observations=None,
        ),
        psr_spec=ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=0.05 * 252**0.5,
            required_psr_confidence_level=0.95,
        ),
    )

    assert [finding.code for finding in findings] == [
        "OBSERVED_SHARPE_NOT_ABOVE_BENCHMARK"
    ]
    assert findings[0].category is FindingCategory.STATISTICAL_EVIDENCE


def test_short_track_record_generates_confidence_finding() -> None:
    findings = generate_track_record_findings(
        _psr_uncertainty(),
        _track_record(),
        psr_spec=ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=0.05 * 252**0.5,
            required_psr_confidence_level=0.95,
        ),
    )

    assert [finding.code for finding in findings] == [
        "PSR_CONFIDENCE_REQUIREMENT_NOT_MET"
    ]
    assert findings[0].category is FindingCategory.SAMPLE_SUFFICIENCY
    assert "50 additional observations" in findings[0].remediation


def test_satisfied_confidence_requirement_generates_no_finding() -> None:
    findings = generate_track_record_findings(
        _psr_uncertainty(psr=0.96),
        _track_record(
            requirement_met=True,
            minimum_required_observations=95,
            additional_observations=0,
        ),
        psr_spec=ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=0.05 * 252**0.5,
            required_psr_confidence_level=0.95,
        ),
    )

    assert findings == ()
