import builtins
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from backtest_auditor.domain.reproducibility import AuditRunSpec
from backtest_auditor.presentation.streamlit_app import (
    _construction,
    _download_stem,
    _manifest,
    _optional_text,
    _parameter_scales,
    _rows,
    _stretch_kwargs,
)
from backtest_auditor.presentation.streamlit_controller import AuditPresentation
from backtest_auditor.presentation.streamlit_controller import (
    IbkrFlexImportPresentation,
    ImplementationRiskPresentation,
)
from backtest_auditor.presentation.streamlit_controller import presentation_to_snapshot
from backtest_auditor.persistence.sqlalchemy_repository import SQLAlchemyAuditRepository
from backtest_auditor.presentation.streamlit_launcher import main as launch


APP_PATH = (
    Path(__file__).parents[3]
    / "src"
    / "backtest_auditor"
    / "presentation"
    / "streamlit_app.py"
)


def test_streamlit_single_and_family_workflows_render_without_exceptions() -> None:
    app = AppTest.from_file(str(APP_PATH)).run()

    assert not app.exception
    assert app.title[0].value == "Backtest Integrity Auditor"
    assert app.header[0].value == "Single-Run audit"

    app.sidebar.radio[0].set_value("Experiment-Family").run()

    assert not app.exception
    assert app.header[0].value == "Experiment-Family audit"

    app.sidebar.radio[0].set_value("IBKR Flex Import").run()

    assert not app.exception
    assert app.header[0].value == "IBKR Activity Flex import"

    app.sidebar.radio[0].set_value("Implementation Risk").run()

    assert not app.exception
    assert app.header[0].value == "Cross-engine implementation-risk audit"


def test_streamlit_implementation_risk_panel_and_result_are_bounded() -> None:
    app = AppTest.from_file(str(APP_PATH)).run()
    app.sidebar.radio[0].set_value("Implementation Risk").run()
    button = next(
        item for item in app.button if item.label == "Audit implementation risk"
    )
    button.click().run()

    assert not app.exception
    assert "One reference" in app.error[0].value

    result = ImplementationRiskPresentation(
        "reconciliation / one",
        1,
        {
            "interpretation_boundary": "No engine is certified as correct.",
            "candidates": [
                {
                    "candidate_run": {"run_id": "candidate", "engine_name": "engine"},
                    "implementation_risk_score": "25",
                    "uncertainty": "low",
                    "score_withheld_reason": None,
                }
            ],
            "findings": [{"code": "EXAMPLE", "kind": "adverse"}],
            "normalization": {"runs": [{"run_id": "reference"}]},
        },
        '{"report_type":"implementation_risk"}\n',
        "# Implementation Risk\n",
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["implementation_risk_result"] = result
    app.run()
    app.sidebar.radio[0].set_value("Implementation Risk").run()

    assert not app.exception
    assert app.header[-1].value == "Implementation-risk result"
    assert len(app.download_button) == 2


def test_streamlit_ibkr_flex_file_and_api_panels_validate_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AppTest.from_file(str(APP_PATH)).run()
    app.sidebar.radio[0].set_value("IBKR Flex Import").run()

    import_button = next(
        item for item in app.button if item.label == "Import IBKR Flex evidence"
    )
    import_button.click().run()

    assert not app.exception
    assert "At least one Activity Flex" in app.error[0].value

    monkeypatch.setenv("BACKTEST_AUDITOR_IBKR_FLEX_TOKEN", "configured-token")
    monkeypatch.setenv("BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID", "configured-query")
    app.radio[0].set_value("Read-only Flex Web Service").run()

    assert not app.exception
    assert any("available" in item.value for item in app.caption)


def test_streamlit_ibkr_import_result_renders_downloads() -> None:
    result = IbkrFlexImportPresentation(
        canonical_csv="timestamp,return,period_start,period_end\n",
        manifest_json='{"source_mode":"files"}\n',
        import_sha256="a" * 64,
        period_count=2,
        first_period_start="2026-01-01",
        last_period_end="2026-02-28",
        warning_codes=("EXAMPLE_WARNING",),
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["ibkr_import_result"] = result
    app.run()
    app.sidebar.radio[0].set_value("IBKR Flex Import").run()

    assert not app.exception
    assert any("canonicalized" in item.value for item in app.success)
    assert any("EXAMPLE_WARNING" in item.value for item in app.warning)
    assert len(app.download_button) == 2


def test_streamlit_reports_missing_required_uploads_as_configuration_error() -> None:
    app = AppTest.from_file(str(APP_PATH)).run()

    app.button[0].click().run()

    assert not app.exception
    assert "Strategy returns CSV is required" in app.error[0].value


def test_failed_replacement_audit_clears_stale_successful_result() -> None:
    prior = AuditPresentation(
        "single_run",
        "prior-run",
        {"schema_version": "2.4", "findings": [], "input_issues": []},
        '{"schema_version":"2.4"}\n',
        "# Prior audit\n",
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["audit_result"] = prior
    app.run()

    app.button[0].click().run()

    assert not app.exception
    assert "Strategy returns CSV is required" in app.error[0].value
    assert [item.value for item in app.header] == ["Single-Run audit"]
    assert "audit_result" not in app.session_state


def test_streamlit_result_surface_renders_tables_and_downloads() -> None:
    result = AuditPresentation(
        audit_type="single_run",
        subject_id="run / one",
        payload={
            "evidence_profile": {
                "dimensions": [{"dimension": "input_integrity", "status": "supported"}],
                "interpretation_boundary": "No global pass/fail.",
            },
            "findings": [{"code": "EXAMPLE", "claim": "Example finding"}],
            "input_issues": [],
        },
        json_report='{"audit_type": "single_run"}\n',
        markdown_report="# Audit\n",
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["audit_result"] = result
    app.run()

    assert not app.exception
    assert [item.value for item in app.header] == ["Single-Run audit", "Audit result"]
    assert len(app.dataframe) == 2
    assert len(app.download_button) == 2


def test_streamlit_pure_configuration_helpers_validate_and_normalize() -> None:
    construction = _construction('{"currency": "usd", "leverage_policy": "unlevered"}')
    scales = _parameter_scales('{"z": 2, "a": 1}')
    manifest = _manifest((True, "audit-1", "2026-08-13T12:00:00Z", "revision"))

    assert construction.currency == "USD"
    assert [item.name for item in scales] == ["a", "z"]
    assert manifest == AuditRunSpec(
        "audit-1",
        datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        "revision",
    )


def test_streamlit_width_helper_preserves_old_and_new_api_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signature = SimpleNamespace(
        parameters={"width": SimpleNamespace(default="stretch")}
    )
    monkeypatch.setattr(
        "backtest_auditor.presentation.streamlit_app.inspect.signature",
        lambda _component: signature,
    )
    assert _stretch_kwargs() == {"width": "stretch"}

    signature.parameters.clear()
    assert _stretch_kwargs() == {"use_container_width": True}
    assert _manifest((False, "", "", "")) is None
    assert _construction(" ") is None
    assert _optional_text(" value ") == "value"
    assert _optional_text(" ") is None
    assert _rows({"items": [{"x": 1}, "ignored"]}, "items") == [{"x": 1}]
    assert _rows({"items": "not a list"}, "items") == []
    assert (
        _download_stem(AuditPresentation("single_run", "run / one", {}, "", ""))
        == "backtest-audit-run---one"
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("[]", "must be an object"),
        ('{"x": 1}', "unexpected keyword"),
    ],
)
def test_return_construction_helper_rejects_invalid_json_shapes(
    raw: str, message: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _construction(raw)


@pytest.mark.parametrize("raw", ("[]", "{}"))
def test_parameter_scale_helper_requires_non_empty_object(raw: str) -> None:
    with pytest.raises(ValueError, match="non-empty JSON object"):
        _parameter_scales(raw)


def test_launcher_calls_streamlit_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr("streamlit.web.cli.main", lambda: called.append(True) or 7)

    with pytest.raises(SystemExit) as error:
        launch()

    assert error.value.code == 7
    assert called == [True]
    assert Path(__import__("sys").argv[2]).name == "streamlit_app.py"


def test_launcher_explains_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "streamlit.web":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(SystemExit, match="optional UI"):
        launch()


def test_issue_rows_are_rendered_by_validation_error_path() -> None:
    issue = SimpleNamespace(
        code="CODE",
        severity=SimpleNamespace(value="error"),
        blocking=True,
        message="message",
        location="file.csv",
    )
    from backtest_auditor.presentation.streamlit_app import _issue_row

    assert _issue_row(issue) == {
        "code": "CODE",
        "severity": "error",
        "blocking": True,
        "message": "message",
        "location": "file.csv",
    }


def test_streamlit_history_lists_and_reopens_saved_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'history.db'}"
    monkeypatch.setenv("BACKTEST_AUDITOR_DATABASE_URL", url)
    result = AuditPresentation(
        audit_type="single_run",
        subject_id="saved-run",
        payload={"schema_version": "2.4", "findings": [], "input_issues": []},
        json_report='{"schema_version":"2.4","findings":[],"input_issues":[]}\n',
        markdown_report="# Saved audit\n",
        report_schema_version="2.4",
        package_version="1.3.0",
    )
    SQLAlchemyAuditRepository(url).save(presentation_to_snapshot(result))

    app = AppTest.from_file(str(APP_PATH)).run()
    app.sidebar.radio[0].set_value("Audit History").run()

    assert not app.exception
    assert app.header[0].value == "Audit history"
    assert len(app.dataframe) == 1
    app.button[0].click().run()
    assert not app.exception
    assert app.header[-1].value == "Audit result"
    assert len(app.download_button) == 2


def test_streamlit_history_reports_invalid_database_url_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BACKTEST_AUDITOR_DATABASE_URL", "not a URL")
    app = AppTest.from_file(str(APP_PATH)).run()

    app.sidebar.radio[0].set_value("Audit History").run()

    assert not app.exception
    assert "database URL is invalid" in app.error[0].value


def test_streamlit_result_can_be_saved_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'saved.db'}"
    monkeypatch.setenv("BACKTEST_AUDITOR_DATABASE_URL", url)
    result = AuditPresentation(
        "single_run",
        "saved-run",
        {"schema_version": "2.4", "findings": [], "input_issues": []},
        '{"schema_version":"2.4","findings":[],"input_issues":[]}\n',
        "# Saved audit\n",
        report_schema_version="2.4",
        package_version="1.3.0",
    )
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["audit_result"] = result
    app.run()
    save_button = next(
        item for item in app.button if item.label == "Save audit to database"
    )
    save_button.click().run()

    assert not app.exception
    assert any("Audit saved" in item.value for item in app.success)
    assert len(SQLAlchemyAuditRepository(url).list()) == 1
