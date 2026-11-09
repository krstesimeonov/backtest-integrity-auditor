import json

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)
from backtest_auditor.reporting.json_report import render_json_report
from backtest_auditor.reporting.markdown_report import (
    render_markdown_report,
)


def _result():
    normalized = read_experiment_family_files(
        "examples/experiment_family_manifest.json",
        "examples/experiment_family_trials.csv",
        "examples/experiment_family_returns.csv",
        splits_path="examples/experiment_family_splits.csv",
        benchmark_path="examples/sample_benchmark.csv",
    )
    return audit_experiment_family(
        normalized.family,
        input_issues=normalized.issues,
    )


def test_family_json_report_is_deterministic_and_complete() -> None:
    result = _result()
    first = render_json_report(result)
    second = render_json_report(result)
    payload = json.loads(first)

    assert first == second
    assert first.endswith("\n")
    assert payload["schema_version"] == "2.5"
    assert payload["audit_type"] == "experiment_family"
    assert payload["family_id"] == "example-family"
    assert payload["status"] == "eligible"
    assert payload["structurally_eligible"] is True
    assert payload["completeness"]["complete_search_history"] is True
    assert payload["selection"]["selected_trial_id"] == "trial-003"
    assert payload["deflated_sharpe_ratio"] is None
    assert payload["cscv_probability_of_backtest_overfitting"] is None
    assert payload["parameter_robustness"] is None
    assert payload["temporal_robustness"] is None
    assert payload["evidence_profile"]["overall_status"] is None
    assert payload["run_manifest"] is None
    assert payload["return_matrix"]["exact_timestamp_alignment"] is True
    assert payload["parameter_schema"]["parameter_names"] == [
        "lookback",
        "threshold",
    ]
    assert len(payload["trials"]) == 4
    assert payload["trials"][2]["selection_score"] == 1.1
    assert payload["trials"][3]["return_series_supplied"] is False
    assert len(payload["splits"]) == 2
    assert payload["splits"][0]["in_sample_timestamps"] == [
        "2026-01-01T00:00:00",
        "2026-01-02T00:00:00",
        "2026-01-03T00:00:00",
    ]
    assert payload["splits"][0]["out_of_sample_timestamps"] == [
        "2026-01-04T00:00:00",
        "2026-01-05T00:00:00",
    ]
    assert payload["benchmark"]["benchmark_id"] == "market"


def test_family_markdown_report_is_human_readable() -> None:
    report = render_markdown_report(_result())

    assert report.startswith("# Backtest Integrity Audit\n")
    assert "- Audit type: `experiment_family`" in report
    assert "## Experiment-family completeness" in report
    assert "## Selection record" in report
    assert "## Canonical return matrix" in report
    assert "## Trial evidence" in report
    assert "## Declared splits" in report
    assert "## Shared benchmark" in report
    assert "| Selected trial ID | trial-003 |" in report
    assert "## Deflated Sharpe Ratio" in report
    assert "DSR was not configured." in report
    assert "CSCV/PBO was not configured." in report
    assert "Parameter-neighborhood robustness was not configured." in report
    assert "Temporal robustness was not configured." in report
    assert "## Dimensioned evidence profile" in report
    assert "## Audit-run manifest" in report
    assert "FAILED_EXPERIMENT_TRIALS_DOCUMENTED" in report
