"""Integration checks require real PostgreSQL; no SQLite substitute."""

import getpass
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alphasense.db import (
    CorruptReport,
    ReportNotFound,
    ReportStore,
    RevisionConflict,
    StoreUnavailable,
    UnstorableReport,
    create_postgres_engine,
)
from alphasense.report_contracts import ReportContent, ReportRevision, seal_report

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = Path(__file__).parent / "fixtures/report.synthetic.json"


def sample(report_id: UUID | None = None) -> ReportRevision:
    payload = json.loads(SAMPLE.read_text("utf-8"))
    payload.pop("checksum")
    payload.pop("input_sha256")
    payload["report_id"] = str(report_id or uuid4())
    payload["revision_id"] = str(uuid4())
    return seal_report(ReportContent.model_validate(payload))


def next_revision(previous: ReportRevision) -> ReportRevision:
    payload = previous.model_dump(mode="json", exclude={"checksum", "input_sha256"})
    payload.update(
        revision=previous.revision + 1,
        revision_id=str(uuid4()),
        parent_revision_id=str(previous.revision_id),
    )
    return seal_report(ReportContent.model_validate(payload))


@pytest.fixture
def database() -> Iterator[tuple[Engine, str]]:
    dsn = os.environ.get("ALPHASENSE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real PostgreSQL requires ALPHASENSE_TEST_DATABASE_URL")
    schema = "store_test_" + uuid4().hex
    assert re.fullmatch(r"store_test_[a-f0-9]{32}", schema)
    admin = create_engine(dsn, hide_parameters=True)
    engine = create_engine(
        dsn, hide_parameters=True, connect_args={"options": f"-c search_path={schema}"}
    )
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.begin() as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine, schema
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_non_postgres_configuration_is_rejected() -> None:
    with pytest.raises(StoreUnavailable):
        create_postgres_engine("sqlite:///private.db")


@pytest.mark.postgres
def test_nul_text_is_invalid_data_not_a_storage_outage(database: tuple[Engine, str]) -> None:
    store = ReportStore(database[0])
    report = sample()
    payload = report.model_dump(mode="json", exclude={"checksum", "input_sha256"})
    payload["limitations"] = ["Synthetic \x00 marker"]
    sealed = seal_report(ReportContent.model_validate(payload))
    with pytest.raises(UnstorableReport):
        store.append(sealed)
    with pytest.raises(ReportNotFound):
        store.list_revisions(report.report_id)


@pytest.mark.postgres
def test_signed_zero_survives_jsonb_roundtrip(database: tuple[Engine, str]) -> None:
    payload = sample().model_dump(mode="json", exclude={"checksum", "input_sha256"})
    payload["input"]["observations"][0]["value"] = -0.0
    report = seal_report(ReportContent.model_validate(payload))
    store = ReportStore(database[0])
    store.append(report)
    assert store.get_report(report.report_id).checksum == report.checksum


@pytest.mark.postgres
def test_persists_across_new_engine_and_retry_is_idempotent(database: tuple[Engine, str]) -> None:
    engine, schema = database
    report = sample()
    store = ReportStore(engine)
    store.check_ready()
    assert store.append(report).created is True
    assert store.append(report).created is False
    other = create_engine(
        engine.url, hide_parameters=True, connect_args={"options": f"-c search_path={schema}"}
    )
    try:
        assert ReportStore(other).get_report(report.report_id) == report
    finally:
        other.dispose()


@pytest.mark.postgres
def test_history_and_cursor_preserve_all_revisions(database: tuple[Engine, str]) -> None:
    store = ReportStore(database[0])
    first = sample()
    second = next_revision(first)
    third = next_revision(second)
    for report in [first, second, third]:
        store.append(report)
    assert store.get_report(first.report_id) == third
    assert store.get_report(first.report_id, 1) == first
    assert store.append(first).created is False
    page = store.list_revisions(first.report_id, limit=2)
    assert [item.revision for item in page.items] == [1, 2]
    assert page.next_after_revision == 2
    last = store.list_revisions(first.report_id, after_revision=2, limit=2)
    assert [item.revision for item in last.items] == [3]
    assert last.next_after_revision is None
    assert store.list_revisions(first.report_id, after_revision=3).items == []


@pytest.mark.postgres
@pytest.mark.parametrize("case", ["rewrite", "branch", "skip", "instrument", "origin", "time"])
def test_conflicts_leave_existing_report_untouched(database: tuple[Engine, str], case: str) -> None:
    store = ReportStore(database[0])
    first = sample()
    second = next_revision(first)
    store.append(first)
    store.append(second)
    payload = next_revision(second).model_dump(mode="json", exclude={"checksum", "input_sha256"})
    if case == "rewrite":
        payload = first.model_dump(mode="json", exclude={"checksum", "input_sha256"})
        payload["limitations"] = ["Changed revision identity"]
    elif case == "branch":
        payload["parent_revision_id"] = str(first.revision_id)
    elif case == "skip":
        payload["revision"] = 4
    elif case == "instrument":
        payload["input"]["instrument_id"] = "OTHER-INSTRUMENT"
    elif case == "origin":
        # Both identities can be valid independent reports; stream cannot switch.
        payload["input"]["data_origin"] = "live"
        payload["sources"][0]["url"] = "https://example.invalid/synthetic-fixture"
    else:
        payload["generated_at_utc"] = "2024-02-01T00:00:00Z"
    conflict = seal_report(ReportContent.model_validate(payload))
    with pytest.raises(RevisionConflict):
        store.append(conflict)
    assert store.get_report(first.report_id) == second
    assert len(store.list_revisions(first.report_id).items) == 2


@pytest.mark.postgres
def test_global_revision_id_conflict_rolls_back_new_stream(database: tuple[Engine, str]) -> None:
    store = ReportStore(database[0])
    first = sample()
    store.append(first)
    payload = first.model_dump(mode="json", exclude={"checksum", "input_sha256"})
    other_id = uuid4()
    payload["report_id"] = str(other_id)
    with pytest.raises(RevisionConflict):
        store.append(seal_report(ReportContent.model_validate(payload)))
    with pytest.raises(ReportNotFound):
        store.list_revisions(other_id)


@pytest.mark.postgres
@pytest.mark.parametrize("identical", [False, True])
def test_concurrent_appends_are_linear(database: tuple[Engine, str], identical: bool) -> None:
    store = ReportStore(database[0])
    first = sample()
    store.append(first)
    second = next_revision(first)
    candidates = [second, second if identical else next_revision(first)]
    barrier = Barrier(2)

    def append(report: ReportRevision) -> str:
        barrier.wait(timeout=10)
        try:
            return "created" if store.append(report).created else "retry"
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, candidates))
    assert sorted(results) == sorted(["created", "retry" if identical else "conflict"])
    assert [item.revision for item in store.list_revisions(first.report_id).items] == [1, 2]


@pytest.mark.postgres
def test_missing_records_and_missing_schema_fail_closed(database: tuple[Engine, str]) -> None:
    store = ReportStore(database[0])
    with pytest.raises(ReportNotFound):
        store.get_report(uuid4())
    with pytest.raises(ReportNotFound):
        store.list_revisions(uuid4())
    with database[0].begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='unexpected'"))
    with pytest.raises(StoreUnavailable):
        store.check_ready()


@pytest.mark.postgres
def test_read_detects_corruption_even_if_owner_bypasses_trigger(
    database: tuple[Engine, str],
) -> None:
    engine = database[0]
    store = ReportStore(engine)
    report = sample()
    store.append(report)
    # Test-only simulation by the schema owner, who can disable DB protections.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE report_revisions DISABLE TRIGGER USER"))
        connection.execute(
            text("UPDATE report_revisions SET checksum=:checksum"), {"checksum": "0" * 64}
        )
        connection.execute(text("ALTER TABLE report_revisions ENABLE TRIGGER USER"))
    with pytest.raises(CorruptReport):
        store.get_report(report.report_id)
    with pytest.raises(CorruptReport):
        store.list_revisions(report.report_id)


@pytest.mark.postgres
def test_pg_dump_restore_preserves_checksums(database: tuple[Engine, str], tmp_path: Path) -> None:
    from test_document_archive import request as document_request
    from test_document_archive import review as review_command

    from alphasense.document_archive import DocumentArchiveStore
    from alphasense.document_task_contracts import DocumentTaskCreate
    from alphasense.document_task_worker import implementation_fingerprint, process_document_once
    from alphasense.document_tasks import DocumentTaskStore
    from alphasense.schedule_contracts import ScheduleCommand, ScheduleCreate
    from alphasense.sec_contracts import SecImportRequest
    from alphasense.sec_schedules import ScheduleStore
    from alphasense.tasks import TaskStore
    from alphasense.worker_session_contracts import WorkerSessionStart
    from alphasense.worker_sessions import WorkerSessionStore

    engine, schema = database
    tools = os.environ.get("ALPHASENSE_PG_BIN", "")
    suffix = ".exe" if os.name == "nt" else ""
    dump_tool = str(Path(tools) / ("pg_dump" + suffix)) if tools else shutil.which("pg_dump")
    restore_tool = str(Path(tools) / ("psql" + suffix)) if tools else shutil.which("psql")
    if not dump_tool or not restore_tool:
        pytest.skip("pg_dump/psql are required for backup verification")
    from alphasense.instrument_contracts import InstrumentCreate
    from alphasense.instruments import InstrumentStore
    from alphasense.run_contracts import (
        STEPS,
        RunAdvance,
        RunCreate,
        RunFail,
        RunFinish,
        RunResume,
        RunStart,
    )
    from alphasense.runs import ResearchStore
    from alphasense.snapshot_contracts import SnapshotCreate
    from alphasense.snapshots import SnapshotStore

    registry_payload = json.loads((SAMPLE.parent / "instrument.synthetic.json").read_text("utf-8"))
    registry_payload["instrument_id"] = str(uuid4())
    registered = InstrumentStore(engine).create(InstrumentCreate.model_validate(registry_payload))
    document_store = DocumentArchiveStore(engine)
    imported = document_store.create(document_request(instrument_id=str(registered.instrument_id)))
    document_decision = review_command()
    decision = document_store.review(imported.archive_id, document_decision)
    document_checkpoint = document_store.get(imported.archive_id)
    original_document = document_store.content(imported.archive_id)
    document_jobs = DocumentTaskStore(engine)
    document_job = document_jobs.create(
        DocumentTaskCreate(job_id=uuid4(), archive_id=imported.archive_id)
    )
    assert document_jobs.claim("before-backup", implementation_fingerprint()) is not None
    document_job_checkpoint = document_jobs.detail(document_job.job_id)
    sessions = WorkerSessionStore(engine)
    session = sessions.start(
        WorkerSessionStart(
            session_id=uuid4(),
            worker_id="backup-session",
            kind="document_validation",
            mode="once",
            process_id=1,
            implementation_sha256="a" * 64,
        )
    )
    sessions.heartbeat(session.session_id)
    session_checkpoint = sessions.stop(session.session_id, "completed")
    with engine.connect() as connection:
        schedule_start = connection.scalar(text("SELECT clock_timestamp()-INTERVAL '2 hours'"))
    schedule_id = uuid4()
    schedule_template = SecImportRequest(
        cik="0000320193",
        symbol="AAPL",
        exchange_mic="XNAS",
        instrument_id=uuid4(),
        run_id=schedule_id,
        pipeline_version="sec-fundamentals-v2",
    )
    schedules = ScheduleStore(engine)
    schedules.create(
        ScheduleCreate(
            schedule_id=schedule_id,
            symbol="AAPL",
            exchange_mic="XNAS",
            interval_seconds=3600,
            first_run_at=schedule_start,
            enabled=True,
        ),
        schedule_template,
    )
    schedule_receipt = schedules.dispatch_due()[0]
    schedule_checkpoint = schedules.get(schedule_id)
    schedule_history = schedules.occurrences(schedule_id)
    task_history = TaskStore(engine).history(schedule_receipt.run_id)
    snapshot_data = json.loads((SAMPLE.parent / "snapshot.synthetic.json").read_text("utf-8"))
    snapshot_data.update(snapshot_id=str(uuid4()), instrument_id=str(registered.instrument_id))
    uploaded = SnapshotCreate.model_validate(snapshot_data)
    archived = SnapshotStore(engine).create(uploaded)
    report_payload = sample().model_dump(mode="json", exclude={"checksum", "input_sha256"})
    report_payload["input"]["instrument_id"] = str(registered.instrument_id)
    report_payload["input"]["observations"][0]["snapshot_id"] = str(archived.snapshot_id)
    report_payload["sources"][0]["snapshot_id"] = str(archived.snapshot_id)
    report = seal_report(ReportContent.model_validate(report_payload))
    ReportStore(engine).append(report)
    ledger = ResearchStore(engine)
    definition = RunCreate(
        schema_version="1.0",
        run_id=uuid4(),
        instrument_id=registered.instrument_id,
        as_of=report.input.as_of,
        snapshot_ids=[archived.snapshot_id],
    )
    state = ledger.create(definition)

    def command_fields():
        return {"request_id": uuid4(), "expected_sequence": state.sequence, "actor": "restore-test"}

    state = ledger.apply(definition.run_id, RunStart(action="start", **command_fields())).state
    state = ledger.apply(
        definition.run_id, RunAdvance(action="advance", step="data", **command_fields())
    ).state
    state = ledger.apply(
        definition.run_id,
        RunFail(
            action="fail",
            step="validate",
            error_code="TEST_FAILURE",
            reason="Synthetic restore checkpoint",
            **command_fields(),
        ),
    ).state
    target = "restore_test_" + uuid4().hex
    assert re.fullmatch(r"restore_test_[a-f0-9]{32}", target)
    url = make_url(str(engine.url.render_as_string(hide_password=False)))
    env = os.environ.copy()
    env.update(
        PGHOST=url.host or "",
        PGPORT=str(url.port or 5432),
        PGUSER=url.username or getpass.getuser(),
        PGPASSWORD=url.password or "",
        PGDATABASE=url.database or "postgres",
    )
    archive = tmp_path / "report-store.sql"

    def run_tool(arguments: list[str]) -> None:
        try:
            subprocess.run(arguments, env=env, check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as error:
            # Avoid a subprocess traceback displaying its credential-bearing env.
            pytest.fail(f"Backup command failed ({type(error).__name__})", pytrace=False)

    run_tool([dump_tool, "--format=plain", "--schema", schema, "--file", str(archive)])
    admin = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    restored = create_engine(
        url.set(database=target),
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema}"},
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{target}"'))
        env["PGDATABASE"] = target
        run_tool(
            [
                restore_tool,
                "--no-psqlrc",
                "--set",
                "ON_ERROR_STOP=1",
                "--dbname",
                target,
                "--file",
                str(archive),
            ]
        )
        assert ReportStore(restored).get_report(report.report_id).checksum == report.checksum
        assert ReportStore(restored).get_report(report.report_id) == report
        assert InstrumentStore(restored).get(registered.instrument_id).symbol == registered.symbol
        assert SnapshotStore(restored).content(archived.snapshot_id)[1] == uploaded.raw_bytes()
        restored_documents = DocumentArchiveStore(restored)
        restored_schedules = ScheduleStore(restored)
        assert restored_schedules.get(schedule_id) == schedule_checkpoint
        assert restored_schedules.occurrences(schedule_id) == schedule_history
        assert TaskStore(restored).history(schedule_receipt.run_id) == task_history
        assert restored_schedules.dispatch_due() == []
        pause_schedule = ScheduleCommand(command_id=uuid4(), expected_revision=0, enabled=False)
        assert restored_schedules.command(schedule_id, pause_schedule).revision == 1
        assert restored_schedules.command(schedule_id, pause_schedule).enabled is False
        restored_session = WorkerSessionStore(restored).get(session.session_id)
        assert restored_session.model_dump(
            exclude={"observed_at"}
        ) == session_checkpoint.model_dump(exclude={"observed_at"})
        assert restored_documents.get(imported.archive_id) == document_checkpoint
        assert restored_documents.content(imported.archive_id) == original_document
        assert restored_documents.review(imported.archive_id, document_decision) == decision
        revised_decision = restored_documents.review(
            imported.archive_id, review_command(expected_revision=1, verdict="rejected")
        )
        assert revised_decision.revision == 2
        assert restored_documents.get(imported.archive_id).reviews[0] == decision
        restored_document_jobs = DocumentTaskStore(restored)
        assert restored_document_jobs.detail(document_job.job_id) == document_job_checkpoint
        with restored.begin() as connection:
            connection.execute(
                text(
                    "UPDATE document_tasks "
                    "SET lease_expires_at=clock_timestamp()-INTERVAL '1 second' "
                    "WHERE job_id=:job_id"
                ),
                {"job_id": document_job.job_id},
            )
        assert process_document_once(restored, "after-restore")
        recovered_document_job = restored_document_jobs.detail(document_job.job_id)
        assert recovered_document_job.task.status == "completed"
        assert recovered_document_job.task.attempt == 2
        assert [audit.outcome for audit in recovered_document_job.audits] == [
            "interrupted",
            "completed",
        ]
        assert recovered_document_job.task.result == document_checkpoint.result
        with restored.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(text("TRUNCATE document_reviews"))
        restored_ledger = ResearchStore(restored)
        state = restored_ledger.get(definition.run_id)
        assert state.status == "failed" and state.completed_steps == ["data"]
        state = restored_ledger.apply(
            definition.run_id, RunResume(action="resume", **command_fields())
        ).state
        for step in STEPS[1:-1]:
            state = restored_ledger.apply(
                definition.run_id, RunAdvance(action="advance", step=step, **command_fields())
            ).state
        state = restored_ledger.apply(
            definition.run_id,
            RunFinish(action="finish", report_revision_id=report.revision_id, **command_fields()),
        ).state
        assert state.status == "completed" and state.report_status == "partial"
        from alphasense.db_schema import report_streams

        with restored.connect() as connection:
            assert (
                connection.scalar(
                    select(report_streams.c.registry_instrument_id).where(
                        report_streams.c.report_id == report.report_id
                    )
                )
                == registered.instrument_id
            )
    finally:
        restored.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.postgres
def test_http_roundtrip_uses_real_store(database: tuple[Engine, str], monkeypatch) -> None:
    import alphasense.api as api
    from alphasense.db import get_store

    store = ReportStore(database[0])
    first = sample()
    second = next_revision(first)
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "configured-test-store")
    monkeypatch.setattr(api, "get_store", lambda: store)
    api.app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(api.app) as client:
            assert client.get("/ready").json()["mode"] == "postgresql"
            assert client.post("/v1/reports", json=first.model_dump(mode="json")).status_code == 201
            assert client.post("/v1/reports", json=first.model_dump(mode="json")).status_code == 200
            assert (
                client.post("/v1/reports", json=second.model_dump(mode="json")).status_code == 201
            )
            latest = client.get(f"/v1/reports/{first.report_id}")
            assert latest.status_code == 200
            assert latest.json() == second.model_dump(mode="json")
            old = client.get(f"/v1/reports/{first.report_id}/revisions/1")
            assert old.json() == first.model_dump(mode="json")
            page = client.get(f"/v1/reports/{first.report_id}/revisions?limit=1")
            assert page.json()["next_after_revision"] == 1
    finally:
        api.app.dependency_overrides.clear()
