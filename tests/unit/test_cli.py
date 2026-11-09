import json
from pathlib import Path

import pytest

from backtest_auditor.cli import main


_IBKR_FLEX_XML = (
    b'<ChangeInNAV accountId="U123456" fromDate="20260101" '
    b'toDate="20260131" twr="2.5" />'
)


def test_cli_imports_ibkr_flex_files_to_canonical_contract(
    tmp_path: Path, capsys
) -> None:
    statement = tmp_path / "statement.xml"
    statement.write_bytes(_IBKR_FLEX_XML)
    output = tmp_path / "returns.csv"

    exit_code = main(
        [
            "ibkr",
            "files",
            str(statement),
            "--output",
            str(output),
            "--declared-frequency",
            "ME",
            "--periods-per-year",
            "12",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    manifest = json.loads((tmp_path / "returns.ibkr-import.json").read_text())

    assert exit_code == 0
    assert output.read_text() == (
        "timestamp,return,period_start,period_end\n"
        "2026-01-31,0.025000000000000001,2026-01-01,2026-01-31\n"
    )
    assert summary["period_count"] == 1
    assert manifest["source_mode"] == "files"
    assert "U123456" not in json.dumps(manifest)


def test_cli_ibkr_import_refuses_implicit_overwrite(tmp_path: Path) -> None:
    statement = tmp_path / "statement.xml"
    statement.write_bytes(_IBKR_FLEX_XML)
    output = tmp_path / "returns.csv"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main(["ibkr", "files", str(statement), "--output", str(output)])

    assert error.value.code == 2
    assert output.read_text() == "existing"


def test_cli_ibkr_api_uses_environment_token_without_emitting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.configuration = kwargs

        def fetch_statement(self, credentials: object, request: object) -> bytes:
            assert "api-token" not in repr(credentials)
            return _IBKR_FLEX_XML

    monkeypatch.setenv("BACKTEST_AUDITOR_IBKR_FLEX_TOKEN", "api-token")
    monkeypatch.setenv("BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID", "query-id")
    monkeypatch.setattr("backtest_auditor.cli.FlexWebServiceClient", FakeClient)
    output = tmp_path / "api.csv"

    assert main(["ibkr", "api", "--output", str(output)]) == 0
    captured = capsys.readouterr()

    assert output.exists()
    assert "api-token" not in captured.out
    assert "api-token" not in captured.err
    manifest = (tmp_path / "api.ibkr-import.json").read_text()
    assert "api-token" not in manifest
    assert "query-id" not in manifest


def test_cli_ibkr_api_requires_environment_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BACKTEST_AUDITOR_IBKR_FLEX_TOKEN", raising=False)
    with pytest.raises(SystemExit) as error:
        main(
            [
                "ibkr",
                "api",
                "--query-id",
                "query",
                "--output",
                str(tmp_path / "returns.csv"),
            ]
        )
    assert error.value.code == 2


def test_cli_writes_json_report(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "returns.csv"
    output_path = tmp_path / "audit.json"
    input_path.write_text(
        "timestamp,return\n"
        "2026-01-05,0.015\n"
        "2026-01-04,0.005\n"
        "2026-01-03,-0.01\n"
        "2026-01-02,0.02\n"
        "2026-01-01,0.01\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            str(input_path),
            "--run-id",
            "cli-test-run",
            "--declared-frequency",
            "D",
            "--periods-per-year",
            "365",
            "--annual-risk-free-rate",
            "0.0",
            "--benchmark-annualized-sharpe-ratio",
            "0.0",
            "--required-psr-confidence-level",
            "0.75",
            "--serial-max-lag",
            "1",
            "--serial-significance-level",
            "0.05",
            "--hac-max-lag",
            "1",
            "--hac-kernel",
            "bartlett",
            "--bootstrap-method",
            "moving_block",
            "--bootstrap-interval-method",
            "percentile",
            "--bootstrap-replications",
            "100",
            "--bootstrap-confidence-level",
            "0.9",
            "--bootstrap-block-length",
            "2",
            "--bootstrap-seed",
            "42",
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["run_id"] == "cli-test-run"
    assert payload["sampling_assessment"]["status"] == ("declared")
    assert payload["sampling_assessment"]["annualization_eligible"] is True
    assert payload["annualized_statistics"] is not None
    assert payload["annualized_statistics"]["annualized_sharpe_ratio"] is not None
    assert payload["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] is not None
    assert payload["track_record_length"] is not None
    assert payload["schema_version"] == "2.5"
    assert payload["serial_dependence"] is not None
    assert payload["serial_dependence"]["maximum_lag"] == 1
    assert payload["serial_adjustment"] is not None
    assert payload["serial_adjustment"]["maximum_lag"] == 1
    assert payload["serial_adjustment"]["kernel"] == "bartlett"
    assert payload["bootstrap"] is not None
    assert payload["bootstrap"]["method"] == "moving_block"
    assert payload["bootstrap"]["interval_method"] == "percentile"
    assert payload["bootstrap"]["replications"] == 100
    assert len(payload["bootstrap"]["metrics"]) == 8
    assert payload["track_record_length"]["required_psr_confidence_level"] == 0.75
    assert payload["input_issues"][0]["code"] == ("TIMESTAMPS_SORTED")


def test_cli_audits_experiment_family_end_to_end(tmp_path: Path) -> None:
    output_path = tmp_path / "family-audit.json"

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
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["audit_type"] == "experiment_family"
    assert payload["family_id"] == "example-family"
    assert payload["schema_version"] == "2.5"
    assert payload["status"] == "eligible"
    assert payload["completeness"]["documented_trial_count"] == 4
    assert payload["selection"]["selected_trial_id"] == "trial-003"


def test_cli_family_markdown_can_write_report(tmp_path: Path) -> None:
    output_path = tmp_path / "family-audit.md"

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
            "--format",
            "markdown",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert "## Experiment-family completeness" in output_path.read_text(
        encoding="utf-8"
    )


def test_cli_configures_part_o_parameter_temporal_and_fold_evidence(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "part-o.json"

    exit_code = main(
        [
            "family",
            "examples/cscv_family_manifest.json",
            "examples/cscv_family_trials.csv",
            "examples/cscv_family_returns.csv",
            "--splits-csv",
            "examples/cscv_family_splits.csv",
            "--parameter-robustness-metric",
            "period_sharpe_ratio",
            "--parameter-selection-metric-name",
            "period_sharpe_ratio",
            "--parameter-annual-risk-free-rate",
            "0.0",
            "--parameter-distance-metric",
            "standardized_euclidean",
            "--parameter-scale",
            "lookback=5",
            "--parameter-maximum-distance",
            "3",
            "--parameter-minimum-neighbors",
            "2",
            "--parameter-maximum-score-difference",
            "1",
            "--parameter-minimum-acceptable-neighbor-fraction",
            "0.5",
            "--temporal-robustness-metric",
            "period_sharpe_ratio",
            "--temporal-selection-metric-name",
            "period_sharpe_ratio",
            "--temporal-annual-risk-free-rate",
            "0.0",
            "--temporal-windows",
            "4",
            "--temporal-rank-tie-method",
            "average",
            "--temporal-winner-tie-policy",
            "first_by_attempt_index",
            "--temporal-minimum-acceptable-top-half-fraction",
            "0.5",
            "--temporal-maximum-acceptable-below-zero-fraction",
            "0.5",
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["parameter_robustness"]["status"] == "eligible"
    assert payload["parameter_robustness"]["trial_counts"]["neighbors"] == 2
    assert payload["temporal_robustness"]["status"] == "eligible"
    assert len(payload["temporal_robustness"]["windows"]) == 4
    external = payload["temporal_robustness"]["external_split_consistency"]
    assert external["valid_split_count"] == 2
    assert external["invalid_split_count"] == 0


@pytest.mark.parametrize(
    "partial_arguments",
    [
        ["--parameter-robustness-metric", "period_sharpe_ratio"],
        ["--temporal-windows", "4"],
    ],
)
def test_cli_rejects_incomplete_part_o_configuration(
    partial_arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "family",
                "examples/cscv_family_manifest.json",
                "examples/cscv_family_trials.csv",
                "examples/cscv_family_returns.csv",
                *partial_arguments,
            ]
        )

    assert error.value.code == 2


def test_cli_family_returns_two_for_invalid_contract(
    tmp_path: Path,
    capsys,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    trials = tmp_path / "trials.csv"
    trials.write_text("", encoding="utf-8")
    returns = tmp_path / "returns.csv"
    returns.write_text("", encoding="utf-8")

    exit_code = main(["family", str(manifest), str(trials), str(returns)])
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert payload["error"] == "input_validation_failed"
    assert payload["issues"][0]["code"] == ("MISSING_FAMILY_MANIFEST_FIELD")


def test_cli_explicit_single_alias_preserves_legacy_mode(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "single.json"

    exit_code = main(
        [
            "single",
            "examples/sample_returns.csv",
            "--run-id",
            "explicit-single",
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["audit_type"] == "single_run"
    assert payload["run_id"] == "explicit-single"


def test_cli_returns_two_for_invalid_input(
    tmp_path: Path,
    capsys,
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,value\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    exit_code = main([str(input_path), "--run-id", "invalid-run"])
    error_payload = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert error_payload["error"] == "input_validation_failed"
    assert error_payload["issues"][0]["code"] == ("MISSING_REQUIRED_COLUMN")


def test_cli_ingests_calendar_metadata_and_benchmark(
    tmp_path: Path,
) -> None:
    strategy_path = tmp_path / "strategy.csv"
    benchmark_path = tmp_path / "benchmark.csv"
    sessions_path = tmp_path / "sessions.csv"
    output_path = tmp_path / "audit.json"
    strategy_path.write_text(
        "timestamp,return\n2026-01-02,0.02\n2026-01-05,0.01\n2026-01-06,-0.01\n",
        encoding="utf-8",
    )
    benchmark_path.write_text(
        "timestamp,return\n2026-01-02,0.01\n2026-01-05,0.00\n2026-01-06,-0.005\n",
        encoding="utf-8",
    )
    sessions_path.write_text(
        "session\n2026-01-02\n2026-01-05\n2026-01-06\n",
        encoding="utf-8",
    )
    common_metadata = [
        "--transaction-costs-included",
        "true",
        "--fees-included",
        "true",
        "--leverage-policy",
        "unlevered",
        "--currency",
        "USD",
        "--price-adjustment-policy",
        "adjusted",
        "--data-source",
        "point-in-time-vendor",
        "--data-vintage",
        "2026-08-11",
        "--stale-price-policy",
        "reject-carried-prices",
        "--delisting-return-policy",
        "include-terminal-returns",
        "--survivorship-bias-controlled",
        "true",
        "--lookahead-bias-controlled",
        "true",
        "--signal-timing",
        "close-t",
        "--execution-timing",
        "open-t-plus-1",
    ]
    benchmark_metadata = [
        item.replace("--", "--benchmark-", 1) if item.startswith("--") else item
        for item in common_metadata
    ]

    exit_code = main(
        [
            str(strategy_path),
            "--run-id",
            "relative-cli-run",
            "--periods-per-year",
            "252",
            "--timestamp-timezone",
            "America/New_York",
            "--observation-calendar",
            "XNYS",
            "--calendar-timezone",
            "America/New_York",
            "--calendar-sessions-csv",
            str(sessions_path),
            *common_metadata,
            "--benchmark-csv",
            str(benchmark_path),
            "--benchmark-id",
            "market",
            "--benchmark-timestamp-timezone",
            "America/New_York",
            "--benchmark-observation-calendar",
            "XNYS",
            "--benchmark-calendar-timezone",
            "America/New_York",
            "--benchmark-calendar-sessions-csv",
            str(sessions_path),
            *benchmark_metadata,
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["observation_calendar"]["status"] == "verified"
    assert payload["sampling_assessment"]["status"] == ("calendar_verified")
    assert payload["return_construction"]["completeness_ratio"] == 1.0
    assert payload["benchmark"]["alignment"]["eligible"] is True
    assert payload["benchmark"]["comparison"]["benchmark_id"] == "market"
    assert payload["benchmark"]["comparison"]["period_tracking_error"] is not None


@pytest.mark.parametrize(
    "arguments",
    [
        ["--observation-calendar", "XNYS"],
        ["--calendar-timezone", "America/New_York"],
        ["--benchmark-csv", "benchmark.csv"],
        ["--benchmark-id", "market"],
    ],
)
def test_cli_rejects_incomplete_calendar_or_benchmark_contract(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,return\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        main([str(input_path), "--run-id", "invalid-context", *arguments])

    assert error.value.code == 2


def test_cli_confidence_level_requires_sharpe_benchmark(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,return\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        main(
            [
                str(input_path),
                "--run-id",
                "invalid-confidence-run",
                "--required-psr-confidence-level",
                "0.95",
            ]
        )

    assert error.value.code == 2


@pytest.mark.parametrize(
    "serial_arguments",
    [
        ["--serial-max-lag", "1"],
        ["--serial-significance-level", "0.05"],
    ],
)
def test_cli_requires_both_serial_diagnostic_choices(
    tmp_path: Path,
    serial_arguments: list[str],
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,return\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        main(
            [
                str(input_path),
                "--run-id",
                "invalid-serial-run",
                *serial_arguments,
            ]
        )

    assert error.value.code == 2


@pytest.mark.parametrize(
    "hac_arguments",
    [
        ["--hac-max-lag", "1"],
        ["--hac-kernel", "bartlett"],
    ],
)
def test_cli_requires_both_hac_adjustment_choices(
    tmp_path: Path,
    hac_arguments: list[str],
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,return\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        main(
            [
                str(input_path),
                "--run-id",
                "invalid-hac-run",
                *hac_arguments,
            ]
        )

    assert error.value.code == 2


@pytest.mark.parametrize(
    "bootstrap_arguments",
    [
        ["--bootstrap-method", "moving_block"],
        ["--bootstrap-seed", "42"],
        [
            "--bootstrap-method",
            "moving_block",
            "--bootstrap-interval-method",
            "percentile",
            "--bootstrap-replications",
            "100",
            "--bootstrap-confidence-level",
            "0.9",
            "--bootstrap-block-length",
            "2",
        ],
    ],
)
def test_cli_requires_complete_bootstrap_configuration(
    tmp_path: Path,
    bootstrap_arguments: list[str],
) -> None:
    input_path = tmp_path / "returns.csv"
    input_path.write_text(
        "timestamp,return\n2026-01-01,0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        main(
            [
                str(input_path),
                "--run-id",
                "invalid-bootstrap-run",
                *bootstrap_arguments,
            ]
        )

    assert error.value.code == 2


def test_cli_exposes_v1_4_single_run_evidence_end_to_end(tmp_path: Path) -> None:
    output = tmp_path / "v1-4-single.json"

    exit_code = main(
        [
            "examples/sample_returns.csv",
            "--run-id",
            "v1-4-single",
            "--declared-frequency",
            "D",
            "--periods-per-year",
            "365",
            "--risk-free-csv",
            "examples/sample_risk_free.csv",
            "--gross-returns-csv",
            "examples/sample_gross_returns.csv",
            "--regimes-csv",
            "examples/sample_regimes.csv",
            "--minimum-acceptable-period-return",
            "0.0",
            "--tail-confidence-level",
            "0.95",
            "--serial-max-lag",
            "2",
            "--serial-significance-level",
            "0.05",
            "--bootstrap-method",
            "stationary",
            "--bootstrap-interval-method",
            "percentile",
            "--bootstrap-replications",
            "20",
            "--bootstrap-confidence-level",
            "0.9",
            "--bootstrap-block-length",
            "2",
            "--bootstrap-seed",
            "42",
            "--benchmark-csv",
            "examples/sample_benchmark.csv",
            "--benchmark-id",
            "market",
            "--benchmark-alpha-hac-max-lag",
            "1",
            "--benchmark-alpha-confidence-level",
            "0.95",
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["advanced_risk_statistics"]["status"] == "eligible"
    assert payload["risk_free_series"]["alignment"]["status"] == "eligible"
    assert payload["gross_net_cost_drag"]["alignment"]["status"] == "eligible"
    assert payload["regime_analysis"]["regime_count"] == 2
    assert payload["benchmark_alpha_inference"]["status"] == "eligible"
    assert payload["bootstrap"]["method"] == "stationary"
    assert len(payload["serial_dependence"]["partial_autocorrelations"]) == 2
    assert len(payload["serial_dependence"]["variance_ratios"]) == 1


def test_cli_exposes_v1_4_family_data_snooping_end_to_end(tmp_path: Path) -> None:
    output = tmp_path / "v1-4-family.json"

    exit_code = main(
        [
            "family",
            "examples/cscv_family_manifest_v1_4.json",
            "examples/cscv_family_trials.csv",
            "examples/cscv_family_returns.csv",
            "--benchmark-csv",
            "examples/cscv_family_benchmark.csv",
            "--data-snooping-replications",
            "50",
            "--data-snooping-mean-block-length",
            "2",
            "--data-snooping-seed",
            "42",
            "--data-snooping-significance-level",
            "0.05",
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["data_snooping"]["status"] == "eligible"
    assert payload["data_snooping"]["benchmark_id"] == "market"
    assert payload["data_snooping"]["replications"] == 50
    assert payload["data_snooping"]["random_seed"] == 42
