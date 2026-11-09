"""Shared validation primitives for canonical implementation-risk contracts."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import (
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DEFAULT_PRECISION = 28
# Sums of canonical decimals are exact (N13): a sum that would need more than
# this many significant digits is rejected, never rounded, so the size of a
# result stays bounded however far apart the operands' exponents are.
EXACT_ADDITION_DIGITS = 100
_EXACT_ADDITION = Context(
    prec=EXACT_ADDITION_DIGITS,
    traps=[Inexact, InvalidOperation, Overflow, DivisionByZero],
)
_CURRENCY_PATTERN = re.compile(r"[A-Z][A-Z0-9]{2,11}")


def normalize_text(value: object, *, field: str, maximum_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty.")
    if len(normalized) > maximum_length:
        raise ValueError(f"{field} must contain at most {maximum_length} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field} must not contain control characters.")
    return normalized


def normalize_optional_text(
    value: object | None,
    *,
    field: str,
    maximum_length: int,
) -> str | None:
    if value is None:
        return None
    return normalize_text(value, field=field, maximum_length=maximum_length)


def normalize_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    normalized = value.strip().lower()
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be exactly 64 hexadecimal characters.")
    return normalized


def normalize_optional_sha256(value: object | None, *, field: str) -> str | None:
    if value is None:
        return None
    return normalize_sha256(value, field=field)


def normalize_decimal(
    value: object,
    *,
    field: str,
    positive: bool = False,
    non_negative: bool = False,
) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(
            f"{field} must be a Decimal, integer, or decimal string; floats are rejected."
        )
    if not isinstance(value, (Decimal, int, str)):
        raise ValueError(f"{field} must be a Decimal, integer, or decimal string.")
    try:
        normalized = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be a valid decimal value.") from error
    if not normalized.is_finite():
        raise ValueError(f"{field} must be finite.")
    if positive and normalized <= 0:
        raise ValueError(f"{field} must be greater than zero.")
    if non_negative and normalized < 0:
        raise ValueError(f"{field} must be greater than or equal to zero.")
    # normalize() rounds to the context precision (28 significant digits by
    # default). A context at least as wide as the value only strips trailing
    # zeros, so the canonical value is always the supplied one; up to 28 digits
    # it is the default context, exponent limits included.
    normalized = normalized.normalize(
        Context(prec=max(len(normalized.as_tuple().digits), _DEFAULT_PRECISION))
    )
    return Decimal(0) if normalized == 0 else normalized


def exact_add(left: Decimal, right: Decimal) -> Decimal:
    """``left + right`` exactly, whatever the caller's context precision."""

    try:
        return _EXACT_ADDITION.add(left, right)
    except Inexact as error:
        raise ValueError(
            f"a decimal sum needs more than {EXACT_ADDITION_DIGITS} significant "
            "digits; it is rejected rather than rounded."
        ) from error


def normalize_optional_decimal(
    value: object | None,
    *,
    field: str,
    positive: bool = False,
    non_negative: bool = False,
) -> Decimal | None:
    if value is None:
        return None
    return normalize_decimal(
        value,
        field=field,
        positive=positive,
        non_negative=non_negative,
    )


def normalize_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def normalize_optional_timestamp(
    value: object | None, *, field: str
) -> datetime | None:
    if value is None:
        return None
    return normalize_timestamp(value, field=field)


def normalize_currency(value: object, *, field: str = "currency") -> str:
    normalized = normalize_text(value, field=field, maximum_length=12).upper()
    if _CURRENCY_PATTERN.fullmatch(normalized) is None:
        raise ValueError(
            f"{field} must contain 3 to 12 uppercase alphanumeric characters "
            "and begin with a letter."
        )
    return normalized


def require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean.")
    return value
