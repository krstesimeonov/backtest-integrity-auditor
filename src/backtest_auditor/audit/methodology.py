from backtest_auditor.domain.enums import (
    ReturnCostBasis,
    SeriesRole,
)
from backtest_auditor.domain.metadata import ReturnConstructionSpec
from backtest_auditor.domain.results import (
    ReturnConstructionAssessmentResult,
)


_REQUIRED_FIELDS = (
    "transaction_costs_included",
    "fees_included",
    "leverage_policy",
    "currency",
    "price_adjustment_policy",
    "data_source",
    "data_vintage",
    "stale_price_policy",
    "delisting_return_policy",
    "survivorship_bias_controlled",
    "lookahead_bias_controlled",
    "signal_timing",
    "execution_timing",
)


def assess_return_construction(
    spec: ReturnConstructionSpec | None,
    *,
    role: SeriesRole,
) -> ReturnConstructionAssessmentResult:
    """Preserve declared methodology and quantify its completeness."""

    if spec is None:
        return ReturnConstructionAssessmentResult(
            role=role,
            supplied=False,
            declared_field_count=0,
            required_field_count=len(_REQUIRED_FIELDS),
            completeness_ratio=0.0,
            cost_basis=ReturnCostBasis.UNDECLARED,
            transaction_costs_included=None,
            fees_included=None,
            leverage_policy=None,
            currency=None,
            price_adjustment_policy=None,
            data_source=None,
            data_vintage=None,
            stale_price_policy=None,
            delisting_return_policy=None,
            survivorship_bias_controlled=None,
            lookahead_bias_controlled=None,
            signal_timing=None,
            execution_timing=None,
        )

    declared_field_count = sum(
        getattr(spec, field_name) is not None for field_name in _REQUIRED_FIELDS
    )

    return ReturnConstructionAssessmentResult(
        role=role,
        supplied=True,
        declared_field_count=declared_field_count,
        required_field_count=len(_REQUIRED_FIELDS),
        completeness_ratio=(declared_field_count / len(_REQUIRED_FIELDS)),
        cost_basis=_derive_cost_basis(spec),
        transaction_costs_included=(spec.transaction_costs_included),
        fees_included=spec.fees_included,
        leverage_policy=spec.leverage_policy,
        currency=spec.currency,
        price_adjustment_policy=spec.price_adjustment_policy,
        data_source=spec.data_source,
        data_vintage=spec.data_vintage,
        stale_price_policy=spec.stale_price_policy,
        delisting_return_policy=spec.delisting_return_policy,
        survivorship_bias_controlled=(spec.survivorship_bias_controlled),
        lookahead_bias_controlled=(spec.lookahead_bias_controlled),
        signal_timing=spec.signal_timing,
        execution_timing=spec.execution_timing,
    )


def _derive_cost_basis(
    spec: ReturnConstructionSpec,
) -> ReturnCostBasis:
    transaction_costs = spec.transaction_costs_included
    fees = spec.fees_included

    if transaction_costs is None and fees is None:
        return ReturnCostBasis.UNDECLARED
    if transaction_costs is None or fees is None:
        return ReturnCostBasis.PARTIALLY_DECLARED
    if not transaction_costs and not fees:
        return ReturnCostBasis.GROSS
    if transaction_costs and not fees:
        return ReturnCostBasis.NET_OF_TRANSACTION_COSTS
    if transaction_costs and fees:
        return ReturnCostBasis.NET_OF_ALL_DECLARED_COSTS
    return ReturnCostBasis.MIXED
