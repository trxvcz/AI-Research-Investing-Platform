"""V2 paid admission and audit tested entirely offline on frozen synthetic evidence."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_ai_history_context import context_fixture, narrative

import alphasense.ai_history_analysis as engine
from alphasense.ai_analysis import AiAnalysisDenied
from alphasense.gemini_transport import GeminiTransportError


def activation_v2(tmp_path, monkeypatch):
    key = "synthetic-not-a-real-gemini-key"
    monkeypatch.setenv("GEMINI_API_KEY", key)
    monkeypatch.delenv("ALPHASENSE_AI_ENV_FILE", raising=False)
    now = datetime.now(UTC)
    value = {
        "model_id": engine.MODEL_ID,
        "prompt_version": engine.PROMPT_VERSION,
        "synthesis_sha256": engine.history_synthesis_signature(),
        "billing": "paid_owner_confirmed",
        "budget_total_pln": "50.00",
        "budget_renewal": False,
        "paid_fallback": False,
        "credential_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "input_usd_per_million": "0.25",
        "output_usd_per_million": "1.50",
        "pricing_sha256": "a" * 64,
        "terms_sha256": "b" * 64,
        "reviewed_at": now.isoformat(),
        "review_expires_at": (now + timedelta(hours=1)).isoformat(),
        "enabled": True,
        "quality_pass": True,
    }
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("ALPHASENSE_AI_SETTINGS_FILE", str(path))
    return path, value


def test_v2_activation_distinct_from_legacy_and_key_bound(tmp_path, monkeypatch):
    path, value = activation_v2(tmp_path, monkeypatch)
    engine.check_history_activation()
    for name, invalid in [
        ("prompt_version", "report-synthesis-v1"),
        ("synthesis_sha256", "0" * 64),
        ("credential_sha256", "0" * 64),
        ("budget_total_pln", "51.00"),
        ("budget_renewal", True),
        ("quality_pass", False),
        ("paid_fallback", True),
    ]:
        path.write_text(json.dumps({**value, name: invalid}))
        with pytest.raises(AiAnalysisDenied, match="AI_NOT_CONFIGURED"):
            engine.check_history_activation()


def test_unqualified_review_only_allows_developer_measurement(tmp_path, monkeypatch):
    path, value = activation_v2(tmp_path, monkeypatch)
    path.write_text(json.dumps({**value, "enabled": False, "quality_pass": False}))
    engine.check_history_activation(qualification=True)
    with pytest.raises(AiAnalysisDenied):
        engine.check_history_activation()


def test_payload_has_frozen_history_and_schema_without_raw_documents():
    report, _, context = context_fixture()
    payload = engine.build_history_request(report, context, qualification=True)
    user = json.loads(payload["messages"][1]["content"])
    assert user["context_sha256"] == context.context_sha256
    assert len(user["evidence"]) == 5 and any(e["kind"] == "comparison" for e in user["evidence"])
    assert "context_sha256" in user and "source" not in user["evidence"][0]
    assert "report_observation_index" not in user["evidence"][0]
    assert "gold" not in user and "raw_document" not in user
    assert "long_term_debt_current" in payload["messages"][0]["content"]


def test_request_limit_before_transport(monkeypatch):
    report, _, context = context_fixture()
    monkeypatch.setattr(engine, "MAX_REQUEST_BYTES", 1)
    with pytest.raises(AiAnalysisDenied, match="AI_INPUT_TOO_LARGE"):
        engine.build_history_request(report, context)


def test_transport_failure_has_frozen_hash_audit_and_no_retry(monkeypatch):
    report, _, context = context_fixture()
    payload = engine.build_history_request(report, context)
    calls = []

    def fail(self, body):
        calls.append(body)
        raise GeminiTransportError("GEMINI_HTTP_429")

    monkeypatch.setattr(engine.GeminiTransport, "generate_with_receipt", fail)
    with pytest.raises(AiAnalysisDenied, match="GEMINI_HTTP_429") as raised:
        engine.generate_history_analysis(report, context, payload)
    assert calls == [payload]
    audit = raised.value.audit
    assert audit["context_sha256"] == context.context_sha256 and audit["request"] == payload
    assert audit["usage"] is None and audit["raw_response"] is None
    assert audit["finished_at"] >= audit["started_at"]


@pytest.mark.parametrize("direction,valid", [("increase", True), ("decrease", False)])
def test_response_semantics_checked_and_raw_audited(monkeypatch, direction, valid):
    report, _, context = context_fixture()
    payload = engine.build_history_request(report, context)
    draft = json.dumps(narrative(direction=direction))
    raw = json.dumps(
        {"usageMetadata": {"promptTokenCount": 10}, "modelVersion": "synthetic"}
    ).encode()
    monkeypatch.setattr(
        engine.GeminiTransport,
        "generate_with_receipt",
        lambda *a: SimpleNamespace(draft=draft, raw_response=raw),
    )
    if valid:
        result, audit = engine.generate_history_analysis(report, context, payload)
        assert result.summary[0].direction == "increase"
        assert audit["response_sha256"] == hashlib.sha256(raw).hexdigest()
    else:
        with pytest.raises(AiAnalysisDenied, match="AI_RESPONSE_INVALID") as raised:
            engine.generate_history_analysis(report, context, payload)
        assert raised.value.audit["raw_response"] == raw.decode()


def test_changed_payload_never_reaches_transport(monkeypatch):
    report, _, context = context_fixture()
    monkeypatch.setattr(
        engine.GeminiTransport,
        "generate_with_receipt",
        lambda *a: pytest.fail("Unexpected paid call"),
    )
    with pytest.raises(AiAnalysisDenied, match="AI_REQUEST_MISMATCH"):
        engine.generate_history_analysis(report, context, {"messages": []})
