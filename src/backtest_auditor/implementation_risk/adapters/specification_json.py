"""Canonical JSON mapping for strategy and simulation specifications."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, NoReturn

from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
)
from backtest_auditor.implementation_risk.domain import (
    AssetClass,
    CanonicalParameter,
    CanonicalParameterScalar,
    CanonicalRunSpecification,
    InstrumentReference,
    ModelSpecification,
    SimulationSpecification,
    StrategySpecification,
)


SPECIFICATION_SCHEMA_VERSION = "1.0"
SPECIFICATION_FILE = "specification.json"


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _parameter_json(parameter: CanonicalParameter) -> dict[str, Any]:
    value = parameter.value
    if value is None:
        value_type = "null"
        encoded: object = None
    elif isinstance(value, bool):
        value_type = "boolean"
        encoded = value
    elif isinstance(value, int):
        value_type = "integer"
        encoded = value
    elif isinstance(value, Decimal):
        value_type = "decimal"
        encoded = _decimal_text(value)
    else:
        value_type = "string"
        encoded = value
    return {
        "name": parameter.name,
        "unit": parameter.unit,
        "value_type": value_type,
        "value": encoded,
    }


def _model_json(model: ModelSpecification) -> dict[str, Any]:
    return {
        "name": model.name,
        "parameters": [_parameter_json(item) for item in model.parameters],
        "version": model.version,
        "implementation_sha256": model.implementation_sha256,
    }


def specification_to_json(
    specification: CanonicalRunSpecification,
) -> dict[str, Any]:
    """Return the one canonical JSON-compatible representation."""

    strategy = specification.strategy
    simulation = specification.simulation
    return {
        "specification_schema_version": SPECIFICATION_SCHEMA_VERSION,
        "strategy": {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "version": strategy.version,
            "logic_sha256": strategy.logic_sha256,
            "universe": [
                {
                    "instrument_id": instrument.instrument_id,
                    "asset_class": instrument.asset_class.value,
                    "symbol": instrument.symbol,
                    "currency": instrument.currency,
                    "venue": instrument.venue,
                    "contract_multiplier": _decimal_text(
                        instrument.contract_multiplier
                    ),
                    "attributes": [
                        _parameter_json(item) for item in instrument.attributes
                    ],
                }
                for instrument in strategy.universe
            ],
            "parameters": [_parameter_json(item) for item in strategy.parameters],
            "data_frequency": strategy.data_frequency,
            "signal_timing": strategy.signal_timing,
            "signal_model": _model_json(strategy.signal_model),
            "sizing_model": _model_json(strategy.sizing_model),
        },
        "simulation": {
            "base_currency": simulation.base_currency,
            "initial_cash": _decimal_text(simulation.initial_cash),
            "calendar": simulation.calendar,
            "calendar_timezone": simulation.calendar_timezone,
            "data_adjustment_policy": simulation.data_adjustment_policy,
            "execution_timing": simulation.execution_timing,
            "execution_model": _model_json(simulation.execution_model),
            "accounting_model": _model_json(simulation.accounting_model),
            "cost_models": [_model_json(item) for item in simulation.cost_models],
            "shorting_allowed": simulation.shorting_allowed,
            "fractional_quantity_allowed": (simulation.fractional_quantity_allowed),
        },
    }


def _invalid(message: str, *, field: str | None = None) -> NoReturn:
    raise BundleContractError(
        BundleErrorCode.INVALID_SPECIFICATION,
        message,
        file_path=SPECIFICATION_FILE,
        field=field,
    )


def _object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _invalid("value must be a JSON object.", field=field)
    return value


def _exact_keys(
    value: dict[str, Any],
    expected: set[str],
    *,
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        _invalid(
            "object keys must match exactly (" + "; ".join(details) + ").", field=field
        )


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        _invalid("value must be a string.", field=field)
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        _invalid("value must be a boolean.", field=field)
    return value


def _list(value: object, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        _invalid("value must be a JSON array.", field=field)
    return value


def _parameter(value: object, *, field: str) -> CanonicalParameter:
    item = _object(value, field=field)
    _exact_keys(item, {"name", "unit", "value_type", "value"}, field=field)
    value_type = _string(item["value_type"], field=f"{field}.value_type")
    raw_value = item["value"]
    parameter_value: CanonicalParameterScalar
    if value_type == "null":
        if raw_value is not None:
            _invalid("null parameters require a null value.", field=f"{field}.value")
        parameter_value = None
    elif value_type == "boolean":
        parameter_value = _boolean(raw_value, field=f"{field}.value")
    elif value_type == "integer":
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            _invalid(
                "integer parameters require a JSON integer.", field=f"{field}.value"
            )
        parameter_value = raw_value
    elif value_type == "decimal":
        parameter_value = Decimal(_string(raw_value, field=f"{field}.value"))
    elif value_type == "string":
        parameter_value = _string(raw_value, field=f"{field}.value")
    else:
        _invalid("value_type is unsupported.", field=f"{field}.value_type")
    return CanonicalParameter(
        name=_string(item["name"], field=f"{field}.name"),
        value=parameter_value,
        unit=_optional_string(item["unit"], field=f"{field}.unit"),
    )


def _parameters(value: object, *, field: str) -> tuple[CanonicalParameter, ...]:
    return tuple(
        _parameter(item, field=f"{field}[{index}]")
        for index, item in enumerate(_list(value, field=field))
    )


def _model(value: object, *, field: str) -> ModelSpecification:
    item = _object(value, field=field)
    _exact_keys(
        item,
        {"name", "parameters", "version", "implementation_sha256"},
        field=field,
    )
    return ModelSpecification(
        name=_string(item["name"], field=f"{field}.name"),
        parameters=_parameters(item["parameters"], field=f"{field}.parameters"),
        version=_optional_string(item["version"], field=f"{field}.version"),
        implementation_sha256=_optional_string(
            item["implementation_sha256"],
            field=f"{field}.implementation_sha256",
        ),
    )


def _instrument(value: object, *, field: str) -> InstrumentReference:
    item = _object(value, field=field)
    _exact_keys(
        item,
        {
            "instrument_id",
            "asset_class",
            "symbol",
            "currency",
            "venue",
            "contract_multiplier",
            "attributes",
        },
        field=field,
    )
    return InstrumentReference(
        instrument_id=_string(item["instrument_id"], field=f"{field}.instrument_id"),
        asset_class=AssetClass(
            _string(item["asset_class"], field=f"{field}.asset_class")
        ),
        symbol=_string(item["symbol"], field=f"{field}.symbol"),
        currency=_string(item["currency"], field=f"{field}.currency"),
        venue=_optional_string(item["venue"], field=f"{field}.venue"),
        contract_multiplier=Decimal(
            _string(
                item["contract_multiplier"],
                field=f"{field}.contract_multiplier",
            )
        ),
        attributes=_parameters(item["attributes"], field=f"{field}.attributes"),
    )


def _decode(value: object) -> CanonicalRunSpecification:
    root = _object(value, field="root")
    _exact_keys(
        root,
        {"specification_schema_version", "strategy", "simulation"},
        field="root",
    )
    version = _string(
        root["specification_schema_version"],
        field="specification_schema_version",
    )
    if version != SPECIFICATION_SCHEMA_VERSION:
        raise BundleContractError(
            BundleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            f"specification schema {version!r} is unsupported.",
            file_path=SPECIFICATION_FILE,
            field="specification_schema_version",
        )

    strategy = _object(root["strategy"], field="strategy")
    _exact_keys(
        strategy,
        {
            "strategy_id",
            "name",
            "version",
            "logic_sha256",
            "universe",
            "parameters",
            "data_frequency",
            "signal_timing",
            "signal_model",
            "sizing_model",
        },
        field="strategy",
    )
    simulation = _object(root["simulation"], field="simulation")
    _exact_keys(
        simulation,
        {
            "base_currency",
            "initial_cash",
            "calendar",
            "calendar_timezone",
            "data_adjustment_policy",
            "execution_timing",
            "execution_model",
            "accounting_model",
            "cost_models",
            "shorting_allowed",
            "fractional_quantity_allowed",
        },
        field="simulation",
    )

    universe = tuple(
        _instrument(item, field=f"strategy.universe[{index}]")
        for index, item in enumerate(
            _list(strategy["universe"], field="strategy.universe")
        )
    )
    cost_models = tuple(
        _model(item, field=f"simulation.cost_models[{index}]")
        for index, item in enumerate(
            _list(simulation["cost_models"], field="simulation.cost_models")
        )
    )
    return CanonicalRunSpecification(
        strategy=StrategySpecification(
            strategy_id=_string(strategy["strategy_id"], field="strategy.strategy_id"),
            name=_string(strategy["name"], field="strategy.name"),
            version=_optional_string(strategy["version"], field="strategy.version"),
            logic_sha256=_string(
                strategy["logic_sha256"], field="strategy.logic_sha256"
            ),
            universe=universe,
            parameters=_parameters(strategy["parameters"], field="strategy.parameters"),
            data_frequency=_string(
                strategy["data_frequency"], field="strategy.data_frequency"
            ),
            signal_timing=_string(
                strategy["signal_timing"], field="strategy.signal_timing"
            ),
            signal_model=_model(
                strategy["signal_model"], field="strategy.signal_model"
            ),
            sizing_model=_model(
                strategy["sizing_model"], field="strategy.sizing_model"
            ),
        ),
        simulation=SimulationSpecification(
            base_currency=_string(
                simulation["base_currency"], field="simulation.base_currency"
            ),
            initial_cash=Decimal(
                _string(simulation["initial_cash"], field="simulation.initial_cash")
            ),
            calendar=_string(simulation["calendar"], field="simulation.calendar"),
            calendar_timezone=_string(
                simulation["calendar_timezone"],
                field="simulation.calendar_timezone",
            ),
            data_adjustment_policy=_string(
                simulation["data_adjustment_policy"],
                field="simulation.data_adjustment_policy",
            ),
            execution_timing=_string(
                simulation["execution_timing"],
                field="simulation.execution_timing",
            ),
            execution_model=_model(
                simulation["execution_model"],
                field="simulation.execution_model",
            ),
            accounting_model=_model(
                simulation["accounting_model"],
                field="simulation.accounting_model",
            ),
            cost_models=cost_models,
            shorting_allowed=_boolean(
                simulation["shorting_allowed"],
                field="simulation.shorting_allowed",
            ),
            fractional_quantity_allowed=_boolean(
                simulation["fractional_quantity_allowed"],
                field="simulation.fractional_quantity_allowed",
            ),
        ),
    )


def specification_from_json(value: object) -> CanonicalRunSpecification:
    """Decode and require canonical ordering and scalar representation."""

    try:
        specification = _decode(value)
    except BundleContractError:
        raise
    except (ArithmeticError, TypeError, ValueError) as error:
        raise BundleContractError(
            BundleErrorCode.INVALID_SPECIFICATION,
            str(error),
            file_path=SPECIFICATION_FILE,
        ) from error
    if specification_to_json(specification) != value:
        _invalid("specification must use canonical ordering and scalar encoding.")
    return specification
