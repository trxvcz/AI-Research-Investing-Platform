"""Immutable raw bytes and append-only manual research run ledger.

Revision ID: 0003_runs_snapshots
Revises: 0002_instruments
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_runs_snapshots"
down_revision = "0002_instruments"
branch_labels = None
depends_on = None

DENY_MUTATION_SQL = """
CREATE FUNCTION runs_snapshots_deny_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'Research evidence and run history are append-only' USING ERRCODE='23514';
END;
$$
"""

CHECK_SNAPSHOT_SQL = """
CREATE FUNCTION raw_snapshots_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE origin text;
BEGIN
    SELECT data_origin INTO origin FROM instruments WHERE instrument_id=NEW.instrument_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown instrument' USING ERRCODE='23503';
    END IF;
    IF origin IS DISTINCT FROM NEW.data_origin
       OR NEW.metadata->>'schema_version' IS DISTINCT FROM '1.0'
       OR NEW.metadata->>'snapshot_id' IS DISTINCT FROM NEW.snapshot_id::text
       OR NEW.metadata->>'instrument_id' IS DISTINCT FROM NEW.instrument_id::text
       OR NEW.metadata->>'data_origin' IS DISTINCT FROM NEW.data_origin
       OR NEW.metadata->>'source_id' IS DISTINCT FROM NEW.source_id
       OR (NEW.metadata->>'as_of')::timestamptz IS DISTINCT FROM NEW.as_of
       OR (NEW.metadata->>'available_at')::timestamptz IS DISTINCT FROM NEW.available_at
       OR (NEW.metadata->>'retrieved_at')::timestamptz IS DISTINCT FROM NEW.retrieved_at
       OR NEW.metadata->>'sha256' IS DISTINCT FROM NEW.sha256
       OR (NEW.metadata->>'byte_length')::integer IS DISTINCT FROM NEW.byte_length
       OR NEW.metadata ? 'content_base64' OR NEW.metadata ? 'created_at'
       OR octet_length(NEW.content) IS DISTINCT FROM NEW.byte_length
       OR encode(sha256(NEW.content),'hex') IS DISTINCT FROM NEW.sha256 THEN
        RAISE EXCEPTION 'Snapshot metadata or bytes mismatch' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$
"""

CHECK_RUN_SQL = """
CREATE FUNCTION research_runs_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.definition->>'action' IS DISTINCT FROM 'create'
       OR NEW.definition->>'schema_version' IS DISTINCT FROM '1.0'
       OR NEW.definition->>'run_id' IS DISTINCT FROM NEW.run_id::text
       OR NEW.definition->>'instrument_id' IS DISTINCT FROM NEW.instrument_id::text
       OR (NEW.definition->>'as_of')::timestamptz IS DISTINCT FROM NEW.as_of
       OR NEW.definition->>'pipeline_version' IS DISTINCT FROM 'manual-research-v1'
       OR jsonb_typeof(NEW.definition->'snapshot_ids') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Run definition mismatch' USING ERRCODE='23514';
    END IF;
    IF jsonb_array_length(NEW.definition->'snapshot_ids') NOT BETWEEN 1 AND 32
       OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(NEW.definition->'snapshot_ids'))
          <> jsonb_array_length(NEW.definition->'snapshot_ids') THEN
        RAISE EXCEPTION 'Run snapshot set invalid' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$
"""

CHECK_BINDING_SQL = """
CREATE FUNCTION run_snapshots_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    definition_row research_runs%ROWTYPE;
    snapshot raw_snapshots%ROWTYPE;
BEGIN
    SELECT * INTO definition_row FROM research_runs WHERE run_id=NEW.run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown run' USING ERRCODE='23503';
    END IF;
    IF EXISTS(SELECT 1 FROM run_events WHERE run_id=NEW.run_id) THEN
        RAISE EXCEPTION 'Run inputs already frozen' USING ERRCODE='23514';
    END IF;
    SELECT * INTO snapshot FROM raw_snapshots WHERE snapshot_id=NEW.snapshot_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown snapshot' USING ERRCODE='23503';
    END IF;
    IF NOT (definition_row.definition->'snapshot_ids' @> jsonb_build_array(NEW.snapshot_id::text))
       OR snapshot.instrument_id IS DISTINCT FROM definition_row.instrument_id
       OR snapshot.available_at IS NULL OR snapshot.available_at > definition_row.as_of
       OR snapshot.as_of > definition_row.as_of THEN
        RAISE EXCEPTION 'Snapshot is not eligible for this run' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$
"""

CHECK_EVENT_SQL = """
CREATE FUNCTION run_events_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    definition_row research_runs%ROWTYPE;
    previous run_events%ROWTYPE;
    origin text;
BEGIN
    SELECT * INTO definition_row FROM research_runs WHERE run_id=NEW.run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown run' USING ERRCODE='23503';
    END IF;
    SELECT data_origin INTO origin FROM instruments
        WHERE instrument_id=definition_row.instrument_id;
    IF NEW.state->>'run_id' IS DISTINCT FROM NEW.run_id::text
       OR NEW.state->>'instrument_id' IS DISTINCT FROM definition_row.instrument_id::text
       OR (NEW.state->>'as_of')::timestamptz IS DISTINCT FROM definition_row.as_of
       OR NEW.state->>'pipeline_version' IS DISTINCT FROM 'manual-research-v1'
       OR NEW.state->>'data_origin' IS DISTINCT FROM origin
       OR NEW.state->'snapshot_ids' IS DISTINCT FROM definition_row.definition->'snapshot_ids'
       OR (NEW.state->>'sequence')::integer IS DISTINCT FROM NEW.sequence
       OR (NEW.state->>'created_at')::timestamptz IS DISTINCT FROM definition_row.created_at
       OR (NEW.state->>'updated_at')::timestamptz IS DISTINCT FROM NEW.created_at
       OR NEW.created_at < definition_row.created_at
       OR (NEW.state->>'report_revision_id')::uuid IS DISTINCT FROM NEW.report_revision_id
       OR NEW.state->>'status' IS NULL
       OR NEW.state->>'status' NOT IN ('queued','running','failed','completed') THEN
        RAISE EXCEPTION 'Run event metadata mismatch' USING ERRCODE='23514';
    END IF;
    SELECT * INTO previous FROM run_events WHERE run_id=NEW.run_id ORDER BY sequence DESC LIMIT 1;
    IF FOUND THEN
        IF NEW.sequence <> previous.sequence + 1 OR NEW.kind='created'
           OR NEW.request->>'action' IS DISTINCT FROM NEW.kind
           OR (NEW.request->>'request_id')::uuid IS DISTINCT FROM NEW.event_id
           OR (NEW.request->>'expected_sequence')::integer IS DISTINCT FROM previous.sequence
           OR NEW.created_at < previous.created_at THEN
            RAISE EXCEPTION 'Run event sequence conflict' USING ERRCODE='23514';
        END IF;
    ELSE
        IF NEW.sequence<>1 OR NEW.kind<>'created' OR NEW.event_id<>NEW.run_id
           OR NEW.request IS DISTINCT FROM definition_row.definition
           OR NEW.state->>'status' IS DISTINCT FROM 'queued'
           OR NEW.state->>'current_step' IS DISTINCT FROM 'data'
           OR NEW.state->'completed_steps' IS DISTINCT FROM '[]'::jsonb
           OR NEW.report_revision_id IS NOT NULL
           OR (SELECT count(*) FROM run_snapshots WHERE run_id=NEW.run_id)
              <> jsonb_array_length(definition_row.definition->'snapshot_ids') THEN
            RAISE EXCEPTION 'Initial event or snapshot set invalid' USING ERRCODE='23514';
        END IF;
    END IF;
    IF (NEW.kind='finish') IS DISTINCT FROM (NEW.report_revision_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Report link is only valid for finish events' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    # Immutable historical snapshot, intentionally not imported from db_schema.
    op.create_table(
        "raw_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.instrument_id"),
            nullable=False,
        ),
        sa.Column("data_origin", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_length", sa.Integer, nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("data_origin IN ('synthetic','live')", name="ck_snapshot_origin"),
        sa.CheckConstraint("length(btrim(source_id)) > 0", name="ck_snapshot_source"),
        sa.CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_snapshot_sha256"),
        sa.CheckConstraint("byte_length BETWEEN 1 AND 1048576", name="ck_snapshot_size"),
        sa.CheckConstraint(
            "available_at IS NULL OR (available_at <= as_of AND available_at <= retrieved_at)",
            name="ck_snapshot_availability",
        ),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_snapshot_metadata"),
    )
    op.create_index(
        "ix_raw_snapshots_instrument_snapshot", "raw_snapshots", ["instrument_id", "snapshot_id"]
    )
    op.create_table(
        "research_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.instrument_id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("definition", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("jsonb_typeof(definition) = 'object'", name="ck_run_definition"),
    )
    op.create_table(
        "run_snapshots",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.run_id"),
            primary_key=True,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_snapshots.snapshot_id"),
            primary_key=True,
        ),
    )
    op.create_table(
        "run_events",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.run_id"),
            primary_key=True,
        ),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("request", postgresql.JSONB, nullable=False),
        sa.Column("state", postgresql.JSONB, nullable=False),
        sa.Column(
            "report_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("report_revisions.revision_id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("run_id", "event_id", name="uq_run_event_identity"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 2147483647", name="ck_run_event_sequence"),
        sa.CheckConstraint(
            "kind IN ('created','start','advance','fail','resume','finish')",
            name="ck_run_event_kind",
        ),
        sa.CheckConstraint("jsonb_typeof(request) = 'object'", name="ck_run_event_request"),
        sa.CheckConstraint("jsonb_typeof(state) = 'object'", name="ck_run_event_state"),
    )
    for statement in (
        DENY_MUTATION_SQL,
        CHECK_SNAPSHOT_SQL,
        CHECK_RUN_SQL,
        CHECK_BINDING_SQL,
        CHECK_EVENT_SQL,
    ):
        op.execute(statement)
    functions = {
        "raw_snapshots": "raw_snapshots_check_insert",
        "research_runs": "research_runs_check_insert",
        "run_snapshots": "run_snapshots_check_insert",
        "run_events": "run_events_check_insert",
    }
    for table, function in functions.items():
        op.execute(
            f"CREATE TRIGGER {table}_check_insert BEFORE INSERT ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_deny_changes BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION runs_snapshots_deny_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_deny_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION runs_snapshots_deny_mutation()"
        )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade is disabled to protect research evidence")
    bind = op.get_bind()
    # Snapshot creation and run commands acquire these relations in different
    # orders. Fail fast on concurrent use instead of risking a migration deadlock.
    bind.execute(
        sa.text(
            "LOCK TABLE raw_snapshots, research_runs, run_snapshots, run_events "
            "IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    for table in ("raw_snapshots", "research_runs", "run_snapshots", "run_events"):
        if bind.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})")):
            raise RuntimeError("Refusing to remove non-empty research evidence or run history")
    for table in ("run_events", "run_snapshots", "research_runs", "raw_snapshots"):
        op.drop_table(table)
    for function in (
        "run_events_check_insert",
        "run_snapshots_check_insert",
        "research_runs_check_insert",
        "raw_snapshots_check_insert",
        "runs_snapshots_deny_mutation",
    ):
        op.execute(f"DROP FUNCTION {function}()")
