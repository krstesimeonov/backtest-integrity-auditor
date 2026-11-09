"""Adversarial tests: periods-per-year vs timestamp frequency, and return units.

V1 never infers periods-per-year (README). These tests check whether it at least
*cross-checks* the declared value against what the timestamps imply, and what it
does with percent-unit or log returns supplied as simple decimals.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from .conftest import annualized_and_distribution, make_series, ref

from backtest_auditor.cli import main as cli_main
from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.normalization import normalize_return_series


def _write_csv(path, timestamps, values):
    pd.DataFrame(
        {"timestamp": [t.isoformat() for t in timestamps], "return": values}
    ).to_csv(path, index=False)


def _run_cli(tmp_path, csv_path, *extra):
    out = tmp_path / "report.json"
    code = cli_main(
        [
            str(csv_path),
            "--run-id",
            "r",
            "--annual-risk-free-rate",
            "0.0",
            "--format",
            "json",
            "--output",
            str(out),
            *extra,
        ]
    )
    assert code == 0, code
    return json.loads(out.read_text())


@pytest.mark.parametrize(
    "freq,ppy",
    [
        ("h", 24 * 365),
        ("min", 525_600),
        ("D", 365),
        ("B", 252),
        ("W-FRI", 52),
        ("MS", 12),
    ],
)
def test_declared_periods_per_year_is_used_verbatim(freq, ppy):
    rng = np.random.default_rng(ppy)
    r = 0.001 * rng.standard_normal(400) + 0.0001
    series = make_series(r, freq=freq, periods_per_year=ppy)
    sampling, annualized, _ = annualized_and_distribution(series, 0.0)
    assert sampling.annualization_eligible, sampling
    assert annualized.annualized_sharpe_ratio == pytest.approx(
        ref.annualized_sharpe(r, ppy), rel=1e-9
    )


def test_crypto_daily_series_declared_252_is_flagged(tmp_path):
    """365 consecutive calendar days, calendar 24/7 verified, but --periods-per-year 252.
    The timestamps imply 365 periods per year; the annualized Sharpe is then understated
    by √(252/365) = 0.831. The report must carry a warning. (V1 accepts the pair silently:
    the sample report in night3/baseline shows calendar_verified with 252.)"""
    rng = np.random.default_rng(1)
    ts = pd.date_range("2024-01-01", periods=365, freq="D")
    r = 0.02 * rng.standard_normal(365) + 0.001
    csv = tmp_path / "crypto.csv"
    _write_csv(csv, ts, r)
    report = _run_cli(
        tmp_path,
        csv,
        "--declared-frequency",
        "D",
        "--periods-per-year",
        "252",
        "--observation-calendar",
        "24/7",
        "--calendar-timezone",
        "UTC",
        "--timestamp-timezone",
        "UTC",
    )
    assert report["annualized_statistics"]["annualized_sharpe_ratio"] == pytest.approx(
        ref.annualized_sharpe(r, 252), rel=1e-9
    )
    codes = {f["code"] for f in report["findings"]}
    mismatch = {
        c for c in codes if "PERIOD" in c or "FREQUENCY" in c or "CALENDAR" in c
    }
    assert any(
        "PERIODS_PER_YEAR" in c
        and ("MISMATCH" in c or "CONFLICT" in c or "INCONSISTENT" in c)
        for c in codes
    ), (
        f"365 daily observations verified on a 24/7 calendar were annualized with 252 and no finding "
        f"flagged it; frequency/period-related findings present: {sorted(mismatch)}. "
        f"Annualized Sharpe published={report['annualized_statistics']['annualized_sharpe_ratio']:.4f}, "
        f"with 365 it would be {ref.annualized_sharpe(r, 365):.4f} (ratio √(252/365)=0.831)."
    )


def test_business_day_series_declared_365_is_flagged(tmp_path):
    rng = np.random.default_rng(2)
    ts = pd.date_range("2024-01-01", periods=300, freq="B")
    r = 0.01 * rng.standard_normal(300) + 0.0005
    csv = tmp_path / "equity.csv"
    _write_csv(csv, ts, r)
    report = _run_cli(
        tmp_path, csv, "--declared-frequency", "B", "--periods-per-year", "365"
    )
    codes = {f["code"] for f in report["findings"]}
    assert any(
        "PERIODS_PER_YEAR" in c
        and ("MISMATCH" in c or "CONFLICT" in c or "INCONSISTENT" in c)
        for c in codes
    ), (
        f"business-day frequency 'B' annualized with 365 without a finding; codes={sorted(codes)}. "
        f"Published annual Sharpe={report['annualized_statistics']['annualized_sharpe_ratio']:.4f}; "
        f"with 252: {ref.annualized_sharpe(r, 252):.4f}."
    )


def test_percent_units_with_a_loss_over_one_percent_are_rejected_with_a_misleading_code():
    """Returns in percent (1.5 = 1.5 %) containing −1.5 are rejected as 'simple returns
    cannot be less than −1.0'. The rejection is correct in effect but the message does
    not say the likely cause (percent units)."""
    values = [0.5, -1.5, 0.7, 0.2, 1.1]
    with pytest.raises(InputValidationError) as info:
        normalize_return_series(
            list(pd.date_range("2024-01-01", periods=5, freq="D")),
            values,
            convention=ReturnConvention.SIMPLE,
            sampling=SamplingSpec(declared_frequency="D", periods_per_year=252),
        )
    codes = [issue.code for issue in info.value.issues]
    assert codes == ["SIMPLE_RETURN_BELOW_MINUS_ONE"]
    messages = " ".join(issue.message for issue in info.value.issues)
    assert "percent" in messages.lower(), (
        f"message does not mention percent units: {messages!r}"
    )


def test_percent_units_without_large_losses_pass_silently(tmp_path):
    """Percent returns all in (−1, 1): accepted as decimals. Sharpe is scale-invariant and
    therefore right; cumulative return, drawdown and CAGR are wildly wrong. V1 emits no
    warning about the magnitude of the returns."""
    rng = np.random.default_rng(3)
    decimal = np.clip(0.004 * rng.standard_normal(250) + 0.0003, -0.0099, 0.0099)
    percent = decimal * 100.0
    ts = pd.date_range("2024-01-01", periods=250, freq="B")
    csv = tmp_path / "percent.csv"
    _write_csv(csv, ts, percent)
    report = _run_cli(
        tmp_path, csv, "--declared-frequency", "B", "--periods-per-year", "252"
    )
    sr_decimal = ref.annualized_sharpe(decimal, 252)
    assert report["annualized_statistics"]["annualized_sharpe_ratio"] == pytest.approx(
        sr_decimal, rel=1e-9
    )
    cum_percent = report["performance_path"]["cumulative_simple_return"]
    cum_decimal = float(np.prod(1 + decimal) - 1)
    codes = {f["code"] for f in report["findings"]}
    assert any(
        "UNIT" in c or "MAGNITUDE" in c or "PERCENT" in c or "SCALE" in c for c in codes
    ), (
        f"percent-unit series accepted with no magnitude warning; published cumulative return "
        f"{cum_percent:.3f} vs {cum_decimal:.4f} in decimal units, max drawdown "
        f"{report['performance_path']['maximum_drawdown']:.3f}; mean |r| = {np.mean(np.abs(percent)):.3f}. "
        f"Findings: {sorted(codes)}"
    )


def test_log_returns_supplied_as_simple_are_not_detected_but_log_convention_is_exact():
    """Log returns passed as simple: nothing in the data distinguishes them, so no
    detection is possible — the test documents the size of the error for a volatile
    series, and verifies the --return-convention log path is exactly expm1."""
    rng = np.random.default_rng(4)
    simple = 0.03 * rng.standard_normal(500) + 0.001
    log_r = np.log1p(simple)
    as_simple = make_series(log_r, periods_per_year=252)
    as_log = make_series(log_r, periods_per_year=252, convention=ReturnConvention.LOG)
    _, a_simple, _ = annualized_and_distribution(as_simple, 0.0)
    _, a_log, _ = annualized_and_distribution(as_log, 0.0)
    assert a_log.annualized_sharpe_ratio == pytest.approx(
        ref.annualized_sharpe(simple, 252), rel=1e-9
    )
    gap = a_simple.annualized_sharpe_ratio - a_log.annualized_sharpe_ratio
    # Jensen: log returns are lower than simple returns, Sharpe shifts down
    assert gap < 0
    assert abs(gap) < 0.5, f"log-as-simple Sharpe gap {gap:+.3f}"


def test_annualization_is_null_without_periods_per_year_even_when_frequency_is_obvious():
    rng = np.random.default_rng(5)
    r = 0.01 * rng.standard_normal(100)
    series = make_series(r, periods_per_year=None)
    _, annualized, _ = annualized_and_distribution(series, 0.0)
    assert annualized is None
