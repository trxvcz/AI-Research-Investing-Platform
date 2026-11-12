"""HTTP-boundary checks independent of the contract unit tests."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alphasense.api import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def valid_input() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "instrument_id": "DEMO-EQUITY",
        "asset_type": "equity",
        "as_of": "2026-10-30T12:00:00Z",
        "data_origin": "synthetic",
        "observations": [
            {
                "metric": "revenue",
                "unit": "USD",
                "currency": "USD",
                "period_start": "2025-01-01T00:00:00Z",
                "period_end": "2025-12-31T23:59:59Z",
                "status": "available",
                "value": 0,
                "source_id": "synthetic-demo",
                "snapshot_id": "synthetic-snapshot-1",
                "event_time": "2026-02-01T12:00:00Z",
                "available_at": "2026-02-01T12:01:00Z",
            }
        ],
    }


def missing_observation(status: str = "missing") -> dict[str, Any]:
    return {
        "metric": "net_income",
        "unit": "USD",
        "currency": "USD",
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-12-31T23:59:59Z",
        "status": status,
        "value": None,
        "reason": "No input supplied",
    }


@pytest.mark.parametrize("path", ["/health", "/ready"])
def test_health_describes_validation_only_mode(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "validation-only",
        "research_only": True,
        "external_providers_enabled": False,
    }


def test_validate_accepts_zero_without_marking_it_missing(client: TestClient) -> None:
    response = client.post("/v1/validate", json=valid_input())
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "instrument_id": "DEMO-EQUITY",
        "as_of": "2026-10-30T12:00:00Z",
        "data_origin": "synthetic",
        "status": "complete",
        "available_count": 1,
        "missing_count": 0,
        "not_applicable_count": 0,
    }


def test_validate_exposes_partial_input(client: TestClient) -> None:
    payload = valid_input()
    payload["observations"].append(missing_observation())
    response = client.post("/v1/validate", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["available_count"] == 1
    assert response.json()["missing_count"] == 1


@pytest.mark.parametrize("status", ["missing", "not_applicable"])
def test_validate_blocks_input_without_available_values(client: TestClient, status: str) -> None:
    payload = valid_input()
    payload["observations"] = [missing_observation(status)]
    response = client.post("/v1/validate", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["available_count"] == 0


def test_available_and_not_applicable_is_complete(client: TestClient) -> None:
    payload = valid_input()
    payload["observations"].append(missing_observation("not_applicable"))
    response = client.post("/v1/validate", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert response.json()["not_applicable_count"] == 1


def test_invalid_body_returns_redacted_422(client: TestClient) -> None:
    payload = valid_input()
    payload["observations"][0]["value"] = "PRIVATE-DOCUMENT-CONTENTS"
    response = client.post("/v1/validate", json=payload)
    assert response.status_code == 422
    assert "PRIVATE-DOCUMENT-CONTENTS" not in response.text
    assert response.json()["detail"]
    for issue in response.json()["detail"]:
        assert set(issue) == {"loc", "type", "msg"}
        assert issue["msg"] == "Invalid request data"


def test_unknown_fields_do_not_reflect_their_names(client: TestClient) -> None:
    payload = valid_input()
    payload["PRIVATE-EXTRA-FIELD"] = "PRIVATE-CONTENT"
    response = client.post("/v1/validate", json=payload)
    assert response.status_code == 422
    assert "PRIVATE" not in response.text
    assert "<field>" in response.text


def test_malformed_json_returns_redacted_422(client: TestClient) -> None:
    response = client.post(
        "/v1/validate",
        content='{"PRIVATE-DOCUMENT":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "PRIVATE-DOCUMENT" not in response.text
    assert "input" not in response.json()["detail"][0]


def test_future_available_at_is_rejected_at_http_boundary(client: TestClient) -> None:
    payload = valid_input()
    payload["observations"][0]["available_at"] = "2026-10-31T00:00:00Z"
    response = client.post("/v1/validate", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    ["/research-runs", "/orders", "/v1/orders", "/reports"],
)
def test_research_storage_and_execution_routes_are_unavailable(
    client: TestClient, path: str
) -> None:
    assert client.post(path, json=valid_input()).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/docs/oauth2-redirect"])
def test_external_documentation_ui_is_disabled(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_openapi_describes_input_and_validation_result(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"] == {"title": "AlphaSense Research API", "version": "0.1.0"}
    assert set(document["paths"]) == {
        "/v1/panel/runs",
        "/v1/panel/catalog",
        "/v1/panel/catalog/refresh",
        "/v1/panel/analyses",
        "/v1/panel/tasks",
        "/v1/panel/tasks/{run_id}",
        "/v1/panel/tasks/{run_id}/events",
        "/v1/panel/schedules",
        "/v1/panel/schedules/{schedule_id}",
        "/v1/panel/schedules/{schedule_id}/commands",
        "/v1/panel/schedules/{schedule_id}/occurrences",
        "/v1/panel/documents",
        "/v1/panel/document-preview",
        "/v1/panel/ai-budget",
        "/v1/panel/ai-analyses",
        "/v1/panel/ai-analyses/{request_id}",
        "/v1/panel/reports/{report_id}/{revision}/financial-history",
        "/v1/panel/reports/{report_id}/{revision}/financial-ratios",
        "/v1/panel/reports/{report_id}/{revision}/research-export",
        "/v1/panel/reports/{report_id}/{revision}/research-export/html",
        "/v1/panel/documents/{archive_id}",
        "/v1/panel/documents/{archive_id}/reviews",
        "/v1/panel/documents/{archive_id}/content",
        "/v1/panel/document-tasks",
        "/v1/panel/document-tasks/{job_id}",
        "/v1/panel/workers",
        "/v1/panel/workers/{session_id}",
        "/v1/panel/analyses/{run_id}",
        "/v1/panel/reports/{report_id}/{revision}/html",
        "/v1/research-runs/{run_id}/worker-job",
        "/v1/snapshots",
        "/v1/snapshots/{snapshot_id}",
        "/v1/snapshots/{snapshot_id}/content",
        "/v1/instruments/{instrument_id}/snapshots",
        "/v1/research-runs",
        "/v1/research-runs/{run_id}",
        "/v1/research-runs/{run_id}/events",
        "/v1/instruments",
        "/v1/instruments/{instrument_id}",
        "/health",
        "/ready",
        "/v1/validate",
        "/v1/reports/inspect",
        "/v1/reports",
        "/v1/reports/{report_id}",
        "/v1/reports/{report_id}/revisions",
        "/v1/reports/{report_id}/revisions/{revision}",
    }
    operation = document["paths"]["/v1/validate"]["post"]
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ResearchInput"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ValidationResult"
    }


def test_inspect_v1_returns_only_metadata(client: TestClient) -> None:
    sample = Path(__file__).parent / "fixtures" / "report.synthetic.json"
    payload = json.loads(sample.read_text("utf-8"))
    response = client.post("/v1/reports/inspect", json=payload)
    assert response.status_code == 200
    assert response.json() == {
        "format": "v1",
        "schema_version": "1.0",
        "report_id": payload["report_id"],
        "revision_id": payload["revision_id"],
        "revision": 1,
        "status": "partial",
        "data_origin": "synthetic",
        "checksum": payload["checksum"],
    }
    assert "Synthetic revenue" not in response.text


@pytest.mark.parametrize("case", ["checksum", "unknown_version", "private_extra", "path"])
def test_inspect_errors_do_not_echo_reports(client: TestClient, case: str) -> None:
    sample = Path(__file__).parent / "fixtures" / "report.synthetic.json"
    payload = json.loads(sample.read_text("utf-8"))
    if case == "checksum":
        payload["limitations"] = ["PRIVATE-DOCUMENT-TEXT"]
    elif case == "unknown_version":
        payload["schema_version"] = "PRIVATE-VERSION"
    elif case == "private_extra":
        payload["PRIVATE-FIELD"] = "PRIVATE-DOCUMENT-TEXT"
    else:
        payload = {"path": "C:/PRIVATE/report.json", "url": "https://example.invalid/PRIVATE"}
    response = client.post("/v1/reports/inspect", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid report data"}


def test_inspection_schema_is_exposed_in_openapi(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    schema = document["paths"]["/v1/reports/inspect"]["post"]["responses"]["200"]
    union = schema["content"]["application/json"]["schema"]
    assert union["discriminator"]["propertyName"] == "format"


def test_inspect_legacy_does_not_create_v1_provenance(client: TestClient) -> None:
    payload = {
        "id": "synthetic-legacy-api",
        "parent_id": None,
        "created_at": "2024-02-02T00:00:00Z",
        "status": "demo",
        "input_hash": "legacy-synthetic-fixture",
        "code_version": "starter-0.1.0",
        "analysis": {
            "asset_id": "DEMO-EQUITY",
            "asset_type": "equity",
            "as_of": "2024-01-10T00:00:00Z",
            "fundamental": {},
            "technical": {},
            "sources": ["synthetic-demo"],
            "status": "demo",
        },
        "trace": [],
        "charts": [],
        "warnings": ["Synthetic legacy fixture"],
    }
    response = client.post("/v1/reports/inspect", json=payload)
    assert response.status_code == 200
    assert response.json() == {
        "format": "legacy-m0",
        "report_id": payload["id"],
        "legacy_status": "demo",
        "migration_status": "blocked_missing_provenance",
        "missing_fields": [
            "observation_available_at",
            "observation_periods",
            "snapshot_provenance",
        ],
    }
