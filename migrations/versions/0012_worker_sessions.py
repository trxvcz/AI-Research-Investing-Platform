"""Observed worker sessions and immutable process start/stop history."""

import sqlalchemy as sa
from alembic import op

revision = "0012_worker_sessions"
down_revision = "0011_document_tasks"
branch_labels = None
depends_on = None

TABLE_SQL = r"""

CREATE TABLE worker_sessions (
	session_id UUID NOT NULL,
	worker_id VARCHAR(128) NOT NULL,
	kind VARCHAR(32) NOT NULL,
	mode VARCHAR(16) NOT NULL,
	process_id INTEGER NOT NULL,
	implementation_sha256 VARCHAR(64) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL,
	stopped_at TIMESTAMP WITH TIME ZONE,
	stop_reason VARCHAR(16),
	error_code VARCHAR(32),
	PRIMARY KEY (session_id),
	CONSTRAINT ck_worker_session_kind CHECK (kind IN ('sec_import','document_validation')),
	CONSTRAINT ck_worker_session_mode CHECK (mode IN ('once','forever')),
	CONSTRAINT ck_worker_session_pid CHECK (process_id > 0),
	CONSTRAINT ck_worker_session_hash CHECK (implementation_sha256 ~ '^[a-f0-9]{64}$'),
	CONSTRAINT ck_worker_session_name CHECK (length(btrim(worker_id)) BETWEEN 1 AND 128
        AND worker_id=btrim(worker_id) AND worker_id !~ '[[:cntrl:]]'),
	CONSTRAINT ck_worker_session_heartbeat CHECK (heartbeat_at >= started_at),
	CONSTRAINT ck_worker_session_stop CHECK (
        (stopped_at IS NULL AND stop_reason IS NULL AND error_code IS NULL)
        OR (stopped_at IS NOT NULL AND stop_reason IS NOT NULL
        AND stopped_at >= heartbeat_at AND stop_reason IN ('completed','interrupted') AND error_code IS NULL)
        OR (stopped_at IS NOT NULL AND stop_reason IS NOT NULL AND error_code IS NOT NULL
        AND stopped_at >= heartbeat_at AND stop_reason='error'
        AND error_code IN ('WORKER_RUNTIME_FAILED','WORKER_MONITOR_FAILED')))
)

;
CREATE INDEX ix_worker_session_kind ON worker_sessions (kind, session_id);
"""

GUARD_SQL = r"""
CREATE FUNCTION worker_sessions_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
 IF TG_OP IN ('DELETE','TRUNCATE') THEN
  RAISE EXCEPTION 'Worker session history is immutable';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.started_at<>NEW.heartbeat_at OR NEW.stopped_at IS NOT NULL
     OR NEW.stop_reason IS NOT NULL OR NEW.error_code IS NOT NULL THEN
   RAISE EXCEPTION 'Invalid initial worker session';
  END IF;
  RETURN NEW;
 END IF;
 IF OLD.stopped_at IS NOT NULL THEN RAISE EXCEPTION 'Stopped worker session is immutable'; END IF;
 IF ROW(NEW.session_id,NEW.worker_id,NEW.kind,NEW.mode,NEW.process_id,
        NEW.implementation_sha256,NEW.started_at)
    IS DISTINCT FROM ROW(OLD.session_id,OLD.worker_id,OLD.kind,OLD.mode,OLD.process_id,
                         OLD.implementation_sha256,OLD.started_at) THEN
  RAISE EXCEPTION 'Frozen worker session identity';
 END IF;
 IF NEW.heartbeat_at<OLD.heartbeat_at THEN RAISE EXCEPTION 'Worker heartbeat regressed'; END IF;
 IF NEW.stopped_at IS NOT NULL AND NEW.heartbeat_at<>OLD.heartbeat_at THEN
  RAISE EXCEPTION 'Stopping cannot rewrite last heartbeat';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER worker_sessions_guard BEFORE INSERT OR UPDATE OR DELETE ON worker_sessions
FOR EACH ROW EXECUTE FUNCTION worker_sessions_guard();
CREATE TRIGGER worker_sessions_no_truncate BEFORE TRUNCATE ON worker_sessions
FOR EACH STATEMENT EXECUTE FUNCTION worker_sessions_guard();
"""


def upgrade() -> None:
    op.execute(TABLE_SQL)
    op.execute(GUARD_SQL)


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled")
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE worker_sessions IN ACCESS EXCLUSIVE MODE NOWAIT"))
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM worker_sessions)")):
        raise RuntimeError("Refusing to remove non-empty worker session history")
    op.drop_table("worker_sessions")
    op.execute("DROP FUNCTION worker_sessions_guard()")
