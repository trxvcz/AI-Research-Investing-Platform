"""Append real SEC task transitions; legacy rows start with an explicit snapshot."""

import sqlalchemy as sa
from alembic import op

revision = "0013_import_task_events"
down_revision = "0012_worker_sessions"
branch_labels = None
depends_on = None

TABLE_SQL = """
CREATE TABLE import_task_events (
 run_id UUID NOT NULL REFERENCES import_tasks(run_id),
 sequence INTEGER NOT NULL,
 kind VARCHAR(24) NOT NULL,
 recorded_at TIMESTAMPTZ NOT NULL,
 payload JSONB NOT NULL,
 PRIMARY KEY (run_id,sequence),
 CONSTRAINT ck_import_task_event_sequence CHECK (sequence > 0),
 CONSTRAINT ck_import_task_event_kind CHECK (kind IN ('created','transition','legacy_snapshot'))
);
"""

PAYLOAD_SQL = """
CREATE FUNCTION import_task_event_payload(t import_tasks) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path FROM CURRENT AS $$
 SELECT jsonb_build_object(
    'run_id', (t).run_id,
    'symbol', (t).symbol,
    'status', (t).status,
    'stage', (t).stage,
    'attempt', (t).attempt,
    'error_code', (t).error_code,
    'error_reason', (t).error_reason,
    'created_at', (t).created_at,
    'updated_at', (t).updated_at,
    'heartbeat_at', (t).heartbeat_at,
    'lease_expires_at', (t).lease_expires_at,
    'worker_id', (t).worker_id,
    'instrument_id', (t).instrument_id,
    'report_id', (t).report_id,
    'revision', (t).revision,
    'exchange_mic', (t).request->>'exchange_mic'
 );
$$;
"""

GUARD_SQL = """
CREATE FUNCTION import_task_events_protect() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN RAISE EXCEPTION 'Import task events are immutable'; END; $$;
CREATE TRIGGER import_task_events_immutable BEFORE UPDATE OR DELETE ON import_task_events
FOR EACH ROW EXECUTE FUNCTION import_task_events_protect();
CREATE TRIGGER import_task_events_no_truncate BEFORE TRUNCATE ON import_task_events
FOR EACH STATEMENT EXECUTE FUNCTION import_task_events_protect();
CREATE FUNCTION import_task_events_sequence() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE parent import_tasks; previous integer; previous_time timestamptz;
BEGIN
 SELECT * INTO parent FROM import_tasks WHERE run_id=NEW.run_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Missing import task'; END IF;
 SELECT COALESCE(MAX(sequence),0),MAX(recorded_at) INTO previous,previous_time
 FROM import_task_events WHERE run_id=NEW.run_id;
 IF NEW.sequence<>previous+1 OR
    NEW.payload IS DISTINCT FROM import_task_event_payload(parent) OR
    (previous=0 AND NEW.kind NOT IN ('created','legacy_snapshot')) OR
    (previous>0 AND NEW.kind<>'transition') OR
    (previous_time IS NOT NULL AND NEW.recorded_at<previous_time) THEN
  RAISE EXCEPTION 'Invalid import task event';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER import_task_events_sequence BEFORE INSERT ON import_task_events
FOR EACH ROW EXECUTE FUNCTION import_task_events_sequence();
CREATE FUNCTION capture_import_task_event() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE event_kind text; next_sequence integer;
BEGIN
 IF TG_OP='UPDATE' AND
    ROW(NEW.status,NEW.stage,NEW.attempt,NEW.worker_id,NEW.error_code,NEW.error_reason,
        NEW.instrument_id,NEW.report_id,NEW.revision) IS NOT DISTINCT FROM
    ROW(OLD.status,OLD.stage,OLD.attempt,OLD.worker_id,OLD.error_code,OLD.error_reason,
        OLD.instrument_id,OLD.report_id,OLD.revision) THEN RETURN NEW; END IF;
 event_kind=CASE WHEN TG_OP='INSERT' THEN 'created' ELSE 'transition' END;
 SELECT COALESCE(MAX(sequence),0)+1 INTO next_sequence FROM import_task_events
 WHERE run_id=NEW.run_id;
 INSERT INTO import_task_events(run_id,sequence,kind,recorded_at,payload)
 VALUES(NEW.run_id,next_sequence,event_kind,clock_timestamp(),import_task_event_payload(NEW));
 RETURN NEW;
END; $$;
CREATE TRIGGER import_task_event_capture AFTER INSERT OR UPDATE ON import_tasks
FOR EACH ROW EXECUTE FUNCTION capture_import_task_event();
"""


def upgrade() -> None:
    op.execute("LOCK TABLE import_tasks IN SHARE ROW EXCLUSIVE MODE NOWAIT")
    op.execute(TABLE_SQL)
    op.execute(PAYLOAD_SQL)
    # Existing rows are observations at migration time, not reconstructed events.
    op.execute("""
        INSERT INTO import_task_events(run_id,sequence,kind,recorded_at,payload)
        SELECT t.run_id,1,'legacy_snapshot',clock_timestamp(),import_task_event_payload(t)
        FROM import_tasks t
    """)
    op.execute(GUARD_SQL)


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled")
    bind = op.get_bind()
    bind.execute(
        sa.text("LOCK TABLE import_tasks, import_task_events IN ACCESS EXCLUSIVE MODE NOWAIT")
    )
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM import_task_events)")):
        raise RuntimeError("Refusing to remove non-empty import task event history")
    op.execute("DROP TRIGGER import_task_event_capture ON import_tasks")
    op.drop_table("import_task_events")
    op.execute("""
        DROP FUNCTION capture_import_task_event();
        DROP FUNCTION import_task_events_sequence();
        DROP FUNCTION import_task_events_protect();
        DROP FUNCTION import_task_event_payload(import_tasks)
    """)
