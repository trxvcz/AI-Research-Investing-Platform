"""The scheduler only dispatches durable intentions, never source/model calls."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from test_document_archive import database as database

from alphasense import sec_scheduler
from alphasense.db import ReportStore
from alphasense.schedule_contracts import ScheduleCreate
from alphasense.sec_contracts import SecImportRequest
from alphasense.sec_import import SecImporter
from alphasense.sec_schedules import ScheduleStore
from alphasense.tasks import TaskStore
from alphasense.worker_sessions import WorkerSessionStore


def test_dispatcher_enqueues_without_executing_provider(database: Engine, monkeypatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Scheduler attempted source execution")

    monkeypatch.setattr(SecImporter, "import_run", forbidden)
    with database.connect() as connection:
        now = connection.scalar(text("SELECT clock_timestamp()"))
    schedule_id = uuid4()
    template = SecImportRequest(
        cik="0000320193",
        symbol="AAPL",
        exchange_mic="XNAS",
        instrument_id=uuid4(),
        run_id=schedule_id,
        pipeline_version="sec-fundamentals-v2",
    )
    ScheduleStore(database).create(
        ScheduleCreate(
            schedule_id=schedule_id,
            symbol="AAPL",
            exchange_mic="XNAS",
            interval_seconds=3600,
            first_run_at=now - timedelta(hours=2, seconds=13),
            enabled=True,
        ),
        template,
    )
    assert sec_scheduler.dispatch_once(database) == 1
    task = TaskStore(database).page().items[0]
    assert task.status == "queued" and task.attempt == 0
    assert TaskStore(database).history(task.run_id).items[0].kind == "created"
    assert sec_scheduler.dispatch_once(database) == 0


def test_once_scheduler_registers_clean_process_session(database: Engine, monkeypatch) -> None:
    monkeypatch.setattr(sec_scheduler, "get_store", lambda: ReportStore(database))
    assert sec_scheduler.main(["--once", "--worker-id", "test-idle-scheduler"]) == 0
    sessions = WorkerSessionStore(database).page(kind="sec_scheduler").items
    assert len(sessions) == 1 and sessions[0].status == "stopped"
    assert sessions[0].stop_reason == "completed"


@pytest.mark.parametrize(
    "argv", [["--batch-size", "0"], ["--batch-size", "21"], ["--poll-seconds", "nan"]]
)
def test_invalid_scheduler_bounds_do_not_start(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as failure:
        sec_scheduler.main(argv)
    assert failure.value.code == 2
