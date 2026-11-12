"""Synthetic synthesis checks without provider network or paid credentials."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alphasense.ai_analysis import (
    AiAnalysisDenied,
    build_analysis_request,
    check_activation,
    generate_analysis,
    parse_analysis,
    synthesis_signature,
)
from alphasense.gemini_transport import GeminiTransportError
from alphasense.report_contracts import ReportRevision


def report():
    return ReportRevision.model_validate_json(
        (Path(__file__).parent / "fixtures/report.synthetic.json").read_bytes()
    )


def narrative():
    return {
        "summary": [
            {
                "text": "Dostępne dane pozwalają na ograniczoną ocenę finansów.",
                "observation_indexes": [0],
            }
        ],
        "strengths": [],
        "risks": [],
        "questions": [],
        "limitations": ["Brak pełnego kontekstu działalności i notowań."],
    }


def test_prompt_grounded_polish_schema_without_raw_documents_or_gold():
    payload = build_analysis_request(report(), qualification=True)
    user = json.loads(payload["messages"][1]["content"])
    assert set(user) == {
        "as_of",
        "available_observations",
        "missing_metrics",
        "report_status",
        "output_schema",
    }
    assert "niezaufane dane" in payload["messages"][0]["content"]
    assert user["available_observations"][0]["value"] == report().input.observations[0].value
    assert user["available_observations"][0]["observation_index"] == 0
    assert user["missing_metrics"] == ["net_margin"]
    with pytest.raises(AiAnalysisDenied, match="AI_PUBLIC_SEC_DATA_REQUIRED"):
        build_analysis_request(report())


def test_valid_narrative_preserves_evidence():
    result = parse_analysis(report(), json.dumps(narrative()))
    assert result.summary[0].observation_indexes == [0]


@pytest.mark.parametrize(
    "text",
    ["Zysk to 999.", "Kup akcje.", "<script>alert()</script>", "Źródło https://evil.invalid"],
)
def test_invalid_new_numbers_orders_html_links_rejected(text):
    value = narrative()
    value["summary"][0]["text"] = text
    with pytest.raises(AiAnalysisDenied, match="AI_RESPONSE_INVALID"):
        parse_analysis(report(), json.dumps(value))


@pytest.mark.parametrize("indexes", [[999], [-1], [0, 0], [True], []])
def test_invalid_evidence_rejected(indexes):
    value = narrative()
    value["summary"][0]["observation_indexes"] = indexes
    with pytest.raises(AiAnalysisDenied, match="AI_RESPONSE_INVALID"):
        parse_analysis(report(), json.dumps(value))


def test_duplicate_keys_extra_fields_and_nan_rejected():
    for raw in [
        '{"summary":[],"summary":[]}',
        '{"x":NaN}',
        json.dumps(dict(narrative(), tools=[])),
    ]:
        with pytest.raises(AiAnalysisDenied, match="AI_RESPONSE_INVALID"):
            parse_analysis(report(), raw)


def activation(tmp_path, monkeypatch):
    key = "synthetic-not-a-real-gemini-key"
    monkeypatch.setenv("GEMINI_API_KEY", key)
    monkeypatch.delenv("ALPHASENSE_AI_ENV_FILE", raising=False)
    now = datetime.now(UTC)
    value = {
        "model_id": "gemini-3.1-flash-lite",
        "billing": "paid_owner_confirmed",
        "budget_total_pln": "50.00",
        "budget_renewal": False,
        "prompt_version": "report-synthesis-v1",
        "synthesis_sha256": synthesis_signature(),
        "credential_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "paid_fallback": False,
        "input_usd_per_million": "0.25",
        "output_usd_per_million": "1.50",
        "reviewed_at": now.isoformat(),
        "review_expires_at": (now + timedelta(hours=1)).isoformat(),
        "pricing_sha256": "a" * 64,
        "terms_sha256": "b" * 64,
        "enabled": True,
        "quality_pass": True,
    }
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("ALPHASENSE_AI_SETTINGS_FILE", str(path))
    return path, value


def test_paid_activation_requires_explicit_fresh_matching_review(tmp_path, monkeypatch):
    path, value = activation(tmp_path, monkeypatch)
    check_activation()
    for field, invalid in [
        ("billing", "free"),
        ("budget_total_pln", "500"),
        ("budget_renewal", True),
        ("paid_fallback", True),
        ("quality_pass", False),
        ("enabled", False),
        ("credential_sha256", "0" * 64),
        ("input_usd_per_million", "0.1"),
        ("review_expires_at", "2020-01-01T00:00:00+00:00"),
    ]:
        changed = deepcopy(value)
        changed[field] = invalid
        path.write_text(json.dumps(changed))
        with pytest.raises(AiAnalysisDenied, match="AI_NOT_CONFIGURED"):
            check_activation()


def test_developer_qualification_cannot_activate_production(tmp_path, monkeypatch):
    path, value = activation(tmp_path, monkeypatch)
    value.update(enabled=False, quality_pass=False)
    path.write_text(json.dumps(value))
    check_activation(qualification=True)
    with pytest.raises(AiAnalysisDenied):
        check_activation()


def test_missing_settings_refuses_without_key_disclosure(monkeypatch):
    monkeypatch.delenv("ALPHASENSE_AI_SETTINGS_FILE", raising=False)
    monkeypatch.delenv("ALPHASENSE_AI_ENV_FILE", raising=False)
    with pytest.raises(AiAnalysisDenied, match="^AI_NOT_CONFIGURED$"):
        check_activation()


def test_transport_failure_preserves_prompt_audit_without_retry(monkeypatch):
    calls = []

    def fail(self, payload):
        calls.append(payload)
        raise GeminiTransportError("GEMINI_HTTP_429")

    monkeypatch.setattr("alphasense.ai_analysis.GeminiTransport.generate_with_receipt", fail)
    payload = build_analysis_request(report(), qualification=True)
    with pytest.raises(AiAnalysisDenied, match="GEMINI_HTTP_429") as raised:
        generate_analysis(report(), payload)
    assert calls == [payload]
    audit = raised.value.audit
    assert audit["request"] == payload and audit["usage"] is None
    assert audit["raw_response"] is None and audit["finished_at"] >= audit["started_at"]
    assert audit["error_code"] == "GEMINI_HTTP_429"
