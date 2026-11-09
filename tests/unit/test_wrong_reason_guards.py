"""Guards for two inherited tests that can pass without exercising their code.

1. tests/unit/test_failure_contract.py::test_dst_ambiguous_wall_clock_is_a_typed_blocking_issue
   asserts only that no traceback escapes. On a tree where the input is
   rejected for another reason first, it passes without reaching the DST
   branch. Here the issue code itself is asserted.
2. tests/adversarial/test_index_hygiene.py::test_zero_variance_series_publishes_null_sharpe_without_crashing
   uses fifty returns of 0.001, whose np.std happens to be exactly 0.0, so
   it never meets the rounding residue the 19a2eae port is about. Here the
   series is chosen so that the residue exists, and that is asserted first.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_auditor.domain.assumptions import SharpeRatioSpec
from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import calculate_annualized_statistics
from backtest_auditor.statistics.descriptive import calculate_descriptive_statistics
from backtest_auditor.statistics.sampling import assess_sampling

REPO = Path(__file__).resolve().parents[2]


def test_dst_fold_is_rejected_with_its_own_issue_code(tmp_path: Path) -> None:
    path = tmp_path / "dst.csv"
    # 2024-11-03 01:30 occurs twice in America/New_York.
    path.write_text(
        "timestamp,return\n"
        "2024-11-03 01:30:00,0.01\n"
        "2024-11-03 01:30:00.5,0.002\n"
        "2024-11-04 01:30:00,-0.004\n"
        "2024-11-05 01:30:00,0.003\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtest_auditor.cli",
            str(path),
            "--run-id",
            "dst",
            "--timestamp-timezone",
            "America/New_York",
            "--observation-calendar",
            "24/7",
            "--calendar-timezone",
            "America/New_York",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stderr.strip().splitlines()[-1])
    assert payload["error"] == "input_validation_failed"
    assert [issue["code"] for issue in payload["issues"]] == [
        "AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIMESTAMP"
    ]


def test_constant_series_with_a_std_residue_has_no_sharpe() -> None:
    values = np.full(50, 0.0007)
    assert float(np.std(values, ddof=1)) != 0.0  # the residue the port is about
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=values,
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency="D", periods_per_year=365),
    )

    annualized = calculate_annualized_statistics(
        series,
        assess_sampling(series),
        sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0),
    )
    descriptive = calculate_descriptive_statistics(series)

    assert annualized is not None
    assert annualized.annualized_sharpe_ratio is None
    assert annualized.annualized_sample_volatility == 0.0
    assert descriptive.sample_volatility == 0.0
