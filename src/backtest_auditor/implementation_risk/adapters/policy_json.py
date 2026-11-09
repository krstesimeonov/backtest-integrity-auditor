"""Strict JSON decoding for the four V1.5 policy contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn, TypeVar

from backtest_auditor.implementation_risk.domain import (
    AlignmentMode,
    AssetClass,
    AttributionRule,
    CanonicalFrequency,
    CanonicalParameter,
    ComparisonLevel,
    CurrencyNormalizationRule,
    DivergenceFamily,
    DivergenceFieldRule,
    DivergenceMeasurementPolicy,
    EngineRunReference,
    FamilyWeight,
    FrequencyKind,
    FrequencyNormalizationRule,
    InstrumentIdentityRule,
    InstrumentReference,
    LevelComparisonPolicy,
    MaterialityRule,
    ReconciliationComparisonPolicy,
    ReconciliationNormalizationPlan,
    RiskAssessmentPolicy,
    RunNormalizationPolicy,
    StrategyIdentityRule,
    TimestampNormalizationRule,
    comparison_policy_to_json,
    divergence_policy_to_json,
    normalization_plan_to_json,
    risk_policy_to_json,
)


_T = TypeVar("_T")
MAX_POLICY_JSON_BYTES = 1_000_000


class PolicyContractError(ValueError):
    """A policy document is malformed or not in its canonical shape."""


def parse_policy_json(text: str) -> dict[str, Any]:
    """Decode one finite JSON object while rejecting duplicate keys."""

    if not isinstance(text, str):
        raise PolicyContractError("policy JSON must be text.")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError, ValueError) as error:
        raise PolicyContractError(f"invalid policy JSON: {error}") from error
    return _mapping(value, "policy")


def parse_policy_json_bytes(content: bytes) -> dict[str, Any]:
    """Decode one bounded UTF-8 policy document from an upload boundary."""

    if not isinstance(content, bytes):
        raise PolicyContractError("policy JSON content must be bytes.")
    if len(content) > MAX_POLICY_JSON_BYTES:
        raise PolicyContractError(
            f"policy JSON exceeds the {MAX_POLICY_JSON_BYTES}-byte safety limit."
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PolicyContractError("policy JSON must be valid UTF-8.") from error
    return parse_policy_json(text)


def load_policy_json_file(source: str | Path) -> dict[str, Any]:
    """Read one bounded regular policy file without following a symlink."""

    path = Path(source)
    if path.is_symlink():
        raise PolicyContractError("policy JSON source must not be a symbolic link.")
    try:
        if not path.is_file():
            raise PolicyContractError("policy JSON source must be a regular file.")
        if path.stat().st_size > MAX_POLICY_JSON_BYTES:
            raise PolicyContractError(
                f"policy JSON exceeds the {MAX_POLICY_JSON_BYTES}-byte safety limit."
            )
        content = path.read_bytes()
    except PolicyContractError:
        raise
    except OSError as error:
        raise PolicyContractError(f"policy JSON could not be read: {error}") from error
    return parse_policy_json_bytes(content)


def normalization_plan_from_json(value: object) -> ReconciliationNormalizationPlan:
    """Decode a parsed normalization-plan document.

    The document must be exactly the canonical JSON that
    ``normalization_plan_to_json`` writes for the decoded plan: same fields,
    same ordering, nothing extra.

    Raises:
        PolicyContractError: If a field is missing, invalid or non-canonical.
    """

    document = _mapping(value, "normalization plan")
    try:
        policies = tuple(
            _run_policy(item) for item in _list(document["policies"], "policies")
        )
        result = ReconciliationNormalizationPlan(
            _string(document["reconciliation_id"], "reconciliation_id"),
            policies,
            _string(
                document["normalization_schema_version"], "normalization_schema_version"
            ),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise PolicyContractError(f"invalid normalization plan: {error}") from error
    return _canonical(value, result, normalization_plan_to_json, "normalization plan")


def comparison_policy_from_json(value: object) -> ReconciliationComparisonPolicy:
    """Decode a parsed comparison-policy document.

    The document must be exactly the canonical JSON that
    ``comparison_policy_to_json`` writes for the decoded policy.

    Raises:
        PolicyContractError: If a field is missing, invalid or non-canonical.
    """

    document = _mapping(value, "comparison policy")
    try:
        result = ReconciliationComparisonPolicy(
            _string(document["reconciliation_id"], "reconciliation_id"),
            tuple(
                LevelComparisonPolicy(
                    ComparisonLevel(item["level"]),
                    AlignmentMode(item["alignment_mode"]),
                    _string(item["rationale"], "rationale"),
                )
                for raw in _list(document["levels"], "levels")
                for item in (_mapping(raw, "level policy"),)
            ),
            _string(document["comparison_schema_version"], "comparison_schema_version"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PolicyContractError(f"invalid comparison policy: {error}") from error
    return _canonical(value, result, comparison_policy_to_json, "comparison policy")


def divergence_policy_from_json(value: object) -> DivergenceMeasurementPolicy:
    """Decode a parsed measurement-policy document.

    The document must be exactly the canonical JSON that
    ``divergence_policy_to_json`` writes for the decoded policy.

    Raises:
        PolicyContractError: If a field is missing, invalid or non-canonical.
    """

    document = _mapping(value, "measurement policy")
    try:
        result = DivergenceMeasurementPolicy(
            _string(document["reconciliation_id"], "reconciliation_id"),
            tuple(
                DivergenceFieldRule(
                    DivergenceFamily(item["family"]),
                    ComparisonLevel(item["level"]),
                    _string(item["field"], "field"),
                    _string(item["rationale"], "rationale"),
                )
                for raw in _list(document["rules"], "rules")
                for item in (_mapping(raw, "measurement rule"),)
            ),
            _string(document["divergence_schema_version"], "divergence_schema_version"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PolicyContractError(f"invalid measurement policy: {error}") from error
    return _canonical(value, result, divergence_policy_to_json, "measurement policy")


def risk_policy_from_json(value: object) -> RiskAssessmentPolicy:
    """Decode a parsed assessment-policy document.

    The document must be exactly the canonical JSON that
    ``risk_policy_to_json`` writes for the decoded policy.

    Raises:
        PolicyContractError: If a field is missing, invalid or non-canonical.
    """

    document = _mapping(value, "assessment policy")
    try:
        result = RiskAssessmentPolicy(
            _string(document["reconciliation_id"], "reconciliation_id"),
            tuple(
                MaterialityRule(
                    DivergenceFamily(item["family"]),
                    ComparisonLevel(item["level"]),
                    _string(item["field"], "field"),
                    Decimal(_string(item["absolute_threshold"], "absolute_threshold")),
                    Decimal(_string(item["extreme_multiple"], "extreme_multiple")),
                    _string(item["rationale"], "rationale"),
                )
                for raw in _list(document["materiality_rules"], "materiality_rules")
                for item in (_mapping(raw, "materiality rule"),)
            ),
            tuple(
                FamilyWeight(
                    DivergenceFamily(item["family"]),
                    Decimal(_string(item["weight"], "weight")),
                )
                for raw in _list(document["family_weights"], "family_weights")
                for item in (_mapping(raw, "family weight"),)
            ),
            tuple(
                AttributionRule(
                    _string(item["hypothesis_code"], "hypothesis_code"),
                    DivergenceFamily(item["source_family"]),
                    DivergenceFamily(item["target_family"]),
                    _string(item["rationale"], "rationale"),
                )
                for raw in _list(document["attribution_rules"], "attribution_rules")
                for item in (_mapping(raw, "attribution rule"),)
            ),
            _boolean(
                document["require_complete_evidence_for_score"],
                "require_complete_evidence_for_score",
            ),
            _string(
                document["risk_assessment_schema_version"],
                "risk_assessment_schema_version",
            ),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise PolicyContractError(f"invalid assessment policy: {error}") from error
    return _canonical(value, result, risk_policy_to_json, "assessment policy")


def _run_policy(value: object) -> RunNormalizationPolicy:
    item = _mapping(value, "run policy")
    strategy = item["strategy_identity"]
    frequency = item["frequency"]
    return RunNormalizationPolicy(
        _run(item["run"]),
        None
        if strategy is None
        else StrategyIdentityRule(
            _string(
                _mapping(strategy, "strategy identity")["source_strategy_id"],
                "source_strategy_id",
            ),
            _string(
                _mapping(strategy, "strategy identity")["canonical_strategy_id"],
                "canonical_strategy_id",
            ),
            _string(_mapping(strategy, "strategy identity")["rationale"], "rationale"),
        ),
        tuple(
            _instrument_rule(raw) for raw in _list(item["instruments"], "instruments")
        ),
        tuple(
            CurrencyNormalizationRule(
                _string(rule["source_currency"], "source_currency"),
                _string(rule["canonical_currency"], "canonical_currency"),
                _string(rule["rationale"], "rationale"),
            )
            for raw in _list(item["currencies"], "currencies")
            for rule in (_mapping(raw, "currency rule"),)
        ),
        tuple(
            TimestampNormalizationRule(
                ComparisonLevel(rule["level"]),
                _integer(rule["offset_microseconds"], "offset_microseconds"),
                _string(rule["rationale"], "rationale"),
            )
            for raw in _list(item["timestamps"], "timestamps")
            for rule in (_mapping(raw, "timestamp rule"),)
        ),
        None if frequency is None else _frequency_rule(frequency),
    )


def _instrument_rule(value: object) -> InstrumentIdentityRule:
    item = _mapping(value, "instrument rule")
    instrument = _mapping(item["canonical_instrument"], "canonical instrument")
    return InstrumentIdentityRule(
        _string(item["source_instrument_id"], "source_instrument_id"),
        InstrumentReference(
            _string(instrument["instrument_id"], "instrument_id"),
            AssetClass(instrument["asset_class"]),
            _string(instrument["symbol"], "symbol"),
            _string(instrument["currency"], "currency"),
            _optional_string(instrument["venue"], "venue"),
            Decimal(_string(instrument["contract_multiplier"], "contract_multiplier")),
            tuple(
                CanonicalParameter(
                    _string(attribute["name"], "name"),
                    attribute["value"],
                    _optional_string(attribute["unit"], "unit"),
                )
                for raw in _list(instrument["attributes"], "attributes")
                for attribute in (_mapping(raw, "attribute"),)
            ),
        ),
        _string(item["rationale"], "rationale"),
    )


def _frequency_rule(value: object) -> FrequencyNormalizationRule:
    item = _mapping(value, "frequency rule")
    canonical = _mapping(item["canonical_frequency"], "canonical frequency")
    return FrequencyNormalizationRule(
        CanonicalFrequency(
            _string(canonical["frequency_id"], "frequency_id"),
            FrequencyKind(canonical["kind"]),
            _optional_integer(
                canonical["interval_microseconds"], "interval_microseconds"
            ),
            _optional_string(canonical["calendar"], "calendar"),
            _optional_string(canonical["calendar_timezone"], "calendar_timezone"),
        ),
        _string(item["rationale"], "rationale"),
        _optional_string(item["source_frequency"], "source_frequency"),
    )


def _run(value: object) -> EngineRunReference:
    item = _mapping(value, "run")
    return EngineRunReference(
        _string(item["run_id"], "run_id"),
        _string(item["engine_name"], "engine_name"),
        _optional_string(item["engine_version"], "engine_version"),
        _string(item["source_sha256"], "source_sha256"),
    )


def _canonical(
    raw: object,
    result: _T,
    serializer: Callable[[_T], str],
    name: str,
) -> _T:
    if json.loads(serializer(result)) != raw:
        raise PolicyContractError(
            f"{name} must use the exact canonical fields and ordering."
        )
    return result


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyContractError(f"duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise PolicyContractError(f"non-finite JSON number {value!r} is not allowed.")


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PolicyContractError(f"{field} must be a JSON object.")
    return value


def _list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise PolicyContractError(f"{field} must be a JSON array.")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PolicyContractError(f"{field} must be a string.")
    return value


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyContractError(f"{field} must be an integer.")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PolicyContractError(f"{field} must be boolean.")
    return value


__all__ = [
    "MAX_POLICY_JSON_BYTES",
    "PolicyContractError",
    "comparison_policy_from_json",
    "divergence_policy_from_json",
    "load_policy_json_file",
    "normalization_plan_from_json",
    "parse_policy_json",
    "parse_policy_json_bytes",
    "risk_policy_from_json",
]
