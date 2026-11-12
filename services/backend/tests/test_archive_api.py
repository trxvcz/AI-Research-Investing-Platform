"""Archive transport boundaries and ledger routes without external providers."""

from collections.abc import Iterator
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_run_snapshot_contracts import run_payload, snapshot_payload

from alphasense.api import app
from alphasense.db import CorruptReport, StoreUnavailable
from alphasense.runs import ResearchStore, RunConflict, RunNotFound, get_research_store
from alphasense.snapshot_contracts import (
    MAX_UPLOAD_BODY,
    SnapshotCreate,
    SnapshotRecord,
    SnapshotWrite,
)
from alphasense.snapshots import (
    SnapshotConflict,
    SnapshotNotFound,
    SnapshotStore,
    get_snapshot_store,
)


@pytest.fixture
def stores():
    return create_autospec(SnapshotStore, instance=True), create_autospec(
        ResearchStore, instance=True
    )


@pytest.fixture
def client(stores) -> Iterator[TestClient]:
    snapshots, runs = stores
    app.dependency_overrides[get_snapshot_store] = lambda: snapshots
    app.dependency_overrides[get_research_store] = lambda: runs
    try:
        with TestClient(app) as value:
            yield value
    finally:
        app.dependency_overrides.clear()


def record(
    raw: bytes = b"\x00\xff<script>untrusted</script>",
) -> tuple[SnapshotCreate, SnapshotRecord]:
    create = SnapshotCreate.model_validate(snapshot_payload(raw))
    metadata = create.model_dump(exclude={"content_base64"})
    return create, SnapshotRecord(**metadata, created_at="2026-10-30T00:00:00Z")


@pytest.mark.parametrize("created", [True, False])
def test_upload_is_bounded_metadata_response(client, stores, created) -> None:
    create, stored = record()
    stores[0].create.return_value = SnapshotWrite(**stored.model_dump(), created=created)
    response = client.post("/v1/snapshots", json=create.model_dump(mode="json"))
    assert response.status_code == (201 if created else 200)
    assert response.json()["sha256"] == create.sha256
    assert "content_base64" not in response.json()


def test_binary_download_never_renders_source_content(client, stores) -> None:
    create, stored = record()
    stores[0].content.return_value = stored, create.raw_bytes()
    response = client.get(f"/v1/snapshots/{create.snapshot_id}/content")
    assert response.status_code == 200
    assert response.content == create.raw_bytes()
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="snapshot-{create.snapshot_id}.bin"'
    )


@pytest.mark.parametrize("prefixed", [False, True])
@pytest.mark.parametrize("chunked", [False, True])
def test_upload_limit_precedes_json_and_respects_root_path(stores, prefixed, chunked) -> None:
    app.dependency_overrides[get_snapshot_store] = lambda: stores[0]
    try:
        with TestClient(app, root_path="/prefix" if prefixed else "") as client:
            path = "/prefix/v1/snapshots" if prefixed else "/v1/snapshots"
            raw = b"x" * (MAX_UPLOAD_BODY + 1)
            response = client.post(
                path, content=iter([raw[:500000], raw[500000:]]) if chunked else raw
            )
            assert response.status_code == 413
            assert response.json() == {"detail": "Snapshot upload too large"}
            stores[0].create.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_limit_uses_actual_bytes_not_claimed_content_length(client, stores) -> None:
    response = client.post(
        "/v1/snapshots", content=b"x" * (MAX_UPLOAD_BODY + 1), headers={"Content-Length": "1"}
    )
    assert response.status_code == 413
    stores[0].create.assert_not_called()


def test_hash_mismatch_and_unknown_fields_are_redacted(client, stores) -> None:
    payload = snapshot_payload()
    payload["sha256"] = "0" * 64
    payload["PRIVATE-FIELD"] = "PRIVATE-DOCUMENT"
    response = client.post("/v1/snapshots", json=payload)
    assert response.status_code == 422
    assert "PRIVATE" not in response.text
    stores[0].create.assert_not_called()


@pytest.mark.parametrize(
    "error,status",
    [
        (SnapshotConflict, 409),
        (SnapshotNotFound, 404),
        (CorruptReport, 503),
        (StoreUnavailable, 503),
    ],
)
def test_snapshot_errors_do_not_echo_data(client, stores, error, status) -> None:
    stores[0].create.side_effect = error("PRIVATE DSN SQL DOCUMENT")
    response = client.post("/v1/snapshots", json=snapshot_payload())
    assert response.status_code == status
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize(
    "error,status",
    [(RunConflict, 409), (RunNotFound, 404), (CorruptReport, 503), (StoreUnavailable, 503)],
)
def test_ledger_errors_do_not_echo_data(client, stores, error, status) -> None:
    stores[1].create.side_effect = error("PRIVATE DSN SQL DOCUMENT")
    response = client.post("/v1/research-runs", json=run_payload())
    assert response.status_code == status
    assert "PRIVATE" not in response.text


def test_ledger_api_rejects_arbitrary_commands_and_bad_sequences(client, stores) -> None:
    payload = {
        "action": "execute_python",
        "request_id": str(uuid4()),
        "actor": "test",
        "expected_sequence": 1,
    }
    response = client.post(f"/v1/research-runs/{uuid4()}/events", json=payload)
    assert response.status_code == 422
    stores[1].apply.assert_not_called()


def test_unconfigured_database_stays_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("ALPHASENSE_DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.post("/v1/snapshots", json=snapshot_payload()).status_code == 503
        assert client.post("/v1/research-runs", json=run_payload()).status_code == 503


def test_event_command_schema_has_discriminator(client) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/v1/research-runs/{run_id}/events"][
        "post"
    ]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["discriminator"]["propertyName"] == "action"
