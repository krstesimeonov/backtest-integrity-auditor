from decimal import Decimal

import pytest

from backtest_auditor.implementation_risk import (
    AssetClass,
    CanonicalParameter,
    CanonicalRunSpecification,
    InstrumentReference,
    ModelSpecification,
    SimulationSpecification,
    StrategySpecification,
)


def _instrument(
    instrument_id: str = "AAPL.XNAS",
    *,
    symbol: str = "AAPL",
    currency: str = "USD",
) -> InstrumentReference:
    return InstrumentReference(
        instrument_id=instrument_id,
        asset_class=AssetClass.EQUITY,
        symbol=symbol,
        currency=currency,
        venue="XNAS",
    )


def _model(name: str = "model") -> ModelSpecification:
    return ModelSpecification(name=name)


def _strategy(**overrides) -> StrategySpecification:
    values = {
        "strategy_id": "momentum-1",
        "name": "Momentum",
        "logic_sha256": "a" * 64,
        "universe": (_instrument(),),
        "parameters": (CanonicalParameter("lookback", Decimal("20"), "bars"),),
        "data_frequency": "1 trading day",
        "signal_timing": "after adjusted close at t",
        "signal_model": _model("cross-sectional momentum"),
        "sizing_model": _model("equal weight"),
        "version": "1",
    }
    values.update(overrides)
    return StrategySpecification(**values)


def _simulation(**overrides) -> SimulationSpecification:
    values = {
        "base_currency": "USD",
        "initial_cash": Decimal("100000"),
        "calendar": "XNYS",
        "calendar_timezone": "America/New_York",
        "data_adjustment_policy": "split and dividend adjusted",
        "execution_timing": "next session open",
        "execution_model": _model("next-open fill"),
        "accounting_model": _model("average cost"),
        "cost_models": (_model("slippage"), _model("commission")),
        "shorting_allowed": False,
        "fractional_quantity_allowed": True,
    }
    values.update(overrides)
    return SimulationSpecification(**values)


@pytest.mark.parametrize("value", [None, True, 3, Decimal("1.2500"), " close "])
def test_parameter_accepts_canonical_scalar_types(value) -> None:
    parameter = CanonicalParameter(" rule ", value, " units ")

    assert parameter.name == "rule"
    assert parameter.unit == "units"
    if isinstance(value, Decimal):
        assert parameter.value == Decimal("1.25")
    elif isinstance(value, str):
        assert parameter.value == "close"
    else:
        assert parameter.value == value


@pytest.mark.parametrize("value", [1.5, object(), [], " "])
def test_parameter_rejects_noncanonical_or_empty_values(value) -> None:
    with pytest.raises(ValueError, match="parameter value"):
        CanonicalParameter("value", value)  # type: ignore[arg-type]


def test_parameter_rejects_invalid_name_or_unit() -> None:
    with pytest.raises(ValueError, match="parameter name"):
        CanonicalParameter("", 1)
    with pytest.raises(ValueError, match="parameter unit"):
        CanonicalParameter("value", 1, "\n")


def test_instrument_normalizes_identity_and_sorts_attributes() -> None:
    instrument = InstrumentReference(
        instrument_id=" es-2026 ",
        asset_class="future",  # type: ignore[arg-type]
        symbol=" ES ",
        currency="usd",
        venue=" CME ",
        contract_multiplier="50.00",  # type: ignore[arg-type]
        attributes=(
            CanonicalParameter("expiry", "2026-12-18"),
            CanonicalParameter("contract", "ESZ6"),
        ),
    )

    assert instrument.instrument_id == "es-2026"
    assert instrument.asset_class is AssetClass.FUTURE
    assert instrument.symbol == "ES"
    assert instrument.currency == "USD"
    assert instrument.venue == "CME"
    assert instrument.contract_multiplier == Decimal(50)
    assert tuple(item.name for item in instrument.attributes) == (
        "contract",
        "expiry",
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("asset_class", "unknown", "asset_class"),
        ("currency", "1", "currency"),
        ("contract_multiplier", 0, "greater than zero"),
        ("attributes", None, "iterable"),
        ("attributes", ("expiry",), "CanonicalParameter"),
        (
            "attributes",
            (CanonicalParameter("expiry", "x"), CanonicalParameter("expiry", "y")),
            "duplicate",
        ),
    ],
)
def test_instrument_rejects_invalid_contract(field, value, message) -> None:
    values = {
        "instrument_id": "AAPL.XNAS",
        "asset_class": AssetClass.EQUITY,
        "symbol": "AAPL",
        "currency": "USD",
        "contract_multiplier": Decimal(1),
        "attributes": (),
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        InstrumentReference(**values)


def test_model_normalizes_parameters_version_and_hash() -> None:
    model = ModelSpecification(
        name=" fill model ",
        parameters=(CanonicalParameter("z", 2), CanonicalParameter("a", 1)),
        version=" 1.0 ",
        implementation_sha256="A" * 64,
    )

    assert model.name == "fill model"
    assert tuple(item.name for item in model.parameters) == ("a", "z")
    assert model.version == "1.0"
    assert model.implementation_sha256 == "a" * 64


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": ""}, "model name"),
        ({"parameters": None}, "iterable"),
        ({"parameters": ("bad",)}, "CanonicalParameter"),
        (
            {
                "parameters": (
                    CanonicalParameter("x", 1),
                    CanonicalParameter("x", 2),
                )
            },
            "duplicate",
        ),
        ({"implementation_sha256": "bad"}, "implementation_sha256"),
    ],
)
def test_model_rejects_invalid_contract(overrides, message) -> None:
    values = {"name": "model"}
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        ModelSpecification(**values)


def test_strategy_sorts_universe_and_parameters_without_mixing_simulation() -> None:
    strategy = _strategy(
        universe=(
            _instrument("MSFT.XNAS", symbol="MSFT"),
            _instrument("AAPL.XNAS"),
        ),
        parameters=(CanonicalParameter("z", 2), CanonicalParameter("a", 1)),
    )

    assert tuple(item.instrument_id for item in strategy.universe) == (
        "AAPL.XNAS",
        "MSFT.XNAS",
    )
    assert tuple(item.name for item in strategy.parameters) == ("a", "z")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"logic_sha256": "bad"}, "logic_sha256"),
        ({"universe": None}, "universe must be an iterable"),
        ({"universe": ()}, "at least one"),
        ({"universe": ("AAPL",)}, "InstrumentReference"),
        (
            {"universe": (_instrument(), _instrument())},
            "duplicate instrument_id",
        ),
        ({"parameters": None}, "strategy parameters must be an iterable"),
        ({"signal_model": "model"}, "signal_model"),
        ({"sizing_model": "model"}, "sizing_model"),
        ({"data_frequency": ""}, "data_frequency"),
        ({"signal_timing": "\n"}, "signal_timing"),
    ],
)
def test_strategy_rejects_invalid_contract(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        _strategy(**overrides)


def test_simulation_normalizes_models_and_explicit_booleans() -> None:
    simulation = _simulation(base_currency="usd", initial_cash="100000.00")

    assert simulation.base_currency == "USD"
    assert simulation.initial_cash == Decimal("1E+5")
    assert tuple(item.name for item in simulation.cost_models) == (
        "commission",
        "slippage",
    )
    assert simulation.shorting_allowed is False
    assert simulation.fractional_quantity_allowed is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"initial_cash": -1}, "greater than or equal"),
        ({"calendar": ""}, "calendar"),
        ({"calendar_timezone": ""}, "calendar_timezone"),
        ({"data_adjustment_policy": ""}, "data_adjustment_policy"),
        ({"execution_timing": ""}, "execution_timing"),
        ({"execution_model": "model"}, "execution_model"),
        ({"accounting_model": "model"}, "accounting_model"),
        ({"cost_models": None}, "iterable"),
        ({"cost_models": ("cost",)}, "ModelSpecification"),
        ({"cost_models": (_model("cost"), _model("cost"))}, "duplicate"),
        ({"shorting_allowed": 0}, "shorting_allowed"),
        ({"fractional_quantity_allowed": 1}, "fractional_quantity_allowed"),
    ],
)
def test_simulation_rejects_invalid_contract(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        _simulation(**overrides)


def test_run_specification_requires_both_valid_sections() -> None:
    specification = CanonicalRunSpecification(_strategy(), _simulation())

    assert specification.strategy.strategy_id == "momentum-1"

    with pytest.raises(ValueError, match="strategy"):
        CanonicalRunSpecification("strategy", _simulation())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="simulation"):
        CanonicalRunSpecification(_strategy(), "simulation")  # type: ignore[arg-type]
