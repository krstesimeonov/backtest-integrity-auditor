"""Adversarial tests: report numbers == function numbers, manifest hashes, determinism,
and the shipped examples recomputed from the reference."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from .conftest import DATA, REPO, ref

from backtest_auditor.cli import main as cli_main

SINGLE_ARGS = [
    "--declared-frequency",
    "B",
    "--periods-per-year",
    "252",
    "--annual-risk-free-rate",
    "0.02",
    "--benchmark-annualized-sharpe-ratio",
    "0.0",
    "--required-psr-confidence-level",
    "0.95",
    "--serial-max-lag",
    "3",
    "--serial-significance-level",
    "0.05",
    "--hac-max-lag",
    "3",
    "--hac-kernel",
    "bartlett",
    "--bootstrap-method",
    "moving_block",
    "--bootstrap-interval-method",
    "percentile",
    "--bootstrap-replications",
    "300",
    "--bootstrap-confidence-level",
    "0.95",
    "--bootstrap-block-length",
    "5",
    "--bootstrap-seed",
    "42",
    "--audit-id",
    "night3",
    "--audit-timestamp",
    "2026-10-20T03:00:00+02:00",
    "--git-commit",
    "fedfb66",
]


@pytest.fixture(scope="module")
def synthetic_csv(tmp_path_factory):
    rng = np.random.default_rng(2026)
    ts = pd.date_range("2022-01-03", periods=300, freq="B")
    r = 0.01 * rng.standard_normal(300) + 0.0006
    path = tmp_path_factory.mktemp("data") / "returns.csv"
    pd.DataFrame({"timestamp": [t.isoformat() for t in ts], "return": r}).to_csv(
        path, index=False
    )
    return path, ts, r


def _run(tmp_path, csv, fmt, name, *args):
    out = tmp_path / name
    assert (
        cli_main(
            [
                str(csv),
                "--run-id",
                "night3-run",
                "--format",
                fmt,
                "--output",
                str(out),
                *args,
            ]
        )
        == 0
    )
    return out.read_text()


def _flatten_numbers(obj, acc):
    if isinstance(obj, bool):
        return
    if isinstance(obj, str):
        acc.add(obj)  # version strings such as "2.4" are rendered verbatim
        return
    if isinstance(obj, (int, float)):
        acc.add(format(obj, ".12g"))
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _flatten_numbers(v, acc)


_NUM = re.compile(r"^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$")


def test_every_number_in_the_markdown_report_is_a_json_number_to_twelve_digits(
    tmp_path, synthetic_csv
):
    csv, _, _ = synthetic_csv
    js = json.loads(_run(tmp_path, csv, "json", "r.json", *SINGLE_ARGS))
    md = _run(tmp_path, csv, "markdown", "r.md", *SINGLE_ARGS)
    numbers = set()
    _flatten_numbers(js, numbers)
    unmatched = []
    for line in md.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
        for cell in cells:
            if _NUM.match(cell) and cell not in numbers:
                unmatched.append((cell, line[:80]))
    assert not unmatched, (
        f"{len(unmatched)} markdown numbers not found in JSON: {unmatched[:10]}"
    )


def test_report_numbers_equal_reference_recomputation(tmp_path, synthetic_csv):
    csv, ts, r = synthetic_csv
    js = json.loads(_run(tmp_path, csv, "json", "r.json", *SINGLE_ARGS))
    rf_p = ref.annual_to_period_rate_geometric(0.02, 252)
    sr = ref.period_sharpe(r, rf_p)
    assert js["annualized_statistics"]["annualized_sharpe_ratio"] == pytest.approx(
        sr * math.sqrt(252), rel=1e-9
    )
    g1, k = ref.adjusted_skewness(r), ref.adjusted_pearson_kurtosis(r)
    assert js["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] == pytest.approx(
        ref.psr(sr, 0.0, 300, g1, k), abs=1e-9
    )
    trl = js["track_record_length"]["minimum_track_record_length_observations"]
    if sr > 0:
        assert trl == pytest.approx(ref.min_trl(sr, 0.0, g1, k, 0.95), rel=1e-9)
    dd = ref.drawdown_path(r)
    assert js["performance_path"]["maximum_drawdown"] == pytest.approx(
        dd.max_drawdown, abs=1e-12
    )
    assert (
        js["performance_path"]["maximum_drawdown_duration_observations"] == dd.duration
    )
    Q, p = ref.ljung_box(r, 3)
    assert js["serial_dependence"]["ljung_box_statistic"] == pytest.approx(Q, rel=1e-9)
    assert js["serial_dependence"]["p_value"] == pytest.approx(p, abs=1e-9)
    ratio = ref.bartlett_lrv_ratio(r, 3)
    assert js["serial_adjustment"][
        "hac_adjusted_annualized_sharpe_ratio"
    ] == pytest.approx(sr * math.sqrt(252 / ratio), rel=1e-9)
    boot = {m["metric"]: m for m in js["bootstrap"]["metrics"]}
    samples = ref.moving_block_bootstrap(
        r, lambda x: (x.mean() - rf_p) / x.std(ddof=1), 5, 300, 42
    )
    lo, hi = ref.percentile_interval(samples, 0.95)
    assert boot["period_sharpe_ratio"]["lower_bound"] == pytest.approx(lo, rel=1e-9)
    assert boot["period_sharpe_ratio"]["upper_bound"] == pytest.approx(hi, rel=1e-9)


def test_manifest_hashes_are_recomputable_from_the_inputs(tmp_path, synthetic_csv):
    csv, ts, r = synthetic_csv
    js = json.loads(_run(tmp_path, csv, "json", "r.json", *SINGLE_ARGS))
    m = js["run_manifest"]
    raw = Path(csv).read_bytes()
    art = m["input_artifacts"][0]
    assert art["sha256"] == hashlib.sha256(raw).hexdigest()
    assert art["size_bytes"] == len(raw)
    assert art["file_name"] == Path(csv).name

    def canon(v):
        return json.dumps(
            v,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    # normalized data identity, rebuilt from the CSV with pandas only.
    # Manifest 1.1 (package 1.4.0+) adds the three optional V1.4 inputs to the
    # strategy payload (application/run_manifest.py `_strategy_payload`); they are
    # null here. docs/EVIDENCE_PROFILE_AND_RUN_MANIFEST.md "Normalized-data
    # identity" still lists only the 1.0 inputs (night 7 finding N01).
    frame = pd.read_csv(csv)
    payload = {
        "audit_type": "single_run",
        "run_id": "night3-run",
        "strategy": {
            "returns": {
                "timestamps": [pd.Timestamp(t).isoformat() for t in frame["timestamp"]],
                "values_hex": [float(v).hex() for v in frame["return"]],
                "convention": "simple",
            },
            "risk_free_returns": None,
            "gross_returns": None,
            "regimes": None,
            "benchmark": None,
        },
    }
    assert (
        m["normalized_data_sha256"]
        == hashlib.sha256(canon(payload).encode()).hexdigest()
    )
    assert (
        m["configuration_sha256"]
        == hashlib.sha256(canon(m["configuration"]).encode()).hexdigest()
    )
    body = {k: v for k, v in m.items() if k != "manifest_sha256"}
    assert m["manifest_sha256"] == hashlib.sha256(canon(body).encode()).hexdigest()
    assert m["audit_timestamp_utc"] == "2026-10-20T01:00:00Z"
    assert m["random_seeds"] == {"bootstrap": 42}


def test_rerunning_the_cli_is_byte_identical(tmp_path, synthetic_csv):
    csv, _, _ = synthetic_csv
    a = _run(tmp_path, csv, "json", "a.json", *SINGLE_ARGS)
    b = _run(tmp_path, csv, "json", "b.json", *SINGLE_ARGS)
    assert a == b
    assert _run(tmp_path, csv, "markdown", "a.md", *SINGLE_ARGS) == _run(
        tmp_path, csv, "markdown", "b.md", *SINGLE_ARGS
    )


def test_row_order_does_not_change_normalized_data_identity_but_changes_raw_hash(
    tmp_path, synthetic_csv
):
    csv, ts, r = synthetic_csv
    a = json.loads(_run(tmp_path, csv, "json", "a.json", *SINGLE_ARGS))["run_manifest"]
    frame = pd.read_csv(csv).iloc[::-1]
    reversed_csv = tmp_path / "reversed.csv"
    frame.to_csv(reversed_csv, index=False)
    b = json.loads(_run(tmp_path, reversed_csv, "json", "b.json", *SINGLE_ARGS))[
        "run_manifest"
    ]
    assert a["normalized_data_sha256"] == b["normalized_data_sha256"]
    assert a["input_artifacts"][0]["sha256"] != b["input_artifacts"][0]["sha256"]
    assert {"code": "TIMESTAMPS_SORTED", "source": "input_issue"} in b["warnings"]


# --------------------------------------------------------------------------- #
# Shipped examples: CLI output == reference recomputation
# --------------------------------------------------------------------------- #


def test_example_single_run_report_matches_reference(tmp_path):
    csv = REPO / "examples" / "sample_returns.csv"
    args = [
        "--declared-frequency",
        "D",
        "--periods-per-year",
        "252",
        "--annual-risk-free-rate",
        "0.03",
        "--benchmark-annualized-sharpe-ratio",
        "0.0",
        "--required-psr-confidence-level",
        "0.95",
        "--serial-max-lag",
        "2",
        "--serial-significance-level",
        "0.05",
        "--hac-max-lag",
        "2",
        "--hac-kernel",
        "bartlett",
        "--bootstrap-method",
        "moving_block",
        "--bootstrap-interval-method",
        "percentile",
        "--bootstrap-replications",
        "2000",
        "--bootstrap-confidence-level",
        "0.95",
        "--bootstrap-block-length",
        "2",
        "--bootstrap-seed",
        "42",
    ]
    js = json.loads(_run(tmp_path, csv, "json", "ex.json", *args))
    r = pd.read_csv(csv)["return"].to_numpy()
    rf_p = ref.annual_to_period_rate_geometric(0.03, 252)
    sr = ref.period_sharpe(r, rf_p)
    assert js["annualized_statistics"]["annualized_sharpe_ratio"] == pytest.approx(
        sr * math.sqrt(252), rel=1e-9
    )
    assert js["sharpe_uncertainty"]["probabilistic_sharpe_ratio"] == pytest.approx(
        ref.psr(sr, 0.0, 5, ref.adjusted_skewness(r), ref.adjusted_pearson_kurtosis(r)),
        abs=1e-9,
    )
    assert js["performance_path"]["maximum_drawdown"] == pytest.approx(
        ref.drawdown_path(r).max_drawdown, abs=1e-12
    )
    baseline = json.loads((DATA / "single_run_sample.json").read_text())
    assert baseline["annualized_statistics"] == js["annualized_statistics"]


def test_example_family_report_matches_reference(tmp_path):
    ex = REPO / "examples"
    out = tmp_path / "fam.json"
    code = cli_main(
        [
            "family",
            str(ex / "cscv_family_manifest.json"),
            str(ex / "cscv_family_trials.csv"),
            str(ex / "cscv_family_returns.csv"),
            "--dsr-method",
            "classic_expected_maximum",
            "--dsr-trial-count-policy",
            "selection_eligible",
            "--dsr-annual-risk-free-rate",
            "0.03",
            "--dsr-confidence-level",
            "0.95",
            "--cscv-method",
            "combinatorially_symmetric",
            "--cscv-performance-metric",
            "period_sharpe_ratio",
            "--cscv-selection-metric-name",
            "period_sharpe_ratio",
            "--cscv-partitions",
            "4",
            "--cscv-annual-risk-free-rate",
            "0.03",
            "--cscv-maximum-combinations",
            "100",
            "--cscv-rank-tie-method",
            "average",
            "--cscv-winner-tie-policy",
            "first_by_attempt_index",
            "--cscv-maximum-acceptable-pbo",
            "0.05",
            "--format",
            "json",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    js = json.loads(out.read_text())
    long = pd.read_csv(ex / "cscv_family_returns.csv")
    M = long.pivot(index="timestamp", columns="trial_id", values="return").sort_index()
    M = M[["trial-001", "trial-002", "trial-003", "trial-004"]].to_numpy()
    rf_p = ref.annual_to_period_rate_geometric(0.03, 252)
    pbo = ref.cscv_pbo(M, 4, rf_p)
    assert js["cscv_probability_of_backtest_overfitting"][
        "probability_of_backtest_overfitting"
    ] == pytest.approx(pbo.pbo, abs=1e-12)
    logits = [
        s["rank_logit"]
        for s in js["cscv_probability_of_backtest_overfitting"]["splits"]
    ]
    assert np.allclose(logits, pbo.logits, atol=1e-12)
    sharpes = (M.mean(axis=0) - rf_p) / M.std(axis=0, ddof=1)
    k = int(np.argmax(sharpes))
    assert (
        js["deflated_sharpe_ratio"]["selected_trial"]["trial_id"] == f"trial-00{k + 1}"
    )
    sel = M[:, k]
    expected = ref.dsr(
        sharpes[k],
        sharpes,
        M.shape[0],
        ref.adjusted_skewness(sel),
        ref.adjusted_pearson_kurtosis(sel),
        ddof=1,
    )
    scenario = next(
        s
        for s in js["deflated_sharpe_ratio"]["scenarios"]
        if s["trial_count_basis"] == "selection_eligible"
    )
    assert scenario["deflated_sharpe_ratio"] == pytest.approx(expected, abs=1e-9)
    baseline = json.loads((DATA / "family_cscv.json").read_text())
    assert (
        baseline["cscv_probability_of_backtest_overfitting"][
            "probability_of_backtest_overfitting"
        ]
        == js["cscv_probability_of_backtest_overfitting"][
            "probability_of_backtest_overfitting"
        ]
    )
