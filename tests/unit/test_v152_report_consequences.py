"""1.5.2: each fix reaches the published report, through the public CLI.

The adversarial tests in tests/adversarial/ pin each finding at the function
that had the defect. These tests pin what a reader of the report sees once the
fix is in, so a fix that is correct in the helper but not wired into the
report would still fail here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_auditor.cli import main as cli_main


def _write_returns(path: Path, values: np.ndarray, *, freq: str = "D") -> Path:
    timestamps = pd.date_range("2022-01-03", periods=len(values), freq=freq)
    pd.DataFrame(
        {"timestamp": [t.isoformat() for t in timestamps], "return": values}
    ).to_csv(path, index=False)
    return path


def _report(tmp_path: Path, csv_path: Path, *extra: str) -> dict:
    output = tmp_path / f"{csv_path.stem}.json"
    code = cli_main(
        [
            str(csv_path),
            "--run-id",
            csv_path.stem,
            "--format",
            "json",
            "--output",
            str(output),
            *extra,
        ]
    )
    assert code == 0, code
    return json.loads(output.read_text())


def _ar1(phi: float, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    shocks = 0.01 * rng.standard_normal(n + 200)
    path = np.empty_like(shocks)
    path[0] = shocks[0]
    for t in range(1, len(shocks)):
        path[t] = phi * path[t - 1] + shocks[t]
    return path[200:] + 0.0003


def _codes(report: dict) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def test_n18_an_ar1_series_now_carries_the_variance_ratio_finding(tmp_path):
    """AR(1) phi = 0.3, n = 1000: VR(2) - 1 is about 0.3, z* about 8.5. In 1.5.1
    the report printed z = 0.27, p = 0.79 and no finding; now the horizon is
    rejected and the report says so. An IID series of the same length is not
    (seed 6: z = 1.28, p = 0.20; a calibrated test rejects 5 % of IID seeds, and
    seed 5 is one of them, z = 2.14)."""

    dependent = _report(
        tmp_path,
        _write_returns(tmp_path / "ar1.csv", _ar1(0.3, 1000, 4)),
        "--serial-max-lag",
        "2",
        "--serial-significance-level",
        "0.05",
    )
    (horizon,) = dependent["serial_dependence"]["variance_ratios"]
    assert horizon["z_statistic"] > 5.0 and horizon["p_value"] < 1e-6
    assert horizon["dependence_detected"] is True
    assert "VARIANCE_RATIO_DEPENDENCE_DETECTED" in _codes(dependent)

    iid = _report(
        tmp_path,
        _write_returns(
            tmp_path / "iid.csv",
            0.01 * np.random.default_rng(6).standard_normal(1000) + 0.0003,
        ),
        "--serial-max-lag",
        "2",
        "--serial-significance-level",
        "0.05",
    )
    (horizon,) = iid["serial_dependence"]["variance_ratios"]
    assert (
        abs(horizon["z_statistic"]) < 1.96 and horizon["dependence_detected"] is False
    )
    assert "VARIANCE_RATIO_DEPENDENCE_DETECTED" not in _codes(iid)


def test_n21_runs_within_half_a_run_of_their_expectation_publish_z_0_p_1(tmp_path):
    """Two sequences whose run count is within 1/2 of its expectation. 1.5.1's
    continuity correction moved them away from zero (z 0.38, p 0.70 for the
    first; the second flipped sign); now both publish z = 0, p = 1, no finding.

    First: signs + + - - + - - + (median 0.5 %), n+ = n- = 4, R = 5 = E.
    Second: signs + - - + + after the two values equal to the median (3 %)
    are removed, n+ = 3, n- = 2, E = 1 + 12/5 = 3.4, R = 3, R - E = -0.4."""

    for name, values in (
        ("equal", [0.9, 0.8, 0.1, 0.2, 0.7, 0.3, 0.0, 0.6]),
        ("within_half", [4.0, 1.0, 2.0, 3.0, 5.0, 6.0, 3.0]),
    ):
        report = _report(
            tmp_path,
            _write_returns(tmp_path / f"{name}.csv", np.asarray(values) * 0.01),
            "--serial-max-lag",
            "2",
            "--serial-significance-level",
            "0.05",
        )
        runs = report["serial_dependence"]["runs_test"]
        assert runs["z_statistic"] == 0.0 and runs["p_value"] == 1.0, (name, runs)
        assert runs["dependence_detected"] is False
        assert "RUNS_DEPENDENCE_DETECTED" not in _codes(report)


def test_f06_mixed_offsets_get_the_machine_readable_envelope(tmp_path, capsys):
    """Rows alternating +00:00 and +02:00. In 1.5.1 pandas' "Mixed timezones
    detected" escaped normalize_return_series and the CLI printed an argparse
    usage error; now it is the input_validation_failed envelope every other
    input defect uses, naming the first two offsets that differ."""

    timestamps = pd.date_range("2024-01-01", periods=10, freq="D")
    csv_path = tmp_path / "mixed.csv"
    pd.DataFrame(
        {
            "timestamp": [
                t.isoformat() + ("+00:00" if i % 2 == 0 else "+02:00")
                for i, t in enumerate(timestamps)
            ],
            "return": 0.01 * np.random.default_rng(4).standard_normal(10),
        }
    ).to_csv(csv_path, index=False)
    code = cli_main([str(csv_path), "--run-id", "mixed", "--format", "json"])
    assert code == 2
    envelope = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert envelope["error"] == "input_validation_failed"
    (issue,) = envelope["issues"]
    assert issue["code"] == "INVALID_TIMESTAMP" and issue["blocking"] is True
    assert "row 1 has +00:00, row 2 has +02:00" in issue["message"]


def test_f04_percent_units_warning_fires_on_percent_and_not_on_real_decimal_data(
    tmp_path,
):
    """RETURN_MAGNITUDE_SUGGESTS_PERCENT_UNITS: mean |r| above 0.05 for daily or
    faster sampling, 0.05 * sqrt(median interval in days) for slower sampling.
    Decimal series that real strategies produce stay silent: a daily ETF curve
    (sd 1 %), a volatile daily crypto curve (sd 4 %), a monthly equity curve
    (sd 4.5 %), a weekly low-volatility curve (sd 0.3 %). The weekly curve in
    percent units warns; its values all lie in (-1, 1), so nothing else in the
    input contract catches it. (A percent file with a loss below -1 % is
    rejected at ingestion instead, by the message test below.)"""

    rng = np.random.default_rng(11)
    weekly = np.clip(0.003 * rng.standard_normal(104) + 0.0008, -0.0099, 0.0099)
    silent = {
        "etf_daily": (0.01 * rng.standard_normal(500) + 0.0004, "B"),
        "crypto_daily": (0.04 * rng.standard_normal(500) + 0.001, "D"),
        "equity_monthly": (0.045 * rng.standard_normal(60) + 0.007, "MS"),
        "bond_weekly": (weekly, "W-FRI"),
    }
    for name, (values, freq) in silent.items():
        report = _report(
            tmp_path, _write_returns(tmp_path / f"{name}.csv", values, freq=freq)
        )
        assert "RETURN_MAGNITUDE_SUGGESTS_PERCENT_UNITS" not in _codes(report), name

    report = _report(
        tmp_path,
        _write_returns(tmp_path / "weekly_percent.csv", weekly * 100.0, freq="W-FRI"),
    )
    (finding,) = [
        f
        for f in report["findings"]
        if f["code"] == "RETURN_MAGNITUDE_SUGGESTS_PERCENT_UNITS"
    ]
    assert finding["category"] == "data_quality"
    assert "divide percent returns by 100" in finding["remediation"]


def test_f04_threshold_is_the_documented_one():
    from backtest_auditor.audit.context_checks import (
        PERCENT_UNITS_MEAN_ABSOLUTE_RETURN,
        generate_return_magnitude_findings,
    )
    from backtest_auditor.domain.enums import ReturnConvention
    from backtest_auditor.domain.series import ReturnSeries, SamplingSpec

    assert PERCENT_UNITS_MEAN_ABSOLUTE_RETURN == 0.05

    def series(magnitude: float, freq: str) -> ReturnSeries:
        values = np.tile([magnitude, -magnitude], 10)
        return ReturnSeries(
            timestamps=pd.date_range("2024-01-01", periods=20, freq=freq),
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(declared_frequency=freq, periods_per_year=None),
        )

    assert generate_return_magnitude_findings(series(0.0499, "D")) == ()
    assert len(generate_return_magnitude_findings(series(0.0501, "D"))) == 1
    assert generate_return_magnitude_findings(series(0.0501, "h")) != ()
    weekly = 0.05 * np.sqrt(7.0)
    assert generate_return_magnitude_findings(series(weekly * 0.999, "W-MON")) == ()
    assert generate_return_magnitude_findings(series(weekly * 1.001, "W-MON")) != ()


def test_f04_both_below_minus_one_messages_name_percent_units(tmp_path):
    from backtest_auditor.domain.issues import InputValidationError
    from backtest_auditor.ingestion.experiment_family import (
        read_experiment_family_files,
    )

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "family_id": "percent",
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
        "timestamp,trial_id,return\n2026-01-01,t1,0.5\n2026-01-02,t1,-1.5\n"
        "2026-01-03,t1,0.7\n",
        encoding="utf-8",
    )
    try:
        read_experiment_family_files(manifest, trials, returns)
    except InputValidationError as error:
        (issue,) = error.issues
    else:  # pragma: no cover - the -1.5 must be rejected
        raise AssertionError("a simple family return of -1.5 was accepted")
    assert issue.code == "FAMILY_SIMPLE_RETURN_BELOW_MINUS_ONE"
    assert "percent values" in issue.message and "divide them by 100" in issue.message


def _ppy_codes(tmp_path, name, values, freq, ppy, *extra):
    report = _report(
        tmp_path,
        _write_returns(tmp_path / f"{name}.csv", values, freq=freq),
        "--declared-frequency",
        freq,
        "--periods-per-year",
        str(ppy),
        *extra,
    )
    return report, _codes(report)


def test_f03_periods_per_year_cross_check_is_silent_on_the_usual_declarations(
    tmp_path,
):
    """Business days with 252 (about 261 weekdays a year, 3.4 % apart), daily
    with 365, weekly with 52, monthly with 12, hourly 24/7 with 8760."""

    rng = np.random.default_rng(12)
    for name, n, freq, ppy in (
        ("business", 300, "B", 252),
        ("daily", 400, "D", 365),
        ("weekly", 120, "W-FRI", 52),
        ("monthly", 48, "MS", 12),
        ("hourly", 2000, "h", 8760),
    ):
        values = 0.01 * rng.standard_normal(n) + 0.0005
        report, codes = _ppy_codes(tmp_path, name, values, freq, ppy)
        assert report["annualized_statistics"] is not None, name
        assert "PERIODS_PER_YEAR_SAMPLING_MISMATCH" not in codes, name


def test_f03_hourly_crypto_annualized_on_trading_days_is_reported(tmp_path):
    """24/7 hourly bars annualized with 24 x 252 = 6048 instead of 8766: the
    claim gives the implied rate and the implication the Sharpe factor."""

    values = 0.002 * np.random.default_rng(13).standard_normal(3000)
    report, codes = _ppy_codes(tmp_path, "hourly_6048", values, "h", 6048)
    assert "PERIODS_PER_YEAR_SAMPLING_MISMATCH" in codes
    (finding,) = [
        f
        for f in report["findings"]
        if f["code"] == "PERIODS_PER_YEAR_SAMPLING_MISMATCH"
    ]
    assert "8766.0 observations per year" in finding["claim"]
    assert "1.204 times the published values" in finding["implication"]
    # The declaration is still used verbatim.
    assert report["annualized_statistics"]["periods_per_year"] == 6048


def test_f03_spans_under_four_weeks_are_not_judged(tmp_path):
    """20 calendar days declared as 252 per year: a real mismatch, but a span
    this short is not long enough to tell one from a weekend effect."""

    values = 0.01 * np.random.default_rng(14).standard_normal(20)
    _, codes = _ppy_codes(tmp_path, "short", values, "D", 252)
    assert "PERIODS_PER_YEAR_SAMPLING_MISMATCH" not in codes
