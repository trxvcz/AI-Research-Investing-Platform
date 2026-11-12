"""Paid mutations require origin and exact idempotent report identity."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_ai_analysis import narrative, report
from test_ai_history_analysis import activation_v2

import alphasense.ai_analysis_api as module
from alphasense.ai_analysis_contracts import AiAnalysisRecord
from alphasense.ai_history_context import build_history_context
from alphasense.ai_history_contracts import AiHistoryNarrative
from alphasense.api import app
from alphasense.db import get_store
from alphasense.financial_history import FinancialHistory
from alphasense.report_contracts import ReportContent, seal_report


@pytest.fixture
def setup_api(monkeypatch):
    content = report().model_dump(mode="python", exclude={"checksum", "input_sha256"})
    content["input"]["data_origin"] = "live"
    content["sources"][0]["url"] = "https://www.sec.gov/Archives/synthetic"
    source = seal_report(ReportContent.model_validate(content))
    records = {}
    calls = []

    def reserve(request_id, current, model_id, **kwargs):
        calls.append("reserve")
        if request_id in records:
            return False
        records[request_id] = AiAnalysisRecord(
            request_id=request_id,
            report_id=current.report_id,
            revision=current.revision,
            report_checksum=current.checksum,
            status="running",
            created_at=datetime.now(UTC),
            finished_at=None,
            model_id=model_id,
            analysis=None,
            error_code=None,
            prompt_version=kwargs.get("prompt_version", "report-synthesis-v1"),
            evidence_context=kwargs.get("evidence_context"),
        )
        return True

    def finish(request_id, analysis, error_code, audit):
        records[request_id] = AiAnalysisRecord.model_validate(
            {
                **records[request_id].model_dump(mode="python"),
                "analysis": analysis,
                "error_code": error_code,
                "status": "completed" if analysis else "failed",
                "finished_at": datetime.now(UTC),
            }
        )
        return records[request_id]

    store = SimpleNamespace(
        get=records.get,
        reserve=reserve,
        finish=finish,
        list=lambda report_id, revision: list(records.values()),
        budget=lambda: {
            "budget_pln": "50.00",
            "reserved_pln": "0.00",
            "remaining_pln": "50.00",
            "reservation_per_attempt_pln": "1.00",
        },
    )
    app.dependency_overrides[get_store] = lambda: SimpleNamespace(get_report=lambda *args: source)
    app.dependency_overrides[module.get_ai_store] = lambda: store
    monkeypatch.setattr(module, "check_activation", lambda: None)

    def context(current, *args):
        return build_history_context(
            current,
            FinancialHistory(
                report_id=current.report_id,
                revision=current.revision,
                report_checksum=current.checksum,
                as_of=current.input.as_of,
                series=[],
                limitations=["No comparative data in this synthetic API test."],
            ),
        )

    monkeypatch.setattr(module, "prepare_history_context", context)

    def generate(current, frozen, payload):
        calls.append("provider")
        value = narrative()
        value["summary"] = [
            {
                "kind": "state",
                "text": "Dane są ograniczone.",
                "evidence_indexes": [0],
                "direction": None,
            }
        ]
        return AiHistoryNarrative.model_validate(value), {"usage": None}

    # No actual transport or credentials; count explicit provider invocation only.
    monkeypatch.setattr(module, "generate_analysis", generate)
    try:
        with TestClient(app) as client:
            yield client, source, calls, records
    finally:
        app.dependency_overrides.clear()


HEADERS = {
    "Origin": "http://testserver",
    "Content-Type": "application/json",
    "X-AlphaSense-Panel": "1",
}


def test_health_reports_explicit_paid_activation_without_calling_provider(tmp_path, monkeypatch):
    activation_v2(tmp_path, monkeypatch)
    monkeypatch.delenv("ALPHASENSE_DATABASE_URL", raising=False)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["external_providers_enabled"] is True


def test_no_origin_never_reserves_or_calls_provider(setup_api):
    client, source, calls, _ = setup_api
    result = client.post(
        "/v1/panel/ai-analyses",
        json={"request_id": str(uuid4()), "report_id": str(source.report_id), "revision": 1},
    )
    assert result.status_code == 403 and calls == []


def test_duplicate_post_returns_saved_record_without_new_charge(setup_api):
    client, source, calls, _ = setup_api
    # Trusted private host scope permits testserver, analogous to existing private boundary.
    # Use actual loopback request authority so no verification override is needed.
    client.base_url = "http://127.0.0.1"
    headers = {**HEADERS, "Origin": "http://127.0.0.1"}
    payload = {"request_id": str(uuid4()), "report_id": str(source.report_id), "revision": 1}
    first = client.post("/v1/panel/ai-analyses", json=payload, headers=headers)
    second = client.post("/v1/panel/ai-analyses", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and calls == ["reserve", "provider"]
    assert "audit" not in first.json() and "request" not in first.json()


def test_body_limit_precedes_json_parsing(setup_api):
    client, _, calls, _ = setup_api
    result = client.post("/v1/panel/ai-analyses", content=b"x" * 4097, headers=HEADERS)
    assert result.status_code == 413 and calls == []


def test_legacy_saved_request_needs_no_activation_or_new_reservation(setup_api, monkeypatch):
    client, source, calls, records = setup_api
    request_id = uuid4()
    now = datetime.now(UTC)
    saved = AiAnalysisRecord(
        request_id=request_id,
        report_id=source.report_id,
        revision=source.revision,
        report_checksum=source.checksum,
        status="completed",
        created_at=now,
        finished_at=now,
        model_id="synthetic-model",
        analysis=narrative(),
        error_code=None,
    )
    records[request_id] = saved
    monkeypatch.setattr(
        module, "check_activation", lambda: pytest.fail("Legacy read invoked activation")
    )
    client.base_url = "http://127.0.0.1"
    result = client.post(
        "/v1/panel/ai-analyses",
        json={"request_id": str(request_id), "report_id": str(source.report_id), "revision": 1},
        headers={**HEADERS, "Origin": "http://127.0.0.1"},
    )
    assert result.status_code == 200 and result.json() == saved.model_dump(mode="json")
    assert result.json()["prompt_version"] == "report-synthesis-v1"
    assert "evidence_context" not in result.json() and calls == []


def test_client_cannot_supply_its_own_context(setup_api):
    client, source, calls, _ = setup_api
    client.base_url = "http://127.0.0.1"
    result = client.post(
        "/v1/panel/ai-analyses",
        json={
            "request_id": str(uuid4()),
            "report_id": str(source.report_id),
            "revision": 1,
            "evidence_context": {"forged": True},
        },
        headers={**HEADERS, "Origin": "http://127.0.0.1"},
    )
    assert result.status_code == 422 and calls == []
