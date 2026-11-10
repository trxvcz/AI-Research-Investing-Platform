"""Single bounded SEC GET. Admission, quota and cross-process pacing belong to caller."""

import http.client
import math
import re
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import ValidationError

from alphasense.sec_contracts import SecFetchRequest, sec_url
from alphasense.snapshot_contracts import MAX_BYTES


class SecTransportError(Exception):
    """Stable failure code; never includes source body, contact or request headers."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SecResponse:
    url: str
    content: bytes
    retrieved_at: datetime


def _user_agent(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 8 <= len(value) <= 256
        or value != value.strip()
        or any(not 32 <= ord(char) <= 126 for char in value)
        or not re.search(r"[A-Za-z]", value.split()[0])
        or not re.search(r"\S+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:\s|$)", value)
        or len(value.split()) < 2
    ):
        raise SecTransportError("SEC_USER_AGENT_INVALID")
    return value


def _headers(response: http.client.HTTPResponse) -> dict[str, str]:
    result: dict[str, str] = {}
    protected = {"content-length", "content-type", "content-encoding", "transfer-encoding"}
    for name, value in response.getheaders():
        key = name.lower()
        if key in protected and key in result:
            raise SecTransportError("SEC_RESPONSE_HEADERS")
        result[key] = value
    return result


class SecTransport:
    def __init__(self, user_agent: str, *, timeout: float = 15) -> None:
        self._user_agent = _user_agent(user_agent)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 1 <= timeout <= 30
        ):
            raise SecTransportError("SEC_TIMEOUT_INVALID")
        self._timeout = float(timeout)

    def __call__(self, request: object) -> SecResponse:
        if not isinstance(request, SecFetchRequest):
            raise SecTransportError("SEC_REQUEST_INVALID")
        try:
            checked = SecFetchRequest.model_validate(
                request.model_dump(mode="python", warnings=False)
            )
            url = sec_url(checked)
        except (ValidationError, ValueError, TypeError):
            raise SecTransportError("SEC_REQUEST_INVALID") from None
        parsed = urlsplit(url)
        connection: http.client.HTTPSConnection | None = None
        try:
            # HTTPSConnection does not consult environment proxies and performs no redirects.
            connection = http.client.HTTPSConnection(
                "data.sec.gov", timeout=self._timeout, context=ssl.create_default_context()
            )
            connection.request(
                "GET",
                parsed.path,
                headers={
                    "User-Agent": self._user_agent,
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
            if headers.get("content-type", "").split(";", 1)[0].strip().lower() != (
                "application/json"
            ):
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
                if declared > MAX_BYTES:
                    raise SecTransportError("SEC_RESPONSE_TOO_LARGE")
            content = bytearray()
            while True:
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise SecTransportError("SEC_RESPONSE_TOO_LARGE")
            if not content or (declared is not None and declared != len(content)):
                raise SecTransportError("SEC_RESPONSE_LENGTH")
            return SecResponse(url=url, content=bytes(content), retrieved_at=datetime.now(UTC))
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
