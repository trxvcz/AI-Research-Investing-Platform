"""Real SEC task transitions are durable; heartbeats are not fictitious stages."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_document_archive import ROOT
from test_document_archive import database as database
from test_tasks import request

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.task_api import router
from alphasense.tasks import TaskLeaseLost, TaskStore, create_task


def test_real_stages_and_paginated_history_exclude_heartbeat(database: Engine) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    tasks.create(frozen)
    claim = tasks.claim("history-worker")
    assert claim is not None
    token, _ = claim
    tasks.heartbeat(frozen.run_id, token)
    tasks.change(frozen.run_id, token, stage="analysis", instrument_id=frozen.instrument_id)
    report_id = uuid4()
    tasks.finish(
        frozen.run_id, token, instrument_id=frozen.instrument_id, report_id=report_id, revision=1
    )
    history = tasks.history(frozen.run_id)
    assert history.coverage == "complete"
    assert [event.task.stage for event in history.items] == [
        "queued",
        "import",
        "analysis",
        "completed",
    ]
    assert [event.sequence for event in history.items] == [1, 2, 3, 4]
    assert history.items[-1].task.report_id == report_id
    assert str(token) not in history.model_dump_json()
    page = tasks.history(frozen.run_id, after_sequence=1, limit=2)
    assert [event.sequence for event in page.items] == [2, 3]
    assert page.next_after_sequence == 3
    assert tasks.history(frozen.run_id, 3, 2).next_after_sequence is None


def test_recovery_records_new_attempt_and_lost_owner_cannot_append(database: Engine) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    old = tasks.claim("old")
    assert old is not None
    with database.begin() as conn:
        conn.execute(
            text("UPDATE import_tasks SET lease_expires_at=clock_timestamp()-INTERVAL '1 second'")
        )
    current = tasks.claim("recovered")
    assert current is not None
    with pytest.raises(TaskLeaseLost):
        tasks.fail(frozen.run_id, old[0], "OLD_OWNER", "Must not publish")
    tasks.fail(frozen.run_id, current[0], "TEST_FAILURE", "Synthetic failure")
    events = tasks.history(frozen.run_id).items
    assert [event.task.attempt for event in events] == [0, 1, 2, 2]
    assert [event.task.worker_id for event in events] == [None, "old", "recovered", "recovered"]


def test_create_task_participates_in_caller_transaction(database: Engine) -> None:
    frozen = request()
    with pytest.raises(RuntimeError), database.begin() as conn:
        create_task(conn, frozen)
        raise RuntimeError("rollback enqueue and history")
    with database.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM import_tasks")) == 0
        assert conn.scalar(text("SELECT count(*) FROM import_task_events")) == 0


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE import_task_events SET kind=kind",
        "DELETE FROM import_task_events",
        "TRUNCATE import_task_events",
    ],
)
def test_history_is_append_only(database: Engine, operation: str) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    with database.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(text(operation))
    assert len(tasks.history(frozen.run_id).items) == 1


def test_corrupt_snapshot_is_not_returned(database: Engine) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    with database.begin() as conn:
        conn.execute(
            text("ALTER TABLE import_task_events DISABLE TRIGGER import_task_events_immutable")
        )
        conn.execute(
            text(
                "UPDATE import_task_events "
                "SET payload=jsonb_set(payload,'{symbol}',to_jsonb('BAD'::text))"
            )
        )
    with pytest.raises(StoreUnavailable, match="integrity"):
        tasks.history(frozen.run_id)


def test_legacy_backfill_is_explicit_and_does_not_invent_steps(database: Engine) -> None:
    with database.begin() as conn:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0012_worker_sessions")
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    claim = tasks.claim("old-version")
    assert claim is not None
    tasks.fail(frozen.run_id, claim[0], "LEGACY_FAILURE", "Synthetic old failure")
    with database.begin() as conn:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    history = tasks.history(frozen.run_id)
    assert history.coverage == "legacy_snapshot"
    assert len(history.items) == 1 and history.items[0].kind == "legacy_snapshot"
    assert history.items[0].task.status == "failed"
    assert history.items[0].recorded_at >= history.items[0].task.updated_at


def test_nonempty_history_downgrade_is_refused(database: Engine) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    with pytest.raises(RuntimeError, match="non-empty import task event"), database.begin() as conn:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0012_worker_sessions")
    assert tasks.history(frozen.run_id).coverage == "complete"


def test_api_history_is_read_only_and_bounded(database: Engine) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    with TestClient(app) as client:
        url = f"/v1/panel/tasks/{frozen.run_id}/events"
        assert client.get(url).json()["coverage"] == "complete"
        assert client.get(url + "?limit=101").status_code == 422
        assert client.post(url, json={}).status_code == 405
