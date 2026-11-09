"""Credential-safe, read-only client for IBKR Flex Web Service v3."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from backtest_auditor import PACKAGE_VERSION


SEND_REQUEST_URL = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
)
GET_STATEMENT_URL = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/"
    "FlexWebService/GetStatement"
)
FLEX_WEB_SERVICE_VERSION = "3"
MAX_RESPONSE_BYTES = 20 * 1024 * 1024

_CONTROL_XML_PATTERN = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_TRANSIENT_ERROR_CODES = {
    "1001",
    "1003",
    "1004",
    "1005",
    "1006",
    "1007",
    "1008",
    "1009",
    "1018",
    "1019",
    "1021",
}
_KNOWN_ERROR_MESSAGES = {
    "1001": "Statement could not be generated at this time.",
    "1003": "Statement is not available.",
    "1004": "Statement is incomplete at this time.",
    "1005": "Settlement data is not ready at this time.",
    "1006": "FIFO P/L data is not ready at this time.",
    "1007": "MTM P/L data is not ready at this time.",
    "1008": "MTM performance data is not ready at this time.",
    "1009": "VaR data is not ready at this time.",
    "1010": "Legacy Flex service version is unsupported.",
    "1011": "The Flex token is invalid.",
    "1012": "The Flex token has expired.",
    "1013": "The account is invalid.",
    "1014": "The account is not authorized for this statement.",
    "1015": "The Flex query is invalid.",
    "1016": "The Flex token is invalid for the account.",
    "1017": "The account is inactive.",
    "1018": "The Flex request rate limit was exceeded.",
    "1019": "The statement is still being generated.",
    "1020": "The Flex token was revoked.",
    "1021": "The statement service is temporarily unavailable.",
}


class IbkrFlexError(RuntimeError):
    """Base class whose messages never contain credentials or request URLs."""


class IbkrFlexTransportError(IbkrFlexError):
    pass


class IbkrFlexProtocolError(IbkrFlexError):
    pass


class IbkrFlexServiceError(IbkrFlexError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        message = _KNOWN_ERROR_MESSAGES.get(
            error_code,
            "IBKR Flex Web Service returned an unrecognized error.",
        )
        super().__init__(f"IBKR Flex error {error_code}: {message}")


@dataclass(frozen=True, slots=True)
class IbkrFlexCredentials:
    token: str = field(repr=False)
    query_id: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", _credential(self.token, "token"))
        object.__setattr__(self, "query_id", _credential(self.query_id, "query_id"))


@dataclass(frozen=True, slots=True)
class IbkrFlexRequest:
    from_date: date | None = None
    to_date: date | None = None

    def __post_init__(self) -> None:
        if (self.from_date is None) != (self.to_date is None):
            raise ValueError("Flex date overrides must be supplied together.")
        if self.from_date is None:
            return
        assert self.to_date is not None
        if self.from_date > self.to_date:
            raise ValueError("Flex from_date must not follow to_date.")
        if (self.to_date - self.from_date).days >= 365:
            raise ValueError("Flex date overrides must span at most 365 days.")


@dataclass(frozen=True, slots=True)
class FlexHttpResponse:
    status: int
    body: bytes


class FlexHttpTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        parameters: Mapping[str, str],
        headers: Mapping[str, str],
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> FlexHttpResponse: ...


class UrllibFlexHttpTransport:
    """Small no-redirect transport with bounded response reads."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def get(
        self,
        url: str,
        *,
        parameters: Mapping[str, str],
        headers: Mapping[str, str],
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> FlexHttpResponse:
        query = urllib.parse.urlencode(parameters, quote_via=urllib.parse.quote)
        request = urllib.request.Request(
            f"{url}?{query}",
            headers=dict(headers),
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(maximum_bytes + 1)
                status = int(response.status)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise IbkrFlexTransportError(
                "IBKR Flex Web Service request failed before a valid response."
            ) from None
        if len(body) > maximum_bytes:
            raise IbkrFlexTransportError(
                "IBKR Flex Web Service response exceeded the configured size limit."
            )
        return FlexHttpResponse(status=status, body=body)


class FlexRateLimiter:
    """Serial limiter satisfying both one/second and ten/minute token limits."""

    def __init__(
        self,
        minimum_interval_seconds: float = 6.1,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 6.0 <= minimum_interval_seconds <= 60.0:
            raise ValueError("minimum_interval_seconds must be between 6 and 60.")
        self.minimum_interval_seconds = float(minimum_interval_seconds)
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._last_request: float | None = None

    def acquire(self) -> None:
        now = self._monotonic()
        if self._last_request is None:
            self._last_request = now
            return
        earliest = self._last_request + self.minimum_interval_seconds
        if now < earliest:
            self._sleeper(earliest - now)
            now = max(self._monotonic(), earliest)
        self._last_request = now


class FlexWebServiceClient:
    """Fetch one configured Activity Flex statement without persisting secrets."""

    def __init__(
        self,
        *,
        transport: FlexHttpTransport | None = None,
        timeout_seconds: float = 30.0,
        maximum_poll_attempts: int = 10,
        minimum_interval_seconds: float = 6.1,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1.0 <= timeout_seconds <= 120.0:
            raise ValueError("timeout_seconds must be between 1 and 120.")
        if (
            isinstance(maximum_poll_attempts, bool)
            or not isinstance(maximum_poll_attempts, int)
            or not 1 <= maximum_poll_attempts <= 100
        ):
            raise ValueError("maximum_poll_attempts must be an integer from 1 to 100.")
        self._transport = transport or UrllibFlexHttpTransport()
        self._timeout_seconds = float(timeout_seconds)
        self._maximum_poll_attempts = maximum_poll_attempts
        self._rate_limiter = FlexRateLimiter(
            minimum_interval_seconds,
            monotonic=monotonic,
            sleeper=sleeper,
        )

    def fetch_statement(
        self,
        credentials: IbkrFlexCredentials,
        request: IbkrFlexRequest | None = None,
    ) -> bytes:
        request = request or IbkrFlexRequest()
        send_parameters = {
            "t": credentials.token,
            "q": credentials.query_id,
            "v": FLEX_WEB_SERVICE_VERSION,
        }
        if request.from_date is not None:
            assert request.to_date is not None
            send_parameters["fd"] = request.from_date.strftime("%Y%m%d")
            send_parameters["td"] = request.to_date.strftime("%Y%m%d")
        send_body = self._get(SEND_REQUEST_URL, send_parameters)
        control = _parse_control_response(send_body, required=True)
        assert control is not None
        if control.status != "success":
            raise IbkrFlexServiceError(control.error_code or "unknown")
        reference_code = control.reference_code
        if reference_code is None or not reference_code.isdigit():
            raise IbkrFlexProtocolError(
                "IBKR Flex SendRequest response omitted a numeric reference code."
            )

        get_parameters = {
            "t": credentials.token,
            "q": reference_code,
            "v": FLEX_WEB_SERVICE_VERSION,
        }
        for attempt in range(1, self._maximum_poll_attempts + 1):
            statement_body = self._get(GET_STATEMENT_URL, get_parameters)
            response = _parse_control_response(statement_body, required=False)
            if response is None:
                return statement_body
            error_code = response.error_code or "unknown"
            if (
                response.status != "success"
                and error_code in _TRANSIENT_ERROR_CODES
                and attempt < self._maximum_poll_attempts
            ):
                continue
            if response.status != "success":
                raise IbkrFlexServiceError(error_code)
            raise IbkrFlexProtocolError(
                "IBKR Flex GetStatement returned control XML without statement data."
            )
        raise IbkrFlexProtocolError("IBKR Flex polling exhausted unexpectedly.")

    def _get(self, url: str, parameters: Mapping[str, str]) -> bytes:
        self._rate_limiter.acquire()
        response = self._transport.get(
            url,
            parameters=parameters,
            headers={
                "Accept": "application/xml,text/csv,text/plain",
                "User-Agent": f"backtest-integrity-auditor/{PACKAGE_VERSION}",
            },
            timeout_seconds=self._timeout_seconds,
            maximum_bytes=MAX_RESPONSE_BYTES,
        )
        if response.status != 200:
            raise IbkrFlexTransportError(
                f"IBKR Flex Web Service returned HTTP status {response.status}."
            )
        if not response.body:
            raise IbkrFlexProtocolError(
                "IBKR Flex Web Service returned an empty response."
            )
        return response.body


@dataclass(frozen=True, slots=True)
class _ControlResponse:
    status: str
    reference_code: str | None
    error_code: str | None


def _parse_control_response(
    body: bytes,
    *,
    required: bool,
) -> _ControlResponse | None:
    if not body.lstrip().startswith(b"<"):
        if required:
            raise IbkrFlexProtocolError(
                "IBKR Flex SendRequest did not return XML control data."
            )
        return None
    if _CONTROL_XML_PATTERN.search(body):
        raise IbkrFlexProtocolError(
            "IBKR Flex control XML contained a prohibited declaration."
        )
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        if required:
            raise IbkrFlexProtocolError(
                "IBKR Flex SendRequest returned malformed XML control data."
            ) from None
        return None
    if _local_name(root.tag) != "flexstatementresponse":
        if required:
            raise IbkrFlexProtocolError(
                "IBKR Flex SendRequest returned an unexpected XML document."
            )
        return None
    values = {
        _local_name(element.tag): (element.text or "").strip()
        for element in root.iter()
    }
    status = values.get("status", "").casefold()
    if status not in {"success", "fail"}:
        raise IbkrFlexProtocolError(
            "IBKR Flex control response omitted a recognized status."
        )
    return _ControlResponse(
        status=status,
        reference_code=values.get("referencecode") or None,
        error_code=values.get("errorcode") or None,
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _credential(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if len(normalized) > 256:
        raise ValueError(f"{field_name} must not exceed 256 characters.")
    if any(ord(character) < 33 or ord(character) > 126 for character in normalized):
        raise ValueError(f"{field_name} must contain printable ASCII without spaces.")
    return normalized


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()
