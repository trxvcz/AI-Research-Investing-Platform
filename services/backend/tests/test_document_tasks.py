"""Offline document jobs are durable, fenced, idempotent and auditable."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_document_archive import database as database
from test_document_archive import request, review

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.db_schema import document_task_audits, document_tasks
from alphasense.document_archive import DocumentArchiveStore
from alphasense.document_task_api import router
from alphasense.document_task_contracts import DocumentTaskCreate
from alphasense.document_tasks import DocumentTaskConflict, DocumentTaskLeaseLost, DocumentTaskStore

FINGERPRINT = "a" * 64


def queued(engine: Engine, mode: str = "validate_saved_draft"):
    archive = DocumentArchiveStore(engine).create(request())
    command = DocumentTaskCreate(job_id=uuid4(), archive_id=archive.archive_id, mode=mode)
    tasks = DocumentTaskStore(engine)
    return tasks, command, tasks.create(command)


def complete(tasks, job, token, result):
    tasks.stage(job.job_id, token, "validating")
    tasks.stage(job.job_id, token, "archiving")
    tasks.finish(job.job_id, token, "completed", result)


def expire(engine: Engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE document_tasks SET lease_expires_at=clock_timestamp()-INTERVAL '1 second' "
                "WHERE status='running'"
            )
        )


def test_durable_frozen_input_and_review_changes_are_independent(database: Engine):
    tasks, command, saved = queued(database)
    assert saved.status == "queued" and saved.attempt == 0
    assert DocumentTaskStore(database).get(saved.job_id) == saved
    assert tasks.create(command) == saved
    DocumentArchiveStore(database).review(saved.archive_id, review())
    assert tasks.get(saved.job_id) == saved
    with pytest.raises(DocumentTaskConflict):
        tasks.create(command.model_copy(update={"mode": "model_extract"}))
    assert len(tasks.detail(saved.job_id).events) == 1


def test_execution_receipt_is_honest_offline_and_terminal_history_is_immutable(database: Engine):
    tasks, command, saved = queued(database)
    token, job = tasks.claim("worker-one", FINGERPRINT)
    tasks.renew(job.job_id, token)
    source = DocumentArchiveStore(database).get(saved.archive_id)
    complete(tasks, job, token, source.result)
    detail = tasks.detail(job.job_id)
    assert detail.task.status == "completed" and detail.task.result == source.result
    assert [e.stage for e in detail.events] == [
        "queued",
        "reading",
        "validating",
        "archiving",
        "completed",
    ]
    audit = detail.audits[0]
    assert audit.provider_called is False and audit.cost_usd == "0"
    assert audit.input_tokens is None and audit.model_id is None and audit.prompt_version is None
    assert audit.request_sha256 == detail.task.input_sha256 and audit.output_sha256
    assert tasks.claim("worker-two", FINGERPRINT) is None
    with pytest.raises(DocumentTaskLeaseLost):
        tasks.finish(job.job_id, token, "completed", source.result)


def test_expired_owner_cannot_publish_or_renew_and_recovery_is_audited(database: Engine):
    tasks, command, saved = queued(database)
    old, job = tasks.claim("old-worker", FINGERPRINT)
    expire(database)
    with pytest.raises(DocumentTaskLeaseLost):
        tasks.renew(job.job_id, old)
    new, job = tasks.claim("new-worker", FINGERPRINT)
    with pytest.raises(DocumentTaskLeaseLost):
        tasks.stage(job.job_id, old, "validating")
    source = DocumentArchiveStore(database).get(saved.archive_id)
    complete(tasks, job, new, source.result)
    detail = tasks.detail(job.job_id)
    assert detail.task.attempt == 2
    assert [a.outcome for a in detail.audits] == ["interrupted", "completed"]
    assert detail.audits[0].error_code == "LEASE_EXPIRED"


def test_three_crashed_attempts_exhaust_without_fake_completion(database: Engine):
    tasks, _, saved = queued(database)
    for _number in range(3):
        assert tasks.claim("worker", FINGERPRINT) is not None
        expire(database)
    assert tasks.claim("worker", FINGERPRINT) is None
    detail = tasks.detail(saved.job_id)
    assert detail.task.status == "failed" and detail.task.error_code == "RECOVERY_EXHAUSTED"
    assert [a.outcome for a in detail.audits] == ["interrupted"] * 3
    assert detail.task.result is None


def test_disabled_model_receipt_never_claims_provider_usage(database: Engine):
    tasks, _, saved = queued(database, "model_extract")
    token, job = tasks.claim("worker", FINGERPRINT)
    tasks.finish(job.job_id, token, "blocked", error_code="MODEL_EXECUTION_DISABLED")
    detail = tasks.detail(saved.job_id)
    assert detail.task.status == "blocked"
    assert detail.audits[0].execution == "model-disabled-v1"
    assert detail.audits[0].provider_called is False and detail.audits[0].response_sha256 is None


def test_two_workers_claim_once(database: Engine):
    tasks, _, saved = queued(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: tasks.claim("worker", FINGERPRINT), range(2)))
    assert sum(claim is not None for claim in claims) == 1


@pytest.mark.parametrize(
    "table", ["document_tasks", "document_task_events", "document_task_audits"]
)
@pytest.mark.parametrize("operation", ["DELETE", "TRUNCATE", "UPDATE"])
def test_sql_cannot_remove_or_rewrite_terminal_history(
    database: Engine, table: str, operation: str
):
    tasks, _, saved = queued(database, "model_extract")
    token, job = tasks.claim("worker", FINGERPRINT)
    tasks.finish(job.job_id, token, "blocked", error_code="MODEL_EXECUTION_DISABLED")
    if operation == "UPDATE":
        statement = f"UPDATE {table} SET job_id=job_id"
    elif operation == "DELETE":
        statement = f"DELETE FROM {table}"
    else:
        statement = f"TRUNCATE {table} CASCADE"
    with database.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(text(statement))
    assert tasks.get(saved.job_id).status == "blocked"


def test_hash_corruption_fails_closed(database: Engine):
    tasks, _, saved = queued(database, "model_extract")
    token, job = tasks.claim("worker", FINGERPRINT)
    tasks.finish(job.job_id, token, "blocked", error_code="MODEL_EXECUTION_DISABLED")
    with database.begin() as conn:
        conn.execute(
            text("ALTER TABLE document_task_audits DISABLE TRIGGER document_task_audits_immutable")
        )
        conn.execute(document_task_audits.update().values(sha256="b" * 64))
    with pytest.raises(StoreUnavailable):
        tasks.detail(saved.job_id)


def test_frozen_task_sql_update_rejected_and_page_has_no_duplicates(database: Engine):
    tasks, _, saved = queued(database)
    with database.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(document_tasks.update().values(input_sha256="b" * 64))
    queued(database)
    queued(database)
    first = tasks.page(limit=2)
    second = tasks.page(first.next_after_id, limit=2)
    assert len({item.job_id for item in first.items + second.items}) == 3
    assert second.next_after_id is None


def test_api_submission_only_and_origin_guard(database: Engine):
    tasks, command, saved = queued(database)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    headers = {"Origin": "http://127.0.0.1", "X-AlphaSense-Panel": "1"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        payload = command.model_dump(mode="json")
        assert client.post("/v1/panel/document-tasks", json=payload).status_code == 403
        result = client.post("/v1/panel/document-tasks", json=payload, headers=headers)
        assert result.status_code == 200 and result.json()["status"] == "queued"
        assert client.get(f"/v1/panel/document-tasks/{saved.job_id}").json()["audits"] == []
        assert client.get("/v1/panel/document-tasks").json()["items"][0]["job_id"] == str(
            saved.job_id
        )
        assert client.get(f"/v1/panel/document-tasks/{uuid4()}").status_code == 404
    assert tasks.get(saved.job_id).attempt == 0


def test_detail_reads_one_snapshot_during_concurrent_stage_change(database: Engine, monkeypatch):
    from alphasense import document_tasks as module

    tasks, _, saved = queued(database)
    token, job = tasks.claim("worker", FINGERPRINT)
    original = module._source
    updated = False

    def interleave(connection, archive_id):
        nonlocal updated
        if not updated:
            updated = True
            tasks.stage(job.job_id, token, "validating")
        return original(connection, archive_id)

    monkeypatch.setattr(module, "_source", interleave)
    checkpoint = tasks.detail(saved.job_id)
    assert checkpoint.task.stage == "reading"
    assert checkpoint.events[-1].stage == "reading"
    assert tasks.detail(saved.job_id).task.stage == "validating"
