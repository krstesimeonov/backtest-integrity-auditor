from pathlib import Path

import numpy as np
import pytest

from backtest_auditor.domain.enums import FrequencyStatus
from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion import ibkr_flex
from backtest_auditor.ingestion.ibkr_flex import (
    IbkrFlexPayload,
    IbkrFlexSelection,
    load_ibkr_flex_files,
    normalize_ibkr_flex_payloads,
    payload_sha256,
    read_ibkr_flex_files,
)


def _xml(
    *,
    account: str = "U1234567",
    model: str | None = None,
    from_date: str = "20260101",
    to_date: str = "20260131",
    twr: str = "2.5",
) -> bytes:
    model_attribute = "" if model is None else f' model="{model}"'
    return (
        '<FlexQueryResponse><FlexStatements count="1">'
        f'<FlexStatement accountId="{account}">'
        f'<ChangeInNAV accountId="{account}" accountAlias="Primary"'
        f'{model_attribute} fromDate="{from_date}" toDate="{to_date}"'
        f' twr="{twr}" />'
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    ).encode()


def _issue_code(error: pytest.ExceptionInfo[InputValidationError]) -> str:
    return error.value.issues[0].code


def test_normalizes_xml_period_twr_percent_to_simple_return() -> None:
    result = normalize_ibkr_flex_payloads(
        [IbkrFlexPayload("statement.xml", _xml())],
        sampling=SamplingSpec(
            status=FrequencyStatus.DECLARED,
            declared_frequency="ME",
            periods_per_year=12,
        ),
        name="broker-account",
    )

    assert result.normalized.series.name == "broker-account"
    assert result.normalized.series.timestamps[0].isoformat() == "2026-01-31T00:00:00"
    assert np.array_equal(result.normalized.series.values, np.array([0.025]))
    assert result.periods[0].from_date.isoformat() == "2026-01-01"
    assert result.account_id_sha256 == payload_sha256(
        IbkrFlexPayload("account", b"U1234567")
    )
    assert result.model_sha256 is None
    assert result.source_formats == ("xml",)


def test_xml_supports_namespace_statement_defaults_and_percent_suffix() -> None:
    payload = IbkrFlexPayload(
        "namespaced.xml",
        b'<x:FlexQueryResponse xmlns:x="urn:test">'
        b'<x:FlexStatement accountId="U1" fromDate="2026-01-01" '
        b'toDate="2026-01-02"><x:ChangeInNAV twr="1.25%" />'
        b"</x:FlexStatement></x:FlexQueryResponse>",
    )

    result = normalize_ibkr_flex_payloads(
        [payload],
        date_format="yyyy-MM-dd",
    )

    assert result.normalized.series.values[0] == pytest.approx(0.0125)


def test_csv_supports_plain_and_section_descriptor_layouts() -> None:
    plain = IbkrFlexPayload(
        "plain.csv",
        b"Account ID,From Date,To Date,TWR\nU1,20260101,20260102,1.0\n",
    )
    wrapped = IbkrFlexPayload(
        "wrapped.csv",
        b"BOF,U1,1\n"
        b"EQUT,HEADER,AccountId,FromDate,ToDate,TWR,Model\n"
        b"EQUT,DATA,U1,20260201,20260228,-2.0,Core\n"
        b"EQUT,EOS,1,0\nEOF,U1\n",
    )

    plain_result = normalize_ibkr_flex_payloads([plain])
    wrapped_result = normalize_ibkr_flex_payloads([wrapped])

    assert plain_result.normalized.series.values[0] == pytest.approx(0.01)
    assert wrapped_result.normalized.series.values[0] == pytest.approx(-0.02)
    assert wrapped_result.model_sha256 is not None


def test_combines_files_sorts_observations_and_preserves_intervals() -> None:
    result = normalize_ibkr_flex_payloads(
        [
            IbkrFlexPayload(
                "feb.xml",
                _xml(from_date="20260201", to_date="20260228", twr="2"),
            ),
            IbkrFlexPayload("jan.xml", _xml(twr="1")),
        ]
    )

    assert [period.to_date.isoformat() for period in result.periods] == [
        "2026-01-31",
        "2026-02-28",
    ]
    assert result.normalized.issues == ()
    assert result.normalized.series.values.tolist() == [0.01, 0.02]


def test_requires_explicit_scope_for_multiple_accounts_or_models() -> None:
    payloads = [
        IbkrFlexPayload("one.xml", _xml(account="U1", model="Core")),
        IbkrFlexPayload("two.xml", _xml(account="U2", model="Core")),
    ]
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads(payloads)
    assert _issue_code(error) == "IBKR_FLEX_AMBIGUOUS_SCOPE"

    selected = normalize_ibkr_flex_payloads(
        payloads,
        selection=IbkrFlexSelection(account_id="U2", model="Core"),
    )
    assert selected.normalized.series.values[0] == pytest.approx(0.025)


def test_rejects_missing_scope_and_model_without_account() -> None:
    with pytest.raises(ValueError, match="requires an account_id"):
        IbkrFlexSelection(model="Core")
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads(
            [IbkrFlexPayload("one.xml", _xml(account="U1"))],
            selection=IbkrFlexSelection(account_id="U2"),
        )
    assert _issue_code(error) == "IBKR_FLEX_SCOPE_NOT_FOUND"


def test_rejects_overlapping_or_duplicate_periods() -> None:
    payloads = [
        IbkrFlexPayload("one.xml", _xml()),
        IbkrFlexPayload(
            "two.xml",
            _xml(from_date="20260131", to_date="20260228"),
        ),
    ]
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads(payloads)
    assert _issue_code(error) == "IBKR_FLEX_OVERLAPPING_PERIODS"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"", "IBKR_FLEX_EMPTY_PAYLOAD"),
        (b"<broken", "IBKR_FLEX_XML_PARSE_ERROR"),
        (b'<!DOCTYPE x><ChangeInNAV accountId="U1"/>', "IBKR_FLEX_UNSAFE_XML"),
        (
            b"<FlexStatementResponse><Status>Success</Status></FlexStatementResponse>",
            "IBKR_FLEX_CONTROL_RESPONSE",
        ),
        (b"<FlexQueryResponse />", "IBKR_FLEX_CHANGE_IN_NAV_MISSING"),
        (b"not,change,in,nav\n", "IBKR_FLEX_CHANGE_IN_NAV_MISSING"),
        (b"\xff\xfe", "IBKR_FLEX_CSV_ENCODING_ERROR"),
    ],
)
def test_rejects_invalid_payload_contracts(payload: bytes, expected_code: str) -> None:
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads([IbkrFlexPayload("bad.input", payload)])
    assert _issue_code(error) == expected_code


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"twr": "nan"}, "IBKR_FLEX_INVALID_TWR"),
        ({"twr": "-100.1"}, "IBKR_FLEX_INVALID_TWR"),
        ({"twr": "word"}, "IBKR_FLEX_INVALID_TWR"),
        ({"from_date": "bad"}, "IBKR_FLEX_INVALID_DATE"),
        ({"from_date": "20260201", "to_date": "20260101"}, "IBKR_FLEX_INVALID_PERIOD"),
    ],
)
def test_rejects_invalid_change_in_nav_values(
    overrides: dict[str, str], expected_code: str
) -> None:
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads([IbkrFlexPayload("bad.xml", _xml(**overrides))])
    assert _issue_code(error) == expected_code


def test_rejects_missing_required_field_and_unsupported_date_format() -> None:
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads(
            [
                IbkrFlexPayload(
                    "missing.xml",
                    b'<ChangeInNAV accountId="U1" fromDate="20260101" '
                    b'toDate="20260131" />',
                )
            ]
        )
    assert _issue_code(error) == "IBKR_FLEX_MISSING_FIELD"
    with pytest.raises(ValueError, match="date_format"):
        normalize_ibkr_flex_payloads(
            [IbkrFlexPayload("one.xml", _xml())], date_format="ISO"
        )


def test_file_loading_and_read_adapter(tmp_path: Path) -> None:
    path = tmp_path / "statement.xml"
    path.write_bytes(_xml())

    payloads = load_ibkr_flex_files([path])
    result = read_ibkr_flex_files([path])

    assert payloads[0].name == "statement.xml"
    assert result.normalized.series.values[0] == pytest.approx(0.025)
    with pytest.raises(InputValidationError) as missing:
        load_ibkr_flex_files([tmp_path / "missing.xml"])
    assert _issue_code(missing) == "IBKR_FLEX_FILE_NOT_FOUND"
    with pytest.raises(InputValidationError, match="At least one"):
        load_ibkr_flex_files([])


def test_payload_limit_and_safe_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ibkr_flex, "MAX_FLEX_PAYLOAD_BYTES", 2)
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads([IbkrFlexPayload("large.xml", b"123")])
    assert _issue_code(error) == "IBKR_FLEX_PAYLOAD_TOO_LARGE"
    with pytest.raises(ValueError, match="identify a file"):
        IbkrFlexPayload("../", b"x")
    assert IbkrFlexPayload("folder/file.xml", b"x").name == "file.xml"
    assert "U1" not in repr(IbkrFlexPayload("statement.xml", _xml(account="U1")))
    assert "U1" not in repr(IbkrFlexSelection(account_id="U1"))


def test_empty_payload_sequence_is_rejected() -> None:
    with pytest.raises(InputValidationError) as error:
        normalize_ibkr_flex_payloads([])
    assert _issue_code(error) == "IBKR_FLEX_NO_PAYLOADS"
