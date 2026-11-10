"""Task migration keeps existing document archives intact and refuses history loss."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from test_document_archive import ROOT, request
from test_document_archive import database as database
from test_document_tasks import queued

from alphasense.db_schema import MIGRATION_HEAD
from alphasense.document_archive import DocumentArchiveStore


def test_empty_downgrade_preserves_archive_and_reupgrade(database: Engine):
    source = DocumentArchiveStore(database).create(request())
    with database.begin() as conn:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0010_document_archive")
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version")) == "0010_document_archive"
        )
        command.upgrade(cfg, "head")
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD
    assert DocumentArchiveStore(database).get(source.archive_id) == source


def test_nonempty_downgrade_refuses_task_loss(database: Engine):
    tasks, _, saved = queued(database)
    with database.begin() as conn:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = conn
        with pytest.raises(RuntimeError, match="non-empty document task history"):
            command.downgrade(cfg, "0010_document_archive")
    assert tasks.get(saved.job_id) == saved
