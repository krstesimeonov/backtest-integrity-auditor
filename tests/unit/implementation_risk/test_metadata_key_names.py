"""N15 (1.5.2): an invalid adapter-metadata error names the offending key.

The adversarial suite drops each required key for every engine. These cases
add an unexpected key and a payload that is not a JSON object, through the
shared reader every engine uses.
"""

import pytest

from backtest_auditor.implementation_risk.adapters.engine_csv import (
    ADAPTER_METADATA_FILE,
    canonical_json_bytes,
    read_adapter_metadata,
)
from backtest_auditor.implementation_risk.application.errors import EngineAdapterError
from backtest_auditor.implementation_risk.domain.engine_adapters import (
    EngineExportPayload,
    SupportedEngine,
)


def _read(value: object) -> EngineAdapterError:
    payload = EngineExportPayload(
        path=ADAPTER_METADATA_FILE,
        role="adapter_metadata",
        media_type="application/json",
        data=canonical_json_bytes(value),
    )
    with pytest.raises(EngineAdapterError) as caught:
        read_adapter_metadata(
            payload, engine=SupportedEngine.VECTORBT, adapter_id="vectorbt-test"
        )
    return caught.value


def test_unexpected_metadata_key_is_named():
    error = _read(
        {
            "adapter_export_schema_version": "1.0",
            "base_currency": "USD",
            "timezone": "UTC",
        }
    )
    assert error.engine_error_code == "vectorbt.invalid_metadata"
    assert error.field == "timezone"
    assert "unexpected key 'timezone'" in error.message


def test_missing_and_unexpected_keys_are_both_named():
    error = _read({"schema_version": "1.0", "base_currency": "USD"})
    assert error.field == "adapter_export_schema_version"
    assert error.message.endswith(
        "missing key 'adapter_export_schema_version'; unexpected key 'schema_version'."
    )


def test_metadata_that_is_not_an_object_says_so():
    error = _read(["adapter_export_schema_version", "base_currency"])
    assert error.engine_error_code == "vectorbt.invalid_metadata"
    assert error.message == "adapter metadata must be a JSON object."
