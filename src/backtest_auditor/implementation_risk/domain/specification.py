"""Canonical strategy intent and simulation-assumption contracts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias

from backtest_auditor.implementation_risk.domain.enums import AssetClass
from backtest_auditor.implementation_risk.domain.validation import (
    normalize_currency,
    normalize_decimal,
    normalize_optional_sha256,
    normalize_optional_text,
    normalize_sha256,
    normalize_text,
    require_bool,
)


CanonicalParameterScalar: TypeAlias = str | int | Decimal | bool | None

_MAX_IDENTIFIER_LENGTH = 128
_MAX_NAME_LENGTH = 256
_MAX_RULE_LENGTH = 1024


def _normalize_parameter_value(value: object) -> CanonicalParameterScalar:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return normalize_decimal(value, field="parameter value")
    if isinstance(value, str):
        return normalize_text(
            value,
            field="parameter value",
            maximum_length=_MAX_RULE_LENGTH,
        )
    if isinstance(value, float):
        raise ValueError(
            "parameter value floats are rejected; use Decimal for numeric values."
        )
    raise ValueError(
        "parameter value must be a string, integer, Decimal, boolean, or None."
    )


def _parameter_tuple(
    values: Iterable[CanonicalParameter],
    *,
    field: str,
) -> tuple[CanonicalParameter, ...]:
    try:
        parameters = tuple(values)
    except TypeError as error:
        raise ValueError(f"{field} must be an iterable.") from error
    if any(not isinstance(item, CanonicalParameter) for item in parameters):
        raise ValueError(f"{field} must contain only CanonicalParameter values.")
    names = tuple(item.name for item in parameters)
    if len(set(names)) != len(names):
        raise ValueError(f"{field} must not contain duplicate parameter names.")
    return tuple(sorted(parameters, key=lambda item: item.name))


@dataclass(frozen=True, slots=True)
class CanonicalParameter:
    """One typed, scalar parameter; nested configuration uses dotted names."""

    name: str
    value: CanonicalParameterScalar
    unit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            normalize_text(
                self.name,
                field="parameter name",
                maximum_length=_MAX_NAME_LENGTH,
            ),
        )
        object.__setattr__(self, "value", _normalize_parameter_value(self.value))
        object.__setattr__(
            self,
            "unit",
            normalize_optional_text(
                self.unit,
                field="parameter unit",
                maximum_length=_MAX_NAME_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class InstrumentReference:
    """Engine-neutral identity for one instrument in the strategy universe."""

    instrument_id: str
    asset_class: AssetClass
    symbol: str
    currency: str
    venue: str | None = None
    contract_multiplier: Decimal = Decimal(1)
    attributes: tuple[CanonicalParameter, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            normalize_text(
                self.instrument_id,
                field="instrument_id",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        try:
            asset_class = AssetClass(self.asset_class)
        except (TypeError, ValueError) as error:
            raise ValueError("asset_class must be a supported AssetClass.") from error
        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(
            self,
            "symbol",
            normalize_text(
                self.symbol,
                field="symbol",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(
            self,
            "venue",
            normalize_optional_text(
                self.venue,
                field="venue",
                maximum_length=_MAX_NAME_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "contract_multiplier",
            normalize_decimal(
                self.contract_multiplier,
                field="contract_multiplier",
                positive=True,
            ),
        )
        object.__setattr__(
            self,
            "attributes",
            _parameter_tuple(self.attributes, field="instrument attributes"),
        )


@dataclass(frozen=True, slots=True)
class ModelSpecification:
    """Named model plus typed parameters and optional implementation identity."""

    name: str
    parameters: tuple[CanonicalParameter, ...] = ()
    version: str | None = None
    implementation_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            normalize_text(
                self.name,
                field="model name",
                maximum_length=_MAX_NAME_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "parameters",
            _parameter_tuple(self.parameters, field="model parameters"),
        )
        object.__setattr__(
            self,
            "version",
            normalize_optional_text(
                self.version,
                field="model version",
                maximum_length=_MAX_NAME_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "implementation_sha256",
            normalize_optional_sha256(
                self.implementation_sha256,
                field="implementation_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class StrategySpecification:
    """Intended strategy logic, independent of engine simulation mechanics."""

    strategy_id: str
    name: str
    logic_sha256: str
    universe: tuple[InstrumentReference, ...]
    parameters: tuple[CanonicalParameter, ...]
    data_frequency: str
    signal_timing: str
    signal_model: ModelSpecification
    sizing_model: ModelSpecification
    version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "strategy_id",
            normalize_text(
                self.strategy_id,
                field="strategy_id",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "name",
            normalize_text(
                self.name,
                field="strategy name",
                maximum_length=_MAX_NAME_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "logic_sha256",
            normalize_sha256(self.logic_sha256, field="logic_sha256"),
        )
        try:
            universe = tuple(self.universe)
        except TypeError as error:
            raise ValueError("universe must be an iterable.") from error
        if not universe:
            raise ValueError("universe must contain at least one instrument.")
        if any(not isinstance(item, InstrumentReference) for item in universe):
            raise ValueError("universe must contain only InstrumentReference values.")
        identifiers = tuple(item.instrument_id for item in universe)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError(
                "universe must not contain duplicate instrument_id values."
            )
        object.__setattr__(
            self,
            "universe",
            tuple(sorted(universe, key=lambda item: item.instrument_id)),
        )
        object.__setattr__(
            self,
            "parameters",
            _parameter_tuple(self.parameters, field="strategy parameters"),
        )
        object.__setattr__(
            self,
            "data_frequency",
            normalize_text(
                self.data_frequency,
                field="data_frequency",
                maximum_length=_MAX_RULE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "signal_timing",
            normalize_text(
                self.signal_timing,
                field="signal_timing",
                maximum_length=_MAX_RULE_LENGTH,
            ),
        )
        if not isinstance(self.signal_model, ModelSpecification):
            raise ValueError("signal_model must be a ModelSpecification.")
        if not isinstance(self.sizing_model, ModelSpecification):
            raise ValueError("sizing_model must be a ModelSpecification.")
        object.__setattr__(
            self,
            "version",
            normalize_optional_text(
                self.version,
                field="strategy version",
                maximum_length=_MAX_NAME_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class SimulationSpecification:
    """Declared simulation mechanics that may differ across engine runs."""

    base_currency: str
    initial_cash: Decimal
    calendar: str
    calendar_timezone: str
    data_adjustment_policy: str
    execution_timing: str
    execution_model: ModelSpecification
    accounting_model: ModelSpecification
    cost_models: tuple[ModelSpecification, ...]
    shorting_allowed: bool
    fractional_quantity_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "base_currency",
            normalize_currency(self.base_currency, field="base_currency"),
        )
        object.__setattr__(
            self,
            "initial_cash",
            normalize_decimal(
                self.initial_cash,
                field="initial_cash",
                non_negative=True,
            ),
        )
        for field in (
            "calendar",
            "calendar_timezone",
            "data_adjustment_policy",
            "execution_timing",
        ):
            object.__setattr__(
                self,
                field,
                normalize_text(
                    getattr(self, field),
                    field=field,
                    maximum_length=_MAX_RULE_LENGTH,
                ),
            )
        if not isinstance(self.execution_model, ModelSpecification):
            raise ValueError("execution_model must be a ModelSpecification.")
        if not isinstance(self.accounting_model, ModelSpecification):
            raise ValueError("accounting_model must be a ModelSpecification.")
        try:
            cost_models = tuple(self.cost_models)
        except TypeError as error:
            raise ValueError("cost_models must be an iterable.") from error
        if any(not isinstance(item, ModelSpecification) for item in cost_models):
            raise ValueError("cost_models must contain only ModelSpecification values.")
        names = tuple(item.name for item in cost_models)
        if len(set(names)) != len(names):
            raise ValueError("cost_models must not contain duplicate model names.")
        object.__setattr__(
            self,
            "cost_models",
            tuple(sorted(cost_models, key=lambda item: item.name)),
        )
        object.__setattr__(
            self,
            "shorting_allowed",
            require_bool(self.shorting_allowed, field="shorting_allowed"),
        )
        object.__setattr__(
            self,
            "fractional_quantity_allowed",
            require_bool(
                self.fractional_quantity_allowed,
                field="fractional_quantity_allowed",
            ),
        )


@dataclass(frozen=True, slots=True)
class CanonicalRunSpecification:
    """Separates intended trading logic from one run's simulation mechanics."""

    strategy: StrategySpecification
    simulation: SimulationSpecification

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, StrategySpecification):
            raise ValueError("strategy must be a StrategySpecification.")
        if not isinstance(self.simulation, SimulationSpecification):
            raise ValueError("simulation must be a SimulationSpecification.")
