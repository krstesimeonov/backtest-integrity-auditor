import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from backtest_auditor.application.run_manifest import canonical_configuration
from backtest_auditor.cli import main


_IDENTITY_ARGUMENTS = [
    "--audit-id",
    "audit-2026-08-12-001",
    "--audit-timestamp",
    "2026-08-12T20:00:00+02:00",
    "--git-commit",
    "abc123def456",
]


def test_manifest_configuration_serializes_plain_calendar_dates() -> None:
    configuration = canonical_configuration(
        {"expected_session_dates": (date(2026, 1, 1), date(2026, 1, 2))}
    )

    assert configuration == {"expected_session_dates": ["2026-01-01", "2026-01-02"]}


def _write_returns(path: Path, rows: list[str]) -> None:
    path.write_text(
        "timestamp,return\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _single_manifest(
    input_path: Path,
    output_path: Path,
    *,
    periods_per_year: int = 365,
) -> dict:
    exit_code = main(
        [
            str(input_path),
            "--run-id",
            "manifest-test-run",
            "--declared-frequency",
            "D",
            "--periods-per-year",
            str(periods_per_year),
            *_IDENTITY_ARGUMENTS,
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    return json.loads(output_path.read_text(encoding="utf-8"))["run_manifest"]


def test_single_manifest_is_deterministic_and_self_hashing(tmp_path: Path) -> None:
    input_path = tmp_path / "returns.csv"
    _write_returns(
        input_path,
        [
            "2026-01-01,0.01",
            "2026-01-02,-0.005",
            "2026-01-03,0.02",
            "2026-01-04,0.003",
        ],
    )
    first = _single_manifest(input_path, tmp_path / "first.json")
    second = _single_manifest(input_path, tmp_path / "second.json")

    assert first == second
    assert first["audit_timestamp_utc"] == "2026-08-12T18:00:00Z"
    assert first["git_commit"] == "abc123def456"
    assert first["input_artifacts"][0]["file_name"] == "returns.csv"
    assert str(tmp_path) not in first["input_artifacts"][0]["file_name"]
    assert first["random_seeds"] == {}
    assert {item["name"] for item in first["method_versions"]} >= {
        "audit_run_manifest",
        "evidence_profile",
        "sampling_assessment",
    }
    assert {item["name"] for item in first["environment"]["dependencies"]} == {
        "numpy",
        "pandas",
        "scipy",
    }
    body = dict(first)
    recorded_hash = body.pop("manifest_sha256")
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == recorded_hash


def test_raw_and_normalized_hashes_distinguish_bytes_from_data(tmp_path: Path) -> None:
    sorted_input = tmp_path / "sorted.csv"
    unsorted_input = tmp_path / "unsorted.csv"
    rows = [
        "2026-01-01,0.01",
        "2026-01-02,-0.005",
        "2026-01-03,0.02",
        "2026-01-04,0.003",
    ]
    _write_returns(sorted_input, rows)
    _write_returns(unsorted_input, list(reversed(rows)))

    sorted_manifest = _single_manifest(sorted_input, tmp_path / "sorted.json")
    unsorted_manifest = _single_manifest(unsorted_input, tmp_path / "unsorted.json")

    assert (
        sorted_manifest["input_artifacts"][0]["sha256"]
        != unsorted_manifest["input_artifacts"][0]["sha256"]
    )
    assert (
        sorted_manifest["normalized_data_sha256"]
        == unsorted_manifest["normalized_data_sha256"]
    )
    assert {item["code"] for item in unsorted_manifest["warnings"]} >= {
        "TIMESTAMPS_SORTED"
    }


def test_configuration_change_has_its_own_hash(tmp_path: Path) -> None:
    input_path = tmp_path / "returns.csv"
    _write_returns(
        input_path,
        [
            "2026-01-01,0.01",
            "2026-01-02,-0.005",
            "2026-01-03,0.02",
            "2026-01-04,0.003",
        ],
    )
    first = _single_manifest(
        input_path,
        tmp_path / "365.json",
        periods_per_year=365,
    )
    second = _single_manifest(
        input_path,
        tmp_path / "252.json",
        periods_per_year=252,
    )

    assert first["normalized_data_sha256"] == second["normalized_data_sha256"]
    assert first["configuration_sha256"] != second["configuration_sha256"]
    assert first["manifest_sha256"] != second["manifest_sha256"]


@pytest.mark.parametrize(
    "identity_arguments",
    [
        ["--audit-id", "partial"],
        ["--audit-timestamp", "2026-08-12T18:00:00Z"],
        ["--git-commit", "abc123"],
    ],
)
def test_cli_rejects_partial_manifest_identity(
    identity_arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "examples/sample_returns.csv",
                "--run-id",
                "partial-manifest",
                *identity_arguments,
            ]
        )

    assert error.value.code == 2


def test_cli_rejects_naive_audit_timestamp() -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "examples/sample_returns.csv",
                "--run-id",
                "naive-timestamp",
                "--audit-id",
                "audit-1",
                "--audit-timestamp",
                "2026-08-12T18:00:00",
                "--git-commit",
                "abc123",
            ]
        )

    assert error.value.code == 2


def test_family_cli_hashes_every_supplied_input(tmp_path: Path) -> None:
    output_path = tmp_path / "family.json"

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
            *_IDENTITY_ARGUMENTS,
            "--output",
            str(output_path),
        ]
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    manifest = payload["run_manifest"]

    assert exit_code == 0
    assert {item["role"] for item in manifest["input_artifacts"]} == {
        "family_manifest",
        "family_trials",
        "family_returns",
        "family_splits",
        "shared_benchmark",
    }
    reproducibility = next(
        item
        for item in payload["evidence_profile"]["dimensions"]
        if item["dimension"] == "reproducibility"
    )
    assert reproducibility["status"] == "supported_under_stated_assumptions"
