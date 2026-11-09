import json
from pathlib import Path

import pytest

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.cli import main
from backtest_auditor.domain.assumptions import DeflatedSharpeRatioSpec
from backtest_auditor.domain.enums import (
    DeflatedSharpeRatioMethod,
    DeflatedSharpeRatioStatus,
    DSRTrialCountBasis,
    DSRTrialCountPolicy,
)
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)
from backtest_auditor.reporting.json_report import render_json_report
from backtest_auditor.reporting.markdown_report import (
    render_markdown_report,
)


def _family():
    return read_experiment_family_files(
        "examples/experiment_family_manifest.json",
        "examples/experiment_family_trials.csv",
        "examples/experiment_family_returns.csv",
        splits_path="examples/experiment_family_splits.csv",
        benchmark_path="examples/sample_benchmark.csv",
    ).family


def _spec() -> DeflatedSharpeRatioSpec:
    return DeflatedSharpeRatioSpec(
        method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        annual_risk_free_rate=0.03,
        required_confidence_level=0.95,
        effective_independent_trial_count=1,
        effective_trial_count_methodology="predeclared cluster count",
    )


def test_family_audit_orchestrates_dsr_and_methodology_findings() -> None:
    result = audit_experiment_family(_family(), dsr_spec=_spec())
    dsr = result.deflated_sharpe_ratio
    finding_codes = {finding.code for finding in result.findings}

    assert dsr is not None
    assert dsr.status is DeflatedSharpeRatioStatus.ELIGIBLE
    assert [item.trial_count_basis for item in dsr.scenarios] == [
        DSRTrialCountBasis.SELECTION_ELIGIBLE,
        DSRTrialCountBasis.DECLARED_ATTEMPTS,
        DSRTrialCountBasis.USER_SUPPLIED_EFFECTIVE,
    ]
    assert "DEFLATED_SHARPE_RATIO_NOT_CONFIGURED" not in finding_codes
    assert "DSR_CONFIDENCE_REQUIREMENT_NOT_MET" in finding_codes
    assert "DSR_INDEPENDENT_TRIALS_APPROXIMATION" in finding_codes
    assert "DSR_ASYMPTOTIC_PLUGIN_INFERENCE" in finding_codes
    assert "DSR_SERIAL_DEPENDENCE_NOT_ADJUSTED" in finding_codes
    assert "EXCLUDED_TRIALS_EXCEED_SELECTED_SHARPE" in finding_codes
    assert "USER_SUPPLIED_EFFECTIVE_TRIAL_COUNT_UNVERIFIED" in finding_codes


def test_family_reports_expose_complete_dsr_evidence() -> None:
    result = audit_experiment_family(_family(), dsr_spec=_spec())
    payload = json.loads(render_json_report(result))
    markdown = render_markdown_report(result)
    dsr = payload["deflated_sharpe_ratio"]

    assert payload["schema_version"] == "2.5"
    assert dsr["status"] == "eligible"
    assert dsr["method"] == "classic_expected_maximum"
    assert dsr["trial_counts"]["declared_attempted"] == 4
    assert dsr["trial_counts"]["selection_eligible"] == 2
    assert dsr["trial_counts"]["effective_count_verified"] is False
    assert dsr["selected_trial"]["trial_id"] == "trial-003"
    assert dsr["selected_trial"]["is_observed_maximum"] is True
    assert dsr["selected_trial"]["iid_annualized_sharpe_ratio"] is not None
    assert len(dsr["trial_sharpe_estimates"]) == 3
    assert [item["trial_count_basis"] for item in dsr["scenarios"]] == [
        "selection_eligible",
        "declared_attempts",
        "user_supplied_effective",
    ]
    assert dsr["correlation_summary"]["pair_count"] == 1
    assert "## Deflated Sharpe Ratio" in markdown
    assert "### DSR trial-count scenarios" in markdown
    assert "### Trial-dependence evidence" in markdown
    assert "DSR is not CSCV or PBO" in markdown


def test_family_cli_runs_configured_dsr_end_to_end(tmp_path: Path) -> None:
    output_path = tmp_path / "part-m.json"
    exit_code = main(
        [
            "family",
            "examples/experiment_family_manifest.json",
            "examples/experiment_family_trials.csv",
            "examples/experiment_family_returns.csv",
            "--splits-csv",
            "examples/experiment_family_splits.csv",
            "--benchmark-csv",
            "examples/sample_benchmark.csv",
            "--dsr-method",
            "classic_expected_maximum",
            "--dsr-trial-count-policy",
            "selection_eligible",
            "--dsr-annual-risk-free-rate",
            "0.03",
            "--dsr-confidence-level",
            "0.95",
            "--dsr-effective-independent-trials",
            "1",
            "--dsr-effective-trial-count-methodology",
            "predeclared cluster count",
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["deflated_sharpe_ratio"]["status"] == "eligible"
    assert len(payload["deflated_sharpe_ratio"]["scenarios"]) == 3


@pytest.mark.parametrize(
    "arguments",
    [
        ["--dsr-method", "classic_expected_maximum"],
        [
            "--dsr-method",
            "classic_expected_maximum",
            "--dsr-trial-count-policy",
            "selection_eligible",
            "--dsr-annual-risk-free-rate",
            "0.0",
        ],
        ["--dsr-effective-independent-trials", "1"],
        [
            "--dsr-effective-trial-count-methodology",
            "external clusters",
        ],
    ],
)
def test_family_cli_rejects_incomplete_dsr_configuration(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "family",
                "examples/experiment_family_manifest.json",
                "examples/experiment_family_trials.csv",
                "examples/experiment_family_returns.csv",
                *arguments,
            ]
        )

    assert error.value.code == 2
