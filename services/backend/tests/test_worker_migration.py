"""Worker operational rows and immutable claim provenance on PostgreSQL."""

import io
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from test_run_snapshot_migration import instrument, snapshot_model, snapshot_values

from alphasense.db_schema import (
    MIGRATION_HEAD,
    raw_snapshots,
    research_runs,
    run_events,
    run_snapshots,
    worker_claims,
    worker_jobs,
)

ROOT = Path(__file__).resolve().parents[3]
HASH = "a" * 64
GIT = "6d7e7269fe72199c365b157a456ddab399f85e93"


def config(connection: Connection | None = None) -> Config:
    value = Config(str(ROOT / "alembic.ini"))
    if connection is not None:
        value.attributes["connection"] = connection
    return value


@pytest.fixture
def database() -> Iterator[Connection]:
    dsn = os.environ.get("ALPHASENSE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real PostgreSQL requires ALPHASENSE_TEST_DATABASE_URL")
    schema = "worker_migration_" + uuid4().hex
    assert re.fullmatch(r"worker_migration_[a-f0-9]{32}", schema)
    engine = create_engine(dsn, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            command.upgrade(config(connection), "head")
            connection.commit()
            yield connection
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def new_run(
    connection: Connection,
    pipeline: str = "deterministic-research-v1",
    instrument_id: UUID | None = None,
) -> UUID:
    registered_id = instrument_id or instrument(connection).instrument_id
    snapshot = snapshot_model(registered_id)
    connection.execute(raw_snapshots.insert().values(**snapshot_values(snapshot)))
    run_id = uuid4()
    definition = {
        "action": "create",
        "schema_version": "1.0",
        "run_id": str(run_id),
        "instrument_id": str(registered_id),
        "as_of": snapshot.retrieved_at.isoformat(),
        "snapshot_ids": [str(snapshot.snapshot_id)],
        "pipeline_version": pipeline,
    }
    created = connection.scalar(
        research_runs.insert()
        .values(
            run_id=run_id,
            instrument_id=registered_id,
            as_of=snapshot.retrieved_at,
            definition=definition,
        )
        .returning(research_runs.c.created_at)
    )
    connection.execute(
        run_snapshots.insert().values(run_id=run_id, snapshot_id=snapshot.snapshot_id)
    )
    state = {
        key: value for key, value in definition.items() if key not in {"action", "schema_version"}
    }
    state.update(
        data_origin="synthetic",
        sequence=1,
        status="queued",
        current_step="data",
        completed_steps=[],
        error_code=None,
        error_reason=None,
        report_revision_id=None,
        report_status=None,
        created_at=created.isoformat(),
        updated_at=created.isoformat(),
    )
    connection.execute(
        run_events.insert().values(
            run_id=run_id,
            sequence=1,
            event_id=run_id,
            kind="created",
            request=definition,
            state=state,
            created_at=created,
        )
    )
    return run_id


def queued_job(connection: Connection, run_id: UUID) -> None:
    connection.execute(
        worker_jobs.insert().values(
            run_id=run_id,
            status="queued",
            attempts=0,
            worker_id=None,
            lease_token=None,
            lease_expires_at=None,
            implementation_hash=HASH,
            pipeline_git_sha=GIT,
            last_error_code=None,
        )
    )


def claim_values(connection: Connection, run_id: UUID, attempt: int = 1) -> dict[str, Any]:
    now = connection.scalar(text("SELECT clock_timestamp()"))
    return {
        "run_id": run_id,
        "attempt": attempt,
        "lease_token": uuid4(),
        "worker_id": "synthetic-worker",
        "implementation_hash": HASH,
        "pipeline_git_sha": GIT,
        "claimed_at": now,
        "initial_expires_at": now + timedelta(seconds=60),
    }


def update_for_claim(connection: Connection, claim: dict[str, Any]) -> None:
    connection.execute(
        worker_jobs.update()
        .where(worker_jobs.c.run_id == claim["run_id"])
        .values(
            status="running",
            attempts=claim["attempt"],
            lease_token=claim["lease_token"],
            worker_id=claim["worker_id"],
            lease_expires_at=claim["initial_expires_at"],
            updated_at=claim["claimed_at"],
        )
    )


def claimed_job(connection: Connection) -> tuple[UUID, dict[str, Any]]:
    run_id = new_run(connection)
    queued_job(connection, run_id)
    claim = claim_values(connection, run_id)
    update_for_claim(connection, claim)
    connection.execute(worker_claims.insert().values(**claim))
    connection.commit()
    return run_id, claim


def test_offline_upgrade_has_worker_audit_and_both_pipelines(monkeypatch) -> None:
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "postgresql+psycopg://unused/unused")
    output = io.StringIO()
    migration = config()
    migration.output_buffer = output
    command.upgrade(migration, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE worker_jobs" in sql
    assert "CREATE TABLE worker_claims" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "deterministic-research-v1" in sql
    assert "manual-research-v1" in sql


@pytest.mark.postgres
def test_upgrade_preserves_manual_history_and_enables_auto(database: Connection) -> None:
    command.downgrade(config(database), "0003_runs_snapshots")
    database.commit()
    manual_id = new_run(database, pipeline="manual-research-v1")
    database.commit()
    before = database.scalar(select(run_events.c.state))
    registered_id = database.scalar(select(research_runs.c.instrument_id))
    database.commit()
    command.upgrade(config(database), "head")
    database.commit()
    assert (
        database.scalar(select(run_events.c.state).where(run_events.c.run_id == manual_id))
        == before
    )
    auto_id = new_run(database, instrument_id=registered_id)
    assert auto_id != manual_id
    assert database.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


@pytest.mark.postgres
def test_manual_runs_cannot_have_worker_jobs(database: Connection) -> None:
    run_id = new_run(database, pipeline="manual-research-v1")
    with pytest.raises(DBAPIError), database.begin_nested():
        queued_job(database, run_id)


@pytest.mark.postgres
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_claim_history_is_append_only(database: Connection, operation: str) -> None:
    claimed_job(database)
    statement = (
        "UPDATE worker_claims SET worker_id=worker_id"
        if operation == "UPDATE"
        else "DELETE FROM worker_claims"
        if operation == "DELETE"
        else "TRUNCATE worker_claims"
    )
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(text(statement))


@pytest.mark.postgres
def test_commit_requires_claim_for_running_job(database: Connection) -> None:
    run_id = new_run(database)
    queued_job(database, run_id)
    database.commit()
    with pytest.raises(DBAPIError), database.begin_nested():
        update_for_claim(database, claim_values(database, run_id))
        database.execute(text("SET CONSTRAINTS worker_jobs_check_commit IMMEDIATE"))
    assert database.scalar(select(worker_jobs.c.status)) == "queued"


@pytest.mark.postgres
@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "unknown"),
        ("attempts", 4),
        ("worker_id", ""),
        ("implementation_hash", "invalid"),
        ("pipeline_git_sha", "short"),
        ("lease_token", None),
        ("lease_expires_at", None),
    ],
)
def test_running_job_requires_consistent_columns(
    database: Connection, field: str, value: Any
) -> None:
    run_id, _ = claimed_job(database)
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(
            worker_jobs.update().where(worker_jobs.c.run_id == run_id).values(**{field: value})
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    "field,value",
    [
        ("worker_id", "other-worker"),
        ("implementation_hash", "b" * 64),
        ("pipeline_git_sha", "b" * 40),
        ("attempt", 2),
    ],
)
def test_claim_must_match_job_provenance(database: Connection, field: str, value: Any) -> None:
    run_id = new_run(database)
    queued_job(database, run_id)
    database.commit()
    with pytest.raises(DBAPIError), database.begin_nested():
        claim = claim_values(database, run_id)
        update_for_claim(database, claim)
        claim[field] = value
        database.execute(worker_claims.insert().values(**claim))


@pytest.mark.postgres
def test_live_lease_cannot_be_taken_over_and_expired_lease_can(database: Connection) -> None:
    run_id, _ = claimed_job(database)
    next_claim = claim_values(database, run_id, attempt=2)
    with pytest.raises(DBAPIError), database.begin_nested():
        update_for_claim(database, next_claim)
    database.execute(
        worker_jobs.update()
        .where(worker_jobs.c.run_id == run_id)
        .values(
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    database.commit()
    next_claim = claim_values(database, run_id, attempt=2)
    update_for_claim(database, next_claim)
    database.execute(worker_claims.insert().values(**next_claim))
    database.commit()
    assert database.scalar(select(worker_jobs.c.attempts)) == 2
    assert database.scalar(text("SELECT count(*) FROM worker_claims")) == 2


@pytest.mark.postgres
@pytest.mark.parametrize("lease_seconds", [14, 301])
def test_claim_duration_is_bounded(database: Connection, lease_seconds: int) -> None:
    run_id = new_run(database)
    queued_job(database, run_id)
    database.commit()
    with pytest.raises(DBAPIError), database.begin_nested():
        claim = claim_values(database, run_id)
        claim["initial_expires_at"] = claim["claimed_at"] + timedelta(seconds=lease_seconds)
        update_for_claim(database, claim)
        database.execute(worker_claims.insert().values(**claim))


@pytest.mark.postgres
def test_renew_and_terminal_clear_keep_claim_audit(database: Connection) -> None:
    run_id, claim = claimed_job(database)
    database.execute(
        worker_jobs.update()
        .where(worker_jobs.c.run_id == run_id)
        .values(
            lease_expires_at=claim["initial_expires_at"] + timedelta(seconds=10),
            updated_at=database.scalar(text("SELECT clock_timestamp()")),
        )
    )
    database.commit()
    database.execute(
        worker_jobs.update()
        .where(worker_jobs.c.run_id == run_id)
        .values(
            status="completed",
            lease_token=None,
            lease_expires_at=None,
            updated_at=database.scalar(text("SELECT clock_timestamp()")),
        )
    )
    database.commit()
    assert database.scalar(select(worker_jobs.c.status)) == "completed"
    assert database.scalar(select(worker_claims.c.lease_token)) == claim["lease_token"]
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(worker_jobs.update().values(last_error_code="changed-after-terminal"))


@pytest.mark.postgres
def test_empty_downgrade_restores_manual_only_guard(database: Connection) -> None:
    command.downgrade(config(database), "0003_runs_snapshots")
    database.commit()
    with pytest.raises(DBAPIError), database.begin_nested():
        new_run(database)


@pytest.mark.postgres
@pytest.mark.parametrize("claimed", [False, True])
def test_downgrade_refuses_automatic_history(database: Connection, claimed: bool) -> None:
    if claimed:
        claimed_job(database)
    else:
        new_run(database)
        database.commit()
    with pytest.raises(RuntimeError, match="non-empty worker or automatic run history"):
        command.downgrade(config(database), "0003_runs_snapshots")
    database.rollback()
    assert database.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD
