"""Real PostgreSQL observations are independent of queue claims and model calls."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_document_archive import database as database

from alphasense import worker_sessions as module
from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.worker_session_api import router
from alphasense.worker_session_contracts import WorkerSessionStart
from alphasense.worker_sessions import (
    WorkerSessionConflict,
    WorkerSessionInvalid,
    WorkerSessionNotFound,
    WorkerSessionStore,
)


def start(**updates: object) -> WorkerSessionStart:
    return WorkerSessionStart.model_validate(
        {
            "session_id": str(uuid4()),
            "worker_id": "test-worker",
            "kind": "document_validation",
            "mode": "forever",
            "process_id": 1234,
            "implementation_sha256": "a" * 64,
        }
        | updates
    )


def test_start_retry_freezes_identity_and_new_boot_has_own_history(database: Engine) -> None:
    sessions = WorkerSessionStore(database)
    definition = start()
    first = sessions.start(definition)
    repeat = sessions.start(definition)
    assert repeat.started_at == first.started_at and repeat.heartbeat_at == first.heartbeat_at
    with pytest.raises(WorkerSessionConflict):
        sessions.start(definition.model_copy(update={"process_id": 5678}))
    second = sessions.start(start())
    assert second.session_id != first.session_id and len(sessions.page().items) == 2


def test_exact_expiry_boundary_revival_and_stop_use_db_clock(database: Engine, monkeypatch) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(module, "_now", lambda _connection: now)
    sessions = WorkerSessionStore(database)
    first = sessions.start(start())
    assert first.status == "online" and first.contact_expires_at == now + timedelta(seconds=45)
    now += timedelta(seconds=45)
    assert sessions.get(first.session_id).status == "stale"
    now += timedelta(seconds=1)
    pulse = sessions.heartbeat(first.session_id)
    assert pulse.status == "online" and pulse.heartbeat_at == now
    now += timedelta(seconds=1)
    stopped = sessions.stop(first.session_id, "completed")
    assert stopped.status == "stopped" and stopped.heartbeat_at == pulse.heartbeat_at
    now += timedelta(seconds=100)
    assert sessions.get(first.session_id).status == "stopped"
    assert sessions.stop(first.session_id, "completed").stopped_at == stopped.stopped_at
    with pytest.raises(WorkerSessionConflict):
        sessions.stop(first.session_id, "error", "WORKER_RUNTIME_FAILED")
    with pytest.raises(WorkerSessionConflict):
        sessions.heartbeat(first.session_id)


@pytest.mark.parametrize(
    "worker_id", ["bad\x00name", "bad\tname", "bad\u202ename", "bad\ud800name"]
)
def test_invalid_worker_name_never_reaches_sql(database: Engine, worker_id: str) -> None:
    payload = start().model_copy(update={"worker_id": worker_id})
    with pytest.raises(WorkerSessionInvalid, match="^Invalid worker session$"):
        WorkerSessionStore(database).start(payload)
    assert WorkerSessionStore(database).page().items == []


@pytest.mark.parametrize(
    "reason,error",
    [
        ("error", None),
        ("completed", "WORKER_RUNTIME_FAILED"),
        ("bad", None),
        ("error", "secret exception text"),
    ],
)
def test_stop_metadata_only_accepts_fixed_codes(database: Engine, reason, error) -> None:
    sessions = WorkerSessionStore(database)
    saved = sessions.start(start())
    with pytest.raises(WorkerSessionInvalid):
        sessions.stop(saved.session_id, reason, error)
    assert sessions.get(saved.session_id).stopped_at is None


def test_concurrent_pulse_and_stop_cannot_revive_stopped_session(database: Engine) -> None:
    sessions = WorkerSessionStore(database)
    saved = sessions.start(start())
    barrier = Barrier(2)

    def pulse() -> str:
        barrier.wait()
        try:
            sessions.heartbeat(saved.session_id)
            return "pulse"
        except WorkerSessionConflict:
            return "stopped"

    def stop() -> str:
        barrier.wait()
        sessions.stop(saved.session_id, "interrupted")
        return "stop"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(pulse)
        second = pool.submit(stop)
        assert first.result() in {"pulse", "stopped"} and second.result() == "stop"
    assert sessions.get(saved.session_id).status == "stopped"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE worker_sessions SET worker_id='other'",
        "UPDATE worker_sessions SET heartbeat_at=started_at-INTERVAL '1 second'",
        "DELETE FROM worker_sessions",
        "TRUNCATE worker_sessions",
    ],
)
def test_sql_history_guards(database: Engine, statement: str) -> None:
    sessions = WorkerSessionStore(database)
    saved = sessions.start(start())
    with database.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(text(statement))
    assert sessions.get(saved.session_id).worker_id == saved.worker_id


def test_terminal_sql_update_is_rejected(database: Engine) -> None:
    sessions = WorkerSessionStore(database)
    saved = sessions.start(start())
    sessions.stop(saved.session_id, "error", "WORKER_MONITOR_FAILED")
    with database.begin() as connection, pytest.raises(DBAPIError):
        connection.execute(text("UPDATE worker_sessions SET heartbeat_at=heartbeat_at"))


def test_page_filter_cursor_and_shared_observation(database: Engine) -> None:
    sessions = WorkerSessionStore(database)
    sessions.start(start(kind="sec_import"))
    sessions.start(start())
    sessions.start(start())
    first = sessions.page(limit=2)
    second = sessions.page(first.next_after_id, limit=2)
    assert len({item.session_id for item in first.items + second.items}) == 3
    assert second.next_after_id is None
    assert all(item.observed_at == first.observed_at for item in first.items)
    assert len(sessions.page(kind="sec_import").items) == 1
    with pytest.raises(WorkerSessionNotFound):
        sessions.get(uuid4())


def test_corrupt_future_heartbeat_fails_closed(database: Engine) -> None:
    sessions = WorkerSessionStore(database)
    saved = sessions.start(start())
    with database.begin() as connection:
        connection.execute(
            text("ALTER TABLE worker_sessions DISABLE TRIGGER worker_sessions_guard")
        )
        connection.execute(
            text("UPDATE worker_sessions SET heartbeat_at=heartbeat_at+INTERVAL '1 day'")
        )
    with pytest.raises(StoreUnavailable, match="integrity failure"):
        sessions.get(saved.session_id)


def test_api_is_read_only_and_rejects_invalid_filters(database: Engine) -> None:
    sessions = WorkerSessionStore(database)
    saved = sessions.start(start())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    with TestClient(app) as client:
        assert client.get("/v1/panel/workers").json()["items"][0]["session_id"] == str(
            saved.session_id
        )
        assert client.get(f"/v1/panel/workers/{saved.session_id}").json()["status"] == "online"
        assert client.get(f"/v1/panel/workers/{uuid4()}").status_code == 404
        assert client.get("/v1/panel/workers?kind=unknown").status_code == 422
        assert client.get("/v1/panel/workers?limit=51").status_code == 422
        assert client.post("/v1/panel/workers", json={}).status_code == 405
