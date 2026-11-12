"""Explicit PostgreSQL migrations; credentials come from server environment only."""

import os

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.pool import NullPool

from alphasense.db_schema import metadata


def database_url() -> str:
    raw = os.environ.get("ALPHASENSE_DATABASE_URL")
    if not raw:
        raise RuntimeError("ALPHASENSE_DATABASE_URL is required for migrations")
    try:
        parsed = make_url(raw)
    except Exception:
        raise RuntimeError("Invalid PostgreSQL configuration") from None
    if parsed.drivername != "postgresql+psycopg":
        raise RuntimeError("Migrations require postgresql+psycopg")
    return raw


def run_on_connection(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Migrations require PostgreSQL")
    schema = connection.scalar(text("SELECT current_schema()"))
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema=schema,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        run_on_connection(supplied)
    else:
        engine = create_engine(database_url(), poolclass=NullPool, hide_parameters=True)
        try:
            with engine.begin() as connection:
                run_on_connection(connection)
        finally:
            engine.dispose()
