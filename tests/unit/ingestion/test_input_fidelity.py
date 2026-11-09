"""The input must reach the report unchanged, or be rejected loudly.

Both defects here published a report with input_issues == [] whose contents
did not correspond to the file the user supplied. For a tool whose product is
evidence about a backtest, silently altering the input is worse than crashing.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.experiment_family import _read_csv
from backtest_auditor.ingestion.normalization import normalize_return_series


def _codes(error: InputValidationError) -> list[str]:
    return sorted(issue.code for issue in error.issues)


def test_ambiguous_date_format_is_rejected_not_guessed() -> None:
    """01/02/2023 is 1 Feb or 2 Jan depending on locale.

    pandas infers the format from the first element and defaults to
    month-first, so a day-first monthly export parsed as a daily series in
    January. Every row "parsed", no issue was raised, and the report published
    wrong start/end timestamps and a DAILY inferred frequency.
    """

    with pytest.raises(InputValidationError) as caught:
        normalize_return_series(
            timestamps=["01/02/2023", "01/03/2023", "01/04/2023"],
            values=[0.01, -0.004, 0.006],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(declared_frequency=None, periods_per_year=None),
        )

    assert "INVALID_TIMESTAMP" in _codes(caught.value)
    message = next(
        issue.message
        for issue in caught.value.issues
        if issue.code == "INVALID_TIMESTAMP"
    )
    # The message must name the offending row and value, not just say "a
    # timestamp could not be parsed".
    assert "row 1" in message
    assert "01/02/2023" in message


def test_iso8601_timestamps_still_parse() -> None:
    result = normalize_return_series(
        timestamps=["2023-02-01", "2023-03-01T12:30:00", "2023-04-01 00:00:00"],
        values=[0.01, -0.004, 0.006],
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency=None, periods_per_year=None),
    )

    assert len(result.series.timestamps) == 3
    assert result.series.timestamps[0] == pd.Timestamp("2023-02-01")


def test_multiple_unparseable_timestamps_do_not_fabricate_duplicates() -> None:
    """Several NaT values are not duplicate timestamps.

    errors="coerce" collapses every unparseable value to NaT, and
    pd.Index counted those as duplicates, so the emitted payload asserted a
    DUPLICATE_TIMESTAMP defect the input did not contain. The existing test
    used a single bad timestamp, which is why it never caught this.
    """

    with pytest.raises(InputValidationError) as caught:
        normalize_return_series(
            timestamps=["2026-01-01", "not-a-date", "also-bad", "2026-01-04"],
            values=[0.01, -0.004, 0.006, 0.002],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(declared_frequency=None, periods_per_year=None),
        )

    assert _codes(caught.value) == ["INVALID_TIMESTAMP"]


def test_genuine_duplicate_timestamps_are_still_rejected() -> None:
    with pytest.raises(InputValidationError) as caught:
        normalize_return_series(
            timestamps=["2026-01-01", "2026-01-01", "2026-01-03"],
            values=[0.01, -0.004, 0.006],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(declared_frequency=None, periods_per_year=None),
        )

    assert "DUPLICATE_TIMESTAMP" in _codes(caught.value)


@pytest.mark.parametrize(
    "identifier",
    ["007", "0042", "1e3", "00", "1000"],
)
def test_family_csv_identifiers_are_read_as_text(
    identifier: str,
    tmp_path: Path,
) -> None:
    """Zero-padded and scientific-notation ids are ordinary grid-search output.

    dtype inference turned an all-numeric trial_id column into int64, so '007'
    was published as '7' and '1e3' as '1000.0'. Because the manifest is JSON
    (where "007" stays a string) the family was then rejected with "manifest
    selected_trial_id does not match trial metadata" -- an error naming ids
    that are present in the file.
    """

    path = tmp_path / "trials.csv"
    path.write_text(f"trial_id,attempt_index\n{identifier},1\n2000,2\n")

    frame = _read_csv(path)

    assert frame["trial_id"].tolist() == [identifier, "2000"]


def test_family_csv_numeric_columns_survive_text_reading(tmp_path: Path) -> None:
    """dtype=str must not disturb the numeric columns.

    They are re-parsed from text downstream, so no statistical value changes.
    """

    path = tmp_path / "trials.csv"
    path.write_text(
        "trial_id,attempt_index,selection_score\n007,1,0.50401613\n008,2,0.41663293\n"
    )

    frame = _read_csv(path)

    assert [float(value) for value in frame["selection_score"]] == [
        0.50401613,
        0.41663293,
    ]
    assert [int(value) for value in frame["attempt_index"]] == [1, 2]


def test_zero_padded_family_round_trips_through_the_cli(tmp_path: Path) -> None:
    """End to end: the ids in the report are the ids in the file."""

    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[3]
    examples = repo / "examples"
    mapping = {
        "trial-001": "007",
        "trial-002": "008",
        "trial-003": "009",
        "trial-004": "010",
    }
    for name in (
        "cscv_family_trials.csv",
        "cscv_family_returns.csv",
        "cscv_family_splits.csv",
    ):
        text = (examples / name).read_text()
        for old, new in mapping.items():
            text = text.replace(old, new)
        (tmp_path / name).write_text(text)

    manifest = json.loads((examples / "cscv_family_manifest.json").read_text())
    manifest["selected_trial_id"] = mapping[manifest["selected_trial_id"]]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtest_auditor.cli",
            "family",
            str(tmp_path / "manifest.json"),
            str(tmp_path / "cscv_family_trials.csv"),
            str(tmp_path / "cscv_family_returns.csv"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        env={"PYTHONPATH": str(repo / "src"), "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [trial["trial_id"] for trial in payload["trials"]] == [
        "007",
        "008",
        "009",
        "010",
    ]
    assert payload["selection"]["selected_trial_id"] == "007"
    assert payload["input_issues"] == []
