import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backtest_auditor.application.single_run_audit import (
    SingleRunAuditResult,
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
    HACKernel,
    ReturnConvention,
)
from backtest_auditor.domain.metadata import (
    ObservationCalendarSpec,
    ReturnConstructionSpec,
)
from backtest_auditor.domain.runs import BenchmarkRun, StrategyRun
from backtest_auditor.domain.reproducibility import AuditRunSpec, InputArtifactHash
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)
from backtest_auditor.reporting.json_report import (
    render_json_report,
)
from backtest_auditor.reporting.markdown_report import (
    render_markdown_report,
)


def _audit_result(values: list[float]) -> SingleRunAuditResult:
    timestamps = pd.date_range(
        "2026-01-01",
        periods=len(values),
        freq="D",
    )
    return audit_single_run(
        StrategyRun(
            run_id="report-test-run",
            returns=ReturnSeries(
                timestamps=timestamps,
                values=np.asarray(values),
                convention=ReturnConvention.SIMPLE,
                sampling=SamplingSpec(),
            ),
        )
    )


def _keys_are_sorted_everywhere(pairs_tree: object) -> bool:
    if isinstance(pairs_tree, list) and all(
        isinstance(item, tuple) and len(item) == 2 for item in pairs_tree
    ):
        keys = [key for key, _ in pairs_tree]
        return keys == sorted(keys) and all(
            _keys_are_sorted_everywhere(value) for _, value in pairs_tree
        )
    if isinstance(pairs_tree, list):
        return all(_keys_are_sorted_everywhere(item) for item in pairs_tree)
    return True


def test_json_report_bytes_are_canonical() -> None:
    # report_sha256 hashes these exact bytes, so their formatting is part of
    # the published contract. The release-contract check parses and re-renders
    # the engine's output before comparing, so it cannot see formatting at all.
    result = audit_single_run(
        StrategyRun(
            run_id="stratégie-α",
            returns=ReturnSeries(
                timestamps=pd.date_range("2026-01-01", periods=4, freq="D"),
                values=np.asarray([0.01, -0.02, 0.015, 0.003]),
                convention=ReturnConvention.SIMPLE,
                sampling=SamplingSpec(),
            ),
        )
    )
    rendered = render_json_report(result)
    lines = rendered.splitlines()

    assert _keys_are_sorted_everywhere(
        json.loads(rendered, object_pairs_hook=lambda pairs: pairs)
    )
    assert lines[0] == "{"
    assert lines[1].startswith('  "') and not lines[1].startswith("   ")
    assert "\t" not in rendered
    # Non-ASCII is written as itself, not as \u escapes, so the hash of a
    # report does not depend on an escaping choice.
    assert '"run_id": "stratégie-α"' in rendered
    assert rendered.endswith("}\n") and not rendered.endswith("\n\n")


def test_json_report_refuses_non_finite_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # NaN and Infinity are not JSON. Emitting them would produce a report that
    # strict parsers reject while this tool's own hash still verifies.
    monkeypatch.setattr(
        "backtest_auditor.reporting.json_report.single_run_audit_to_dict",
        lambda _result: {"value": float("nan")},
    )

    with pytest.raises(ValueError):
        render_json_report(_audit_result([0.01]))


def test_json_report_is_deterministic_and_json_safe() -> None:
    result = _audit_result([0.01])

    first_render = render_json_report(result)
    second_render = render_json_report(result)
    payload = json.loads(first_render)

    assert first_render == second_render
    assert first_render.endswith("\n")
    assert payload["schema_version"] == "2.5"
    assert payload["run_id"] == "report-test-run"
    assert payload["sampling_assessment"]["status"] == ("ambiguous")
    assert payload["sampling_assessment"]["annualization_eligible"] is False
    assert payload["descriptive_statistics"]["sample_volatility"] is None
    assert payload["annualized_statistics"] is None
    assert payload["distribution_statistics"]["sample_skewness"] is None
    assert payload["serial_dependence"] is None
    assert payload["serial_adjustment"] is None
    assert payload["bootstrap"] is None
    assert payload["sharpe_uncertainty"] is None
    assert payload["track_record_length"] is None
    assert payload["evidence_profile"]["overall_status"] is None
    assert payload["run_manifest"] is None
    assert {finding["code"] for finding in payload["findings"]} == {
        "AMBIGUOUS_SAMPLING_FREQUENCY",
        "INSUFFICIENT_OBSERVATIONS_FOR_SAMPLE_VOLATILITY",
        "OBSERVATION_CALENDAR_NOT_DECLARED",
        "RETURN_CONSTRUCTION_METADATA_NOT_SUPPLIED",
    }


def test_markdown_report_is_human_readable() -> None:
    report = render_markdown_report(_audit_result([0.01]))

    assert report.startswith("# Backtest Integrity Audit\n")
    assert "## Sampling assessment" in report
    assert "## Distribution statistics" in report
    assert "## Strategy observation calendar" in report
    assert "## Strategy return construction" in report
    assert "## Performance path evidence" in report
    assert "## Benchmark-relative evidence" in report
    assert "## Serial-dependence diagnostics" in report
    assert "## Serial-dependence adjustment" in report
    assert "## Bootstrap confidence intervals" in report
    assert "## Sharpe uncertainty and PSR" in report
    assert "## Minimum track-record length" in report
    assert "## Dimensioned evidence profile" in report
    assert "## Audit-run manifest" in report
    assert "Overall status: `not calculated`" in report
    assert "| Status | ambiguous |" in report
    assert "| Observation count | 1 |" in report
    assert "| Sample volatility | undefined |" in report
    assert "INSUFFICIENT_OBSERVATIONS_FOR_SAMPLE_VOLATILITY" in report


def test_markdown_report_renders_complete_manifest_tables_and_escapes_text() -> None:
    timestamps = pd.date_range("2026-01-01", periods=4, freq="D")
    result = audit_single_run(
        StrategyRun(
            run_id="manifest|report`run",
            returns=ReturnSeries(
                timestamps=timestamps,
                values=np.asarray([0.01, -0.02, 0.03, 0.01]),
                convention=ReturnConvention.SIMPLE,
                sampling=SamplingSpec(periods_per_year=365),
            ),
        ),
        bootstrap_spec=BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=10,
            confidence_level=0.9,
            block_length=2,
            random_seed=42,
        ),
        run_manifest_spec=AuditRunSpec(
            audit_id="audit|id",
            audit_timestamp=datetime(2026, 8, 12, tzinfo=timezone.utc),
            git_commit="commit`value",
        ),
        input_artifacts=(
            InputArtifactHash(
                role="strategy|returns",
                file_name="returns`sample.csv",
                size_bytes=12,
                sha256="a" * 64,
            ),
        ),
    )

    report = render_markdown_report(result)

    assert "| Audit ID | audit\\|id |" in report
    assert "commit\\`value" in report
    assert "returns\\`sample.csv" in report
    assert "| bootstrap | 42 |" in report
    assert "| dependency | numpy |" in report
    assert "### Preserved warning codes" in report
    assert "### Normalized audit configuration" in report


def test_reports_expose_context_path_and_benchmark_contracts() -> None:
    timestamps = pd.date_range("2026-01-01", periods=4, freq="D")
    sampling = SamplingSpec(periods_per_year=365, timezone="UTC")
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
        data_source="vendor",
        data_vintage="2026-08-11",
        stale_price_policy="reject carried prices",
        delisting_return_policy="include terminal returns",
        survivorship_bias_controlled=True,
        lookahead_bias_controlled=True,
        signal_timing="close t",
        execution_timing="open t+1",
    )
    result = audit_single_run(
        StrategyRun(
            run_id="context-report-run",
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
    )

    payload = json.loads(render_json_report(result))
    markdown = render_markdown_report(result)

    assert payload["observation_calendar"]["verified"] is True
    assert payload["return_construction"]["cost_basis"] == ("net_of_all_declared_costs")
    assert payload["performance_path"]["ending_wealth"] == pytest.approx(
        np.prod([1.02, 1.01, 0.99, 1.03])
    )
    assert payload["benchmark"]["alignment"]["eligible"] is True
    assert payload["benchmark"]["comparison"]["benchmark_id"] == "market"
    assert "| Benchmark ID | market |" in markdown


def test_reports_expose_annualized_statistics_and_sharpe() -> None:
    run = StrategyRun(
        run_id="annualized-report-run",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=3,
                freq="D",
            ),
            values=np.asarray([0.01, 0.03, 0.05]),
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=4),
        ),
    )
    result = audit_single_run(
        run,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=(1.01**4) - 1.0),
    )

    payload = json.loads(render_json_report(result))
    annualized = payload["annualized_statistics"]
    markdown = render_markdown_report(result)

    assert annualized["return_basis"] == "simple"
    assert annualized["period_risk_free_rate"] == (pytest.approx(0.01))
    assert annualized["annualized_sharpe_ratio"] == (pytest.approx(2.0))
    assert "## Annualized statistics" in markdown
    assert "| Annualized Sharpe ratio | 2 |" in markdown


def test_reports_expose_distribution_and_psr() -> None:
    run = StrategyRun(
        run_id="psr-report-run",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=5,
                freq="D",
            ),
            values=np.asarray([0.01, -0.02, 0.03, 0.005, 0.015]),
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
    )

    payload = json.loads(render_json_report(result))
    markdown = render_markdown_report(result)

    assert payload["distribution_statistics"]["return_basis"] == ("simple")
    assert payload["distribution_statistics"]["sample_pearson_kurtosis"] is not None
    assert payload["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] is not None
    assert payload["track_record_length"] is not None
    assert payload["track_record_length"]["required_psr_confidence_level"] == 0.75
    assert "| Probabilistic Sharpe Ratio |" in markdown
    assert "| Required PSR confidence level | 0.75 |" in markdown


def test_reports_expose_serial_dependence_evidence() -> None:
    values = np.asarray([value / 1000 for value in range(1, 31)])
    run = StrategyRun(
        run_id="serial-report-run",
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

    payload = json.loads(render_json_report(result))
    serial = payload["serial_dependence"]
    markdown = render_markdown_report(result)

    assert serial["maximum_lag"] == 3
    assert serial["status"] == "eligible"
    assert serial["eligible"] is True
    assert len(serial["autocorrelations"]) == 3
    assert serial["autocorrelations"][0]["lag"] == 1
    assert serial["serial_dependence_detected"] is True
    assert "| Serial dependence detected | true |" in markdown
    assert "| Lag | Sample autocorrelation |" in markdown


def test_reports_preserve_ineligible_serial_configuration() -> None:
    run = StrategyRun(
        run_id="ineligible-serial-report-run",
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
            significance_level=0.01,
        ),
    )

    payload = json.loads(render_json_report(result))
    serial = payload["serial_dependence"]
    markdown = render_markdown_report(result)

    assert serial["status"] == "insufficient_observations"
    assert serial["eligible"] is False
    assert serial["maximum_lag"] == 3
    assert serial["significance_level"] == 0.01
    assert serial["p_value"] is None
    assert "| Status | insufficient_observations |" in markdown
    assert "| Significance level | 0.01 |" in markdown


def test_reports_expose_hac_adjustment_evidence() -> None:
    values = np.asarray([0.01, 0.02, 0.03, 0.04, 0.05])
    run = StrategyRun(
        run_id="hac-report-run",
        returns=ReturnSeries(
            timestamps=pd.date_range(
                "2026-01-01",
                periods=len(values),
                freq="D",
            ),
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(periods_per_year=4),
        ),
    )
    result = audit_single_run(
        run,
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
        psr_spec=ProbabilisticSharpeRatioSpec(
            benchmark_annualized_sharpe_ratio=0.0,
            required_psr_confidence_level=0.95,
        ),
        serial_adjustment_spec=SerialAdjustmentSpec(
            maximum_lag=2,
            kernel=HACKernel.BARTLETT,
        ),
    )

    payload = json.loads(render_json_report(result))
    adjustment = payload["serial_adjustment"]
    markdown = render_markdown_report(result)

    assert adjustment["status"] == "eligible"
    assert adjustment["eligible"] is True
    assert adjustment["kernel"] == "bartlett"
    assert adjustment["maximum_lag"] == 2
    assert adjustment["return_long_run_variance_ratio"] == (pytest.approx(22 / 15))
    assert len(adjustment["return_autocorrelations"]) == 2
    assert len(adjustment["influence_autocorrelations"]) == 2
    assert adjustment["hac_period_sharpe_standard_error"] is not None
    assert adjustment["hac_probabilistic_sharpe_ratio"] is not None
    assert "### HAC annualization comparison" in markdown
    assert "### HAC Sharpe uncertainty comparison" in markdown
    assert "| Kernel | bartlett |" in markdown


def test_reports_preserve_ineligible_hac_configuration() -> None:
    result = audit_single_run(
        StrategyRun(
            run_id="ineligible-hac-report-run",
            returns=ReturnSeries(
                timestamps=pd.date_range(
                    "2026-01-01",
                    periods=3,
                    freq="D",
                ),
                values=np.asarray([0.01, 0.02, 0.03]),
                convention=ReturnConvention.SIMPLE,
                sampling=SamplingSpec(periods_per_year=4),
            ),
        ),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
        serial_adjustment_spec=SerialAdjustmentSpec(
            maximum_lag=3,
            kernel=HACKernel.BARTLETT,
        ),
    )

    payload = json.loads(render_json_report(result))
    adjustment = payload["serial_adjustment"]
    markdown = render_markdown_report(result)

    assert adjustment["status"] == "insufficient_observations"
    assert adjustment["eligible"] is False
    assert adjustment["maximum_lag"] == 3
    assert adjustment["kernel"] == "bartlett"
    assert "| Status | insufficient_observations |" in markdown


def test_reports_expose_bootstrap_configuration_and_intervals() -> None:
    values = np.asarray([0.01, -0.02, 0.03, 0.005, 0.015, 0.02])
    result = audit_single_run(
        StrategyRun(
            run_id="bootstrap-report-run",
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
        ),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
        serial_adjustment_spec=SerialAdjustmentSpec(
            maximum_lag=1,
            kernel=HACKernel.BARTLETT,
        ),
        bootstrap_spec=BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=100,
            confidence_level=0.9,
            block_length=2,
            random_seed=42,
        ),
    )

    payload = json.loads(render_json_report(result))
    bootstrap = payload["bootstrap"]
    markdown = render_markdown_report(result)

    assert bootstrap["status"] == "eligible"
    assert bootstrap["eligible"] is True
    assert bootstrap["method"] == "moving_block"
    assert bootstrap["interval_method"] == "percentile"
    assert bootstrap["block_length"] == 2
    assert bootstrap["random_seed"] == 42
    assert bootstrap["overlapping_block_count"] == 5
    assert len(bootstrap["metrics"]) == 8
    assert bootstrap["metrics"][0]["interval_available"] is True
    assert bootstrap["metrics"][0]["successful_replications"] == 100
    assert bootstrap["metrics"][-1]["metric"] == "hac_adjusted_annualized_sharpe_ratio"
    assert "| Method | moving_block |" in markdown
    assert "| Interval method | percentile |" in markdown
    assert "| period_mean_return | eligible |" in markdown


def test_reports_preserve_ineligible_bootstrap_configuration() -> None:
    result = audit_single_run(
        StrategyRun(
            run_id="ineligible-bootstrap-report-run",
            returns=ReturnSeries(
                timestamps=pd.date_range(
                    "2026-01-01",
                    periods=4,
                    freq="D",
                ),
                values=np.asarray([0.01, -0.02, 0.03, 0.005]),
                convention=ReturnConvention.SIMPLE,
                sampling=SamplingSpec(periods_per_year=365),
            ),
        ),
        bootstrap_spec=BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=100,
            confidence_level=0.9,
            block_length=4,
            random_seed=7,
        ),
    )

    payload = json.loads(render_json_report(result))
    bootstrap = payload["bootstrap"]
    markdown = render_markdown_report(result)

    assert bootstrap["status"] == ("block_length_not_below_observation_count")
    assert bootstrap["eligible"] is False
    assert bootstrap["block_length"] == 4
    assert bootstrap["random_seed"] == 7
    assert bootstrap["metrics"] == []
    assert "| Status | block_length_not_below_observation_count |" in markdown
