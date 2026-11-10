# Explicit report-store migrations

Run from the repository root with ALPHASENSE_DATABASE_URL set server-side:

    python -m alembic upgrade head

The URL must use postgresql+psycopg. No URL or credentials are stored in alembic.ini.
Migration 0001_report_store creates append-only report history. Downgrade is refused
when either table contains rows. It is never a report-deletion command.

Tests can pass an already-open connection through Config.attributes["connection"];
its current schema is used for the migration and version table. Only isolated
schemas created by tests are removed during cleanup. No migration runs at API start.
