from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from backtest_auditor.implementation_risk import (
    EngineAdapterError,
    EngineAdapterErrorCode,
    EngineExportPayload,
    SupportedEngine,
    VerifiedEngineExport,
)
from backtest_auditor.implementation_risk.adapters.engine_csv import (
    ADAPTER_METADATA_FILE,
    canonical_csv_bytes,
    canonical_decimal,
    canonical_json_bytes,
    canonical_timestamp,
    optional_decimal,
    optional_timestamp,
    parse_decimal,
    parse_timestamp,
    read_adapter_metadata,
    read_csv_rows,
    require_payload_contract,
)
from backtest_auditor.implementation_risk.exporters.common import (
    adapter_metadata_payload,
    installed_engine_version,
    require_datetime_index,
    require_frame,
    require_series,
    utc_timestamp,
    validate_base_currency,
)


def _payload(data: bytes, *, path: str = "table.csv") -> EngineExportPayload:
    return EngineExportPayload(path, "table", "text/csv", data)


def _metadata(data: bytes) -> EngineExportPayload:
    return EngineExportPayload(
        ADAPTER_METADATA_FILE,
        "adapter_metadata",
        "application/json",
        data,
    )


def test_canonical_decimal_and_timestamp_round_trip() -> None:
    assert canonical_decimal(Decimal("1.250")) == "1.250"
    assert canonical_decimal(-0.0) == "0"
    assert parse_decimal("1.250") == Decimal("1.250")
    assert optional_decimal("") is None
    assert optional_decimal("2") == Decimal(2)

    value = datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc)
    encoded = canonical_timestamp(value)
    assert encoded == "2024-01-01T12:30:00.000000Z"
    assert parse_timestamp(encoded) == value
    assert optional_timestamp("") is None
    assert optional_timestamp(encoded) == value
    assert utc_timestamp(pd.Timestamp(value), field="time") == encoded


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), object()])
def test_canonical_decimal_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        canonical_decimal(value)


@pytest.mark.parametrize("value", ["", "01", "1e2", "NaN", "-1"])
def test_parse_decimal_rejects_noncanonical_or_negative_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_decimal(value, non_negative=True)


@pytest.mark.parametrize(
    "value",
    [
        datetime(2024, 1, 1),
        "2024-01-01T00:00:00Z",
        "2024-01-01T00:00:00.000000+00:00",
        "not-a-time",
    ],
)
def test_timestamp_contract_rejects_timezone_inference_or_noncanonical_text(
    value: object,
) -> None:
    with pytest.raises(ValueError):
        if isinstance(value, datetime):
            canonical_timestamp(value)
        else:
            parse_timestamp(value)  # type: ignore[arg-type]


def test_metadata_and_csv_contracts_accept_canonical_payloads() -> None:
    metadata = adapter_metadata_payload("USD")
    assert (
        read_adapter_metadata(
            metadata,
            engine=SupportedEngine.BT,
            adapter_id="backtest-auditor.bt",
        )
        == "USD"
    )

    headers = ("id", "value")
    rows = ({"id": "1", "value": "a,b"},)
    payload = _payload(canonical_csv_bytes(headers, rows))
    assert (
        read_csv_rows(
            payload,
            headers,
            engine=SupportedEngine.BT,
            adapter_id="backtest-auditor.bt",
        )
        == rows
    )


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        (b"not-json", "bt.invalid_metadata"),
        (
            b'{"adapter_export_schema_version":"1.0","base_currency":"USD"}\n',
            "bt.noncanonical_metadata",
        ),
        (
            canonical_json_bytes({"adapter_export_schema_version": "1.0"}),
            "bt.invalid_metadata",
        ),
        (
            canonical_json_bytes(
                {
                    "adapter_export_schema_version": "2.0",
                    "base_currency": "USD",
                }
            ),
            "bt.unsupported_metadata_version",
        ),
        (
            canonical_json_bytes(
                {
                    "adapter_export_schema_version": "1.0",
                    "base_currency": "usd",
                }
            ),
            "bt.invalid_currency",
        ),
        (
            b'{"adapter_export_schema_version":"1.0","base_currency":"USD","base_currency":"EUR"}\n',
            "bt.invalid_metadata",
        ),
    ],
)
def test_metadata_contract_fails_with_typed_engine_detail(
    data: bytes,
    detail: str,
) -> None:
    with pytest.raises(EngineAdapterError) as captured:
        read_adapter_metadata(
            _metadata(data),
            engine=SupportedEngine.BT,
            adapter_id="backtest-auditor.bt",
        )
    assert captured.value.code is EngineAdapterErrorCode.MAPPING_FAILED
    assert captured.value.engine_error_code == detail


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        (b"\xff", "bt.invalid_utf8"),
        (b"wrong,value\n1,a\n", "bt.header_mismatch"),
        (b"id,value\n1,a,extra\n", "bt.invalid_row"),
        (b"id,value\r\n1,a\r\n", "bt.noncanonical_csv"),
    ],
)
def test_csv_contract_fails_closed(data: bytes, detail: str) -> None:
    with pytest.raises(EngineAdapterError) as captured:
        read_csv_rows(
            _payload(data),
            ("id", "value"),
            engine=SupportedEngine.BT,
            adapter_id="backtest-auditor.bt",
        )
    assert captured.value.engine_error_code == detail


def test_payload_contract_requires_exact_paths_roles_and_media_types() -> None:
    export = VerifiedEngineExport.create(
        run_id="run",
        engine=SupportedEngine.BT,
        engine_version="1.2.0",
        export_format_id="backtest-auditor.bt",
        export_format_version="1.0",
        declared_levels=(),
        payloads=(_payload(b"id,value\n"),),
    )
    assert (
        require_payload_contract(
            export,
            {"table.csv": ("table", "text/csv")},
            engine=SupportedEngine.BT,
            adapter_id="backtest-auditor.bt",
        )["table.csv"]
        == export.payloads[0]
    )

    for expected, detail in (
        ({"missing.csv": ("table", "text/csv")}, "bt.payload_inventory_mismatch"),
        ({"table.csv": ("wrong", "text/csv")}, "bt.payload_metadata_mismatch"),
    ):
        with pytest.raises(EngineAdapterError) as captured:
            require_payload_contract(
                export,
                expected,
                engine=SupportedEngine.BT,
                adapter_id="backtest-auditor.bt",
            )
        assert captured.value.engine_error_code == detail


def test_exporter_common_validation_helpers() -> None:
    assert validate_base_currency("EUR") == "EUR"
    with pytest.raises(ValueError, match="base_currency"):
        validate_base_currency("eur")
    with pytest.raises(ValueError, match="must be installed"):
        installed_engine_version("definitely-not-an-installed-engine")

    index = pd.date_range("2024-01-01", periods=2, tz="UTC")
    series = pd.Series([1, 2], index=index)
    frame = pd.DataFrame({"x": [1, 2]}, index=index)
    assert require_datetime_index(series, field="series").equals(index)
    assert require_series(series, field="series") is series
    assert require_frame(frame, field="frame") is frame

    with pytest.raises(ValueError, match="Series"):
        require_series(frame, field="bad")
    with pytest.raises(ValueError, match="DataFrame"):
        require_frame(series, field="bad")
    with pytest.raises(ValueError, match="DatetimeIndex"):
        require_datetime_index(pd.Series([1]), field="bad")
    with pytest.raises(ValueError, match="timezone-aware"):
        require_datetime_index(
            pd.Series([1], index=pd.DatetimeIndex(["2024-01-01"])),
            field="bad",
        )
    with pytest.raises(ValueError, match="duplicate"):
        require_datetime_index(
            pd.Series([1, 2], index=pd.DatetimeIndex([index[0], index[0]])),
            field="bad",
        )
    with pytest.raises(ValueError, match="increasing"):
        require_datetime_index(
            pd.Series([1, 2], index=pd.DatetimeIndex([index[1], index[0]])),
            field="bad",
        )
    duplicate_columns = pd.DataFrame([[1, 2]], columns=["x", "x"], index=index[:1])
    with pytest.raises(ValueError, match="columns"):
        require_frame(duplicate_columns, field="bad")
