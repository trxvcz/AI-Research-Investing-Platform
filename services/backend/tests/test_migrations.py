"""Real PostgreSQL migration/trigger gates, isolated from user-owned schemas."""

import io
import json
import os
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from alphasense.db_schema import (
    MIGRATION_HEAD,
    metadata,
    report_revisions,
    report_streams,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / "fixtures" / "report.synthetic.json"


def migration_config(connection: Connection | None = None) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


@pytest.fixture
def migrated() -> Iterator[Connection]:
    dsn = os.environ.get("ALPHASENSE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real PostgreSQL requires ALPHASENSE_TEST_DATABASE_URL")
    engine = create_engine(dsn, hide_parameters=True)
    schema = "migration_test_" + uuid4().hex
    assert re.fullmatch(r"migration_test_[a-f0-9]{32}", schema)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            command.upgrade(migration_config(connection), "head")
            connection.commit()
            yield connection
    finally:
        # Only the fresh, UUID-named test schema can reach this cleanup target.
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def insert_report(connection: Connection, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if payload is None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    connection.execute(
        report_streams.insert().values(
            report_id=payload["report_id"],
            instrument_id=payload["input"]["instrument_id"],
            asset_type=payload["input"]["asset_type"],
            data_origin=payload["input"]["data_origin"],
        )
    )
    insert_revision(connection, payload)
    return payload


def insert_revision(connection: Connection, payload: dict[str, Any]) -> None:
    connection.execute(
        report_revisions.insert().values(
            revision_id=payload["revision_id"],
            report_id=payload["report_id"],
            revision=payload["revision"],
            parent_revision_id=payload["parent_revision_id"],
            generated_at_utc=payload["generated_at_utc"],
            checksum=payload["checksum"],
            input_sha256=payload["input_sha256"],
            payload=payload,
        )
    )


def test_offline_upgrade_contains_append_only_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "postgresql+psycopg://unused/unused")
    output = io.StringIO()
    config = migration_config()
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE report_streams" in sql
    assert "CREATE TABLE report_revisions" in sql
    assert "FOR UPDATE" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "BEFORE TRUNCATE" in sql
    assert "fk_revision_parent_same_report" in sql


@pytest.mark.postgres
def test_downgrade_waits_for_append_then_refuses_nonempty_history(migrated: Connection) -> None:
    # Test the historical 0001 guard itself, independent of later migration locks.
    command.downgrade(migration_config(migrated), "0001_report_store")
    migrated.commit()
    schema = migrated.scalar(text("SELECT current_schema()"))
    assert re.fullmatch(r"migration_test_[a-f0-9]{32}", schema)
    migrated.commit()

    def downgrade() -> str:
        with migrated.engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            try:
                command.downgrade(migration_config(connection), "base")
            except RuntimeError as error:
                assert "non-empty" in str(error)
                return "refused"
        return "removed"

    with migrated.engine.connect() as writer:
        writer.execute(text(f'SET search_path TO "{schema}"'))
        writer.commit()
        insert_report(writer)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(downgrade)
            try:
                waiting = False
                for _ in range(100):
                    waiting = bool(
                        migrated.scalar(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE NOT granted "
                                "AND mode='AccessExclusiveLock' "
                                "AND relation='report_streams'::regclass)"
                            )
                        )
                    )
                    if waiting:
                        break
                    time.sleep(0.02)
                assert waiting, "downgrade must wait for the in-flight append lock"
                migrated.commit()
                writer.commit()
                assert future.result(timeout=5) == "refused"
            finally:
                writer.rollback()
    assert migrated.scalar(text("SELECT count(*) FROM report_revisions")) == 1


@pytest.mark.postgres
def test_upgrade_is_repeatable_and_metadata_matches(migrated: Connection) -> None:
    command.upgrade(migration_config(migrated), "head")
    migrated.commit()
    assert migrated.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD
    assert {"report_streams", "report_revisions"} <= set(inspect(migrated).get_table_names())
    diffs = compare_metadata(MigrationContext.configure(migrated), metadata)
    assert diffs == []


@pytest.mark.postgres
def test_empty_downgrade_and_upgrade_are_safe(migrated: Connection) -> None:
    command.downgrade(migration_config(migrated), "base")
    migrated.commit()
    assert "report_revisions" not in inspect(migrated).get_table_names()
    command.upgrade(migration_config(migrated), "head")
    migrated.commit()
    assert migrated.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


@pytest.mark.postgres
def test_nonempty_history_cannot_be_downgraded(migrated: Connection) -> None:
    insert_report(migrated)
    migrated.commit()
    with pytest.raises(RuntimeError, match="non-empty"):
        command.downgrade(migration_config(migrated), "base")
    migrated.rollback()
    assert migrated.scalar(text("SELECT count(*) FROM report_revisions")) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("table", ["report_streams", "report_revisions"])
@pytest.mark.parametrize("operation", ["update", "delete", "truncate"])
def test_direct_mutation_is_blocked(migrated: Connection, table: str, operation: str) -> None:
    insert_report(migrated)
    if operation == "update":
        key = "report_id" if table == "report_streams" else "revision_id"
        statement = f"UPDATE {table} SET {key}={key}"
    elif operation == "delete":
        statement = f"DELETE FROM {table}"
    else:
        statement = f"TRUNCATE {table} CASCADE"
    with pytest.raises(DBAPIError), migrated.begin_nested():
        migrated.execute(text(statement))
    assert migrated.scalar(text("SELECT count(*) FROM report_revisions")) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("case", ["skip", "wrong_parent", "time", "identity", "metadata"])
def test_direct_insert_cannot_bypass_history_rules(migrated: Connection, case: str) -> None:
    first = insert_report(migrated)
    following = deepcopy(first)
    following.update(revision=2, revision_id=str(uuid4()), parent_revision_id=first["revision_id"])
    if case == "skip":
        following["revision"] = 3
    elif case == "wrong_parent":
        following["parent_revision_id"] = str(uuid4())
    elif case == "time":
        following["generated_at_utc"] = "2024-02-01T00:00:00Z"
    elif case == "identity":
        following["input"]["instrument_id"] = "OTHER"
    else:
        following["report_id"] = following["revision_id"]
        # The passed row still belongs to the first report stream.
        with pytest.raises(DBAPIError), migrated.begin_nested():
            migrated.execute(
                report_revisions.insert().values(
                    revision_id=following["revision_id"],
                    report_id=first["report_id"],
                    revision=2,
                    parent_revision_id=first["revision_id"],
                    generated_at_utc=following["generated_at_utc"],
                    checksum=following["checksum"],
                    input_sha256=following["input_sha256"],
                    payload=following,
                )
            )
        return
    with pytest.raises(DBAPIError), migrated.begin_nested():
        insert_revision(migrated, following)


@pytest.mark.postgres
def test_valid_second_insert_preserves_both_revisions(migrated: Connection) -> None:
    first = insert_report(migrated)
    following = deepcopy(first)
    following.update(revision=2, revision_id=str(uuid4()), parent_revision_id=first["revision_id"])
    insert_revision(migrated, following)
    assert migrated.scalar(text("SELECT count(*) FROM report_revisions")) == 2
