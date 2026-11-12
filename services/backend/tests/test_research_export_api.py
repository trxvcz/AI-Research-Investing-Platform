"""Downloads use only exact persisted inputs and never reserve or generate AI."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_research_export import export_fixture

import alphasense.research_export_api as module
from alphasense.ai_analysis_store import AiStoreUnavailable
from alphasense.db import get_store
from alphasense.financial_ratios_api import financial_ratios


@pytest.fixture
def client():
    report, ratios, old = export_fixture("v1")
    _, _, new = export_fixture("v2")
    records = {old.request_id: old, new.request_id: new}
    reads = []

    def read(request_id):
        reads.append(request_id)
        return records.get(request_id)

    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_store] = lambda: SimpleNamespace(get_report=lambda *args: report)
    app.dependency_overrides[financial_ratios] = lambda: ratios
    # Only get is provided: any attempt to reserve/generate would fail this fixture.
    app.dependency_overrides[module.get_ai_store] = lambda: SimpleNamespace(get=read)
    with TestClient(app) as current:
        yield current, app, report, old, new, records, reads


def path(report):
    return f"/v1/panel/reports/{report.report_id}/{report.revision}/research-export"


def test_no_ai_parameter_means_no_ai_lookup_and_deterministic_attachment(client):
    current, _, report, _, _, _, reads = client
    response = current.get(path(report))
    assert response.status_code == 200 and response.json()["ai_analysis"] is None
    assert reads == [] and current.get(path(report)).content == response.content
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-disposition"].endswith('.json"')
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert current.post(path(report)).status_code == 405


@pytest.mark.parametrize("version", ["old", "new"])
def test_explicit_old_or_new_ai_stays_exactly_selected(client, version):
    current, _, report, old, new, _, reads = client
    selected = old if version == "old" else new
    response = current.get(path(report), params={"ai_request_id": str(selected.request_id)})
    assert response.status_code == 200
    assert response.json()["ai_analysis"] == selected.model_dump(mode="json")
    assert reads == [selected.request_id]


def test_html_attachment_is_standalone_and_bound_to_selected_request(client):
    current, _, report, old, _, _, _ = client
    response = current.get(path(report) + "/html", params={"ai_request_id": str(old.request_id)})
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    assert response.headers["content-disposition"].endswith('.html"')
    assert str(old.request_id) in response.text
    assert "<script" not in response.text.lower()


def test_unknown_ai_returns_404_not_latest(client):
    current, _, report, _, _, _, _ = client
    response = current.get(path(report), params={"ai_request_id": str(uuid4())})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPORT_AI_NOT_FOUND"


@pytest.mark.parametrize("damage", ["identity", "running", "failed"])
def test_mismatch_and_nonterminal_ai_are_explicit_conflicts(client, damage):
    current, _, report, old, _, records, _ = client
    updates = {"report_id": uuid4()} if damage == "identity" else {"status": damage}
    records[old.request_id] = old.model_copy(update=updates)
    response = current.get(path(report), params={"ai_request_id": str(old.request_id)})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "EXPORT_AI_MISMATCH" if damage == "identity" else "EXPORT_AI_NOT_COMPLETED"
    )


def test_ai_store_failure_is_safe_503(client):
    current, app, report, old, _, _, _ = client

    def failed(_request_id):
        raise AiStoreUnavailable()

    app.dependency_overrides[module.get_ai_store] = lambda: SimpleNamespace(get=failed)
    response = current.get(path(report), params={"ai_request_id": str(old.request_id)})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EXPORT_STORAGE_UNAVAILABLE"


def test_invalid_optional_uuid_is_rejected_before_ai_lookup(client):
    current, _, report, _, _, _, reads = client
    assert current.get(path(report), params={"ai_request_id": "not-uuid"}).status_code == 422
    assert reads == []


def test_saved_export_ignores_model_activation_and_generation(client, monkeypatch):
    import alphasense.ai_analysis_api as ai_api
    import alphasense.ai_history_analysis as engine

    def forbidden(*args, **kwargs):
        raise AssertionError("Export must not activate or generate AI")

    monkeypatch.setattr(ai_api, "check_activation", forbidden)
    monkeypatch.setattr(ai_api, "generate_analysis", forbidden)
    monkeypatch.setattr(engine, "check_history_activation", forbidden)
    monkeypatch.setattr(engine, "generate_history_analysis", forbidden)
    monkeypatch.delenv("ALPHASENSE_AI_SETTINGS_FILE", raising=False)
    current, _, report, old, _, _, _ = client
    response = current.get(path(report), params={"ai_request_id": str(old.request_id)})
    assert response.status_code == 200
    assert response.json()["ai_analysis"]["request_id"] == str(old.request_id)
