"""Schedule downgrade cannot erase dispatch intentions or scheduler sessions."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_document_archive import ROOT
from test_document_archive import database as database
from test_sec_schedules import prepared

from alphasense.db_schema import MIGRATION_HEAD


def test_empty_downgrade_and_reupgrade(database: Engine) -> None:
    with database.begin() as conn:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0013_import_task_events")
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version"))
            == "0013_import_task_events"
        )
        command.upgrade(cfg, "head")
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


def test_nonempty_schedule_history_cannot_be_removed(database: Engine) -> None:
    store, _, _, saved = prepared(database)
    with database.begin() as conn:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = conn
        with pytest.raises(RuntimeError, match="non-empty schedule history"):
            command.downgrade(cfg, "0013_import_task_events")
    assert store.get(saved.schedule_id) == saved


def test_inflight_task_blocks_downgrade_with_nowait(database: Engine) -> None:
    with database.connect() as writer:
        writer.execute(text("LOCK TABLE import_tasks IN ROW EXCLUSIVE MODE"))
        with database.connect() as migration:
            migration.execute(text("SET statement_timeout='3s'"))
            migration.commit()
            cfg = Config(str(ROOT / "alembic.ini"))
            cfg.attributes["connection"] = migration
            with pytest.raises(DBAPIError) as error:
                command.downgrade(cfg, "0013_import_task_events")
            assert getattr(error.value.orig, "sqlstate", None) == "55P03"
