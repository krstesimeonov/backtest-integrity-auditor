import json
from pathlib import Path

import numpy as np
import pytest

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
    read_experiment_family_manifest_json,
)


def _manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "family_id": "family-test",
        "declared_total_attempted_trials": 3,
        "search_complete": True,
        "selected_trial_id": "trial-2",
        "selection_rule": "maximize validation Sharpe",
        "selection_metric": "validation_sharpe",
        "selection_direction": "maximize",
        "parameter_names": ["lookback"],
        "return_convention": "simple",
        "declared_frequency": "D",
        "periods_per_year": 365,
        "timezone": "UTC",
    }
    payload.update(overrides)
    return payload


def _write_manifest(path: Path, **overrides: object) -> None:
    path.write_text(
        json.dumps(_manifest_payload(**overrides)),
        encoding="utf-8",
    )


def _write_trials(path: Path, *, reversed_rows: bool = False) -> None:
    rows = [
        'trial-1,1,completed,true,false,1.0,"{""lookback"":10}",grid,',
        'trial-2,2,completed,true,true,2.0,"{""lookback"":20}",grid,',
        'trial-3,3,failed,false,false,,"{""lookback"":30}",grid,engine failure',
    ]
    if reversed_rows:
        rows.reverse()
    path.write_text(
        "trial_id,attempt_index,outcome,included_in_selection,selected,"
        "selection_score,parameters,source,reason\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _write_returns(
    path: Path,
    *,
    reverse_rows: bool = False,
    omit_trial_2_last: bool = False,
) -> None:
    rows = [
        "2026-01-01,trial-1,0.01",
        "2026-01-02,trial-1,-0.01",
        "2026-01-03,trial-1,0.02",
        "2026-01-04,trial-1,0.00",
        "2026-01-01,trial-2,0.02",
        "2026-01-02,trial-2,0.00",
        "2026-01-03,trial-2,0.03",
        "2026-01-04,trial-2,-0.01",
    ]
    if omit_trial_2_last:
        rows.pop()
    if reverse_rows:
        rows.reverse()
    path.write_text(
        "timestamp,trial_id,return\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _family_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest = tmp_path / "manifest.json"
    trials = tmp_path / "trials.csv"
    returns = tmp_path / "returns.csv"
    _write_manifest(manifest)
    _write_trials(trials)
    _write_returns(returns)
    return manifest, trials, returns


def test_family_files_normalize_deterministically_and_preserve_failures(
    tmp_path: Path,
) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    _write_trials(trials, reversed_rows=True)
    _write_returns(returns, reverse_rows=True)

    normalized = read_experiment_family_files(manifest, trials, returns)

    assert tuple(item.trial_id for item in normalized.family.trials) == (
        "trial-1",
        "trial-2",
        "trial-3",
    )
    assert normalized.family.returns.trial_ids == ("trial-1", "trial-2")
    assert normalized.family.returns.values.shape == (4, 2)
    assert np.array_equal(
        normalized.family.returns.values[:, 1],
        np.asarray([0.02, 0.0, 0.03, -0.01]),
    )
    assert {issue.code for issue in normalized.issues} == {
        "TRIAL_METADATA_SORTED",
        "FAMILY_RETURNS_SORTED",
    }


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"schema_version": "9.9"}, "UNSUPPORTED_FAMILY_INPUT_SCHEMA_VERSION"),
        ({"parameter_names": ["z", "a"]}, "INVALID_FAMILY_MANIFEST_VALUE"),
        ({"search_complete": "yes"}, "INVALID_FAMILY_SEARCH_COMPLETENESS"),
    ],
)
def test_manifest_rejects_unsupported_or_ambiguous_contracts(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, **overrides)

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_manifest_json(manifest)

    assert error.value.issues[0].code == expected_code


def test_manifest_rejects_missing_and_unknown_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    payload = _manifest_payload(typo_field=True)
    payload.pop("selection_rule")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_manifest_json(manifest)

    assert {issue.code for issue in error.value.issues} == {
        "MISSING_FAMILY_MANIFEST_FIELD",
        "UNKNOWN_FAMILY_MANIFEST_FIELD",
    }


def test_trial_parameter_schema_mismatch_is_blocking(tmp_path: Path) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    trials.write_text(
        "trial_id,attempt_index,outcome,included_in_selection,selected,"
        "selection_score,parameters\n"
        'trial-1,1,completed,true,false,1.0,"{""threshold"":1.0}"\n'
        'trial-2,2,completed,true,true,2.0,"{""lookback"":20}"\n'
        'trial-3,3,failed,false,false,,"{""lookback"":30}"\n',
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_files(manifest, trials, returns)

    assert error.value.issues[0].code == "INVALID_TRIAL_METADATA"
    assert "parameter schema mismatch" in error.value.issues[0].message


def test_duplicate_trial_identity_is_blocking(tmp_path: Path) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    trials.write_text(
        "trial_id,attempt_index,outcome,included_in_selection,selected,"
        "selection_score,parameters,reason\n"
        'trial-1,1,completed,true,false,1.0,"{""lookback"":10}",\n'
        'trial-1,2,completed,true,true,2.0,"{""lookback"":20}",\n'
        'trial-3,3,failed,false,false,,"{""lookback"":30}",failure\n',
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_files(manifest, trials, returns)

    assert any(issue.code == "DUPLICATE_TRIAL_ID" for issue in error.value.issues)


def test_return_matrix_requires_exact_timestamp_alignment(
    tmp_path: Path,
) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    _write_returns(returns, omit_trial_2_last=True)

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_files(manifest, trials, returns)

    assert error.value.issues[0].code == ("FAMILY_RETURN_TIMESTAMPS_NOT_ALIGNED")


def test_completed_trial_must_have_returns_and_failed_trial_must_not(
    tmp_path: Path,
) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    returns.write_text(
        "timestamp,trial_id,return\n"
        "2026-01-01,trial-1,0.01\n"
        "2026-01-02,trial-1,0.02\n"
        "2026-01-01,trial-3,0.00\n"
        "2026-01-02,trial-3,0.00\n",
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_files(manifest, trials, returns)

    assert error.value.issues[0].code == "FAILED_TRIAL_HAS_RETURN_SERIES"


def test_splits_require_complete_disjoint_roles(tmp_path: Path) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    splits = tmp_path / "splits.csv"
    splits.write_text(
        "split_id,timestamp,role\n"
        "fold-1,2026-01-01,in_sample\n"
        "fold-1,2026-01-02,in_sample\n"
        "fold-1,2026-01-03,out_of_sample\n",
        encoding="utf-8",
    )

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_files(
            manifest,
            trials,
            returns,
            splits_path=splits,
        )

    assert error.value.issues[0].code == "INCOMPLETE_SPLIT_MEMBERSHIP"


def test_family_ingests_complete_splits_and_shared_benchmark(
    tmp_path: Path,
) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    _write_manifest(
        manifest,
        benchmark_id="market",
        benchmark_return_convention="simple",
    )
    splits = tmp_path / "splits.csv"
    splits.write_text(
        "split_id,timestamp,role\n"
        "fold-1,2026-01-01,in_sample\n"
        "fold-1,2026-01-02,in_sample\n"
        "fold-1,2026-01-03,out_of_sample\n"
        "fold-1,2026-01-04,out_of_sample\n",
        encoding="utf-8",
    )
    benchmark = tmp_path / "benchmark.csv"
    benchmark.write_text(
        "timestamp,return\n"
        "2026-01-01,0.00\n"
        "2026-01-02,0.01\n"
        "2026-01-03,-0.01\n"
        "2026-01-04,0.02\n",
        encoding="utf-8",
    )

    normalized = read_experiment_family_files(
        manifest,
        trials,
        returns,
        splits_path=splits,
        benchmark_path=benchmark,
    )

    assert len(normalized.family.splits) == 1
    assert normalized.family.benchmark_returns is not None


def test_benchmark_declaration_and_file_are_all_or_nothing(
    tmp_path: Path,
) -> None:
    manifest, trials, returns = _family_files(tmp_path)
    benchmark = tmp_path / "benchmark.csv"
    benchmark.write_text("timestamp,return\n", encoding="utf-8")

    with pytest.raises(InputValidationError) as error:
        read_experiment_family_files(
            manifest,
            trials,
            returns,
            benchmark_path=benchmark,
        )

    assert error.value.issues[0].code == ("INCOMPLETE_FAMILY_BENCHMARK_CONTRACT")
