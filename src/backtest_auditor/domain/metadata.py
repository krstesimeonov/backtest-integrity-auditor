from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backtest_auditor.domain.enums import (
    LeveragePolicy,
    PriceAdjustmentPolicy,
)


@dataclass(frozen=True, slots=True)
class ObservationCalendarSpec:
    """Declared observation sessions and their local timezone.

    A named exchange calendar without session dates is deliberately only a
    declaration. Exact verification requires either one of the two built-in
    policies (``24/7`` or ``WEEKDAYS``) or authoritative session dates.
    """

    calendar_name: str
    timezone: str
    expected_session_dates: tuple[date, ...] | None = None

    def __post_init__(self) -> None:
        calendar_name = self.calendar_name.strip()
        if not calendar_name:
            raise ValueError("calendar_name must not be empty.")

        timezone = self.timezone.strip()
        if not timezone:
            raise ValueError("timezone must not be empty.")

        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA timezone name.") from error

        session_dates = self.expected_session_dates
        if session_dates is not None:
            normalized_dates = tuple(session_dates)
            if not normalized_dates:
                raise ValueError(
                    "expected_session_dates must not be empty when supplied."
                )
            if any(type(item) is not date for item in normalized_dates):
                raise ValueError("expected_session_dates must contain date values.")
            if len(set(normalized_dates)) != len(normalized_dates):
                raise ValueError("expected_session_dates must be unique.")
            if tuple(sorted(normalized_dates)) != normalized_dates:
                raise ValueError("expected_session_dates must be strictly increasing.")
            object.__setattr__(
                self,
                "expected_session_dates",
                normalized_dates,
            )

        object.__setattr__(self, "calendar_name", calendar_name)
        object.__setattr__(self, "timezone", timezone)


@dataclass(frozen=True, slots=True)
class ReturnConstructionSpec:
    """Provenance and economic meaning of a supplied return series.

    Fields are optional so partial external evidence can be preserved. The
    auditor reports incomplete declarations instead of inventing defaults.
    """

    transaction_costs_included: bool | None = None
    fees_included: bool | None = None
    leverage_policy: LeveragePolicy | None = None
    currency: str | None = None
    price_adjustment_policy: PriceAdjustmentPolicy | None = None
    data_source: str | None = None
    data_vintage: str | None = None
    stale_price_policy: str | None = None
    delisting_return_policy: str | None = None
    survivorship_bias_controlled: bool | None = None
    lookahead_bias_controlled: bool | None = None
    signal_timing: str | None = None
    execution_timing: str | None = None

    def __post_init__(self) -> None:
        if self.leverage_policy is not None:
            try:
                leverage_policy = LeveragePolicy(self.leverage_policy)
            except ValueError as error:
                supported = ", ".join(item.value for item in LeveragePolicy)
                raise ValueError(
                    f"leverage_policy must be one of: {supported}."
                ) from error
            object.__setattr__(
                self,
                "leverage_policy",
                leverage_policy,
            )

        if self.price_adjustment_policy is not None:
            try:
                adjustment = PriceAdjustmentPolicy(self.price_adjustment_policy)
            except ValueError as error:
                supported = ", ".join(item.value for item in PriceAdjustmentPolicy)
                raise ValueError(
                    f"price_adjustment_policy must be one of: {supported}."
                ) from error
            object.__setattr__(
                self,
                "price_adjustment_policy",
                adjustment,
            )

        for field_name in (
            "transaction_costs_included",
            "fees_included",
            "survivorship_bias_controlled",
            "lookahead_bias_controlled",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean when supplied.")

        currency = self._normalize_optional_text("currency")
        if currency is not None:
            currency = currency.upper()
            if len(currency) != 3 or not currency.isalpha():
                raise ValueError("currency must be a three-letter alphabetic code.")
            object.__setattr__(self, "currency", currency)

        for field_name in (
            "data_source",
            "data_vintage",
            "stale_price_policy",
            "delisting_return_policy",
            "signal_timing",
            "execution_timing",
        ):
            self._normalize_optional_text(field_name)

    def _normalize_optional_text(self, field_name: str) -> str | None:
        value = getattr(self, field_name)
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty when supplied.")
        object.__setattr__(self, field_name, normalized)
        return normalized
