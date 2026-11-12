"""Catalog transport tests use synthetic HTTPS responses only."""

import pytest
from test_sec_transport import USER_AGENT, FakeResponse, mocked_connection

from alphasense.sec_catalog_transport import CATALOG_URL, MAX_CATALOG_BYTES, fetch_catalog
from alphasense.sec_transport import SecTransportError


def test_catalog_uses_only_fixed_host_path_and_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = b'{"fields":[],"data":[]}\n'
    connection, created = mocked_connection(monkeypatch, FakeResponse(raw))
    result = fetch_catalog(USER_AGENT)
    assert result.content == raw and result.url == CATALOG_URL
    assert created[0][0] == ("www.sec.gov",)
    assert created[0][1]["timeout"] == 15
    assert created[0][1]["context"].check_hostname
    args, kwargs = connection.requests[0]
    assert args == ("GET", "/files/company_tickers_exchange.json")
    assert kwargs["headers"]["User-Agent"] == USER_AGENT
    assert kwargs["headers"]["Accept-Encoding"] == "identity"
    assert connection.closed and len(created) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308, 403, 429, 503])
def test_catalog_errors_never_follow_or_retry(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    response = FakeResponse(b"PRIVATE", status, [("Location", "https://attacker.invalid/")])
    connection, created = mocked_connection(monkeypatch, response)
    with pytest.raises(SecTransportError, match=f"^SEC_HTTP_{status}$"):
        fetch_catalog(USER_AGENT)
    assert connection.closed and len(created) == 1 and response.reads == []


@pytest.mark.parametrize(
    "headers,code",
    [
        ([("Content-Type", "text/html")], "SEC_RESPONSE_TYPE"),
        (
            [("Content-Type", "application/json"), ("Content-Encoding", "gzip")],
            "SEC_RESPONSE_ENCODING",
        ),
        (
            [("Content-Type", "application/json"), ("Content-Length", str(MAX_CATALOG_BYTES + 1))],
            "SEC_RESPONSE_TOO_LARGE",
        ),
        (
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("content-length", "2"),
            ],
            "SEC_RESPONSE_HEADERS",
        ),
    ],
)
def test_catalog_checks_headers_before_read(
    monkeypatch: pytest.MonkeyPatch, headers: list[tuple[str, str]], code: str
) -> None:
    response = FakeResponse(headers=headers)
    mocked_connection(monkeypatch, response)
    with pytest.raises(SecTransportError, match=f"^{code}$"):
        fetch_catalog(USER_AGENT)
    assert response.reads == []


@pytest.mark.parametrize(
    "raw,headers,code",
    [
        (b"", [("Content-Type", "application/json")], "SEC_RESPONSE_LENGTH"),
        (
            b"{}",
            [("Content-Type", "application/json"), ("Content-Length", "3")],
            "SEC_RESPONSE_LENGTH",
        ),
        (
            b"x" * (MAX_CATALOG_BYTES + 1),
            [("Content-Type", "application/json")],
            "SEC_RESPONSE_TOO_LARGE",
        ),
    ],
)
def test_catalog_bounds_actual_body(
    monkeypatch: pytest.MonkeyPatch, raw: bytes, headers: list[tuple[str, str]], code: str
) -> None:
    connection, _ = mocked_connection(monkeypatch, FakeResponse(raw, headers=headers))
    with pytest.raises(SecTransportError, match=f"^{code}$"):
        fetch_catalog(USER_AGENT)
    assert connection.closed


def test_invalid_contact_rejected_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _, created = mocked_connection(monkeypatch, FakeResponse())
    with pytest.raises(SecTransportError, match="SEC_USER_AGENT_INVALID"):
        fetch_catalog("bad")
    assert created == []
