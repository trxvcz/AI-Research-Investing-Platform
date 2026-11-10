"""Immutable instrument registry without retroactive report changes.

Revision ID: 0002_instruments
Revises: 0001_report_store
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_instruments"
down_revision = "0001_report_store"
branch_labels = None
depends_on = None

CHECK_INSTRUMENT_SQL = """
CREATE FUNCTION instruments_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.payload->>'schema_version' IS DISTINCT FROM '1.0'
       OR NEW.payload->>'instrument_id' IS DISTINCT FROM NEW.instrument_id::text
       OR NEW.payload->>'symbol' IS DISTINCT FROM NEW.symbol
       OR NEW.payload->>'exchange_mic' IS DISTINCT FROM NEW.exchange_mic
       OR NEW.payload->>'currency' IS DISTINCT FROM NEW.currency
       OR NEW.payload->>'asset_type' IS DISTINCT FROM NEW.asset_type
       OR NEW.payload->>'data_origin' IS DISTINCT FROM NEW.data_origin
       OR (NEW.payload->>'as_of')::timestamptz IS DISTINCT FROM NEW.as_of
       OR (NEW.payload->>'available_at')::timestamptz IS DISTINCT FROM NEW.available_at THEN
        RAISE EXCEPTION 'Instrument metadata mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""

DENY_MUTATION_SQL = """
CREATE FUNCTION instruments_deny_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'Instrument identity is immutable' USING ERRCODE = '23514';
END;
$$
"""

CHECK_STREAM_SQL = """
CREATE FUNCTION report_streams_check_registry() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    instrument instruments%ROWTYPE;
BEGIN
    IF NEW.registry_instrument_id IS NULL THEN
        IF length(NEW.instrument_id) = 36 AND NEW.instrument_id ~
            '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' THEN
            RAISE EXCEPTION 'Registered instrument required' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO instrument FROM instruments
        WHERE instrument_id = NEW.registry_instrument_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown registered instrument' USING ERRCODE = '23503';
    END IF;
    IF NEW.instrument_id IS DISTINCT FROM NEW.registry_instrument_id::text
       OR NEW.asset_type IS DISTINCT FROM instrument.asset_type
       OR NEW.data_origin IS DISTINCT FROM instrument.data_origin THEN
        RAISE EXCEPTION 'Instrument identity conflict' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # Historical SQL snapshot intentionally independent of mutable runtime metadata.
    op.create_table(
        "instruments",
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange_mic", sa.String(4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("data_origin", sa.String(16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "exchange_mic",
            "symbol",
            "data_origin",
            name="uq_instrument_listing",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("symbol ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name="ck_instrument_symbol"),
        sa.CheckConstraint(
            "exchange_mic IS NULL OR exchange_mic ~ '^[A-Z0-9]{4}$'", name="ck_instrument_exchange"
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_instrument_currency"),
        sa.CheckConstraint("asset_type IN ('equity','etf','commodity')", name="ck_instrument_type"),
        sa.CheckConstraint("data_origin IN ('synthetic','live')", name="ck_instrument_origin"),
        sa.CheckConstraint(
            "asset_type = 'commodity' OR exchange_mic IS NOT NULL", name="ck_instrument_listing_mic"
        ),
        sa.CheckConstraint("available_at <= as_of", name="ck_instrument_availability"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_instrument_payload"),
    )
    op.add_column(
        "report_streams",
        sa.Column("registry_instrument_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_stream_registry_instrument",
        "report_streams",
        "instruments",
        ["registry_instrument_id"],
        ["instrument_id"],
    )
    op.execute(CHECK_INSTRUMENT_SQL)
    op.execute(DENY_MUTATION_SQL)
    op.execute(CHECK_STREAM_SQL)
    op.execute(
        "CREATE TRIGGER instruments_check_insert BEFORE INSERT ON instruments "
        "FOR EACH ROW EXECUTE FUNCTION instruments_check_insert()"
    )
    op.execute(
        "CREATE TRIGGER instruments_deny_changes BEFORE UPDATE OR DELETE ON instruments "
        "FOR EACH ROW EXECUTE FUNCTION instruments_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER instruments_deny_truncate BEFORE TRUNCATE ON instruments "
        "FOR EACH STATEMENT EXECUTE FUNCTION instruments_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER report_streams_registry_guard BEFORE INSERT ON report_streams "
        "FOR EACH ROW EXECUTE FUNCTION report_streams_check_registry()"
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade is disabled to protect instrument identities")
    bind = op.get_bind()
    # Same stream-before-registry order as append and direct stream INSERT.
    bind.execute(sa.text("LOCK TABLE report_streams, instruments IN ACCESS EXCLUSIVE MODE"))
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM instruments)")) or bind.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM report_streams WHERE registry_instrument_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Refusing to remove non-empty instrument registry")
    op.execute("DROP TRIGGER report_streams_registry_guard ON report_streams")
    op.execute("DROP FUNCTION report_streams_check_registry()")
    op.drop_constraint("fk_stream_registry_instrument", "report_streams", type_="foreignkey")
    op.drop_column("report_streams", "registry_instrument_id")
    op.drop_table("instruments")
    op.execute("DROP FUNCTION instruments_check_insert()")
    op.execute("DROP FUNCTION instruments_deny_mutation()")
