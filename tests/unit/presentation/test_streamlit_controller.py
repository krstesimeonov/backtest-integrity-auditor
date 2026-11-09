import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest_auditor.domain.assumptions import (
    AdvancedRiskSpec,
    BenchmarkInferenceSpec,
    BootstrapSpec,
    CSCVSpec,
    DataSnoopingSpec,
    DeflatedSharpeRatioSpec,
    ParameterRobustnessSpec,
    ParameterScale,
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
    SharpeRatioSpec,
    TemporalRobustnessSpec,
)
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    CSCVMethod,
    CSCVPerformanceMetric,
    CSCVRankTieMethod,
    CSCVWinnerTiePolicy,
    DeflatedSharpeRatioMethod,
    DSRTrialCountPolicy,
    HACKernel,
    ParameterDistanceMetric,
    ReturnConvention,
    RobustnessPerformanceMetric,
    RobustnessRankTieMethod,
    RobustnessWinnerTiePolicy,
)
from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.domain.metadata import ReturnConstructionSpec
from backtest_auditor.domain.reproducibility import AuditRunSpec
from backtest_auditor.presentation.streamlit_controller import (
    BenchmarkInput,
    CalendarInput,
    ExperimentFamilyRequest,
    SingleRunRequest,
    UploadedInput,
    run_family_audit,
    run_single_audit,
)


def _upload(path: str) -> UploadedInput:
    source = Path(path)
    return UploadedInput(source.name, source.read_bytes())


def _manifest(audit_id: str) -> AuditRunSpec:
    return AuditRunSpec(
        audit_id,
        datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        "streamlit-test-revision",
    )


def test_uploaded_input_normalizes_browser_paths_and_validates_types() -> None:
    upload = UploadedInput(r"C:\fakepath\returns.csv", b"timestamp,return\n")

    assert upload.name == "returns.csv"
    with pytest.raises(ValueError, match="identify a file"):
        UploadedInput("../", b"")
    with pytest.raises(ValueError, match="name must be a string"):
        UploadedInput(1, b"")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="content must be bytes"):
        UploadedInput("returns.csv", "not bytes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="control characters"):
        UploadedInput("returns\n.csv", b"")
    with pytest.raises(ValueError, match="255 UTF-8 bytes"):
        UploadedInput(f"{'a' * 252}.csv", b"")


def test_calendar_input_rejects_empty_session_column() -> None:
    with pytest.raises(ValueError, match="session column"):
        CalendarInput("24/7", "UTC", session_column=" ")


def test_single_run_controller_uses_all_canonical_adapters_and_methods() -> None:
    construction = ReturnConstructionSpec(
        transaction_costs_included=True,
        fees_included=True,
        leverage_policy="unlevered",
        currency="USD",
        price_adjustment_policy="adjusted",
        data_source="unit-test",
        data_vintage="2026-08-13",
        stale_price_policy="last observation retained",
        delisting_return_policy="total loss",
        survivorship_bias_controlled=True,
        lookahead_bias_controlled=True,
        signal_timing="close",
        execution_timing="next close",
    )
    sessions = UploadedInput(
        "sessions.csv",
        b"session\n2026-01-01\n2026-01-02\n2026-01-03\n2026-01-04\n2026-01-05\n",
    )
    result = run_single_audit(
        SingleRunRequest(
            returns_file=_upload("examples/sample_returns.csv"),
            run_id="ui-single",
            return_convention=ReturnConvention.SIMPLE,
            declared_frequency="D",
            periods_per_year=365,
            timestamp_timezone="UTC",
            observation_calendar=CalendarInput("uploaded", "UTC", sessions),
            return_construction=construction,
            benchmark=BenchmarkInput(
                returns_file=_upload("examples/sample_benchmark.csv"),
                benchmark_id="ui-benchmark",
                timestamp_timezone="UTC",
                observation_calendar=CalendarInput("24/7", "UTC"),
                return_construction=construction,
            ),
            risk_free_file=_upload("examples/sample_risk_free.csv"),
            gross_returns_file=_upload("examples/sample_gross_returns.csv"),
            regimes_file=_upload("examples/sample_regimes.csv"),
            sharpe_spec=SharpeRatioSpec(0.03),
            psr_spec=ProbabilisticSharpeRatioSpec(0.0, 0.95),
            serial_dependence_spec=SerialDependenceSpec(2, 0.05),
            serial_adjustment_spec=SerialAdjustmentSpec(2, HACKernel.BARTLETT),
            bootstrap_spec=BootstrapSpec(
                BootstrapMethod.MOVING_BLOCK,
                BootstrapIntervalMethod.PERCENTILE,
                20,
                0.95,
                2,
                42,
            ),
            advanced_risk_spec=AdvancedRiskSpec(0.0, 0.95),
            benchmark_inference_spec=BenchmarkInferenceSpec(1, 0.95),
            run_manifest_spec=_manifest("ui-single-audit"),
        )
    )

    assert result.audit_type == "single_run"
    assert result.subject_id == "ui-single"
    assert result.payload["schema_version"] == "2.5"
    assert result.payload["bootstrap"]["status"] == "eligible"
    assert result.payload["benchmark"]["comparison"]["benchmark_id"] == ("ui-benchmark")
    manifest = result.payload["run_manifest"]
    assert manifest["package_version"] == "1.6.0"
    assert [item.role for item in result.normalized_series] == [
        "strategy",
        "benchmark",
        "risk_free",
        "gross_strategy",
    ]
    assert [item["role"] for item in manifest["input_artifacts"]] == [
        "benchmark_returns",
        "declared_regimes",
        "gross_strategy_returns",
        "risk_free_returns",
        "strategy_calendar_sessions",
        "strategy_returns",
    ]
    assert "# Backtest Integrity Audit" in result.markdown_report
    assert "## Downside, tail, and drawdown risk" in result.markdown_report
    assert "## Time-varying risk-free evidence" in result.markdown_report
    assert "## Gross-to-net cost drag" in result.markdown_report
    assert "## Declared-regime slices" in result.markdown_report
    assert "## Benchmark alpha inference" in result.markdown_report
    assert json.loads(result.json_report) == result.payload


def test_single_run_controller_preserves_canonical_input_errors() -> None:
    request = SingleRunRequest(
        returns_file=UploadedInput("bad.csv", b"wrong,columns\n1,2\n"),
        run_id="bad",
    )

    with pytest.raises(InputValidationError) as error:
        run_single_audit(request)

    assert error.value.issues[0].code == "MISSING_REQUIRED_COLUMN"


def test_family_controller_runs_every_optional_family_method() -> None:
    request = ExperimentFamilyRequest(
        manifest_file=_upload("examples/cscv_family_manifest.json"),
        trials_file=_upload("examples/cscv_family_trials.csv"),
        returns_file=_upload("examples/cscv_family_returns.csv"),
        splits_file=_upload("examples/cscv_family_splits.csv"),
        dsr_spec=DeflatedSharpeRatioSpec(
            DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
            DSRTrialCountPolicy.SELECTION_ELIGIBLE,
            0.0,
            0.95,
            2,
            "predeclared cluster analysis",
        ),
        cscv_spec=CSCVSpec(
            CSCVMethod.COMBINATORIALLY_SYMMETRIC,
            CSCVPerformanceMetric.PERIOD_SHARPE_RATIO,
            "period_sharpe_ratio",
            4,
            0.0,
            100,
            CSCVRankTieMethod.AVERAGE,
            CSCVWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
            0.05,
        ),
        parameter_robustness_spec=ParameterRobustnessSpec(
            RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
            "period_sharpe_ratio",
            0.0,
            ParameterDistanceMetric.STANDARDIZED_EUCLIDEAN,
            (ParameterScale("lookback", 5.0),),
            3.0,
            2,
            1.0,
            0.5,
        ),
        temporal_robustness_spec=TemporalRobustnessSpec(
            RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
            "period_sharpe_ratio",
            0.0,
            4,
            RobustnessRankTieMethod.AVERAGE,
            RobustnessWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
            0.5,
            0.5,
        ),
        run_manifest_spec=_manifest("ui-family-audit"),
    )

    result = run_family_audit(request)

    assert result.audit_type == "experiment_family"
    assert result.subject_id == "cscv-example-family"
    assert result.payload["schema_version"] == "2.5"
    assert result.payload["deflated_sharpe_ratio"] is not None
    assert result.payload["cscv_probability_of_backtest_overfitting"] is not None
    assert result.payload["parameter_robustness"] is not None
    assert result.payload["temporal_robustness"] is not None
    assert result.payload["run_manifest"]["package_version"] == "1.6.0"
    assert len(result.normalized_series) == 4
    assert [
        item["file_name"] for item in result.payload["run_manifest"]["input_artifacts"]
    ] == [
        "cscv_family_manifest.json",
        "cscv_family_returns.csv",
        "cscv_family_splits.csv",
        "cscv_family_trials.csv",
    ]
    assert "# Backtest Integrity Audit" in result.markdown_report


def test_family_controller_supports_manifest_declared_shared_benchmark() -> None:
    result = run_family_audit(
        ExperimentFamilyRequest(
            manifest_file=_upload("examples/experiment_family_manifest.json"),
            trials_file=_upload("examples/experiment_family_trials.csv"),
            returns_file=_upload("examples/experiment_family_returns.csv"),
            benchmark_file=_upload("examples/sample_benchmark.csv"),
        )
    )

    assert result.payload["benchmark"]["benchmark_id"] == "market"
    assert result.payload["run_manifest"] is None


def test_family_controller_exposes_seeded_data_snooping_controls() -> None:
    result = run_family_audit(
        ExperimentFamilyRequest(
            manifest_file=_upload("examples/cscv_family_manifest_v1_4.json"),
            trials_file=_upload("examples/cscv_family_trials.csv"),
            returns_file=_upload("examples/cscv_family_returns.csv"),
            benchmark_file=_upload("examples/cscv_family_benchmark.csv"),
            data_snooping_spec=DataSnoopingSpec(50, 2, 42, 0.05),
        )
    )

    evidence = result.payload["data_snooping"]
    assert evidence["status"] == "eligible"
    assert evidence["replications"] == 50
    assert evidence["random_seed"] == 42
    assert "## Data-snooping controls" in result.markdown_report
