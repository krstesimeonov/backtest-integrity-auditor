from collections.abc import Mapping
from datetime import date

import pytest

from backtest_auditor.integrations.ibkr_flex import (
    FLEX_WEB_SERVICE_VERSION,
    GET_STATEMENT_URL,
    SEND_REQUEST_URL,
    FlexHttpResponse,
    FlexRateLimiter,
    FlexWebServiceClient,
    IbkrFlexCredentials,
    IbkrFlexProtocolError,
    IbkrFlexRequest,
    IbkrFlexServiceError,
    IbkrFlexTransportError,
    UrllibFlexHttpTransport,
)


def _control(
    status: str,
    *,
    reference: str | None = None,
    error_code: str | None = None,
    returned_url: str = "https://attacker.invalid/ignored",
) -> bytes:
    return (
        "<FlexStatementResponse>"
        f"<Status>{status}</Status>"
        + ("" if reference is None else f"<ReferenceCode>{reference}</ReferenceCode>")
        + ("" if error_code is None else f"<ErrorCode>{error_code}</ErrorCode>")
        + f"<Url>{returned_url}</Url>"
        "</FlexStatementResponse>"
    ).encode()


class FakeTransport:
    def __init__(self, responses: list[FlexHttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], dict[str, str], float, int]] = []

    def get(
        self,
        url: str,
        *,
        parameters: Mapping[str, str],
        headers: Mapping[str, str],
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> FlexHttpResponse:
        self.calls.append(
            (
                url,
                dict(parameters),
                dict(headers),
                timeout_seconds,
                maximum_bytes,
            )
        )
        return self.responses.pop(0)


def _client(
    responses: list[FlexHttpResponse], sleeps: list[float]
) -> tuple[FlexWebServiceClient, FakeTransport]:
    transport = FakeTransport(responses)
    clock = [0.0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    client = FlexWebServiceClient(
        transport=transport,
        monotonic=lambda: clock[0],
        sleeper=sleep,
    )
    return client, transport


def test_fetches_statement_from_fixed_endpoints_and_ignores_returned_url() -> None:
    statement = b'<ChangeInNAV accountId="U1" />'
    sleeps: list[float] = []
    client, transport = _client(
        [
            FlexHttpResponse(200, _control("Success", reference="12345")),
            FlexHttpResponse(200, statement),
        ],
        sleeps,
    )

    result = client.fetch_statement(
        IbkrFlexCredentials("secret-token", "98765"),
        IbkrFlexRequest(date(2026, 1, 1), date(2026, 1, 31)),
    )

    assert result == statement
    assert [call[0] for call in transport.calls] == [
        SEND_REQUEST_URL,
        GET_STATEMENT_URL,
    ]
    assert transport.calls[0][1] == {
        "t": "secret-token",
        "q": "98765",
        "v": FLEX_WEB_SERVICE_VERSION,
        "fd": "20260101",
        "td": "20260131",
    }
    assert transport.calls[1][1]["q"] == "12345"
    assert transport.calls[0][2]["User-Agent"].startswith("backtest-integrity-auditor/")
    assert sleeps == [pytest.approx(6.1)]
    assert all("attacker.invalid" not in call[0] for call in transport.calls)


def test_retries_transient_get_statement_control_response() -> None:
    sleeps: list[float] = []
    client, transport = _client(
        [
            FlexHttpResponse(200, _control("Success", reference="123")),
            FlexHttpResponse(200, _control("Fail", error_code="1019")),
            FlexHttpResponse(200, b"AccountId,FromDate,ToDate,TWR\nU1,1,2,3\n"),
        ],
        sleeps,
    )

    body = client.fetch_statement(IbkrFlexCredentials("token", "query"))

    assert body.startswith(b"AccountId")
    assert len(transport.calls) == 3
    assert sleeps == [pytest.approx(6.1), pytest.approx(6.1)]


def test_service_errors_are_safe_and_do_not_include_credentials() -> None:
    secret = "do-not-leak"
    client, _ = _client(
        [FlexHttpResponse(200, _control("Fail", error_code="1011"))], []
    )

    with pytest.raises(IbkrFlexServiceError) as error:
        client.fetch_statement(IbkrFlexCredentials(secret, "query-secret"))

    assert error.value.error_code == "1011"
    assert secret not in str(error.value)
    assert "query-secret" not in str(error.value)
    assert "invalid" in str(error.value).casefold()


def test_terminal_or_exhausted_polling_error_is_returned() -> None:
    client, _ = _client(
        [
            FlexHttpResponse(200, _control("Success", reference="1")),
            FlexHttpResponse(200, _control("Fail", error_code="1019")),
        ],
        [],
    )
    client = FlexWebServiceClient(
        transport=client._transport,  # type: ignore[attr-defined]
        maximum_poll_attempts=1,
        monotonic=lambda: 0.0,
        sleeper=lambda _: None,
    )
    with pytest.raises(IbkrFlexServiceError, match="1019"):
        client.fetch_statement(IbkrFlexCredentials("token", "query"))


@pytest.mark.parametrize(
    "send_body",
    [
        b"not xml",
        b"<broken",
        b"<Unexpected />",
        b"<FlexStatementResponse><Status>Other</Status></FlexStatementResponse>",
        b"<!DOCTYPE x><FlexStatementResponse />",
        _control("Success"),
    ],
)
def test_rejects_invalid_send_request_protocol(send_body: bytes) -> None:
    client, _ = _client([FlexHttpResponse(200, send_body)], [])
    with pytest.raises(IbkrFlexProtocolError):
        client.fetch_statement(IbkrFlexCredentials("token", "query"))


def test_rejects_success_control_xml_from_get_statement() -> None:
    client, _ = _client(
        [
            FlexHttpResponse(200, _control("Success", reference="1")),
            FlexHttpResponse(200, _control("Success", reference="2")),
        ],
        [],
    )
    with pytest.raises(IbkrFlexProtocolError, match="without statement"):
        client.fetch_statement(IbkrFlexCredentials("token", "query"))


@pytest.mark.parametrize("status", [302, 401, 500])
def test_rejects_non_success_http_status(status: int) -> None:
    client, _ = _client([FlexHttpResponse(status, b"failure")], [])
    with pytest.raises(IbkrFlexTransportError, match=str(status)):
        client.fetch_statement(IbkrFlexCredentials("token", "query"))


def test_rejects_empty_response() -> None:
    client, _ = _client([FlexHttpResponse(200, b"")], [])
    with pytest.raises(IbkrFlexProtocolError, match="empty"):
        client.fetch_statement(IbkrFlexCredentials("token", "query"))


def test_credentials_are_not_represented_and_are_strictly_validated() -> None:
    credentials = IbkrFlexCredentials("token-secret", "query-secret")
    assert "secret" not in repr(credentials)
    with pytest.raises(ValueError, match="must be a string"):
        IbkrFlexCredentials(123, "query")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be empty"):
        IbkrFlexCredentials(" ", "query")
    with pytest.raises(ValueError, match="256"):
        IbkrFlexCredentials("x" * 257, "query")
    with pytest.raises(ValueError, match="printable ASCII"):
        IbkrFlexCredentials("token with space", "query")


def test_request_and_client_configuration_validation() -> None:
    assert isinstance(FlexWebServiceClient(), FlexWebServiceClient)
    with pytest.raises(ValueError, match="supplied together"):
        IbkrFlexRequest(date(2026, 1, 1), None)
    with pytest.raises(ValueError, match="must not follow"):
        IbkrFlexRequest(date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError, match="365"):
        IbkrFlexRequest(date(2025, 1, 1), date(2026, 1, 1))
    with pytest.raises(ValueError, match="timeout"):
        FlexWebServiceClient(timeout_seconds=0.5)
    with pytest.raises(ValueError, match="maximum_poll_attempts"):
        FlexWebServiceClient(maximum_poll_attempts=0)
    with pytest.raises(ValueError, match="between 6 and 60"):
        FlexRateLimiter(1.0)


def test_rate_limiter_does_not_sleep_for_first_or_late_request() -> None:
    times = iter([0.0, 10.0])
    sleeps: list[float] = []
    limiter = FlexRateLimiter(
        6.0,
        monotonic=lambda: next(times),
        sleeper=sleeps.append,
    )

    limiter.acquire()
    limiter.acquire()

    assert sleeps == []


def test_urllib_transport_encodes_parameters_and_bounds_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            assert size == 11
            return b"response"

    class Opener:
        request: object | None = None

        def open(self, request: object, timeout: float) -> Response:
            self.request = request
            assert timeout == 5.0
            return Response()

    opener = Opener()
    monkeypatch.setattr(
        "backtest_auditor.integrations.ibkr_flex.urllib.request.build_opener",
        lambda _handler: opener,
    )
    transport = UrllibFlexHttpTransport()

    response = transport.get(
        "https://example.invalid/flex",
        parameters={"t": "a b", "q": "1"},
        headers={"User-Agent": "test"},
        timeout_seconds=5.0,
        maximum_bytes=10,
    )

    assert response == FlexHttpResponse(200, b"response")
    assert "t=a%20b" in opener.request.full_url  # type: ignore[union-attr]


def test_urllib_transport_hides_network_errors_and_rejects_large_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingOpener:
        def open(self, request: object, timeout: float) -> object:
            raise OSError("secret URL details")

    monkeypatch.setattr(
        "backtest_auditor.integrations.ibkr_flex.urllib.request.build_opener",
        lambda _handler: FailingOpener(),
    )
    transport = UrllibFlexHttpTransport()
    with pytest.raises(IbkrFlexTransportError) as error:
        transport.get(
            "https://example.invalid",
            parameters={"t": "secret"},
            headers={},
            timeout_seconds=1.0,
            maximum_bytes=1,
        )
    assert "secret" not in str(error.value)

    class LargeResponse:
        status = 200

        def __enter__(self) -> "LargeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            return b"too large"

    class LargeOpener:
        def open(self, request: object, timeout: float) -> LargeResponse:
            return LargeResponse()

    monkeypatch.setattr(
        "backtest_auditor.integrations.ibkr_flex.urllib.request.build_opener",
        lambda _handler: LargeOpener(),
    )
    with pytest.raises(IbkrFlexTransportError, match="size limit"):
        UrllibFlexHttpTransport().get(
            "https://example.invalid",
            parameters={},
            headers={},
            timeout_seconds=1.0,
            maximum_bytes=1,
        )
