"""Bounded draft-only Groq transport; admission and durable quota belong to gateway.

This module is not an activation or proof that an account/model is free. Register
it only behind FreeOnlyGateway after server-owned account and data-policy review.
"""

import http.client
import json
import math
import os
import re
import ssl
from typing import Any

MAX_REQUEST_BYTES = 3 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024


class GroqTransportError(Exception):
    """Stable failure code without response text, document, key or request headers."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("Non-finite JSON value")


def _headers(response: http.client.HTTPResponse) -> dict[str, str]:
    result: dict[str, str] = {}
    protected = {"content-length", "content-type", "content-encoding", "transfer-encoding"}
    for name, value in response.getheaders():
        key = name.lower()
        if key in protected and key in result:
            raise GroqTransportError("GROQ_RESPONSE_HEADERS")
        result[key] = value
    return result


class GroqTransport:
    """One HTTPS call, explicit server model, no tools/fallback/redirects/retries."""

    def __init__(
        self, model_id: str, *, timeout: float = 30, max_completion_tokens: int = 4096
    ) -> None:
        if not isinstance(model_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9/._-]{0,127}", model_id
        ):
            raise GroqTransportError("GROQ_MODEL_CONFIGURATION")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 1 <= timeout <= 60
            or type(max_completion_tokens) is not int
            or not 128 <= max_completion_tokens <= 8192
        ):
            raise GroqTransportError("GROQ_LIMIT_CONFIGURATION")
        self._model = model_id
        self._timeout = float(timeout)
        self._tokens = max_completion_tokens

    def __call__(self, payload: object) -> str:
        if not isinstance(payload, dict) or set(payload) != {"messages"}:
            raise GroqTransportError("GROQ_REQUEST_INVALID")
        messages = payload["messages"]
        if not isinstance(messages, list) or len(messages) != 2:
            raise GroqTransportError("GROQ_REQUEST_INVALID")
        for message, role in zip(messages, ("system", "user"), strict=True):
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] != role
                or not isinstance(message["content"], str)
                or not message["content"]
            ):
                raise GroqTransportError("GROQ_REQUEST_INVALID")
        try:
            body = json.dumps(
                {
                    "model": self._model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "stream": False,
                    "max_completion_tokens": self._tokens,
                },
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (ValueError, TypeError, UnicodeError):
            raise GroqTransportError("GROQ_REQUEST_INVALID") from None
        if len(body) > MAX_REQUEST_BYTES:
            raise GroqTransportError("GROQ_REQUEST_TOO_LARGE")
        key = os.environ.get("GROQ_API_KEY", "")
        if not re.fullmatch(r"[!-~]{16,512}", key):
            raise GroqTransportError("GROQ_API_KEY_MISSING_OR_INVALID")
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection(
                "api.groq.com", timeout=self._timeout, context=ssl.create_default_context()
            )
            connection.request(
                "POST",
                "/openai/v1/chat/completions",
                body=body,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                code = (
                    response.status
                    if type(response.status) is int and 100 <= response.status <= 599
                    else "FAILURE"
                )
                raise GroqTransportError(f"GROQ_HTTP_{code}")
            headers = _headers(response)
            if (
                headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise GroqTransportError("GROQ_RESPONSE_TYPE")
            if headers.get("content-encoding", "identity").strip().lower() != "identity":
                raise GroqTransportError("GROQ_RESPONSE_ENCODING")
            transfer = headers.get("transfer-encoding", "").strip().lower()
            length = headers.get("content-length")
            declared = None
            if transfer not in {"", "chunked"} or (transfer and length is not None):
                raise GroqTransportError("GROQ_RESPONSE_HEADERS")
            if length is not None:
                if not re.fullmatch(r"[0-9]{1,10}", length):
                    raise GroqTransportError("GROQ_RESPONSE_HEADERS")
                declared = int(length)
                if declared > MAX_RESPONSE_BYTES:
                    raise GroqTransportError("GROQ_RESPONSE_TOO_LARGE")
            raw = bytearray()
            while True:
                chunk = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise GroqTransportError("GROQ_RESPONSE_TOO_LARGE")
            if not raw or (declared is not None and declared != len(raw)):
                raise GroqTransportError("GROQ_RESPONSE_LENGTH")
            result = json.loads(
                bytes(raw).decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant
            )
            if not isinstance(result, dict) or result.get("model") != self._model:
                raise GroqTransportError("GROQ_RESPONSE_IDENTITY")
            choices = result.get("choices")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choices[0], dict)
            ):
                raise GroqTransportError("GROQ_RESPONSE_SCHEMA")
            choice = choices[0]
            message = choice.get("message")
            if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
                raise GroqTransportError("GROQ_RESPONSE_INCOMPLETE")
            if (
                message.get("role") != "assistant"
                or message.get("tool_calls")
                or message.get("function_call")
                or message.get("refusal")
            ):
                raise GroqTransportError("GROQ_RESPONSE_UNSUPPORTED")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise GroqTransportError("GROQ_RESPONSE_SCHEMA")
            return content
        except GroqTransportError:
            raise
        except (OSError, http.client.HTTPException):
            raise GroqTransportError("GROQ_NETWORK_UNAVAILABLE") from None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise GroqTransportError("GROQ_RESPONSE_SCHEMA") from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except (OSError, http.client.HTTPException):
                    pass
