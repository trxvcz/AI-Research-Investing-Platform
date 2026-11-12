"""Frozen SEC schedules, append-only controls and atomic dispatch receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0014_sec_schedules"
down_revision = "0013_import_task_events"
branch_labels = None
depends_on = None

TABLE_SQL = """

CREATE TABLE sec_schedules (
	schedule_id UUID NOT NULL,
	template JSONB NOT NULL,
	create_request JSONB NOT NULL,
	interval_seconds INTEGER NOT NULL,
	first_run_at TIMESTAMP WITH TIME ZONE NOT NULL,
	next_run_at TIMESTAMP WITH TIME ZONE NOT NULL,
	enabled BOOLEAN NOT NULL,
	revision INTEGER DEFAULT '0' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	last_scheduled_for TIMESTAMP WITH TIME ZONE,
	last_outcome VARCHAR(16),
	last_run_id UUID,
	PRIMARY KEY (schedule_id),
	CONSTRAINT ck_sec_schedule_interval CHECK (interval_seconds BETWEEN 3600 AND 2592000),
	CONSTRAINT ck_sec_schedule_revision CHECK (revision BETWEEN 0 AND 10000),
	CONSTRAINT ck_sec_schedule_next CHECK (next_run_at >= first_run_at),
	CONSTRAINT ck_sec_schedule_outcome CHECK (last_outcome IS NULL OR last_outcome IN
 ('enqueued','skipped_busy')),
	FOREIGN KEY(last_run_id) REFERENCES import_tasks (run_id)
)

;
CREATE INDEX ix_sec_schedule_due ON sec_schedules (enabled, next_run_at);


CREATE TABLE sec_schedule_commands (
	schedule_id UUID NOT NULL,
	revision INTEGER NOT NULL,
	command_id UUID NOT NULL,
	payload JSONB NOT NULL,
	recorded_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (schedule_id, revision),
	CONSTRAINT uq_sec_schedule_command UNIQUE (schedule_id, command_id),
	CONSTRAINT ck_sec_schedule_command_revision CHECK (revision BETWEEN 1 AND 10000),
	FOREIGN KEY(schedule_id) REFERENCES sec_schedules (schedule_id)
)

;


CREATE TABLE sec_schedule_occurrences (
	schedule_id UUID NOT NULL,
	sequence INTEGER NOT NULL,
	scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL,
	dispatched_at TIMESTAMP WITH TIME ZONE NOT NULL,
	skipped_slots INTEGER NOT NULL,
	outcome VARCHAR(16) NOT NULL,
	run_id UUID,
	PRIMARY KEY (schedule_id, sequence),
	CONSTRAINT uq_sec_schedule_slot UNIQUE (schedule_id, scheduled_for),
	CONSTRAINT ck_sec_schedule_occurrence_counts CHECK (sequence > 0 AND skipped_slots >= 0),
	CONSTRAINT ck_sec_schedule_occurrence_outcome CHECK (outcome IN ('enqueued','skipped_busy')),
	CONSTRAINT ck_sec_schedule_occurrence_task CHECK ((outcome='enqueued') = (run_id IS NOT NULL)),
	CONSTRAINT ck_sec_schedule_occurrence_time CHECK (dispatched_at >= scheduled_for),
	FOREIGN KEY(schedule_id) REFERENCES sec_schedules (schedule_id),
	FOREIGN KEY(run_id) REFERENCES import_tasks (run_id)
)

;
"""

GUARD_SQL = r"""
CREATE FUNCTION sec_schedule_history_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN RAISE EXCEPTION 'Schedule history is immutable'; END; $$;
CREATE TRIGGER sec_schedule_commands_immutable BEFORE UPDATE OR DELETE ON sec_schedule_commands
FOR EACH ROW EXECUTE FUNCTION sec_schedule_history_guard();
CREATE TRIGGER sec_schedule_commands_no_truncate BEFORE TRUNCATE ON sec_schedule_commands
FOR EACH STATEMENT EXECUTE FUNCTION sec_schedule_history_guard();
CREATE TRIGGER sec_schedule_occurrences_immutable BEFORE UPDATE OR DELETE ON
 sec_schedule_occurrences
FOR EACH ROW EXECUTE FUNCTION sec_schedule_history_guard();
CREATE TRIGGER sec_schedule_occurrences_no_truncate BEFORE TRUNCATE ON sec_schedule_occurrences
FOR EACH STATEMENT EXECUTE FUNCTION sec_schedule_history_guard();
CREATE FUNCTION sec_schedule_append_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE parent sec_schedules%ROWTYPE; previous integer;
BEGIN
 SELECT * INTO parent FROM sec_schedules WHERE schedule_id=NEW.schedule_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Missing schedule'; END IF;
 IF TG_TABLE_NAME='sec_schedule_commands' THEN
  SELECT COALESCE(MAX(revision),0) INTO previous FROM sec_schedule_commands WHERE
 schedule_id=NEW.schedule_id;
  IF NEW.revision<>previous+1 OR NEW.revision<>parent.revision+1 OR
     (NEW.payload->>'expected_revision')::integer IS DISTINCT FROM parent.revision OR
     (NEW.payload->>'command_id')::uuid IS DISTINCT FROM NEW.command_id OR
     jsonb_typeof(NEW.payload->'enabled') IS DISTINCT FROM 'boolean' THEN
   RAISE EXCEPTION 'Schedule command sequence conflict';
  END IF;
 ELSE
  SELECT COALESCE(MAX(sequence),0) INTO previous FROM sec_schedule_occurrences WHERE
 schedule_id=NEW.schedule_id;
  IF NOT parent.enabled OR NEW.sequence<>previous+1 OR
     NEW.scheduled_for<>parent.next_run_at + NEW.skipped_slots *
 make_interval(secs=>parent.interval_seconds) OR
     NEW.dispatched_at>=NEW.scheduled_for+make_interval(secs=>parent.interval_seconds) THEN
   RAISE EXCEPTION 'Schedule slot sequence conflict';
  END IF;
  IF NEW.outcome='enqueued' AND NOT EXISTS (
   SELECT 1 FROM import_tasks WHERE run_id=NEW.run_id AND
    request=jsonb_set(parent.template,'{run_id}',to_jsonb(NEW.run_id::text))
  ) THEN RAISE EXCEPTION 'Schedule task binding conflict'; END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER sec_schedule_commands_sequence BEFORE INSERT ON sec_schedule_commands
FOR EACH ROW EXECUTE FUNCTION sec_schedule_append_guard();
CREATE TRIGGER sec_schedule_occurrences_sequence BEFORE INSERT ON sec_schedule_occurrences
FOR EACH ROW EXECUTE FUNCTION sec_schedule_append_guard();
CREATE FUNCTION sec_schedules_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE control jsonb; occurrence sec_schedule_occurrences%ROWTYPE;
BEGIN
 IF TG_OP IN ('DELETE','TRUNCATE') THEN RAISE EXCEPTION 'Schedule history is immutable'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.revision<>0 OR NEW.next_run_at<>NEW.first_run_at OR NEW.last_scheduled_for IS NOT NULL OR
     NEW.last_outcome IS NOT NULL OR NEW.last_run_id IS NOT NULL THEN
   RAISE EXCEPTION 'Invalid initial schedule';
  END IF;
  RETURN NEW;
 END IF;
 IF ROW(NEW.schedule_id,NEW.template,NEW.create_request,
        NEW.interval_seconds,NEW.first_run_at,NEW.created_at)
    IS DISTINCT FROM
 ROW(OLD.schedule_id,OLD.template,OLD.create_request,
     OLD.interval_seconds,OLD.first_run_at,OLD.created_at) OR
    NEW.updated_at<OLD.updated_at THEN RAISE EXCEPTION 'Frozen schedule identity'; END IF;
 IF NEW.revision=OLD.revision+1 THEN
  SELECT payload INTO control FROM sec_schedule_commands WHERE schedule_id=NEW.schedule_id AND
 revision=NEW.revision;
  IF control IS NULL OR NEW.enabled IS DISTINCT FROM (control->>'enabled')::boolean OR
     ROW(NEW.next_run_at,NEW.last_scheduled_for,NEW.last_outcome,NEW.last_run_id)
      IS DISTINCT FROM
 ROW(OLD.next_run_at,OLD.last_scheduled_for,OLD.last_outcome,OLD.last_run_id) THEN
   RAISE EXCEPTION 'Unrecorded schedule control';
  END IF;
 ELSIF NEW.revision=OLD.revision AND NEW.enabled=OLD.enabled AND NEW.next_run_at>OLD.next_run_at
 THEN
  SELECT * INTO occurrence FROM sec_schedule_occurrences WHERE schedule_id=NEW.schedule_id ORDER
 BY sequence DESC LIMIT 1;
  IF NOT FOUND OR ROW(NEW.last_scheduled_for,NEW.last_outcome,NEW.last_run_id)
    IS DISTINCT FROM ROW(occurrence.scheduled_for,occurrence.outcome,occurrence.run_id) OR
    NEW.next_run_at<>occurrence.scheduled_for+make_interval(secs=>NEW.interval_seconds) THEN
   RAISE EXCEPTION 'Unrecorded schedule dispatch';
  END IF;
 ELSE RAISE EXCEPTION 'Invalid schedule state transition'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER sec_schedules_guard BEFORE INSERT OR UPDATE OR DELETE ON sec_schedules
FOR EACH ROW EXECUTE FUNCTION sec_schedules_guard();
CREATE TRIGGER sec_schedules_no_truncate BEFORE TRUNCATE ON sec_schedules
FOR EACH STATEMENT EXECUTE FUNCTION sec_schedules_guard();
"""


def upgrade() -> None:
    op.execute(TABLE_SQL)
    op.execute(GUARD_SQL)
    op.drop_constraint("ck_worker_session_kind", "worker_sessions", type_="check")
    op.create_check_constraint(
        "ck_worker_session_kind",
        "worker_sessions",
        "kind IN ('sec_import','document_validation','sec_scheduler')",
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE import_tasks,sec_schedules,sec_schedule_commands,"
            "sec_schedule_occurrences,worker_sessions IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if bind.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM sec_schedules) OR "
            "EXISTS(SELECT 1 FROM worker_sessions WHERE kind='sec_scheduler')"
        )
    ):
        raise RuntimeError("Refusing to remove non-empty schedule history")
    op.drop_table("sec_schedule_occurrences")
    op.drop_table("sec_schedule_commands")
    op.drop_table("sec_schedules")
    op.execute(
        "DROP FUNCTION sec_schedules_guard(); DROP FUNCTION sec_schedule_append_guard(); "
        "DROP FUNCTION sec_schedule_history_guard()"
    )
    op.drop_constraint("ck_worker_session_kind", "worker_sessions", type_="check")
    op.create_check_constraint(
        "ck_worker_session_kind", "worker_sessions", "kind IN ('sec_import','document_validation')"
    )
