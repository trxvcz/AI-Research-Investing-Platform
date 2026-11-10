"""SEC transport boundary tests use local fakes, never network calls."""

from datetime import UTC, datetime
from typing import Any

import pytest

from alphasense.sec_contracts import SecFetchRequest
from alphasense.sec_transport import SecTransport, SecTransportError
from alphasense.snapshot_contracts import MAX_BYTES

USER_AGENT = "Synthetic Research Test contact@example.invalid"


class FakeResponse:
    def __init__(
        self,
        raw: bytes = b'{"synthetic": true}\n',
        status: int = 200,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.status = status
        self.raw = raw
        self.headers = headers if headers is not None else [("Content-Type", "application/json")]
        self.position = 0
        self.reads: list[int] = []

    def getheaders(self) -> list[tuple[str, str]]:
        return self.headers

    def read(self, amount: int) -> bytes:
        self.reads.append(amount)
        chunk = self.raw[self.position : self.position + amount]
        self.position += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    def request(self, *args: Any, **kwargs: Any) -> None:
        self.requests.append((args, kwargs))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def mocked_connection(
    monkeypatch: pytest.MonkeyPatch, response: FakeResponse
) -> tuple[FakeConnection, list[tuple[tuple[Any, ...], dict[str, Any]]]]:
    created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    connection = FakeConnection(response)

    def create(*args: Any, **kwargs: Any) -> FakeConnection:
        created.append((args, kwargs))
        return connection

    monkeypatch.setattr("alphasense.sec_transport.http.client.HTTPSConnection", create)
    return connection, created


@pytest.mark.parametrize(
    "resource,path",
    [
        ("submissions", "/submissions/CIK0000320193.json"),
        (
            "revenue",
            "/api/xbrl/companyconcept/CIK0000320193/us-gaap/"
            "RevenueFromContractWithCustomerExcludingAssessedTax.json",
        ),
        ("net_income", "/api/xbrl/companyconcept/CIK0000320193/us-gaap/NetIncomeLoss.json"),
    ],
)
def test_fixed_sec_get_preserves_entity_bytes_and_identifies_client(
    monkeypatch: pytest.MonkeyPatch, resource: str, path: str
) -> None:
    raw = b' {"synthetic":true}\r\n\x00'
    response = FakeResponse(
        raw,
        headers=[
            ("Content-Type", "application/json; charset=UTF-8"),
            ("Content-Length", str(len(raw))),
        ],
    )
    connection, created = mocked_connection(monkeypatch, response)
    before = datetime.now(UTC)
    result = SecTransport(USER_AGENT)(SecFetchRequest(cik="0000320193", resource=resource))
    assert result.content == raw and result.url == "https://data.sec.gov" + path
    assert before <= result.retrieved_at <= datetime.now(UTC)
    assert created[0][0] == ("data.sec.gov",)
    assert created[0][1]["timeout"] == 15
    assert created[0][1]["context"].check_hostname is True
    args, kwargs = connection.requests[0]
    assert args == ("GET", path)
    assert kwargs["headers"] == {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    assert connection.closed and len(created) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 403, 404, 429, 500, 503])
def test_http_errors_and_redirects_do_not_retry_or_follow(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    response = FakeResponse(
        b"PRIVATE-RESPONSE",
        status,
        [
            ("Location", "https://not-sec.example.invalid/PRIVATE"),
            ("Set-Cookie", "PRIVATE-CREDENTIAL"),
        ],
    )
    connection, created = mocked_connection(monkeypatch, response)
    with pytest.raises(SecTransportError) as error:
        SecTransport(USER_AGENT)(SecFetchRequest(cik="0000320193", resource="submissions"))
    assert error.value.code == f"SEC_HTTP_{status}"
    assert "PRIVATE" not in repr(error.value) and USER_AGENT not in repr(error.value)
    assert connection.closed and len(created) == 1 and response.reads == []


@pytest.mark.parametrize(
    "headers,code",
    [
        ([], "SEC_RESPONSE_TYPE"),
        ([("Content-Type", "text/html")], "SEC_RESPONSE_TYPE"),
        (
            [("Content-Type", "application/json"), ("Content-Encoding", "gzip")],
            "SEC_RESPONSE_ENCODING",
        ),
        (
            [("Content-Type", "application/json"), ("Transfer-Encoding", "gzip, chunked")],
            "SEC_RESPONSE_ENCODING",
        ),
        ([("Content-Type", "application/json"), ("Content-Length", "-1")], "SEC_RESPONSE_HEADERS"),
        ([("Content-Type", "application/json"), ("Content-Length", "1.0")], "SEC_RESPONSE_HEADERS"),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("content-length", "2"),
            ],
            "SEC_RESPONSE_HEADERS",
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Transfer-Encoding", "chunked"),
                ("Content-Length", "2"),
            ],
            "SEC_RESPONSE_HEADERS",
        ),
    ],
)
def test_response_metadata_is_checked_before_body(
    monkeypatch: pytest.MonkeyPatch, headers: list[tuple[str, str]], code: str
) -> None:
    response = FakeResponse(headers=headers)
    mocked_connection(monkeypatch, response)
    with pytest.raises(SecTransportError, match=f"^{code}$"):
        SecTransport(USER_AGENT)(SecFetchRequest(cik="0000320193", resource="submissions"))
    assert response.reads == []


@pytest.mark.parametrize("declared", [None, "2", str(MAX_BYTES + 1)])
def test_oversized_body_never_truncates_or_allocates_unbounded(
    monkeypatch: pytest.MonkeyPatch, declared: str | None
) -> None:
    headers = [("Content-Type", "application/json")]
    if declared is not None:
        headers.append(("Content-Length", declared))
    response = FakeResponse(b"x" * (MAX_BYTES + 50), headers=headers)
    connection, _created = mocked_connection(monkeypatch, response)
    with pytest.raises(SecTransportError, match="^SEC_RESPONSE_TOO_LARGE$"):
        SecTransport(USER_AGENT)(SecFetchRequest(cik="0000320193", resource="submissions"))
    assert response.position <= MAX_BYTES + 1
    assert all(0 < size <= 65536 for size in response.reads)
    assert connection.closed


@pytest.mark.parametrize("raw,declared", [(b"", None), (b"{}", "3"), (b"{}", "1")])
def test_empty_and_length_mismatch_fail_closed(
    monkeypatch: pytest.MonkeyPatch, raw: bytes, declared: str | None
) -> None:
    headers = [("Content-Type", "application/json")]
    if declared is not None:
        headers.append(("Content-Length", declared))
    mocked_connection(monkeypatch, FakeResponse(raw, headers=headers))
    with pytest.raises(SecTransportError, match="^SEC_RESPONSE_LENGTH$"):
        SecTransport(USER_AGENT)(SecFetchRequest(cik="0000320193", resource="submissions"))


def test_exact_limit_and_chunked_body_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = b"x" * MAX_BYTES
    mocked_connection(
        monkeypatch,
        FakeResponse(
            raw, headers=[("Content-Type", "application/json"), ("Transfer-Encoding", "chunked")]
        ),
    )
    assert (
        SecTransport(USER_AGENT)(SecFetchRequest(cik="0000320193", resource="submissions")).content
        == raw
    )


@pytest.mark.parametrize("timeout", [0, 31, -1, True, float("inf"), float("nan"), "15"])
def test_invalid_timeout_is_not_a_network_attempt(timeout: Any) -> None:
    with pytest.raises(SecTransportError, match="^SEC_TIMEOUT_INVALID$"):
        SecTransport(USER_AGENT, timeout=timeout)


@pytest.mark.parametrize(
    "user_agent",
    [
        None,
        "",
        "AnonymousBot",
        "bot contact",
        "bot contact@localhost",
        "contact@example.invalid",
        " bot contact@example.invalid",
        "bot contact@example.invalid\r\nCookie: PRIVATE",
        "bot\tcontact@example.invalid",
        "bot kontakt@przykład.pl",
        "a" * 257,
    ],
)
def test_missing_or_unsafe_user_agent_is_rejected(user_agent: Any) -> None:
    with pytest.raises(SecTransportError, match="^SEC_USER_AGENT_INVALID$") as error:
        SecTransport(user_agent)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("payload", [None, {}, "https://evil.example.invalid", 123])
def test_only_typed_request_is_accepted_without_connecting(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    _connection, created = mocked_connection(monkeypatch, FakeResponse())
    with pytest.raises(SecTransportError, match="^SEC_REQUEST_INVALID$"):
        SecTransport(USER_AGENT)(payload)
    assert created == []


@pytest.mark.parametrize(
    "change", [{"cik": "../../evil"}, {"cik": "0000000000"}, {"resource": "https://evil.invalid"}]
)
def test_forged_model_is_revalidated_before_connecting(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    _connection, created = mocked_connection(monkeypatch, FakeResponse())
    forged = SecFetchRequest(cik="0000320193", resource="submissions").model_copy(update=change)
    with pytest.raises(SecTransportError, match="^SEC_REQUEST_INVALID$"):
        SecTransport(USER_AGENT)(forged)
    assert created == []


def test_socket_error_is_sanitized_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def broken(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise OSError("PRIVATE-CREDENTIAL-AND-CONTACT")

    monkeypatch.setattr("alphasense.sec_transport.http.client.HTTPSConnection", broken)
    with pytest.raises(SecTransportError, match="^SEC_NETWORK_UNAVAILABLE$") as error:
        SecTransport(USER_AGENT)(SecFetchRequest(cik="0000320193", resource="submissions"))
    assert "PRIVATE" not in repr(error.value) and calls == 1
