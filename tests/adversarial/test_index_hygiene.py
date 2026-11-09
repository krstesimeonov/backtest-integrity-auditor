"""Adversarial tests: timestamp-index hygiene and degenerate series through the public
ingestion, application and CLI paths."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from .conftest import (
    annualized_and_distribution,
    bootstrap_spec,
    make_series,
    psr_spec,
    ref,
    serial_adjustment_spec,
    serial_dependence_spec,
    sharpe_spec,
)

from backtest_auditor.application.single_run_audit import audit_single_run
from backtest_auditor.cli import main as cli_main
from backtest_auditor.domain.enums import FrequencyStatus, ReturnConvention
from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.domain.runs import StrategyRun
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.normalization import normalize_return_series
from backtest_auditor.reporting.json_report import render_json_report


def _normalize(ts, values, *, freq="B", ppy=252, tz=None):
    return normalize_return_series(
        list(ts),
        list(values),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(
            declared_frequency=freq, periods_per_year=ppy, timezone=tz
        ),
    )


def _full_audit(series):
    return audit_single_run(
        StrategyRun(run_id="r", returns=series),
        sharpe_spec=sharpe_spec(0.0),
        psr_spec=psr_spec(0.0, 0.95),
        serial_dependence_spec=serial_dependence_spec(3),
        serial_adjustment_spec=serial_adjustment_spec(3),
        bootstrap_spec=bootstrap_spec(replications=200, block_length=2),
    )


def test_unsorted_timestamps_are_sorted_with_a_warning_and_numbers_match_sorted_input():
    rng = np.random.default_rng(1)
    ts = pd.date_range("2024-01-01", periods=200, freq="B")
    r = 0.01 * rng.standard_normal(200)
    perm = rng.permutation(200)
    shuffled = _normalize([ts[i].isoformat() for i in perm], r[perm])
    assert [i.code for i in shuffled.issues] == ["TIMESTAMPS_SORTED"]
    sorted_result = _normalize([t.isoformat() for t in ts], r)
    assert sorted_result.issues == ()
    a = _full_audit(shuffled.series)
    b = _full_audit(sorted_result.series)
    assert render_json_report(a) == render_json_report(b)


def test_duplicate_timestamps_are_blocking():
    ts = ["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03"]
    with pytest.raises(InputValidationError) as info:
        _normalize(ts, [0.01, 0.0, 0.01, -0.01])
    assert [i.code for i in info.value.issues] == ["DUPLICATE_TIMESTAMP"]


def test_nan_in_the_middle_is_blocking_not_dropped():
    ts = [t.isoformat() for t in pd.date_range("2024-01-01", periods=5, freq="B")]
    with pytest.raises(InputValidationError) as info:
        _normalize(ts, [0.01, float("nan"), 0.01, -0.01, 0.0])
    assert [i.code for i in info.value.issues] == ["NONFINITE_RETURN"]
    with pytest.raises(InputValidationError):
        _normalize(ts, [0.01, "", 0.01, -0.01, 0.0])


@pytest.mark.xfail(
    strict=True,
    reason="F05: one missing exchange holiday makes the weekday-calendar series ineligible for annualization",
)
def test_single_holiday_gap_makes_a_business_day_series_ineligible_for_annualization():
    """A real equity series misses exchange holidays. With --declared-frequency B the
    gap is a DECLARED_CONFLICT; without a declaration pandas infers nothing and the
    status is IRREGULAR. Either way every annualized number, PSR, MinTRL, HAC and
    bootstrap Sharpe is null. The only way through is a sessions CSV. Recorded as a
    usability finding: the CLI will hit this on every real daily equity file."""
    rng = np.random.default_rng(2)
    ts = pd.date_range("2024-01-02", periods=120, freq="B")
    ts = ts.drop(pd.Timestamp("2024-02-19"))  # Presidents' Day
    r = 0.01 * rng.standard_normal(len(ts))
    declared = _normalize([t.isoformat() for t in ts], r)
    sampling, annualized, _ = annualized_and_distribution(declared.series, 0.0)
    assert sampling.status is FrequencyStatus.DECLARED_CONFLICT
    assert annualized is None
    undeclared = normalize_return_series(
        [t.isoformat() for t in ts],
        list(r),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency=None, periods_per_year=252),
    )
    sampling2, annualized2, _ = annualized_and_distribution(undeclared.series, 0.0)
    assert sampling2.status is FrequencyStatus.IRREGULAR
    assert annualized2 is None
    # weekday calendar does not help either: the holiday is a "missing session"
    from backtest_auditor.domain.metadata import ObservationCalendarSpec
    from backtest_auditor.statistics.calendar import assess_observation_calendar
    from backtest_auditor.statistics.sampling import assess_sampling

    cal = assess_observation_calendar(
        declared.series,
        ObservationCalendarSpec(calendar_name="weekdays", timezone="UTC"),
    )
    sampling3 = assess_sampling(declared.series, cal)
    assert sampling3.annualization_eligible, (
        f"calendar status={cal.status.value}, missing={cal.missing_session_dates[:3] if hasattr(cal, 'missing_session_dates') else '?'}; "
        f"one exchange holiday makes annualization ineligible under B declaration, no declaration, and the "
        f"weekday calendar alike."
    )


def test_timezone_aware_and_naive_inputs_give_the_same_statistics():
    rng = np.random.default_rng(3)
    ts = pd.date_range("2024-01-01", periods=100, freq="B")
    r = 0.01 * rng.standard_normal(100)
    naive = _normalize([t.isoformat() for t in ts], r)
    aware = _normalize([t.isoformat() + "+00:00" for t in ts], r)
    a = _full_audit(naive.series)
    b = _full_audit(aware.series)
    assert (
        a.annualized_statistics.annualized_sharpe_ratio
        == b.annualized_statistics.annualized_sharpe_ratio
    )
    assert a.bootstrap.metrics[5].lower_bound == b.bootstrap.metrics[5].lower_bound


def test_mixed_offsets_in_one_file_are_rejected_inside_the_validation_contract():
    """Half the rows carry +00:00, half +02:00. pandas raises 'Mixed timezones detected'
    from inside normalize_return_series; the CLI catches it as a generic ValueError and
    prints an argparse-style error (exit 2) rather than the machine-readable
    input_validation_failed envelope every other input defect uses."""
    rng = np.random.default_rng(4)
    ts = pd.date_range("2024-01-01", periods=10, freq="D")
    rows = [
        t.isoformat() + ("+00:00" if i % 2 == 0 else "+02:00") for i, t in enumerate(ts)
    ]
    r = 0.01 * rng.standard_normal(10)
    try:
        result = _normalize(rows, r, freq="D")
    except InputValidationError as error:
        assert [i.code for i in error.issues] == ["INVALID_TIMESTAMP"]
        return
    except ValueError as error:
        pytest.fail(
            f"uncaught pandas ValueError escaped normalize_return_series: {error}"
        )
    sampling, annualized, _ = annualized_and_distribution(result.series, 0.0)
    assert sampling.status is not FrequencyStatus.DECLARED, (
        f"mixed-offset file accepted as a regular daily series: status={sampling.status.value}"
    )


def test_zero_variance_series_publishes_null_sharpe_without_crashing():
    series = make_series(np.full(50, 0.001))
    result = _full_audit(series)
    assert result.annualized_statistics.annualized_sharpe_ratio is None
    assert result.sharpe_uncertainty is None
    text = render_json_report(result)
    d = json.loads(text)
    assert d["descriptive_statistics"]["sample_volatility"] == 0.0


def test_single_observation_audits_without_crashing():
    series = make_series([0.01], periods_per_year=252)
    result = _full_audit(series)
    d = json.loads(render_json_report(result))
    assert d["descriptive_statistics"]["observation_count"] == 1
    assert d["annualized_statistics"] is None
    assert d["performance_path"]["maximum_drawdown"] == 0.0


def test_ten_observations_compute_psr_and_bootstrap():
    rng = np.random.default_rng(5)
    r = 0.01 * rng.standard_normal(10) + 0.002
    series = make_series(r)
    result = _full_audit(series)
    d = json.loads(render_json_report(result))
    assert d["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] is not None
    sr = ref.period_sharpe(r)
    expected = ref.psr(
        sr, 0.0, 10, ref.adjusted_skewness(r), ref.adjusted_pearson_kurtosis(r)
    )
    assert d["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] == pytest.approx(
        expected, abs=1e-9
    )


def test_ten_sigma_outlier_keeps_every_number_finite_and_consistent():
    rng = np.random.default_rng(6)
    r = 0.01 * rng.standard_normal(500) + 0.0005
    r[250] = 0.0005 + 10 * 0.01
    series = make_series(r)
    result = _full_audit(series)
    d = json.loads(render_json_report(result))  # allow_nan=False would raise on NaN
    unc = d["sharpe_uncertainty"]
    sr = ref.period_sharpe(r)
    k = ref.adjusted_pearson_kurtosis(r)
    assert k > 10
    assert unc["sharpe_variance_adjustment"] == pytest.approx(
        1 - ref.adjusted_skewness(r) * sr + (k - 1) / 4 * sr**2, rel=1e-9
    )
    assert unc["probabilistic_sharpe_ratio"] == pytest.approx(
        ref.psr(sr, 0.0, 500, ref.adjusted_skewness(r), k), abs=1e-9
    )
    assert d["performance_path"]["maximum_drawdown"] == pytest.approx(
        ref.drawdown_path(r).max_drawdown, abs=1e-12
    )


def test_negative_sharpe_with_heavy_tails_can_push_variance_adjustment_negative():
    """A = 1 − γ3·SR + (γ4−1)/4·SR². For SR < 0 and large positive skew A can go negative;
    V1 then reports PSR as null with NON_POSITIVE_SHARPE_VARIANCE_ESTIMATE. Verify the
    gate fires rather than a NaN being published."""
    r = np.full(60, -0.02)
    r[0] = (
        0.9  # one huge positive outlier: large positive skew, negative mean? mean = (0.9 - 59*0.02)/60 < 0
    )
    assert r.mean() < 0
    series = make_series(r)
    result = _full_audit(series)
    d = json.loads(render_json_report(result))
    A = d["sharpe_uncertainty"]["sharpe_variance_adjustment"]
    if A <= 0:
        assert d["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] is None
        assert any(
            f["code"] == "NON_POSITIVE_SHARPE_VARIANCE_ESTIMATE" for f in d["findings"]
        )
    else:
        assert d["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] is not None


def test_cli_exit_codes_and_machine_readable_errors_for_bad_inputs(tmp_path, capsys):
    csv = tmp_path / "dup.csv"
    csv.write_text(
        "timestamp,return\n2024-01-01,0.01\n2024-01-01,0.02\n2024-01-02,0.0\n"
    )
    code = cli_main([str(csv), "--run-id", "r", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.err.strip().splitlines()[-1])
    assert payload["error"] == "input_validation_failed"
    assert payload["issues"][0]["code"] == "DUPLICATE_TIMESTAMP"
