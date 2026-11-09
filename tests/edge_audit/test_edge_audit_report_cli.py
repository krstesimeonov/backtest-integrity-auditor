"""Report schema, determinism and the ``edge-audit`` command end to end."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from backtest_auditor.edge_audit import (
    AuditSettings,
    build_report,
    load_price_table,
    load_trade_log,
    render_json,
    render_markdown,
    run_edge_audit,
)
from backtest_auditor.edge_audit.cli import REPORT_JSON, REPORT_MARKDOWN, main
from backtest_auditor.edge_audit.report_schema import REPORT_JSON_SCHEMA
from backtest_auditor.edge_audit.skill import assess_luck_vs_skill
from backtest_auditor.edge_audit.synthetic import noise_log, timing_log, write_log

pytestmark = pytest.mark.filterwarnings(
    "ignore:A future version of pandas will return a BaseOffset"
)

REPO = Path(__file__).resolve().parents[2]
DOCS_SCHEMA = REPO / "docs" / "edge_audit" / "edge-audit-report-1.1.schema.json"
FAST = [
    "--bootstrap",
    "200",
    "--timing-draws",
    "200",
    "--permutations",
    "200",
]


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["PYTHONWARNINGS"] = "ignore"
    return env


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> tuple[Path, Path]:
    directory = tmp_path_factory.mktemp("edge_audit_cli")
    trades, prices = write_log(
        timing_log(21, trades=160, entry_candidates=2), directory, "sample"
    )
    assert prices is not None
    return trades, prices


def validate(report: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(REPORT_JSON_SCHEMA)
    jsonschema.Draft202012Validator(REPORT_JSON_SCHEMA).validate(report)


def test_cli_runs_end_to_end_and_the_report_validates(sample, tmp_path):
    trades, prices = sample
    out = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtest_auditor.edge_audit",
            "run",
            str(trades),
            "--trials",
            "3",
            "--prices",
            str(prices),
            "--out",
            str(out),
            *FAST,
        ],
        capture_output=True,
        text=True,
        env=environment(),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((out / REPORT_JSON).read_text(encoding="utf-8"))
    validate(report)
    markdown = (out / REPORT_MARKDOWN).read_text(encoding="utf-8")
    for question in (
        "Is there evidence of an edge?",
        "Where does it come from?",
        "Is it decaying?",
        "How sensitive is it to costs?",
    ):
        assert question in markdown
    log = load_trade_log(trades)
    expected = assess_luck_vs_skill(
        log.net_pnl, span_years=log.span_years, declared_trials=3
    )
    assert report["verdict"]["edge"] == expected.verdict
    assert report["verdict"]["dsr"] == pytest.approx(expected.dsr, rel=1e-12)
    assert report["timing"]["status"] == "computed"
    assert report["input"]["trades"]["schema_declared_in_file"] is True
    assert completed.stdout.startswith(report["verdict"]["edge"])


def test_edge_audit_console_script_wrapper(sample, tmp_path):
    """The wrapper pip writes for `edge-audit = backtest_auditor.edge_audit.cli:main`."""

    trades, _ = sample
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "edge-audit"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from backtest_auditor.edge_audit.cli import main\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(main())\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    env = environment()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    out = tmp_path / "out"
    completed = subprocess.run(
        ["edge-audit", "run", str(trades), "--trials", "5", "--out", str(out), *FAST],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((out / REPORT_JSON).read_text(encoding="utf-8"))
    validate(report)
    assert report["input"]["prices"] is None
    assert report["timing"]["status"] == "unavailable"
    assert report["verdict"]["declared_trials"] == 5


def test_same_inputs_give_byte_identical_reports(sample, tmp_path):
    trades, prices = sample
    outputs = []
    for name in ("first", "second"):
        assert (
            main(
                [
                    "run",
                    str(trades),
                    "--trials",
                    "2",
                    "--prices",
                    str(prices),
                    "--out",
                    str(tmp_path / name),
                    *FAST,
                ]
            )
            == 0
        )
        outputs.append(
            (
                (tmp_path / name / REPORT_JSON).read_bytes(),
                (tmp_path / name / REPORT_MARKDOWN).read_bytes(),
            )
        )
    assert outputs[0] == outputs[1]
    assert (
        main(
            [
                "run",
                str(trades),
                "--trials",
                "2",
                "--prices",
                str(prices),
                "--out",
                str(tmp_path / "third"),
                "--seed",
                "7",
                *FAST,
            ]
        )
        == 0
    )
    third = (tmp_path / "third" / REPORT_JSON).read_bytes()
    assert third != outputs[0][0]
    first = json.loads(outputs[0][0])
    again = json.loads(third)
    assert first["verdict"] == again["verdict"]  # the verdict uses no random numbers


def test_invalid_input_exits_2_with_line_numbers(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "instrument,side,quantity,entry_time,entry_price,exit_time,exit_price,fees\n"
        "X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0\n"
        "X,up,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00,11,0\n",
        encoding="utf-8",
    )
    assert main(["run", str(bad), "--trials", "1", "--out", str(tmp_path / "o")]) == 2
    error = capsys.readouterr().err
    assert "[invalid_side] line 3:" in error
    assert "[naive_exit_time] line 3:" in error
    assert not (tmp_path / "o").exists()


def test_bad_settings_exit_2(sample, tmp_path, capsys):
    trades, _ = sample
    assert main(["run", str(trades), "--trials", "0", "--out", str(tmp_path)]) == 2
    assert "declared_trials" in capsys.readouterr().err
    assert main(["run", str(trades), "--trials", "1", "--confidence", "1.2"]) == 2


def test_validate_command(sample, capsys):
    trades, prices = sample
    assert main(["validate", str(trades), "--prices", str(prices)]) == 0
    assert capsys.readouterr().out.startswith("ok: 160 trades, prices for 1 instrument")


def test_report_without_prices_short_log_is_schema_valid(tmp_path):
    trades, _ = write_log(noise_log(4, trades=20), tmp_path, "short")
    log = load_trade_log(trades)
    settings = AuditSettings(
        declared_trials=1,
        bootstrap_replications=50,
        permutation_draws=50,
        timing_draws=50,
    )
    result = run_edge_audit(log, None, settings)
    report = build_report(
        result,
        trades_path=trades,
        prices_path=None,
        trade_rows=len(log),
        schema_declared=log.schema_declared,
    )
    validate(report)
    assert report["verdict"]["edge"] == "insufficient_data"
    assert report["decay"]["status"] == "unavailable"
    assert report["conditional"]["holding_period"]["status"] == "unavailable"
    text = render_json(report)
    assert "NaN" not in text and "Infinity" not in text
    assert "Cannot say" in render_markdown(report)


def test_report_with_prices_validates_in_holding_mode(sample):
    trades, prices = sample
    log = load_trade_log(trades)
    settings = AuditSettings(
        declared_trials=1,
        timing_mode="holding",
        bootstrap_replications=50,
        permutation_draws=50,
        timing_draws=50,
    )
    result = run_edge_audit(log, load_price_table(prices), settings)
    report = build_report(
        result,
        trades_path=trades,
        prices_path=prices,
        trade_rows=len(log),
        schema_declared=True,
    )
    validate(report)
    holding = [c for c in report["timing"]["components"] if c["name"] == "holding"][0]
    assert holding["total"] == 0.0
    assert holding["finding"] == "zero by construction in holding-window mode"


def test_docs_copy_of_the_report_schema_is_current():
    published = json.loads(DOCS_SCHEMA.read_text(encoding="utf-8"))
    assert published == json.loads(json.dumps(REPORT_JSON_SCHEMA))


def test_degenerate_logs_report_the_right_reason_and_an_infinite_profit_factor(
    tmp_path,
):
    header = (
        "instrument,side,quantity,entry_time,entry_price,exit_time,exit_price,fees\n"
    )
    one = tmp_path / "one.csv"
    one.write_text(
        header + "X,long,1,2025-01-02T10:00:00Z,10,2025-01-02T11:00:00Z,11,0\n",
        encoding="utf-8",
    )
    winners = tmp_path / "winners.csv"
    winners.write_text(
        header
        + "".join(
            f"X,long,1,2025-01-{day:02d}T10:00:00Z,10,2025-01-{day:02d}T11:00:00Z,"
            f"{10 + day / 10},0\n"
            for day in range(1, 29)
        ),
        encoding="utf-8",
    )
    for path in (one, winners):
        assert (
            main(
                [
                    "run",
                    str(path),
                    "--trials",
                    "1",
                    "--out",
                    str(tmp_path / path.stem),
                    *FAST,
                ]
            )
            == 0
        )
    first = json.loads((tmp_path / "one" / REPORT_JSON).read_text(encoding="utf-8"))
    assert first["verdict"]["reason"] == "1 trade(s); at least 4 are needed for moments"
    report = json.loads(
        (tmp_path / "winners" / REPORT_JSON).read_text(encoding="utf-8")
    )
    validate(report)
    factor = report["performance"]["profit_factor"]
    assert factor["point"] is None and factor["point_unbounded"] is True
    markdown = (tmp_path / "winners" / REPORT_MARKDOWN).read_text(encoding="utf-8")
    assert "| Profit factor | ∞ [" in markdown
