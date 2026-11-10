"""Fenced local document jobs and immutable attempt receipts; no model invocation."""

import sqlalchemy as sa
from alembic import op

revision = "0011_document_tasks"
down_revision = "0010_document_archive"
branch_labels = None
depends_on = None

TABLE_SQL = r"""

CREATE TABLE document_tasks (
	job_id UUID NOT NULL,
	archive_id UUID NOT NULL,
	request JSONB NOT NULL,
	input_sha256 VARCHAR(64) NOT NULL,
	document_sha256 VARCHAR(64) NOT NULL,
	draft_sha256 VARCHAR(64) NOT NULL,
	status VARCHAR(16) NOT NULL,
	stage VARCHAR(16) NOT NULL,
	attempt INTEGER NOT NULL,
	worker_id VARCHAR(128),
	implementation_sha256 VARCHAR(64),
	lease_token UUID,
	started_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	error_code VARCHAR(128),
	result JSONB,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (job_id),
	CONSTRAINT ck_document_task_attempt CHECK (attempt BETWEEN 0 AND 3),
	CONSTRAINT ck_document_task_status CHECK (status IN ('queued','running','completed','blocked',
    'failed')),
	CONSTRAINT ck_document_task_stage CHECK (stage IN ('queued','reading','validating',
    'archiving','completed','blocked','failed')),
	CONSTRAINT ck_document_task_lease CHECK ((status='running') = (lease_token IS NOT NULL AND
    lease_expires_at IS NOT NULL)),
	CONSTRAINT ck_document_task_hash CHECK (input_sha256 ~ '^[a-f0-9]{64}$' AND document_sha256 ~
    '^[a-f0-9]{64}$' AND draft_sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(archive_id) REFERENCES document_archives (archive_id)
);
CREATE INDEX ix_document_task_claim ON document_tasks (status, created_at);

CREATE TABLE document_task_events (
	job_id UUID NOT NULL,
	sequence INTEGER NOT NULL,
	payload JSONB NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	PRIMARY KEY (job_id, sequence),
	CONSTRAINT ck_document_task_event_sequence CHECK (sequence BETWEEN 1 AND 32),
	CONSTRAINT ck_document_task_event_hash CHECK (sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(job_id) REFERENCES document_tasks (job_id)
);


CREATE TABLE document_task_audits (
	job_id UUID NOT NULL,
	attempt INTEGER NOT NULL,
	payload JSONB NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	PRIMARY KEY (job_id, attempt),
	CONSTRAINT ck_document_task_audit_attempt CHECK (attempt BETWEEN 1 AND 3),
	CONSTRAINT ck_document_task_audit_hash CHECK (sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(job_id) REFERENCES document_tasks (job_id)
);

"""


def upgrade() -> None:
    op.execute(TABLE_SQL)
    op.execute(GUARD_SQL)


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE document_archives, document_tasks, document_task_events, "
            "document_task_audits IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM document_tasks)")):
        raise RuntimeError("Refusing to remove non-empty document task history")
    op.drop_table("document_task_audits")
    op.drop_table("document_task_events")
    op.drop_table("document_tasks")
    op.execute(
        "DROP FUNCTION document_tasks_guard(); DROP FUNCTION document_task_history_guard(); "
        "DROP FUNCTION document_task_sequence_guard()"
    )


GUARD_SQL = r"""
CREATE FUNCTION document_tasks_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
 IF TG_OP='DELETE' OR TG_OP='TRUNCATE' THEN RAISE EXCEPTION
    'Document task history is immutable'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.status<>'queued' OR NEW.stage<>'queued' OR NEW.attempt<>0 OR
     NEW.lease_token IS NOT NULL OR NEW.worker_id IS NOT NULL OR NEW.result IS NOT NULL OR
    NEW.error_code IS NOT NULL THEN
   RAISE EXCEPTION 'Invalid initial document task';
  END IF;
  RETURN NEW;
 END IF;
 IF OLD.status IN ('completed','blocked','failed') THEN RAISE EXCEPTION
    'Terminal document task is immutable'; END IF;
 IF ROW(NEW.job_id,NEW.archive_id,NEW.request,NEW.input_sha256,NEW.document_sha256,
    NEW.draft_sha256,NEW.created_at)
    IS DISTINCT FROM ROW(OLD.job_id,OLD.archive_id,OLD.request,OLD.input_sha256,
    OLD.document_sha256,OLD.draft_sha256,OLD.created_at) THEN
  RAISE EXCEPTION 'Frozen document task identity';
 END IF;
 IF NEW.updated_at<OLD.updated_at THEN RAISE EXCEPTION 'Document task time regression'; END IF;
 IF NEW.attempt=OLD.attempt+1 THEN
  IF NOT (OLD.status='queued' OR (OLD.status='running' AND
    OLD.lease_expires_at<=clock_timestamp())) OR
     NEW.status<>'running' OR NEW.stage<>'reading' OR NEW.lease_token IS NULL OR
     NEW.worker_id IS NULL OR NEW.implementation_sha256 IS NULL OR NEW.started_at IS NULL THEN
   RAISE EXCEPTION 'Invalid document claim';
  END IF;
 ELSIF NEW.attempt=OLD.attempt AND OLD.status='running' THEN
  IF NEW.status='failed' AND NEW.error_code='RECOVERY_EXHAUSTED' AND OLD.attempt=3 AND
    OLD.lease_expires_at<=clock_timestamp() THEN
   RETURN NEW;
  END IF;
  IF OLD.lease_expires_at<=clock_timestamp() OR ROW(NEW.worker_id,NEW.implementation_sha256,
    NEW.started_at) IS DISTINCT FROM ROW(OLD.worker_id,OLD.implementation_sha256,
    OLD.started_at) THEN
   RAISE EXCEPTION 'Expired or changed document owner';
  END IF;
  IF NEW.status='running' THEN
   IF NEW.lease_token<>OLD.lease_token OR NOT (NEW.stage=OLD.stage OR (OLD.stage='reading' AND
    NEW.stage='validating') OR (OLD.stage='validating' AND NEW.stage='archiving')) THEN
    RAISE EXCEPTION 'Invalid document stage';
   END IF;
  ELSIF NEW.status NOT IN ('completed','blocked','failed') OR NEW.stage<>NEW.status THEN
   RAISE EXCEPTION 'Invalid document terminal state';
  END IF;
 ELSE RAISE EXCEPTION 'Invalid document attempt progression';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER document_tasks_guard BEFORE INSERT OR UPDATE OR DELETE ON document_tasks
FOR EACH ROW EXECUTE FUNCTION document_tasks_guard();
CREATE TRIGGER document_tasks_no_truncate BEFORE TRUNCATE ON document_tasks
FOR EACH STATEMENT EXECUTE FUNCTION document_tasks_guard();
CREATE FUNCTION document_task_history_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN RAISE EXCEPTION 'Document task history is immutable'; END; $$;
CREATE TRIGGER document_task_events_immutable BEFORE UPDATE OR DELETE ON document_task_events
FOR EACH ROW EXECUTE FUNCTION document_task_history_guard();
CREATE TRIGGER document_task_events_no_truncate BEFORE TRUNCATE ON document_task_events
FOR EACH STATEMENT EXECUTE FUNCTION document_task_history_guard();
CREATE TRIGGER document_task_audits_immutable BEFORE UPDATE OR DELETE ON document_task_audits
FOR EACH ROW EXECUTE FUNCTION document_task_history_guard();
CREATE TRIGGER document_task_audits_no_truncate BEFORE TRUNCATE ON document_task_audits
FOR EACH STATEMENT EXECUTE FUNCTION document_task_history_guard();
CREATE FUNCTION document_task_sequence_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE previous integer; current_attempt integer;
BEGIN
 SELECT attempt INTO current_attempt FROM document_tasks WHERE job_id=NEW.job_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Missing document task'; END IF;
 IF TG_TABLE_NAME='document_task_events' THEN
  SELECT COALESCE(MAX(sequence),0) INTO previous FROM document_task_events WHERE
    job_id=NEW.job_id;
  IF NEW.sequence<>previous+1 OR (NEW.payload->>'sequence')::integer IS DISTINCT FROM
    NEW.sequence OR (NEW.payload->>'attempt')::integer IS DISTINCT FROM current_attempt THEN
   RAISE EXCEPTION 'Document event sequence conflict';
  END IF;
 ELSE
  SELECT COALESCE(MAX(attempt),0) INTO previous FROM document_task_audits WHERE job_id=NEW.job_id;
  IF NEW.attempt<>previous+1 OR NEW.attempt<>current_attempt OR
    (NEW.payload->>'attempt')::integer IS DISTINCT FROM NEW.attempt THEN
   RAISE EXCEPTION 'Document receipt sequence conflict';
  END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER document_task_events_sequence BEFORE INSERT ON document_task_events
FOR EACH ROW EXECUTE FUNCTION document_task_sequence_guard();
CREATE TRIGGER document_task_audits_sequence BEFORE INSERT ON document_task_audits
FOR EACH ROW EXECUTE FUNCTION document_task_sequence_guard();
"""
