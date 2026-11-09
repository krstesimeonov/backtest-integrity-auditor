"""F06 (1.5.2): every timestamp reader keeps mixed UTC offsets inside the
validation contract.

normalize_return_series is pinned by tests/adversarial/test_index_hygiene.py.
The family return matrix, split membership, regime and calendar-session
readers parsed timestamps the same way and let the same pandas ValueError
escape; each now raises InputValidationError with its own code, naming the
first two rows whose offsets differ. The same files with one offset are still
accepted.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.ingestion.calendar_sessions import (
    read_calendar_session_dates_csv,
)
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
    read_experiment_splits_csv,
)
from backtest_auditor.ingestion.regimes import read_regime_series_csv
from backtest_auditor.ingestion.timestamp_offsets import (
    describe_offset_change,
    parse_on_one_timeline,
)

MIXED = [
    "2026-01-01T00:00:00+00:00",
    "2026-01-02T00:00:00+02:00",
    "2026-01-03T00:00:00+00:00",
]
UTC = [
    "2026-01-01T00:00:00+00:00",
    "2026-01-02T00:00:00+00:00",
    "2026-01-03T00:00:00+00:00",
]
CHANGE = "row 1 has +00:00, row 2 has +02:00"


def _family(tmp_path: Path, stamps: list[str]) -> tuple[Path, Path, Path]:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "family_id": "offsets",
                "declared_total_attempted_trials": 1,
                "search_complete": True,
                "selected_trial_id": "t1",
                "selection_rule": "maximize Sharpe",
                "selection_metric": "sharpe",
                "selection_direction": "maximize",
                "parameter_names": ["lookback"],
                "return_convention": "simple",
                "declared_frequency": "D",
                "periods_per_year": 365,
                "timezone": "UTC",
            }
        ),
        encoding="utf-8",
    )
    trials = tmp_path / "trials.csv"
    trials.write_text(
        "trial_id,attempt_index,outcome,included_in_selection,selected,"
        'selection_score,parameters,source,reason\nt1,1,completed,true,true,1.0,"'
        '{""lookback"":10}",grid,\n',
        encoding="utf-8",
    )
    returns = tmp_path / "returns.csv"
    returns.write_text(
        "timestamp,trial_id,return\n"
        + "".join(f"{s},t1,{r}\n" for s, r in zip(stamps, (0.01, 0.02, -0.01))),
        encoding="utf-8",
    )
    return manifest, trials, returns


def _only_issue(error: pytest.ExceptionInfo[InputValidationError]):
    (issue,) = error.value.issues
    return issue


def test_family_returns(tmp_path):
    with pytest.raises(InputValidationError) as caught:
        read_experiment_family_files(*_family(tmp_path, MIXED))
    issue = _only_issue(caught)
    assert issue.code == "INVALID_FAMILY_TIMESTAMP" and CHANGE in issue.message
    accepted = read_experiment_family_files(*_family(tmp_path, UTC))
    assert accepted.family.returns.values.shape == (3, 1)


def test_family_splits(tmp_path):
    expected = pd.DatetimeIndex(pd.to_datetime(UTC))
    path = tmp_path / "splits.csv"
    path.write_text(
        "timestamp,split_id,role\n" + "".join(f"{s},s1,train\n" for s in MIXED),
        encoding="utf-8",
    )
    with pytest.raises(InputValidationError) as caught:
        read_experiment_splits_csv(path, expected_timestamps=expected)
    issue = _only_issue(caught)
    assert issue.code == "INVALID_SPLIT_TIMESTAMP" and CHANGE in issue.message


def test_regimes(tmp_path):
    path = tmp_path / "regimes.csv"
    path.write_text(
        "timestamp,regime\n" + "".join(f"{s},calm\n" for s in MIXED),
        encoding="utf-8",
    )
    with pytest.raises(InputValidationError) as caught:
        read_regime_series_csv(path)
    issue = _only_issue(caught)
    assert issue.code == "INVALID_REGIME_TIMESTAMP" and CHANGE in issue.message
    path.write_text(
        "timestamp,regime\n" + "".join(f"{s},calm\n" for s in UTC),
        encoding="utf-8",
    )
    assert len(read_regime_series_csv(path).series.timestamps) == 3


def test_calendar_sessions(tmp_path):
    path = tmp_path / "sessions.csv"
    path.write_text("session\n" + "".join(f"{s}\n" for s in MIXED), encoding="utf-8")
    with pytest.raises(InputValidationError) as caught:
        read_calendar_session_dates_csv(path, session_column="session")
    issue = _only_issue(caught)
    assert issue.code == "INVALID_CALENDAR_SESSION_DATE" and CHANGE in issue.message


def test_helper_names_offset_free_rows_and_accepts_z_as_utc():
    assert parse_on_one_timeline(["2026-01-01T00:00:00Z", UTC[1]]) is not None
    assert parse_on_one_timeline(["2026-01-01", UTC[1]]) is None
    assert describe_offset_change(["2026-01-01", UTC[1]]) == (
        "row 1 has no offset, row 2 has +00:00"
    )


def test_mixed_offsets_and_an_unparseable_row_are_both_reported():
    """The W2-J6 adversarial review: with mixed offsets the garbage row went
    unreported. Both issues now appear, the unparseable row named by number."""

    from backtest_auditor.domain.enums import ReturnConvention
    from backtest_auditor.domain.series import SamplingSpec
    from backtest_auditor.ingestion.normalization import normalize_return_series

    rows = [*MIXED, "not a date"]
    with pytest.raises(InputValidationError) as caught:
        normalize_return_series(
            rows,
            [0.01, 0.02, -0.01, 0.0],
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(declared_frequency="D", periods_per_year=365),
        )
    messages = [issue.message for issue in caught.value.issues]
    assert [issue.code for issue in caught.value.issues] == ["INVALID_TIMESTAMP"] * 2
    assert CHANGE in messages[0]
    assert "not ISO 8601. First at row 4: 'not a date'" in messages[1]


def test_the_message_names_offsets_only_when_they_differ():
    from backtest_auditor.ingestion.timestamp_offsets import mixed_offset_message

    assert CHANGE in mixed_offset_message("Timestamps", MIXED)
    same = mixed_offset_message("Timestamps", UTC)
    assert "could not be placed on one timeline" in same and "offset (" not in same
