"""Real PostgreSQL archive/review checks; no provider calls or report publication."""

import base64
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError

from alphasense.api import invalid_request
from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.db_schema import document_archives, document_reviews, report_revisions
from alphasense.document_archive import (
    DocumentArchiveConflict,
    DocumentArchiveInvalid,
    DocumentArchiveNotFound,
    DocumentArchiveStore,
)
from alphasense.document_archive_api import router
from alphasense.document_archive_contracts import DocumentArchiveCreate, DocumentReviewCommand

ROOT = Path(__file__).resolve().parents[3]
RAW = b"Consolidated revenue 2025: 12.5 million PLN."


def request(**updates: object) -> DocumentArchiveCreate:
    value: dict[str, object] = {
        "archive_id": str(uuid4()),
        "title": "Synthetic research",
        "format": "text",
        "classification": "private",
        "content_base64": base64.b64encode(RAW).decode(),
        "draft_json": json.dumps(
            {
                "schema_version": "1.0",
                "facts": [
                    {
                        "metric": "revenue",
                        "value_token": "12.5",
                        "value": "12500000",
                        "scale": 1000000,
                        "currency": "PLN",
                        "period_start": "2025-01-01",
                        "period_end": "2025-12-31",
                        "scope": "consolidated",
                        "evidence": [{"block_id": "block-1", "quote": "12.5 million PLN"}],
                    }
                ],
            }
        ),
        "source_available_at": "2026-01-01T00:00:00Z",
        "as_of": "2026-01-02T00:00:00Z",
    }
    value.update(updates)
    return DocumentArchiveCreate.model_validate(value)


def review(**updates: object) -> DocumentReviewCommand:
    value: dict[str, object] = {
        "command_id": str(uuid4()),
        "expected_revision": 0,
        "fact_index": 0,
        "verdict": "accepted",
        "note": "Checked source",
    }
    value.update(updates)
    return DocumentReviewCommand.model_validate(value)


@pytest.fixture
def database() -> Iterator[Engine]:
    dsn = os.environ.get("ALPHASENSE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real PostgreSQL requires ALPHASENSE_TEST_DATABASE_URL")
    schema = "document_archive_test_" + uuid4().hex
    admin = create_engine(dsn, hide_parameters=True)
    engine = create_engine(
        dsn, hide_parameters=True, connect_args={"options": f"-c search_path={schema}"}
    )
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.begin() as conn:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_roundtrip_retries_history_and_no_publication(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    original = request()
    saved = store.create(original)
    assert saved == store.create(original)
    assert saved.provenance == "unverified_offline_import"
    assert saved.result.status == "needs_review"
    assert store.content(saved.archive_id) == RAW
    first = review()
    event = store.review(saved.archive_id, first)
    assert event == store.review(saved.archive_id, first)
    second = review(expected_revision=1, verdict="rejected", note="Semantic correction")
    store.review(saved.archive_id, second)
    record = store.get(saved.archive_id)
    assert record.review_revision == 2
    assert [x.command.verdict for x in record.reviews] == ["accepted", "rejected"]
    assert record.result.status == "needs_review"
    assert store.page().items[0].review_revision == 2
    with database.connect() as conn:
        assert conn.execute(select(report_revisions)).first() is None


def test_frozen_identity_and_stale_commands(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    original = request()
    store.create(original)
    with pytest.raises(DocumentArchiveConflict):
        store.create(original.model_copy(update={"title": "Changed"}))
    first = review()
    store.review(original.archive_id, first)
    with pytest.raises(DocumentArchiveConflict):
        store.review(original.archive_id, review())
    with pytest.raises(DocumentArchiveConflict):
        store.review(original.archive_id, first.model_copy(update={"note": "Changed"}))
    with pytest.raises(DocumentArchiveInvalid):
        store.review(original.archive_id, review(expected_revision=1, fact_index=1))
    with pytest.raises(DocumentArchiveNotFound):
        store.get(uuid4())


@pytest.mark.parametrize(
    "updates",
    [
        {"content_base64": "!!!!"},
        {"content_base64": "YQ==\n"},
        {"content_base64": "YR=="},
        {"content_base64": base64.b64encode(b"\x00text").decode()},
        {"draft_json": "x" * 200000 + "\u00e9" * 100000},
        {"title": "secret\x00title"},
        {"instrument_id": uuid4()},
    ],
)
def test_invalid_imports_are_refused(database: Engine, updates: dict[str, object]) -> None:
    # model_copy bypasses Pydantic intentionally: store must revalidate at its boundary.
    with pytest.raises((DocumentArchiveInvalid, ValueError)):
        DocumentArchiveStore(database).create(request().model_copy(update=updates))
    with database.connect() as conn:
        assert conn.execute(select(document_archives)).first() is None


def test_rejected_fact_cannot_be_human_accepted(database: Engine) -> None:
    original = request()
    original.draft_json = original.draft_json.replace('"12500000"', '"100"')
    store = DocumentArchiveStore(database)
    saved = store.create(original)
    assert saved.result.facts[0].status == "rejected"
    with pytest.raises(DocumentArchiveInvalid):
        store.review(saved.archive_id, review())
    assert store.review(saved.archive_id, review(verdict="rejected")).revision == 1


def test_two_reviewers_are_serialized(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    saved = store.create(request())

    def attempt() -> str:
        try:
            store.review(saved.archive_id, review())
            return "saved"
        except DocumentArchiveConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ["conflict", "saved"]
    assert store.get(saved.archive_id).review_revision == 1


def test_pagination_has_no_duplicate_records(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    ids = {store.create(request()).archive_id for _ in range(3)}
    first = store.page(limit=2)
    second = store.page(first.next_after_id, limit=2)
    assert {x.archive_id for x in first.items + second.items} == ids
    assert second.next_after_id is None
    assert store.page(instrument_id=uuid4()).items == []


def test_integrity_failures_are_not_silently_returned(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    saved = store.create(request())
    with database.begin() as conn:
        conn.execute(
            text("ALTER TABLE document_archives DISABLE TRIGGER document_archives_immutable")
        )
        conn.execute(document_archives.update().values(document_sha256="b" * 64))
        conn.execute(
            text("ALTER TABLE document_archives ENABLE TRIGGER document_archives_immutable")
        )
    with pytest.raises(StoreUnavailable):
        store.get(saved.archive_id)


def test_api_origin_validation_download_and_retry(database: Engine) -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    headers = {"origin": "http://127.0.0.1", "x-alphasense-panel": "1"}
    payload = request().model_dump(mode="json")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/v1/panel/documents", json=payload).status_code == 403
        saved = client.post("/v1/panel/documents", headers=headers, json=payload)
        assert saved.status_code == 200
        identifier = saved.json()["archive_id"]
        assert client.get("/v1/panel/documents").json()["items"][0]["archive_id"] == identifier
        detail = client.get(f"/v1/panel/documents/{identifier}")
        assert detail.json()["provenance"] == "unverified_offline_import"
        downloaded = client.get(f"/v1/panel/documents/{identifier}/content")
        assert downloaded.content == RAW
        assert downloaded.headers["x-content-type-options"] == "nosniff"
        assert "attachment" in downloaded.headers["content-disposition"]
        event = review().model_dump(mode="json")
        assert (
            client.post(f"/v1/panel/documents/{identifier}/reviews", json=event).status_code == 403
        )
        assert (
            client.post(
                f"/v1/panel/documents/{identifier}/reviews", headers=headers, json=event
            ).status_code
            == 200
        )
        stale = review().model_dump(mode="json")
        assert (
            client.post(
                f"/v1/panel/documents/{identifier}/reviews", headers=headers, json=stale
            ).status_code
            == 409
        )
        assert client.get(f"/v1/panel/documents/{uuid4()}").status_code == 404


@pytest.mark.parametrize("table", ["document_archives", "document_reviews"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_sql_history_is_immutable(database: Engine, table: str, operation: str) -> None:
    store = DocumentArchiveStore(database)
    saved = store.create(request())
    store.review(saved.archive_id, review())
    statements = {
        "UPDATE": f"UPDATE {table} SET archive_id=archive_id",
        "DELETE": f"DELETE FROM {table}",
        "TRUNCATE": f"TRUNCATE {table} CASCADE",
    }
    with database.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(text(statements[operation]))
    assert store.get(saved.archive_id).review_revision == 1


def test_review_integrity_checks_command_hash(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    saved = store.create(request())
    store.review(saved.archive_id, review())
    with database.begin() as conn:
        conn.execute(
            text("ALTER TABLE document_reviews DISABLE TRIGGER document_reviews_immutable")
        )
        conn.execute(document_reviews.update().values(command_sha256="a" * 64))
    with pytest.raises(StoreUnavailable):
        store.get(saved.archive_id)


def test_surrogate_metadata_and_review_note_are_redacted(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    saved = store.create(request())
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    headers = {
        "origin": "http://127.0.0.1",
        "x-alphasense-panel": "1",
        "content-type": "application/json",
    }
    payload = request().model_dump(mode="json")
    payload["title"] = "bad\ud800title"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/v1/panel/documents", headers=headers, content=json.dumps(payload).encode("ascii")
        )
        assert response.status_code == 422
        assert "bad" not in response.text and "ud800" not in response.text
        command = review().model_dump(mode="json")
        command["note"] = "bad\ud800note"
        response = client.post(
            f"/v1/panel/documents/{saved.archive_id}/reviews",
            headers=headers,
            content=json.dumps(command).encode("ascii"),
        )
        assert response.status_code == 422
        assert "bad" not in response.text and "ud800" not in response.text
    assert store.get(saved.archive_id).review_revision == 0


def test_malformed_persisted_request_fails_closed(database: Engine) -> None:
    store = DocumentArchiveStore(database)
    saved = store.create(request())
    with database.begin() as conn:
        conn.execute(
            text("ALTER TABLE document_archives DISABLE TRIGGER document_archives_immutable")
        )
        conn.execute(document_archives.update().values(request=[1]))
    with pytest.raises(StoreUnavailable, match="integrity failure"):
        store.get(saved.archive_id)
