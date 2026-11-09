import hashlib
import json
from datetime import date

import pytest

from backtest_auditor.application.ibkr_flex_import import (
    IbkrFlexImportContext,
    import_ibkr_flex_payloads,
)
from backtest_auditor.ingestion.ibkr_flex import IbkrFlexPayload


def _payload(twr: str = "1.5") -> IbkrFlexPayload:
    return IbkrFlexPayload(
        "statement.xml",
        (
            '<FlexStatement accountId="U123456">'
            '<ChangeInNAV accountId="U123456" model="Secret Model" '
            'fromDate="20260101" toDate="20260131" '
            f'twr="{twr}" />'
            "</FlexStatement>"
        ).encode(),
    )


def test_builds_canonical_csv_and_credential_free_file_manifest() -> None:
    result = import_ibkr_flex_payloads(
        [_payload()],
        context=IbkrFlexImportContext(source_mode="files"),
    )
    manifest = json.loads(result.manifest_json)

    assert result.canonical_csv == (
        "timestamp,return,period_start,period_end\n"
        "2026-01-31,0.014999999999999999,2026-01-01,2026-01-31\n"
    )
    assert manifest["adapter"] == "ibkr_activity_flex_change_in_nav"
    assert manifest["source_mode"] == "files"
    assert manifest["api_request"] is None
    assert manifest["period_count"] == 1
    assert manifest["canonicalization"]["source_unit"] == "percent"
    assert "U123456" not in result.manifest_json
    assert "Secret Model" not in result.manifest_json
    assert "statement.xml" not in result.manifest_json
    assert manifest["source_artifacts"][0]["source_ordinal"] == 1
    assert "file_name_sha256" in manifest["source_artifacts"][0]
    assert manifest["import_sha256"] == result.import_sha256
    assert (
        manifest["canonical_csv_sha256"]
        == hashlib.sha256(result.canonical_csv.encode()).hexdigest()
    )


def test_api_manifest_hashes_query_id_and_records_override_dates() -> None:
    result = import_ibkr_flex_payloads(
        [_payload()],
        context=IbkrFlexImportContext(
            source_mode="api",
            query_id="987654",
            requested_from_date=date(2026, 1, 1),
            requested_to_date=date(2026, 1, 31),
        ),
    )
    manifest = json.loads(result.manifest_json)

    assert manifest["api_request"] == {
        "flex_web_service_version": 3,
        "query_id_sha256": hashlib.sha256(b"987654").hexdigest(),
        "requested_from_date": "2026-01-01",
        "requested_to_date": "2026-01-31",
    }
    assert "987654" not in result.manifest_json


def test_import_is_deterministic_across_source_order() -> None:
    january = _payload("1.5")
    february = IbkrFlexPayload(
        "february.xml",
        b'<ChangeInNAV accountId="U123456" model="Secret Model" '
        b'fromDate="20260201" toDate="20260228" twr="2" />',
    )

    first = import_ibkr_flex_payloads(
        [january, february], context=IbkrFlexImportContext("files")
    )
    second = import_ibkr_flex_payloads(
        [february, january], context=IbkrFlexImportContext("files")
    )

    assert first.canonical_csv == second.canonical_csv
    assert first.import_sha256 == second.import_sha256
    assert json.loads(first.manifest_json)["warnings"] == []
    assert json.loads(second.manifest_json)["warnings"] == []


def test_context_rejects_invalid_combinations() -> None:
    with pytest.raises(ValueError, match="source_mode"):
        IbkrFlexImportContext("other")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not declare"):
        IbkrFlexImportContext("files", query_id="123")
    with pytest.raises(ValueError, match="require a query_id"):
        IbkrFlexImportContext("api")
    with pytest.raises(ValueError, match="supplied together"):
        IbkrFlexImportContext(
            "api", query_id="123", requested_from_date=date(2026, 1, 1)
        )
    with pytest.raises(ValueError, match="must not follow"):
        IbkrFlexImportContext(
            "api",
            query_id="123",
            requested_from_date=date(2026, 2, 1),
            requested_to_date=date(2026, 1, 1),
        )
