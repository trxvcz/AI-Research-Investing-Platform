"""Append-only report streams and linear revision history.

Revision ID: 0001_report_store
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_report_store"
down_revision = None
branch_labels = None
depends_on = None

DENY_MUTATION_SQL = """
CREATE FUNCTION report_store_deny_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'Report history is append-only' USING ERRCODE = '23514';
END;
$$
"""

CHECK_INSERT_SQL = """
CREATE FUNCTION report_store_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    stream report_streams%ROWTYPE;
    previous report_revisions%ROWTYPE;
BEGIN
    SELECT * INTO stream FROM report_streams
        WHERE report_id = NEW.report_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown report stream' USING ERRCODE = '23503';
    END IF;
    SELECT * INTO previous FROM report_revisions
        WHERE report_id = NEW.report_id ORDER BY revision DESC LIMIT 1;
    IF FOUND THEN
        IF NEW.revision <> previous.revision + 1
           OR NEW.parent_revision_id IS DISTINCT FROM previous.revision_id
           OR NEW.generated_at_utc < previous.generated_at_utc THEN
            RAISE EXCEPTION 'Revision history conflict' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.revision <> 1 OR NEW.parent_revision_id IS NOT NULL THEN
        RAISE EXCEPTION 'First revision required' USING ERRCODE = '23514';
    END IF;
    IF NEW.payload->>'schema_version' IS DISTINCT FROM '1.0'
       OR NEW.payload->>'report_id' IS DISTINCT FROM NEW.report_id::text
       OR NEW.payload->>'revision_id' IS DISTINCT FROM NEW.revision_id::text
       OR (NEW.payload->>'revision')::integer IS DISTINCT FROM NEW.revision
       OR (NEW.payload->>'parent_revision_id')::uuid IS DISTINCT FROM NEW.parent_revision_id
       OR (NEW.payload->>'generated_at_utc')::timestamptz IS DISTINCT FROM NEW.generated_at_utc
       OR NEW.payload->>'checksum' IS DISTINCT FROM NEW.checksum
       OR NEW.payload->>'input_sha256' IS DISTINCT FROM NEW.input_sha256
       OR NEW.payload->'input'->>'instrument_id' IS DISTINCT FROM stream.instrument_id
       OR NEW.payload->'input'->>'asset_type' IS DISTINCT FROM stream.asset_type
       OR NEW.payload->'input'->>'data_origin' IS DISTINCT FROM stream.data_origin THEN
        RAISE EXCEPTION 'Report metadata mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # Keep this historical snapshot independent of future runtime metadata.
    op.create_table(
        "report_streams",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_id", sa.String(128), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("data_origin", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(btrim(instrument_id)) > 0", name="ck_stream_instrument"),
        sa.CheckConstraint(
            "asset_type IN ('equity','etf','commodity')", name="ck_stream_asset_type"
        ),
        sa.CheckConstraint("data_origin IN ('synthetic','live')", name="ck_stream_origin"),
    )
    op.create_table(
        "report_revisions",
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("report_streams.report_id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "stored_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("report_id", "revision", name="uq_report_revision_number"),
        sa.UniqueConstraint("report_id", "revision_id", name="uq_report_revision_identity"),
        sa.ForeignKeyConstraint(
            ["report_id", "parent_revision_id"],
            ["report_revisions.report_id", "report_revisions.revision_id"],
            name="fk_revision_parent_same_report",
        ),
        sa.CheckConstraint("revision > 0", name="ck_revision_positive"),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision_id IS NULL) OR "
            "(revision > 1 AND parent_revision_id IS NOT NULL)",
            name="ck_revision_parent_required",
        ),
        sa.CheckConstraint(
            "parent_revision_id IS DISTINCT FROM revision_id", name="ck_not_own_parent"
        ),
        sa.CheckConstraint("checksum ~ '^[a-f0-9]{64}$'", name="ck_revision_checksum"),
        sa.CheckConstraint("input_sha256 ~ '^[a-f0-9]{64}$'", name="ck_revision_input_checksum"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_revision_payload_object"),
    )
    op.execute(DENY_MUTATION_SQL)
    op.execute(CHECK_INSERT_SQL)
    for table in ("report_streams", "report_revisions"):
        op.execute(
            f"CREATE TRIGGER {table}_deny_changes BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION report_store_deny_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_deny_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION report_store_deny_mutation()"
        )
    op.execute(
        "CREATE TRIGGER report_revisions_check_insert BEFORE INSERT ON report_revisions "
        "FOR EACH ROW EXECUTE FUNCTION report_store_check_insert()"
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade is disabled to protect report history")
    bind = op.get_bind()
    # Lock before checking emptiness so a concurrent append cannot commit in
    # between EXISTS and DROP TABLE. Match the stream -> revision lock order.
    bind.execute(sa.text("LOCK TABLE report_streams, report_revisions IN ACCESS EXCLUSIVE MODE"))
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM report_streams)")) or bind.scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM report_revisions)")
    ):
        raise RuntimeError("Refusing to remove non-empty report history")
    op.drop_table("report_revisions")
    op.drop_table("report_streams")
    op.execute("DROP FUNCTION report_store_check_insert()")
    op.execute("DROP FUNCTION report_store_deny_mutation()")
