"""Company-neutral model adapters are tested with synthetic HTTPS, never API keys."""

import json

import pytest
from test_sec_transport import FakeResponse, mocked_connection

from alphasense.gemini_transport import GeminiTransport, GeminiTransportError
from alphasense.groq_transport import GroqTransport, GroqTransportError

PAYLOAD = {
    "messages": [
        {"role": "system", "content": "Return JSON draft only."},
        {"role": "user", "content": '{"blocks":[]}'},
    ]
}
KEY = "synthetic-key-not-a-real-credential"


def envelope(provider: str) -> bytes:
    if provider == "gemini":
        value = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"role": "model", "parts": [{"text": '{"facts":[]}'}]},
                }
            ]
        }
    else:
        value = {
            "model": "synthetic-model",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": '{"facts":[]}'},
                }
            ],
        }
    return json.dumps(value).encode()


def adapter(provider: str):
    return (
        GeminiTransport("synthetic-model")
        if provider == "gemini"
        else GroqTransport("synthetic-model")
    )


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_fixed_tls_endpoint_and_bounded_draft_without_tools(monkeypatch, provider):
    monkeypatch.setenv(provider.upper() + "_API_KEY", KEY)
    response = FakeResponse(envelope(provider))
    connection, created = mocked_connection(monkeypatch, response)
    assert adapter(provider)(PAYLOAD) == '{"facts":[]}'
    expected = "generativelanguage.googleapis.com" if provider == "gemini" else "api.groq.com"
    assert created[0][0] == (expected,)
    assert created[0][1]["context"].check_hostname
    args, kwargs = connection.requests[0]
    assert args[0] == "POST" and "?" not in args[1] and KEY not in args[1]
    body = json.loads(kwargs["body"])
    assert KEY not in kwargs["body"].decode()
    assert "tools" not in body and "cachedContent" not in body
    if provider == "gemini":
        assert args[1] == "/v1beta/models/synthetic-model:generateContent"
        assert kwargs["headers"]["x-goog-api-key"] == KEY
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["contents"][0]["parts"][0]["text"] == PAYLOAD["messages"][1]["content"]
    else:
        assert args[1] == "/openai/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer " + KEY
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream"] is False
    assert connection.closed and len(connection.requests) == 1


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize("status", [301, 307, 401, 403, 429, 500])
def test_no_follow_or_retry_and_error_body_never_leaks(monkeypatch, provider, status):
    monkeypatch.setenv(provider.upper() + "_API_KEY", KEY)
    response = FakeResponse(
        b"private-document-SECRET", status, [("Location", "https://evil.invalid")]
    )
    connection, created = mocked_connection(monkeypatch, response)
    error = GeminiTransportError if provider == "gemini" else GroqTransportError
    with pytest.raises(error, match=f"^{provider.upper()}_HTTP_{status}$"):
        adapter(provider)(PAYLOAD)
    assert response.reads == [] and connection.closed and len(created) == 1


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"messages": [], "tools": []},
        {"messages": [{"role": "user", "content": "x"}, {"role": "system", "content": "y"}]},
    ],
)
def test_invalid_client_controls_never_open_connection(monkeypatch, provider, payload):
    _, created = mocked_connection(monkeypatch, FakeResponse())
    with pytest.raises((GeminiTransportError, GroqTransportError), match="REQUEST_INVALID"):
        adapter(provider)(payload)
    assert created == []


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_key_must_be_env_and_never_in_error(monkeypatch, provider):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _, created = mocked_connection(monkeypatch, FakeResponse())
    with pytest.raises((GeminiTransportError, GroqTransportError), match="KEY_MISSING_OR_INVALID"):
        adapter(provider)(PAYLOAD)
    monkeypatch.setenv(provider.upper() + "_API_KEY", "secret\r\ninjected")
    with pytest.raises((GeminiTransportError, GroqTransportError)) as error:
        adapter(provider)(PAYLOAD)
    assert "secret" not in str(error.value) and created == []


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize(
    "headers",
    [
        [("Content-Type", "text/html")],
        [("Content-Type", "application/json"), ("Content-Encoding", "gzip")],
        [("Content-Type", "application/json"), ("Content-Length", "9999999")],
        [("Content-Type", "application/json"), ("Content-Length", "1"), ("content-length", "1")],
        [
            ("Content-Type", "application/json"),
            ("Content-Length", "1"),
            ("Transfer-Encoding", "chunked"),
        ],
    ],
)
def test_unsafe_headers_are_rejected_before_read(monkeypatch, provider, headers):
    monkeypatch.setenv(provider.upper() + "_API_KEY", KEY)
    response = FakeResponse(envelope(provider), headers=headers)
    mocked_connection(monkeypatch, response)
    with pytest.raises((GeminiTransportError, GroqTransportError)):
        adapter(provider)(PAYLOAD)
    assert response.reads == []


@pytest.mark.parametrize("provider", ["gemini", "groq"])
@pytest.mark.parametrize(
    "raw", [b'{"candidates":[],"candidates":[]}', b'{"x":NaN}', b"[]", b"bad", b"\xff"]
)
def test_malformed_json_is_redacted(monkeypatch, provider, raw):
    monkeypatch.setenv(provider.upper() + "_API_KEY", KEY)
    mocked_connection(monkeypatch, FakeResponse(raw))
    with pytest.raises(
        (GeminiTransportError, GroqTransportError), match="RESPONSE_(SCHEMA|IDENTITY)"
    ):
        adapter(provider)(PAYLOAD)


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_truncation_and_tool_calls_are_not_drafts(monkeypatch, provider):
    monkeypatch.setenv(provider.upper() + "_API_KEY", KEY)
    data = json.loads(envelope(provider))
    if provider == "gemini":
        data["candidates"][0]["finishReason"] = "MAX_TOKENS"
    else:
        data["choices"][0]["finish_reason"] = "length"
    mocked_connection(monkeypatch, FakeResponse(json.dumps(data).encode()))
    with pytest.raises((GeminiTransportError, GroqTransportError), match="RESPONSE_INCOMPLETE"):
        adapter(provider)(PAYLOAD)
    data = json.loads(envelope(provider))
    if provider == "gemini":
        data["candidates"][0]["content"]["parts"] = [{"functionCall": {"name": "execute"}}]
    else:
        data["choices"][0]["message"]["tool_calls"] = [{"type": "function"}]
    mocked_connection(monkeypatch, FakeResponse(json.dumps(data).encode()))
    with pytest.raises((GeminiTransportError, GroqTransportError), match="RESPONSE_UNSUPPORTED"):
        adapter(provider)(PAYLOAD)


def test_gemini_google_env_alias_keeps_key_in_header(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", KEY)
    connection, _ = mocked_connection(monkeypatch, FakeResponse(envelope("gemini")))
    assert GeminiTransport("synthetic-model")(PAYLOAD) == '{"facts":[]}'
    assert connection.requests[0][1]["headers"]["x-goog-api-key"] == KEY


@pytest.mark.parametrize("signature", ["opaque-signature", "", "x" * 65536])
def test_gemini_discards_bounded_thought_signature(monkeypatch, signature):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    data = json.loads(envelope("gemini"))
    data["candidates"][0]["content"]["parts"][0]["thoughtSignature"] = signature
    connection, _ = mocked_connection(monkeypatch, FakeResponse(json.dumps(data).encode()))
    assert GeminiTransport("synthetic-model")(PAYLOAD) == '{"facts":[]}'
    assert len(connection.requests) == 1 and connection.closed


@pytest.mark.parametrize(
    "part",
    [
        {"text": "{}", "thoughtSignature": None},
        {"text": "{}", "thoughtSignature": 1},
        {"text": "{}", "thoughtSignature": "x" * 65537},
        {"thoughtSignature": "opaque"},
        {"text": "{}", "thought": True},
        {"text": "{}", "functionCall": {"name": "execute"}},
        {"text": "{}", "inlineData": {"data": "AA=="}},
        {"text": "{}", "unknown": "extra"},
    ],
)
def test_gemini_signature_does_not_allow_other_response_controls(monkeypatch, part):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    data = json.loads(envelope("gemini"))
    data["candidates"][0]["content"]["parts"] = [part]
    mocked_connection(monkeypatch, FakeResponse(json.dumps(data).encode()))
    with pytest.raises(GeminiTransportError, match="RESPONSE_UNSUPPORTED"):
        GeminiTransport("synthetic-model")(PAYLOAD)
