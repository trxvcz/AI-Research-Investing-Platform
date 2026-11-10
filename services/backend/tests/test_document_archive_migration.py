"""Document migration preserves history and enforces review sequence in SQL."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from test_document_archive import ROOT, database, request, review  # noqa: F401

from alphasense.db_schema import MIGRATION_HEAD, document_reviews
from alphasense.document_archive import DocumentArchiveStore


def test_empty_downgrade_and_upgrade(database: Engine) -> None:  # noqa: F811
    with database.begin() as conn:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = conn
        command.downgrade(config, "0009_import_tasks")
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0009_import_tasks"
        command.upgrade(config, "head")
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


def test_nonempty_downgrade_refuses_history_loss(database: Engine) -> None:  # noqa: F811
    original = request()
    DocumentArchiveStore(database).create(original)
    with database.begin() as conn:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = conn
        with pytest.raises(RuntimeError, match="non-empty document history"):
            command.downgrade(config, "0009_import_tasks")
    assert DocumentArchiveStore(database).get(original.archive_id).title == original.title


@pytest.mark.parametrize("change", ["revision", "expected_revision", "command_id"])
def test_direct_insert_cannot_skip_sequence(database: Engine, change: str) -> None:  # noqa: F811
    store = DocumentArchiveStore(database)
    saved = store.create(request())
    event = store.review(saved.archive_id, review())
    with database.connect() as conn:
        row = dict(conn.execute(select(document_reviews)).mappings().one())
    row["revision"] = 2
    row["command_id"] = review().command_id
    row["command"] = review(expected_revision=1, command_id=str(row["command_id"])).model_dump(
        mode="json"
    )
    if change == "revision":
        row["revision"] = 3
    elif change == "expected_revision":
        row["command"]["expected_revision"] = 0
    else:
        row["command"]["command_id"] = str(event.command.command_id)
    with database.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(document_reviews.insert().values(**row))
    assert store.get(saved.archive_id).review_revision == 1
