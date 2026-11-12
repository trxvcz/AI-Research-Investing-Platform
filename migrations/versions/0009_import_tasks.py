"""Persist import intentions before source fetching, with fenced worker leases."""

import sqlalchemy as sa
from alembic import op

revision = "0009_import_tasks"
down_revision = "0008_sec_fundamentals_v2"
branch_labels = None
depends_on = None


TABLE_SQL = """
CREATE TABLE import_tasks (
	run_id UUID NOT NULL, 
	symbol VARCHAR(16) NOT NULL, 
	request JSONB NOT NULL, 
	status VARCHAR(16) DEFAULT 'queued' NOT NULL, 
	stage VARCHAR(16) DEFAULT 'queued' NOT NULL, 
	attempt INTEGER DEFAULT '0' NOT NULL, 
	lease_token UUID, 
	worker_id VARCHAR(128), 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	lease_expires_at TIMESTAMP WITH TIME ZONE, 
	error_code VARCHAR(64), 
	error_reason VARCHAR(512), 
	instrument_id UUID, 
	report_id UUID, 
	revision INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	PRIMARY KEY (run_id), 
	CONSTRAINT ck_import_task_status CHECK (status IN ('queued','running','completed','failed')), 
	CONSTRAINT ck_import_task_stage CHECK (stage IN
 ('queued','import','analysis','completed','failed')), 
	CONSTRAINT ck_import_task_attempt CHECK (attempt BETWEEN 0 AND 3), 
	CONSTRAINT ck_import_task_lease CHECK ((status='running') =
 (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)), 
	CONSTRAINT ck_import_task_report CHECK ((report_id IS NULL) = (revision IS NULL))
)

;
CREATE INDEX ix_import_task_claim ON import_tasks (status, created_at);"""


def upgrade() -> None:
    op.execute(TABLE_SQL)
    op.execute(
        """
CREATE FUNCTION import_tasks_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Task history cannot be deleted'; END IF;
 IF NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.symbol IS DISTINCT FROM OLD.symbol
    OR NEW.request IS DISTINCT FROM OLD.request OR NEW.created_at IS DISTINCT FROM OLD.created_at
    OR OLD.status IN ('completed','failed') THEN
  RAISE EXCEPTION 'Frozen task identity or terminal history cannot change';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER import_tasks_protect BEFORE UPDATE OR DELETE ON import_tasks
FOR EACH ROW EXECUTE FUNCTION import_tasks_guard();
CREATE TRIGGER import_tasks_no_truncate BEFORE TRUNCATE ON import_tasks
FOR EACH STATEMENT EXECUTE FUNCTION deny_import_tasks_truncate();
""".replace(
            "CREATE TRIGGER import_tasks_no_truncate",
            """
CREATE FUNCTION deny_import_tasks_truncate() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN RAISE EXCEPTION 'Task history cannot be truncated'; END; $$;
CREATE TRIGGER import_tasks_no_truncate""",
        )
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled")
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE import_tasks IN ACCESS EXCLUSIVE MODE NOWAIT"))
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM import_tasks)")):
        raise RuntimeError("Refusing to remove non-empty task history")
    op.drop_table("import_tasks")
    op.execute("DROP FUNCTION import_tasks_guard(); DROP FUNCTION deny_import_tasks_truncate()")
