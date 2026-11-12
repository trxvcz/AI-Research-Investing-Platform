"""Session history cannot be removed, including an in-flight registration."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_document_archive import ROOT
from test_document_archive import database as database
from test_worker_sessions import start

from alphasense.db_schema import MIGRATION_HEAD
from alphasense.worker_sessions import WorkerSessionStore


def test_empty_downgrade_upgrade(database: Engine) -> None:
    with database.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0011_document_tasks")
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


def test_nonempty_downgrade_refuses_history_loss(database: Engine) -> None:
    saved = WorkerSessionStore(database).start(start())
    with database.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="non-empty worker session history"):
            command.downgrade(config, "0011_document_tasks")
    assert WorkerSessionStore(database).get(saved.session_id).worker_id == saved.worker_id


def test_inflight_start_causes_nowait_refusal(database: Engine) -> None:
    saved = WorkerSessionStore(database).start(start())
    with database.connect() as writer:
        writer.execute(text("UPDATE worker_sessions SET heartbeat_at=heartbeat_at"))
        with database.connect() as migration:
            migration.execute(text("SET statement_timeout='3s'"))
            migration.commit()
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = migration
            with pytest.raises(DBAPIError) as error:
                command.downgrade(config, "0011_document_tasks")
            assert getattr(error.value.orig, "sqlstate", None) == "55P03"
            migration.rollback()
        writer.rollback()
    assert WorkerSessionStore(database).get(saved.session_id).worker_id == saved.worker_id
