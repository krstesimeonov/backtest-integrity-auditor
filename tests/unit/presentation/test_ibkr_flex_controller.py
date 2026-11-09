import json
from datetime import date

import pytest

from backtest_auditor.presentation.streamlit_controller import (
    IbkrFlexImportRequest,
    UploadedInput,
    run_ibkr_flex_import,
)


_STATEMENT = (
    b'<ChangeInNAV accountId="U1" fromDate="20260101" toDate="20260131" twr="3" />'
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def fetch_statement(self, credentials: object, request: object) -> bytes:
        self.calls.append((credentials, request))
        return _STATEMENT


def test_runs_file_import_for_streamlit_without_temporary_storage() -> None:
    result = run_ibkr_flex_import(
        IbkrFlexImportRequest(
            source_mode="files",
            statement_files=(UploadedInput("statement.xml", _STATEMENT),),
            declared_frequency="ME",
            periods_per_year=12,
        )
    )

    assert result.period_count == 1
    assert result.first_period_start == "2026-01-01"
    assert result.last_period_end == "2026-01-31"
    assert "0.029999999999999999" in result.canonical_csv
    assert json.loads(result.manifest_json)["source_mode"] == "files"


def test_runs_api_import_with_injected_read_only_client() -> None:
    client = FakeClient()
    request = IbkrFlexImportRequest(
        source_mode="api",
        token="secret-token",
        query_id="secret-query",
        requested_from_date=date(2026, 1, 1),
        requested_to_date=date(2026, 1, 31),
    )

    result = run_ibkr_flex_import(request, client=client)  # type: ignore[arg-type]

    assert len(client.calls) == 1
    assert "secret-token" not in repr(request)
    assert "secret-query" not in repr(request)
    assert "secret" not in result.manifest_json
    assert json.loads(result.manifest_json)["source_mode"] == "api"


def test_import_request_rejects_invalid_source_configuration() -> None:
    with pytest.raises(ValueError, match="source_mode"):
        IbkrFlexImportRequest(source_mode="other")
    with pytest.raises(ValueError, match="At least one"):
        IbkrFlexImportRequest(source_mode="files")
    with pytest.raises(ValueError, match="must not contain"):
        IbkrFlexImportRequest(
            source_mode="files",
            statement_files=(UploadedInput("x.xml", _STATEMENT),),
            token="token",
        )
    with pytest.raises(ValueError, match="require"):
        IbkrFlexImportRequest(source_mode="api", token="token")
