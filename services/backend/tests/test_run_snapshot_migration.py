"""Real PostgreSQL gates for immutable bytes and manual run event history."""

import base64
import hashlib
import io
import os
import re
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from alphasense.db_schema import (
    MIGRATION_HEAD,
    instruments,
    raw_snapshots,
    report_revisions,
    report_streams,
    research_runs,
    run_events,
    run_snapshots,
)
from alphasense.instrument_contracts import InstrumentCreate
from alphasense.report_contracts import ReportRevision
from alphasense.run_contracts import RunCreate, RunState
from alphasense.snapshot_contracts import SnapshotCreate

ROOT = Path(__file__).resolve().parents[3]


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
    schema = "run_snapshot_test_" + uuid4().hex
    assert re.fullmatch(r"run_snapshot_test_[a-f0-9]{32}", schema)
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


def instrument(connection: Connection) -> InstrumentCreate:
    model = InstrumentCreate.model_validate(
        {
            "schema_version": "1.0",
            "instrument_id": str(uuid4()),
            "symbol": "SYNTH",
            "exchange_mic": "XDEM",
            "currency": "USD",
            "display_name": "Synthetic byte archive",
            "asset_type": "equity",
            "data_origin": "synthetic",
            "as_of": "2024-01-01T00:00:00Z",
            "available_at": "2023-12-31T00:00:00Z",
            "source_id": "synthetic-fixture",
            "source_url": None,
            "license": "generated fixture",
        }
    )
    connection.execute(
        instruments.insert().values(
            **{
                key: getattr(model, key)
                for key in (
                    "instrument_id",
                    "symbol",
                    "exchange_mic",
                    "currency",
                    "asset_type",
                    "data_origin",
                    "as_of",
                    "available_at",
                )
            },
            payload=model.model_dump(mode="json"),
        )
    )
    return model


def snapshot_model(instrument_id: UUID, content: bytes = b" synthetic\x00\xff\n") -> SnapshotCreate:
    return SnapshotCreate.model_validate(
        {
            "schema_version": "1.0",
            "snapshot_id": str(uuid4()),
            "instrument_id": str(instrument_id),
            "data_origin": "synthetic",
            "source_id": "synthetic-fixture",
            "source_url": None,
            "license": "generated fixture",
            "as_of": "2024-02-01T00:00:00Z",
            "available_at": "2024-01-01T00:00:00Z",
            "retrieved_at": "2024-02-02T00:00:00Z",
            "media_type": "application/octet-stream",
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_length": len(content),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
    )


def snapshot_values(model: SnapshotCreate) -> dict[str, Any]:
    return {
        **{
            key: getattr(model, key)
            for key in (
                "snapshot_id",
                "instrument_id",
                "data_origin",
                "source_id",
                "as_of",
                "available_at",
                "retrieved_at",
                "sha256",
                "byte_length",
            )
        },
        "metadata": model.model_dump(mode="json", exclude={"content_base64"}),
        "content": model.raw_bytes(),
    }


def create_run(connection: Connection, model: SnapshotCreate) -> tuple[RunCreate, Any]:
    definition = RunCreate(
        schema_version="1.0",
        run_id=uuid4(),
        instrument_id=model.instrument_id,
        as_of=model.retrieved_at,
        snapshot_ids=[model.snapshot_id],
    )
    created = connection.scalar(
        research_runs.insert()
        .values(
            run_id=definition.run_id,
            instrument_id=definition.instrument_id,
            as_of=definition.as_of,
            definition=definition.model_dump(mode="json"),
        )
        .returning(research_runs.c.created_at)
    )
    return definition, created


def initial_event(definition: RunCreate, created: Any) -> dict[str, Any]:
    state = RunState(
        **definition.model_dump(exclude={"schema_version", "action"}),
        data_origin="synthetic",
        sequence=1,
        status="queued",
        current_step="data",
        completed_steps=[],
        error_code=None,
        error_reason=None,
        report_revision_id=None,
        report_status=None,
        created_at=created,
        updated_at=created,
    )
    return {
        "run_id": definition.run_id,
        "event_id": definition.run_id,
        "sequence": 1,
        "kind": "created",
        "request": definition.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "report_revision_id": None,
        "created_at": created,
    }


def seed_run(connection: Connection) -> tuple[SnapshotCreate, RunCreate, dict[str, Any]]:
    model = snapshot_model(instrument(connection).instrument_id)
    connection.execute(raw_snapshots.insert().values(**snapshot_values(model)))
    definition, created = create_run(connection, model)
    connection.execute(
        run_snapshots.insert().values(
            run_id=definition.run_id,
            snapshot_id=model.snapshot_id,
        )
    )
    event = initial_event(definition, created)
    connection.execute(run_events.insert().values(**event))
    return model, definition, event


def test_offline_sql_contains_digest_and_freeze_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "postgresql+psycopg://unused/unused")
    output = io.StringIO()
    migration = config()
    migration.output_buffer = output
    command.upgrade(migration, "head", sql=True)
    sql = output.getvalue()
    assert "encode(sha256(NEW.content),'hex')" in sql
    assert "octet_length(NEW.content)" in sql
    assert "Run inputs already frozen" in sql
    assert "FOR UPDATE" in sql
    assert "CREATE TABLE raw_snapshots" in sql
    assert "CREATE TABLE run_events" in sql


@pytest.mark.postgres
def test_upgrade_from_0002_preserves_existing_identity(database: Connection) -> None:
    command.downgrade(config(database), "0002_instruments")
    database.commit()
    model = instrument(database)
    original_report = ReportRevision.model_validate_json(
        (ROOT / "services/backend/tests/fixtures/report.synthetic.json").read_text("utf-8")
    )
    database.execute(
        report_streams.insert().values(
            report_id=original_report.report_id,
            instrument_id=original_report.input.instrument_id,
            asset_type=original_report.input.asset_type,
            data_origin=original_report.input.data_origin,
        )
    )
    database.execute(
        report_revisions.insert().values(
            revision_id=original_report.revision_id,
            report_id=original_report.report_id,
            revision=1,
            parent_revision_id=None,
            generated_at_utc=original_report.generated_at_utc,
            checksum=original_report.checksum,
            input_sha256=original_report.input_sha256,
            payload=original_report.model_dump(mode="json"),
        )
    )
    database.commit()
    before = database.scalar(select(instruments.c.payload))
    database.commit()
    command.upgrade(config(database), "head")
    database.commit()
    assert database.scalar(select(instruments.c.payload)) == before
    assert model.instrument_id == database.scalar(select(instruments.c.instrument_id))
    restored = ReportRevision.model_validate(database.scalar(select(report_revisions.c.payload)))
    assert restored == original_report
    assert {"raw_snapshots", "research_runs", "run_snapshots", "run_events"} <= set(
        inspect(database).get_table_names()
    )


@pytest.mark.postgres
def test_exact_binary_bytes_roundtrip(database: Connection) -> None:
    model = snapshot_model(instrument(database).instrument_id)
    connection_values = snapshot_values(model)
    database.execute(raw_snapshots.insert().values(**connection_values))
    stored = database.execute(select(raw_snapshots)).mappings().one()
    assert bytes(stored["content"]) == model.raw_bytes()
    assert stored["sha256"] == hashlib.sha256(bytes(stored["content"])).hexdigest()
    assert "content_base64" not in stored["metadata"]


@pytest.mark.postgres
@pytest.mark.parametrize("case", ["bytes", "length", "hash", "metadata", "origin"])
def test_invalid_snapshot_insert_is_atomic(database: Connection, case: str) -> None:
    model = snapshot_model(instrument(database).instrument_id)
    values = snapshot_values(model)
    if case == "bytes":
        values["content"] = b"different bytes"
    elif case == "length":
        values["byte_length"] += 1
        values["metadata"]["byte_length"] += 1
    elif case == "hash":
        values["sha256"] = values["metadata"]["sha256"] = "0" * 64
    elif case == "metadata":
        values["metadata"]["created_at"] = "2024-01-01T00:00:00Z"
    else:
        values["data_origin"] = values["metadata"]["data_origin"] = "live"
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(raw_snapshots.insert().values(**values))
    assert database.scalar(text("SELECT count(*) FROM raw_snapshots")) == 0


@pytest.mark.postgres
@pytest.mark.parametrize("table", ["raw_snapshots", "research_runs", "run_snapshots", "run_events"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_new_tables_are_append_only(database: Connection, table: str, operation: str) -> None:
    seed_run(database)
    database.commit()
    if operation == "UPDATE":
        field = "snapshot_id" if table == "raw_snapshots" else "run_id"
        statement = f"UPDATE {table} SET {field}={field}"
    elif operation == "DELETE":
        statement = f"DELETE FROM {table}"
    else:
        statement = f"TRUNCATE {table} CASCADE"
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(text(statement))


@pytest.mark.postgres
@pytest.mark.parametrize("case", ["sequence", "event_id", "metadata", "incomplete_bindings"])
def test_initial_event_has_exact_identity_and_frozen_set(database: Connection, case: str) -> None:
    model = snapshot_model(instrument(database).instrument_id)
    database.execute(raw_snapshots.insert().values(**snapshot_values(model)))
    definition, created = create_run(database, model)
    if case != "incomplete_bindings":
        database.execute(
            run_snapshots.insert().values(
                run_id=definition.run_id,
                snapshot_id=model.snapshot_id,
            )
        )
    event = initial_event(definition, created)
    if case == "sequence":
        event["sequence"] = event["state"]["sequence"] = 2
    elif case == "event_id":
        event["event_id"] = uuid4()
    elif case == "metadata":
        event["state"]["data_origin"] = "live"
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(run_events.insert().values(**event))


@pytest.mark.postgres
def test_snapshot_bindings_are_frozen_after_initial_event(database: Connection) -> None:
    model, definition, _ = seed_run(database)
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(
            run_snapshots.insert().values(
                run_id=definition.run_id,
                snapshot_id=model.snapshot_id,
            )
        )


@pytest.mark.postgres
@pytest.mark.parametrize("case", ["sequence", "request_id", "expected_sequence", "state"])
def test_event_sequence_and_request_metadata_are_checked(database: Connection, case: str) -> None:
    _, _, initial = seed_run(database)
    event = deepcopy(initial)
    event.update(sequence=2, event_id=uuid4(), kind="start")
    event["request"] = {
        "action": "start",
        "request_id": str(event["event_id"]),
        "expected_sequence": 1,
        "actor": "synthetic-operator",
    }
    event["state"].update(sequence=2, status="running")
    if case == "sequence":
        event["sequence"] = event["state"]["sequence"] = 3
    elif case == "request_id":
        event["request"]["request_id"] = str(uuid4())
    elif case == "expected_sequence":
        event["request"]["expected_sequence"] = 2
    else:
        event["state"]["instrument_id"] = str(uuid4())
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(run_events.insert().values(**event))


@pytest.mark.postgres
def test_empty_downgrade_and_reupgrade(database: Connection) -> None:
    command.downgrade(config(database), "0002_instruments")
    database.commit()
    assert "raw_snapshots" not in inspect(database).get_table_names()
    command.upgrade(config(database), "head")
    database.commit()
    assert database.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


@pytest.mark.postgres
def test_nonempty_downgrade_is_refused(database: Connection) -> None:
    seed_run(database)
    database.commit()
    with pytest.raises(RuntimeError, match="non-empty research evidence"):
        command.downgrade(config(database), "0002_instruments")
    database.rollback()
    assert database.scalar(text("SELECT count(*) FROM run_events")) == 1


@pytest.mark.postgres
def test_downgrade_refuses_inflight_snapshot_without_dropping_data(database: Connection) -> None:
    model = snapshot_model(instrument(database).instrument_id)
    database.commit()
    schema = database.scalar(text("SELECT current_schema()"))
    assert re.fullmatch(r"run_snapshot_test_[a-f0-9]{32}", schema)
    database.execute(text("SET statement_timeout = '3s'"))
    database.commit()
    with database.engine.connect() as writer:
        writer.execute(text(f'SET search_path TO "{schema}"'))
        writer.commit()
        writer.execute(raw_snapshots.insert().values(**snapshot_values(model)))
        with pytest.raises(DBAPIError) as error:
            command.downgrade(config(database), "0002_instruments")
        assert getattr(error.value.orig, "sqlstate", None) == "55P03", "NOWAIT must refuse the lock"
        database.rollback()
        writer.commit()
    assert database.scalar(text("SELECT count(*) FROM raw_snapshots")) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("length", [0, 1048577])
def test_database_enforces_byte_length_bounds(database: Connection, length: int) -> None:
    model = snapshot_model(instrument(database).instrument_id)
    values = snapshot_values(model)
    content = b"x" * length
    values.update(content=content, byte_length=length, sha256=hashlib.sha256(content).hexdigest())
    values["metadata"].update(byte_length=length, sha256=values["sha256"])
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(raw_snapshots.insert().values(**values))


@pytest.mark.postgres
@pytest.mark.parametrize("case", ["unknown_availability", "future_cutoff", "undeclared_snapshot"])
def test_snapshot_binding_requires_declared_point_in_time_evidence(
    database: Connection, case: str
) -> None:
    model = snapshot_model(instrument(database).instrument_id)
    values = snapshot_values(model)
    if case == "unknown_availability":
        values["available_at"] = values["metadata"]["available_at"] = None
    elif case == "future_cutoff":
        values["as_of"] = model.as_of.replace(day=3)
        values["metadata"]["as_of"] = "2024-02-03T00:00:00Z"
    database.execute(raw_snapshots.insert().values(**values))
    definition, _ = create_run(database, model)
    if case == "undeclared_snapshot":
        extra = snapshot_model(model.instrument_id, b"other bytes")
        database.execute(raw_snapshots.insert().values(**snapshot_values(extra)))
        target = extra.snapshot_id
    else:
        target = model.snapshot_id
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(
            run_snapshots.insert().values(run_id=definition.run_id, snapshot_id=target)
        )
