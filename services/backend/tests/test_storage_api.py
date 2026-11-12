"""HTTP statuses, validation and redaction independent of PostgreSQL availability."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

import alphasense.api as api
from alphasense.db import (
    CorruptReport,
    ReportNotFound,
    ReportStore,
    RevisionConflict,
    StoreUnavailable,
    UnstorableReport,
    get_store,
)
from alphasense.report_contracts import ReportRevision
from alphasense.storage_contracts import RevisionPage, StoredRevisionInfo


def report() -> ReportRevision:
    path = Path(__file__).parent / "fixtures/report.synthetic.json"
    return ReportRevision.model_validate_json(path.read_text("utf-8"))


@pytest.fixture
def store():
    return create_autospec(ReportStore, instance=True)


@pytest.fixture
def client(store, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("ALPHASENSE_DATABASE_URL", raising=False)
    api.app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(api.app) as value:
            yield value
    finally:
        api.app.dependency_overrides.clear()


@pytest.mark.parametrize("created", [True, False])
def test_append_distinguishes_new_and_identical_retry(
    client: TestClient, store, created: bool
) -> None:
    sample = report()
    store.append.return_value = StoredRevisionInfo(
        report_id=sample.report_id,
        revision_id=sample.revision_id,
        revision=1,
        checksum=sample.checksum,
        status=sample.status,
        generated_at_utc=sample.generated_at_utc,
        created=created,
    )
    response = client.post("/v1/reports", json=sample.model_dump(mode="json"))
    assert response.status_code == (201 if created else 200)
    assert response.json()["created"] is created
    assert response.json()["checksum"] == sample.checksum


def test_get_specific_and_latest_report(client: TestClient, store) -> None:
    sample = report()
    store.get_report.return_value = sample
    for path in [f"/v1/reports/{sample.report_id}", f"/v1/reports/{sample.report_id}/revisions/1"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == sample.model_dump(mode="json")


def test_keyset_parameters_reach_store(client: TestClient, store) -> None:
    sample = report()
    store.list_revisions.return_value = RevisionPage(items=[], next_after_revision=None)
    response = client.get(f"/v1/reports/{sample.report_id}/revisions?after_revision=3&limit=10")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_after_revision": None}
    store.list_revisions.assert_called_once_with(sample.report_id, after_revision=3, limit=10)


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (StoreUnavailable, 503),
        (CorruptReport, 503),
        (RevisionConflict, 409),
        (ReportNotFound, 404),
        (UnstorableReport, 422),
    ],
)
def test_store_errors_hide_private_details(client: TestClient, store, error, status: int) -> None:
    store.append.side_effect = error("PRIVATE SQL DSN DOCUMENT")
    response = client.post("/v1/reports", json=report().model_dump(mode="json"))
    assert response.status_code == status
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "after_revision=-1"])
def test_pagination_is_bounded(client: TestClient, store, query: str) -> None:
    response = client.get(f"/v1/reports/{report().report_id}/revisions?{query}")
    assert response.status_code == 422
    store.list_revisions.assert_not_called()


def test_bad_uuid_and_revision_are_rejected(client: TestClient, store) -> None:
    assert client.get("/v1/reports/not-a-uuid").status_code == 422
    assert client.get(f"/v1/reports/{report().report_id}/revisions/0").status_code == 422
    store.get_report.assert_not_called()


def test_invalid_checksum_cannot_reach_store(client: TestClient, store) -> None:
    payload = report().model_dump(mode="json")
    payload["limitations"] = ["PRIVATE-MODIFIED-CONTENT"]
    response = client.post("/v1/reports", json=payload)
    assert response.status_code == 422
    assert "PRIVATE" not in response.text
    store.append.assert_not_called()


def test_unconfigured_store_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHASENSE_DATABASE_URL", raising=False)
    with TestClient(api.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json()["mode"] == "validation-only"
        assert client.post("/v1/reports", json=report().model_dump(mode="json")).status_code == 503
        fixture = Path(__file__).parent / "fixtures/research-input.synthetic.json"
        assert client.post("/v1/validate", json=json.loads(fixture.read_text())).status_code == 200


def test_ready_checks_configured_store_but_health_does_not(store, monkeypatch) -> None:
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "configured-server-side")
    monkeypatch.setattr(api, "get_store", lambda: store)
    with TestClient(api.app) as client:
        assert client.get("/health").json()["mode"] == "postgresql"
        store.check_ready.assert_not_called()
        assert client.get("/ready").status_code == 200
        store.check_ready.assert_called_once()
        store.check_ready.side_effect = StoreUnavailable("PRIVATE DSN")
        response = client.get("/ready")
        assert response.status_code == 503
        assert "PRIVATE" not in response.text
