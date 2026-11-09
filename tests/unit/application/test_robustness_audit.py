import json

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.domain.assumptions import (
    ParameterRobustnessSpec,
    ParameterScale,
    TemporalRobustnessSpec,
)
from backtest_auditor.domain.enums import (
    ParameterDistanceMetric,
    ParameterRobustnessStatus,
    RobustnessPerformanceMetric,
    RobustnessRankTieMethod,
    RobustnessWinnerTiePolicy,
    TemporalRobustnessStatus,
)
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)
from backtest_auditor.reporting.json_report import render_json_report
from backtest_auditor.reporting.markdown_report import render_markdown_report


def _family():
    return read_experiment_family_files(
        "examples/cscv_family_manifest.json",
        "examples/cscv_family_trials.csv",
        "examples/cscv_family_returns.csv",
        splits_path="examples/cscv_family_splits.csv",
    ).family


def _parameter_spec(**overrides: object) -> ParameterRobustnessSpec:
    values = {
        "performance_metric": RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
        "selection_metric_name": "period_sharpe_ratio",
        "annual_risk_free_rate": 0.0,
        "distance_metric": ParameterDistanceMetric.STANDARDIZED_EUCLIDEAN,
        "parameter_scales": (ParameterScale("lookback", 5.0),),
        "maximum_distance": 3.0,
        "minimum_neighbor_count": 2,
        "maximum_acceptable_score_difference": 1.0,
        "minimum_acceptable_neighbor_fraction": 0.5,
    }
    values.update(overrides)
    return ParameterRobustnessSpec(**values)


def _temporal_spec() -> TemporalRobustnessSpec:
    return TemporalRobustnessSpec(
        performance_metric=RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
        selection_metric_name="period_sharpe_ratio",
        annual_risk_free_rate=0.0,
        window_count=4,
        rank_tie_method=RobustnessRankTieMethod.AVERAGE,
        winner_tie_policy=RobustnessWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        minimum_acceptable_top_half_fraction=0.5,
        maximum_acceptable_below_zero_fraction=0.5,
    )


def test_application_keeps_part_o_results_distinct_from_other_family_methods() -> None:
    result = audit_experiment_family(
        _family(),
        parameter_robustness_spec=_parameter_spec(),
        temporal_robustness_spec=_temporal_spec(),
    )

    assert result.deflated_sharpe_ratio is None
    assert result.cscv is None
    assert result.parameter_robustness.status is ParameterRobustnessStatus.ELIGIBLE
    assert result.temporal_robustness.status is TemporalRobustnessStatus.ELIGIBLE
    assert result.temporal_robustness.valid_external_split_count == 2
    codes = {finding.code for finding in result.findings}
    assert "PARAMETER_NEIGHBORHOOD_DEFINITION_CONDITIONAL" in codes
    assert "TEMPORAL_WINDOWS_BOUNDARY_SENSITIVE" in codes


def test_application_reports_sparse_parameter_neighborhood_without_widening_it() -> (
    None
):
    result = audit_experiment_family(
        _family(),
        parameter_robustness_spec=_parameter_spec(
            maximum_distance=0.5,
            minimum_neighbor_count=1,
        ),
    )

    assert result.parameter_robustness.status is (
        ParameterRobustnessStatus.INSUFFICIENT_NEIGHBORS
    )
    assert result.parameter_robustness.neighbors == ()
    assert "PARAMETER_ROBUSTNESS_UNAVAILABLE" in {
        finding.code for finding in result.findings
    }


def test_part_o_json_and_markdown_reports_are_complete() -> None:
    result = audit_experiment_family(
        _family(),
        parameter_robustness_spec=_parameter_spec(),
        temporal_robustness_spec=_temporal_spec(),
    )
    payload = json.loads(render_json_report(result))
    markdown = render_markdown_report(result)

    assert payload["schema_version"] == "2.5"
    assert payload["parameter_robustness"]["status"] == "eligible"
    assert payload["temporal_robustness"]["status"] == "eligible"
    assert "## Parameter-neighborhood robustness" in markdown
    assert "## Temporal and declared-split robustness" in markdown
    assert "### Declared train/test or fold consistency" in markdown
