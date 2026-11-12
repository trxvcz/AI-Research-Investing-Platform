"""Durable one-off paid synthesis budget and immutable terminal analyses."""

import sqlalchemy as sa
from alembic import op

revision = "0015_ai_analysis"
down_revision = "0014_sec_schedules"
branch_labels = None
depends_on = None

TABLE_SQL = """
CREATE TABLE ai_budget_controls (
 scope VARCHAR(64) PRIMARY KEY,
 budget_grosz INTEGER NOT NULL,
 reserved_grosz INTEGER NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CONSTRAINT ck_ai_budget_scope CHECK (scope='ai-analysis-pilot-20261111'),
 CONSTRAINT ck_ai_budget_limit CHECK (budget_grosz=5000),
 CONSTRAINT ck_ai_budget_reserved CHECK
  (reserved_grosz BETWEEN 0 AND 5000 AND reserved_grosz % 100=0)
);
INSERT INTO ai_budget_controls(scope,budget_grosz,reserved_grosz)
VALUES ('ai-analysis-pilot-20261111',5000,0);
CREATE TABLE ai_budget_reservations (
 request_id UUID PRIMARY KEY,
 scope VARCHAR(64) NOT NULL REFERENCES ai_budget_controls(scope),
 kind VARCHAR(16) NOT NULL,
 amount_grosz INTEGER NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CONSTRAINT ck_ai_reservation_kind CHECK (kind IN ('analysis','qualification')),
 CONSTRAINT ck_ai_reservation_amount CHECK (amount_grosz=100)
);
CREATE TABLE ai_analyses (
 request_id UUID PRIMARY KEY REFERENCES ai_budget_reservations(request_id),
 revision_id UUID NOT NULL REFERENCES report_revisions(revision_id),
 report_id UUID NOT NULL,
 revision INTEGER NOT NULL,
 report_checksum VARCHAR(64) NOT NULL,
 model_id VARCHAR(128) NOT NULL,
 prompt_version VARCHAR(32) NOT NULL,
 status VARCHAR(16) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 finished_at TIMESTAMPTZ,
 analysis JSONB,
 error_code VARCHAR(64),
 audit JSONB,
 CONSTRAINT ck_ai_analysis_revision CHECK (revision >= 1),
 CONSTRAINT ck_ai_analysis_checksum CHECK (report_checksum ~ '^[a-f0-9]{64}$'),
 CONSTRAINT ck_ai_analysis_model CHECK (model_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
 CONSTRAINT ck_ai_analysis_prompt CHECK (prompt_version='report-synthesis-v1'),
 CONSTRAINT ck_ai_analysis_status CHECK (status IN ('running','completed','failed')),
 CONSTRAINT ck_ai_analysis_time CHECK (finished_at IS NULL OR finished_at >= created_at),
 CONSTRAINT ck_ai_analysis_result CHECK (
  (status='running' AND finished_at IS NULL AND analysis IS NULL AND
   error_code IS NULL AND audit IS NULL) OR
  (status='completed' AND finished_at IS NOT NULL AND analysis IS NOT NULL AND
   jsonb_typeof(analysis)='object' AND error_code IS NULL AND audit IS NOT NULL AND
   jsonb_typeof(audit)='object') OR
  (status='failed' AND finished_at IS NOT NULL AND analysis IS NULL AND
   error_code IS NOT NULL AND error_code ~ '^[A-Z][A-Z0-9_]{0,63}$' AND
   audit IS NOT NULL AND jsonb_typeof(audit)='object')
 )
);
CREATE INDEX ix_ai_analysis_report ON ai_analyses (report_id,revision,created_at);
"""

GUARD_SQL = """
CREATE FUNCTION ai_immutable_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN RAISE EXCEPTION 'AI history is immutable'; END; $$;
CREATE TRIGGER ai_reservations_immutable BEFORE UPDATE OR DELETE ON ai_budget_reservations
FOR EACH ROW EXECUTE FUNCTION ai_immutable_guard();
CREATE TRIGGER ai_reservations_no_truncate BEFORE TRUNCATE ON ai_budget_reservations
FOR EACH STATEMENT EXECUTE FUNCTION ai_immutable_guard();
CREATE FUNCTION ai_budget_control_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
 IF TG_OP<>'UPDATE' OR pg_trigger_depth()<2 THEN
  RAISE EXCEPTION 'AI budget cannot be reset';
 END IF;
 IF ROW(NEW.scope,NEW.budget_grosz,NEW.created_at) IS DISTINCT FROM
    ROW(OLD.scope,OLD.budget_grosz,OLD.created_at) OR
    NEW.reserved_grosz<>OLD.reserved_grosz+100 THEN
  RAISE EXCEPTION 'Invalid AI budget change';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER ai_budget_control_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_budget_controls
FOR EACH ROW EXECUTE FUNCTION ai_budget_control_guard();
CREATE TRIGGER ai_budget_control_no_truncate BEFORE TRUNCATE ON ai_budget_controls
FOR EACH STATEMENT EXECUTE FUNCTION ai_budget_control_guard();
CREATE FUNCTION ai_budget_reserve_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE reserved_scope text;
BEGIN
 IF NEW.scope<>'ai-analysis-pilot-20261111' OR NEW.amount_grosz<>100 OR
    NEW.kind NOT IN ('analysis','qualification') THEN
  RAISE EXCEPTION 'Invalid AI reservation';
 END IF;
 UPDATE ai_budget_controls SET reserved_grosz=reserved_grosz+100
 WHERE scope=NEW.scope AND reserved_grosz<=4900 RETURNING scope INTO reserved_scope;
 IF NOT FOUND THEN
  RAISE EXCEPTION USING ERRCODE='P5000', MESSAGE='AI budget exhausted';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER ai_budget_reserve_guard BEFORE INSERT ON ai_budget_reservations
FOR EACH ROW EXECUTE FUNCTION ai_budget_reserve_guard();
CREATE FUNCTION ai_analysis_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE source report_revisions%ROWTYPE; reservation ai_budget_reservations%ROWTYPE;
BEGIN
 IF TG_OP IN ('DELETE','TRUNCATE') THEN
  RAISE EXCEPTION 'AI history is immutable';
 END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO source FROM report_revisions WHERE revision_id=NEW.revision_id;
  IF NOT FOUND OR ROW(NEW.report_id,NEW.revision,NEW.report_checksum) IS DISTINCT FROM
     ROW(source.report_id,source.revision,source.checksum) THEN
   RAISE EXCEPTION 'AI source revision mismatch';
  END IF;
  SELECT * INTO reservation FROM ai_budget_reservations WHERE request_id=NEW.request_id;
  IF NOT FOUND OR reservation.kind<>'analysis' OR
     NEW.created_at<>reservation.created_at OR NEW.status<>'running' THEN
   RAISE EXCEPTION 'AI reservation mismatch';
  END IF;
 ELSE
  IF OLD.status<>'running' OR NEW.status NOT IN ('completed','failed') OR
    ROW(NEW.request_id,NEW.revision_id,NEW.report_id,NEW.revision,NEW.report_checksum,
        NEW.model_id,NEW.prompt_version,NEW.created_at) IS DISTINCT FROM
    ROW(OLD.request_id,OLD.revision_id,OLD.report_id,OLD.revision,OLD.report_checksum,
        OLD.model_id,OLD.prompt_version,OLD.created_at) THEN
   RAISE EXCEPTION 'Frozen AI analysis identity or terminal result';
  END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER ai_analysis_guard BEFORE INSERT OR UPDATE OR DELETE ON ai_analyses
FOR EACH ROW EXECUTE FUNCTION ai_analysis_guard();
CREATE TRIGGER ai_analysis_no_truncate BEFORE TRUNCATE ON ai_analyses
FOR EACH STATEMENT EXECUTE FUNCTION ai_analysis_guard();
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
            "LOCK TABLE ai_budget_controls,ai_budget_reservations,ai_analyses "
            "IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if bind.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM ai_budget_reservations) OR "
            "EXISTS(SELECT 1 FROM ai_analyses)"
        )
    ):
        raise RuntimeError("Refusing to remove non-empty AI spending history")
    op.drop_table("ai_analyses")
    op.drop_table("ai_budget_reservations")
    op.drop_table("ai_budget_controls")
    op.execute(
        "DROP FUNCTION ai_analysis_guard(); DROP FUNCTION ai_budget_reserve_guard(); "
        "DROP FUNCTION ai_budget_control_guard(); DROP FUNCTION ai_immutable_guard()"
    )
