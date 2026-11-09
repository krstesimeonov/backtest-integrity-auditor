import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.cli import main
from backtest_auditor.domain.assumptions import CSCVSpec
from backtest_auditor.domain.enums import (
    CSCVMethod,
    CSCVPerformanceMetric,
    CSCVRankTieMethod,
    CSCVStatus,
    CSCVWinnerTiePolicy,
)
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)
from backtest_auditor.reporting.json_report import render_json_report
from backtest_auditor.reporting.markdown_report import render_markdown_report

_VALUES = (
    (0.040, 0.010, -0.020, 0.030),
    (-0.010, 0.020, 0.010, -0.020),
    (0.030, -0.010, 0.020, 0.010),
    (-0.020, 0.030, -0.010, 0.020),
    (0.010, -0.020, 0.040, -0.010),
    (0.020, 0.010, -0.020, 0.040),
    (-0.010, 0.040, 0.010, -0.020),
    (0.030, -0.010, 0.020, 0.010),
)


def _write_family_files(
    tmp_path: Path, *, with_splits: bool = False
) -> tuple[Path, ...]:
    manifest_path = tmp_path / "manifest.json"
    trials_path = tmp_path / "trials.csv"
    returns_path = tmp_path / "returns.csv"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "family_id": "part-n-family",
                "declared_total_attempted_trials": 4,
                "search_complete": True,
                "selected_trial_id": "trial-1",
                "selection_rule": "maximize period Sharpe",
                "selection_metric": "period_sharpe_ratio",
                "selection_direction": "maximize",
                "parameter_names": ["lookback"],
                "return_convention": "simple",
                "declared_frequency": "B",
                "periods_per_year": 252,
            }
        ),
        encoding="utf-8",
    )
    with trials_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "trial_id",
                "attempt_index",
                "outcome",
                "included_in_selection",
                "selected",
                "selection_score",
                "parameters",
            ]
        )
        for index in range(4):
            writer.writerow(
                [
                    f"trial-{index + 1}",
                    index + 1,
                    "completed",
                    "true",
                    "true" if index == 0 else "false",
                    4 - index,
                    json.dumps({"lookback": index + 1}),
                ]
            )
    timestamps = [
        item.date().isoformat()
        for item in pd.date_range("2026-01-01", periods=8, freq="B")
    ]
    with returns_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "trial_id", "return"])
        for trial_index in range(4):
            for timestamp, row in zip(timestamps, _VALUES, strict=True):
                writer.writerow(
                    [timestamp, f"trial-{trial_index + 1}", row[trial_index]]
                )
    if not with_splits:
        return manifest_path, trials_path, returns_path

    splits_path = tmp_path / "splits.csv"
    with splits_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["split_id", "timestamp", "role"])
        for timestamp_index, timestamp in enumerate(timestamps):
            writer.writerow(
                [
                    "external-holdout",
                    timestamp,
                    "in_sample" if timestamp_index < 4 else "out_of_sample",
                ]
            )
    return manifest_path, trials_path, returns_path, splits_path


def _spec() -> CSCVSpec:
    return CSCVSpec(
        method=CSCVMethod.COMBINATORIALLY_SYMMETRIC,
        performance_metric=CSCVPerformanceMetric.PERIOD_SHARPE_RATIO,
        selection_metric_name="period_sharpe_ratio",
        partition_count=4,
        annual_risk_free_rate=0.0,
        maximum_combinations=100,
        rank_tie_method=CSCVRankTieMethod.AVERAGE,
        winner_tie_policy=CSCVWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
        maximum_acceptable_pbo=0.05,
    )


def test_family_audit_orchestrates_cscv_and_methodology_findings(
    tmp_path: Path,
) -> None:
    manifest, trials, returns, splits = _write_family_files(
        tmp_path,
        with_splits=True,
    )
    family = read_experiment_family_files(
        manifest,
        trials,
        returns,
        splits_path=splits,
    ).family
    result = audit_experiment_family(family, cscv_spec=_spec())
    finding_codes = {finding.code for finding in result.findings}

    assert result.cscv is not None
    assert result.cscv.status is CSCVStatus.ELIGIBLE
    assert "CSCV_PBO_NOT_CONFIGURED" not in finding_codes
    assert "PBO_RANK_GRANULARITY_LIMITED" in finding_codes
    assert "PBO_COMBINATION_RESOLUTION_LIMITED" in finding_codes
    assert "DECLARED_SPLITS_NOT_USED_BY_CSCV" in finding_codes
    assert "CSCV_TIME_DEPENDENCE_LIMITATION" in finding_codes
    assert "CSCV_NOT_A_SELECTION_OBJECTIVE" in finding_codes


def test_family_reports_expose_complete_cscv_evidence(tmp_path: Path) -> None:
    manifest, trials, returns = _write_family_files(tmp_path)
    family = read_experiment_family_files(manifest, trials, returns).family
    result = audit_experiment_family(family, cscv_spec=_spec())
    payload = json.loads(render_json_report(result))
    markdown = render_markdown_report(result)
    cscv = payload["cscv_probability_of_backtest_overfitting"]

    assert payload["schema_version"] == "2.5"
    assert payload["deflated_sharpe_ratio"] is None
    assert cscv["status"] == "eligible"
    assert cscv["method"] == "combinatorially_symmetric"
    assert cscv["partition_count"] == 4
    assert cscv["total_combinations"] == 6
    assert cscv["valid_split_count"] == 6
    assert len(cscv["partitions"]) == 4
    assert len(cscv["splits"]) == 6
    assert cscv["splits"][0]["in_sample_partition_indices"] == [1, 2]
    assert "## CSCV and Probability of Backtest Overfitting" in markdown
    assert "### CSCV split evidence" in markdown
    assert "distinct from PSR and full-sample DSR" in markdown


def test_family_cli_runs_configured_cscv_end_to_end(
    tmp_path: Path,
) -> None:
    manifest, trials, returns = _write_family_files(tmp_path)
    output_path = tmp_path / "part-n.json"
    exit_code = main(
        [
            "family",
            str(manifest),
            str(trials),
            str(returns),
            "--cscv-method",
            "combinatorially_symmetric",
            "--cscv-performance-metric",
            "period_sharpe_ratio",
            "--cscv-selection-metric-name",
            "period_sharpe_ratio",
            "--cscv-partitions",
            "4",
            "--cscv-annual-risk-free-rate",
            "0.0",
            "--cscv-maximum-combinations",
            "100",
            "--cscv-rank-tie-method",
            "average",
            "--cscv-winner-tie-policy",
            "first_by_attempt_index",
            "--cscv-maximum-acceptable-pbo",
            "0.05",
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["cscv_probability_of_backtest_overfitting"]["status"] == "eligible"
    assert (
        payload["cscv_probability_of_backtest_overfitting"]["total_combinations"] == 6
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--cscv-method", "combinatorially_symmetric"],
        ["--cscv-partitions", "4"],
        ["--cscv-maximum-acceptable-pbo", "0.05"],
    ],
)
def test_family_cli_rejects_incomplete_cscv_configuration(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    manifest, trials, returns = _write_family_files(tmp_path)
    with pytest.raises(SystemExit) as error:
        main(["family", str(manifest), str(trials), str(returns), *arguments])

    assert error.value.code == 2
