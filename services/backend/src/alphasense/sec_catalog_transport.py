"""Fixed public SEC catalog GET; admission, quota and pacing belong to caller."""

import http.client
import re
import ssl
from datetime import UTC, datetime

from alphasense.sec_transport import SecResponse, SecTransportError, _headers, _user_agent

CATALOG_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
MAX_CATALOG_BYTES = 4 * 1024 * 1024


def fetch_catalog(user_agent: str) -> SecResponse:
    """Fetch one fixed resource, without redirects, cookies, proxy or retry."""
    user_agent = _user_agent(user_agent)
    connection: http.client.HTTPSConnection | None = None
    try:
        # HTTPSConnection does not consult environment proxies and performs no redirects.
        connection = http.client.HTTPSConnection(
            "www.sec.gov", timeout=15, context=ssl.create_default_context()
        )
        connection.request(
            "GET",
            "/files/company_tickers_exchange.json",
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            status = response.status
            if type(status) is not int or not 100 <= status <= 599:
                raise SecTransportError("SEC_HTTP_FAILURE")
            raise SecTransportError(f"SEC_HTTP_{status}")
        headers = _headers(response)
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != ("application/json"):
            raise SecTransportError("SEC_RESPONSE_TYPE")
        if headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise SecTransportError("SEC_RESPONSE_ENCODING")
        transfer = headers.get("transfer-encoding", "").strip().lower()
        if transfer not in ("", "chunked"):
            raise SecTransportError("SEC_RESPONSE_ENCODING")
        length = headers.get("content-length")
        declared: int | None = None
        if length is not None:
            if transfer or not re.fullmatch(r"[0-9]{1,10}", length):
                raise SecTransportError("SEC_RESPONSE_HEADERS")
            declared = int(length)
            if declared > MAX_CATALOG_BYTES:
                raise SecTransportError("SEC_RESPONSE_TOO_LARGE")
        content = bytearray()
        while True:
            chunk = response.read(min(65536, MAX_CATALOG_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_CATALOG_BYTES:
                raise SecTransportError("SEC_RESPONSE_TOO_LARGE")
        if not content or (declared is not None and declared != len(content)):
            raise SecTransportError("SEC_RESPONSE_LENGTH")
        return SecResponse(url=CATALOG_URL, content=bytes(content), retrieved_at=datetime.now(UTC))
    except SecTransportError:
        raise
    except (OSError, http.client.HTTPException, ValueError):
        raise SecTransportError("SEC_NETWORK_UNAVAILABLE") from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except (OSError, http.client.HTTPException):
                pass
