"""Registry HTTP schemas, statuses and redaction without requiring PostgreSQL."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from fastapi.testclient import TestClient

from alphasense.api import app
from alphasense.db import CorruptReport, StoreUnavailable
from alphasense.instrument_contracts import (
    InstrumentCreate,
    InstrumentPage,
    InstrumentRecord,
    InstrumentWrite,
)
from alphasense.instruments import (
    InstrumentConflict,
    InstrumentNotFound,
    InstrumentStore,
    get_instrument_store,
)


def sample() -> InstrumentCreate:
    path = Path(__file__).parent / "fixtures/instrument.synthetic.json"
    return InstrumentCreate.model_validate_json(path.read_text("utf-8"))


@pytest.fixture
def store():
    return create_autospec(InstrumentStore, instance=True)


@pytest.fixture
def client(store) -> Iterator[TestClient]:
    app.dependency_overrides[get_instrument_store] = lambda: store
    try:
        with TestClient(app) as value:
            yield value
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("created", [True, False])
def test_create_or_identical_retry(client: TestClient, store, created: bool) -> None:
    stored = InstrumentWrite(
        **sample().model_dump(), created_at="2024-02-02T00:00:00Z", created=created
    )
    store.create.return_value = stored
    response = client.post("/v1/instruments", json=sample().model_dump(mode="json"))
    assert response.status_code == (201 if created else 200)
    assert response.json() == stored.model_dump(mode="json")


def test_get_and_search_preserve_declared_identity(client: TestClient, store) -> None:
    record = InstrumentRecord(**sample().model_dump(), created_at="2024-02-02T00:00:00Z")
    store.get.return_value = record
    assert client.get(f"/v1/instruments/{record.instrument_id}").json() == record.model_dump(
        mode="json"
    )
    store.search.return_value = InstrumentPage(items=[record], next_after_id=None)
    response = client.get(
        "/v1/instruments", params={"query": "%_", "limit": 1, "data_origin": "synthetic"}
    )
    assert response.status_code == 200
    store.search.assert_called_once_with(
        query="%_", after_id=None, limit=1, data_origin="synthetic"
    )


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"after_id": "bad"},
        {"query": "\x00"},
        {"query": "x" * 129},
        {"data_origin": "paid"},
    ],
)
def test_bad_search_cannot_reach_store(client: TestClient, store, params) -> None:
    assert client.get("/v1/instruments", params=params).status_code == 422
    store.search.assert_not_called()


@pytest.mark.parametrize(
    "error,status",
    [
        (InstrumentConflict, 409),
        (InstrumentNotFound, 404),
        (StoreUnavailable, 503),
        (CorruptReport, 503),
    ],
)
def test_errors_never_echo_database_or_document(client: TestClient, store, error, status) -> None:
    store.create.side_effect = error("PRIVATE DSN SQL DOCUMENT")
    response = client.post("/v1/instruments", json=sample().model_dump(mode="json"))
    assert response.status_code == status
    assert "PRIVATE" not in response.text


def test_bad_body_and_path_are_redacted(client: TestClient, store) -> None:
    payload = sample().model_dump(mode="json")
    payload["PRIVATE-FIELD"] = "PRIVATE-DOCUMENT"
    response = client.post("/v1/instruments", json=payload)
    assert response.status_code == 422
    assert "PRIVATE" not in response.text
    assert client.get("/v1/instruments/private-invalid-id").status_code == 422
    store.create.assert_not_called()


def test_unconfigured_database_does_not_enable_writes(monkeypatch) -> None:
    monkeypatch.delenv("ALPHASENSE_DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert (
            client.post("/v1/instruments", json=sample().model_dump(mode="json")).status_code == 503
        )


def test_openapi_exposes_registry_without_mutation_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/v1/instruments"]) == {"get", "post"}
    assert set(paths["/v1/instruments/{instrument_id}"]) == {"get"}
