from copy import deepcopy

import pytest

from backtest_auditor.implementation_risk import CanonicalRunArtifacts
from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
)
from backtest_auditor.implementation_risk.adapters.specification_json import (
    SPECIFICATION_SCHEMA_VERSION,
    specification_from_json,
    specification_to_json,
)


def test_specification_json_round_trip_preserves_typed_parameters(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    specification = canonical_file_bundle.specification
    assert specification is not None

    encoded = specification_to_json(specification)
    decoded = specification_from_json(encoded)

    assert decoded == specification
    assert encoded["specification_schema_version"] == SPECIFICATION_SCHEMA_VERSION
    parameters = encoded["strategy"]["signal_model"]["parameters"]
    assert [item["value_type"] for item in parameters] == [
        "boolean",
        "decimal",
        "integer",
        "null",
        "string",
    ]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value.update(specification_schema_version="2.0"),
            BundleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
        ),
        (
            lambda value: value.update(extra=True),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value.pop("simulation"),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value["strategy"].update(name=1),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value["strategy"].update(universe={}),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value["simulation"].update(shorting_allowed=0),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value["strategy"]["parameters"][0].update(
                value_type="unknown"
            ),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value["strategy"]["parameters"][0].update(
                value_type="integer",
                value=True,
            ),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value["strategy"]["parameters"][0].update(
                value_type="decimal",
                value="not-decimal",
            ),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
        (
            lambda value: value["strategy"]["parameters"][0].update(
                value_type="null",
                value=1,
            ),
            BundleErrorCode.INVALID_SPECIFICATION,
        ),
    ],
)
def test_specification_json_rejects_invalid_shape_or_values(
    canonical_file_bundle: CanonicalRunArtifacts,
    mutation,
    code,
) -> None:
    specification = canonical_file_bundle.specification
    assert specification is not None
    value = deepcopy(specification_to_json(specification))
    mutation(value)

    with pytest.raises(BundleContractError) as captured:
        specification_from_json(value)

    assert captured.value.code is code


def test_specification_json_rejects_noncanonical_parameter_order(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    specification = canonical_file_bundle.specification
    assert specification is not None
    value = deepcopy(specification_to_json(specification))
    parameters = value["strategy"]["signal_model"]["parameters"]
    parameters.reverse()

    with pytest.raises(BundleContractError, match="canonical ordering"):
        specification_from_json(value)


def test_specification_json_requires_object_root() -> None:
    with pytest.raises(BundleContractError, match="JSON object"):
        specification_from_json([])
