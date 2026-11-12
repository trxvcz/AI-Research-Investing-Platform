"""Schedules persist intentions without invoking sources, workers or models."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select, text
from sqlalchemy.exc import DBAPIError
from test_document_archive import database as database

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.db_schema import import_tasks, sec_schedule_occurrences
from alphasense.schedule_api import router
from alphasense.schedule_contracts import ScheduleCommand, ScheduleCreate
from alphasense.sec_contracts import SecImportRequest
from alphasense.sec_schedules import ScheduleConflict, ScheduleStore, slot_run_id


def prepared(database: Engine, *, enabled: bool = True, hours_ago: int = 0):
    now = datetime.now(UTC)
    identifier = uuid4()
    payload = ScheduleCreate(
        schedule_id=identifier,
        symbol="AAPL",
        exchange_mic="XNAS",
        interval_seconds=3600,
        first_run_at=now - timedelta(hours=hours_ago),
        enabled=enabled,
    )
    template = SecImportRequest(
        cik="0000320193",
        symbol="AAPL",
        exchange_mic="XNAS",
        instrument_id=uuid4(),
        run_id=identifier,
        pipeline_version="sec-fundamentals-v2",
    )
    store = ScheduleStore(database)
    return store, payload, template, store.create(payload, template)


def test_frozen_create_retry_after_control_does_not_reset_enabled(database: Engine) -> None:
    store, payload, template, original = prepared(database, enabled=False)
    assert store.create(payload, template) == original
    cmd = ScheduleCommand(command_id=uuid4(), expected_revision=0, enabled=True)
    changed = store.command(original.schedule_id, cmd)
    assert changed.enabled and changed.revision == 1
    assert store.command(original.schedule_id, cmd) == changed
    assert store.create(payload, template) == changed
    with pytest.raises(ScheduleConflict):
        store.create(payload.model_copy(update={"interval_seconds": 7200}), template)
    with pytest.raises(ScheduleConflict):
        store.command(
            original.schedule_id,
            ScheduleCommand(command_id=uuid4(), expected_revision=0, enabled=False),
        )


def test_disabled_and_future_schedules_never_enqueue(database: Engine) -> None:
    store, _, _, saved = prepared(database, enabled=False)
    _, _, _, future = prepared(database, hours_ago=-1)
    assert store.dispatch_due() == []
    assert store.get(saved.schedule_id) == saved
    assert store.get(future.schedule_id) == future
    with database.connect() as conn:
        assert conn.scalar(select(import_tasks.c.run_id).limit(1)) is None


def test_dispatch_latest_slot_skips_backlog_and_is_idempotent(database: Engine) -> None:
    store, payload, template, saved = prepared(database, hours_ago=5)
    occurrence = store.dispatch_due()[0]
    assert occurrence.skipped_slots == 5
    assert occurrence.scheduled_for == payload.first_run_at + timedelta(hours=5)
    assert occurrence.run_id == slot_run_id(saved.schedule_id, occurrence.scheduled_for)
    assert store.dispatch_due() == []
    assert store.get(saved.schedule_id).next_run_at == occurrence.scheduled_for + timedelta(hours=1)
    with database.connect() as conn:
        frozen = SecImportRequest.model_validate(conn.scalar(select(import_tasks.c.request)))
    assert frozen == template.model_copy(update={"run_id": occurrence.run_id})
    assert store.occurrences(saved.schedule_id).items == [occurrence]


def test_busy_instrument_skips_slot_without_new_task(database: Engine) -> None:
    from alphasense.tasks import create_task

    store, _, template, saved = prepared(database)
    with database.begin() as conn:
        create_task(conn, template.model_copy(update={"run_id": uuid4()}))
    occurrence = store.dispatch_due()[0]
    assert occurrence.outcome == "skipped_busy" and occurrence.run_id is None
    with database.connect() as conn:
        assert len(conn.execute(select(import_tasks.c.run_id)).all()) == 1
    assert store.get(saved.schedule_id).last_outcome == "skipped_busy"


def test_concurrent_dispatchers_create_only_one_occurrence(database: Engine) -> None:
    store, _, _, saved = prepared(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: store.dispatch_due(), range(2)))
    assert sum(map(len, outputs)) == 1
    assert len(store.occurrences(saved.schedule_id).items) == 1


def test_receipt_failure_rolls_back_enqueue_and_next_time(database: Engine, monkeypatch) -> None:
    from alphasense import sec_schedules as module

    store, _, _, saved = prepared(database)
    original = module._decode

    def fail_after_enqueue(connection, row):
        if row["last_outcome"] is not None:
            raise StoreUnavailable("Synthetic publication failure")
        return original(connection, row)

    monkeypatch.setattr(module, "_decode", fail_after_enqueue)
    with pytest.raises(StoreUnavailable):
        store.dispatch_due()
    monkeypatch.setattr(module, "_decode", original)
    assert store.get(saved.schedule_id) == saved
    with database.connect() as conn:
        assert conn.scalar(select(import_tasks.c.run_id).limit(1)) is None
        assert conn.scalar(select(sec_schedule_occurrences.c.sequence).limit(1)) is None


@pytest.mark.parametrize(
    "table", ["sec_schedules", "sec_schedule_commands", "sec_schedule_occurrences"]
)
def test_sql_history_cannot_be_deleted_or_truncated(database: Engine, table: str) -> None:
    store, _, _, saved = prepared(database)
    store.command(
        saved.schedule_id, ScheduleCommand(command_id=uuid4(), expected_revision=0, enabled=True)
    )
    store.dispatch_due()
    for statement in (f"DELETE FROM {table}", f"TRUNCATE {table} CASCADE"):
        with database.begin() as conn, pytest.raises(DBAPIError):
            conn.execute(text(statement))


def test_sql_template_or_unrecorded_control_cannot_change(database: Engine) -> None:
    prepared(database)
    for statement in (
        "UPDATE sec_schedules SET enabled=false",
        "UPDATE sec_schedules SET interval_seconds=7200",
    ):
        with database.begin() as conn, pytest.raises(DBAPIError):
            conn.execute(text(statement))


def test_corrupt_occurrence_binding_fails_closed(database: Engine) -> None:
    store, _, _, saved = prepared(database)
    store.dispatch_due()
    with database.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE sec_schedule_occurrences "
                "DISABLE TRIGGER sec_schedule_occurrences_immutable"
            )
        )
        conn.execute(sec_schedule_occurrences.update().values(skipped_slots=3))
    with pytest.raises(StoreUnavailable):
        store.get(saved.schedule_id)


def test_api_create_guard_and_frozen_retry_without_resolve(database: Engine, monkeypatch) -> None:
    from alphasense import schedule_api as module

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    headers = {"Origin": "http://127.0.0.1", "X-AlphaSense-Panel": "1"}
    payload = {
        "schedule_id": str(uuid4()),
        "symbol": "AAPL",
        "exchange_mic": "XNAS",
        "interval_seconds": 3600,
        "first_run_at": "2026-11-10T00:00:00Z",
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/v1/panel/schedules", json=payload).status_code == 403
        saved = client.post("/v1/panel/schedules", json=payload, headers=headers)
        assert saved.status_code == 200 and saved.json()["enabled"] is False

        def forbidden(*_args, **_kwargs):
            pytest.fail("Frozen retry resolved catalog again")

        monkeypatch.setattr(module, "resolve_analysis_request", forbidden)
        assert (
            client.post("/v1/panel/schedules", json=payload, headers=headers).json() == saved.json()
        )
        assert client.get("/v1/panel/schedules/" + payload["schedule_id"]).status_code == 200
        command = {"command_id": str(uuid4()), "expected_revision": 0, "enabled": True}
        assert client.post(
            "/v1/panel/schedules/" + payload["schedule_id"] + "/commands",
            json=command,
            headers=headers,
        ).json()["enabled"]
        assert (
            client.get("/v1/panel/schedules/" + payload["schedule_id"] + "/occurrences").json()[
                "items"
            ]
            == []
        )


def test_old_schedule_record_reads_keep_task_lookup_count_bounded(
    database: Engine, monkeypatch
) -> None:
    from alphasense import sec_schedules as module

    store, payload, _, saved = prepared(database)
    for hour in range(30):
        instant = payload.first_run_at + timedelta(hours=hour, seconds=1)
        monkeypatch.setattr(module, "_now", lambda _connection, value=instant: value)
        assert len(store.dispatch_due()) == 1
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(database, "before_cursor_execute", capture)
    try:
        record = store.get(saved.schedule_id)
    finally:
        event.remove(database, "before_cursor_execute", capture)
    assert record.last_outcome == "skipped_busy"
    assert len(statements) <= 8
    assert sum("FROM import_tasks" in sql for sql in statements) <= 1
    assert len(store.occurrences(saved.schedule_id, after_sequence=10, limit=5).items) == 5
