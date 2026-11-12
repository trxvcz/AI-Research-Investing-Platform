"""Freeze versioned historical evidence without changing existing analyses or budget."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016_ai_history_context"
down_revision = "0015_ai_analysis"
branch_labels = None
depends_on = None

CONTEXT_CHECK = """
(prompt_version='report-synthesis-v1' AND evidence_context IS NULL) OR
(prompt_version='report-history-v2' AND evidence_context IS NOT NULL AND
 jsonb_typeof(evidence_context)='object' AND
 octet_length(evidence_context::text)<=262144 AND
 evidence_context ?& ARRAY['context_version','report_id','revision','report_checksum',
 'as_of','evidence','limitations','context_sha256','methodology_version'] AND
 jsonb_typeof(evidence_context->'context_version')='string' AND
 evidence_context->>'context_version'='report-history-context-v1' AND
 jsonb_typeof(evidence_context->'methodology_version')='string' AND
 evidence_context->>'methodology_version'='sec-comparatives-v1' AND
 jsonb_typeof(evidence_context->'report_id')='string' AND
 evidence_context->>'report_id'=report_id::text AND
 evidence_context->'revision'=to_jsonb(revision) AND
 jsonb_typeof(evidence_context->'report_checksum')='string' AND
 evidence_context->>'report_checksum'=report_checksum AND
 jsonb_typeof(evidence_context->'as_of')='string' AND
 jsonb_typeof(evidence_context->'context_sha256')='string' AND
 evidence_context->>'context_sha256' ~ '^[a-f0-9]{64}$' AND
 jsonb_typeof(evidence_context->'evidence')='array' AND
 jsonb_array_length(evidence_context->'evidence') BETWEEN 1 AND 64 AND
 jsonb_typeof(evidence_context->'limitations')='array')
"""


def guard_sql(history: bool) -> str:
    new_context = ",NEW.evidence_context" if history else ""
    old_context = ",OLD.evidence_context" if history else ""
    as_of_guard = (
        """
  IF NEW.prompt_version='report-history-v2' AND
     NEW.evidence_context->>'as_of' IS DISTINCT FROM source.payload->'input'->>'as_of' THEN
   RAISE EXCEPTION 'AI history cutoff mismatch';
  END IF;
"""
        if history
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION ai_analysis_guard() RETURNS trigger
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
{as_of_guard}
  SELECT * INTO reservation FROM ai_budget_reservations WHERE request_id=NEW.request_id;
  IF NOT FOUND OR reservation.kind<>'analysis' OR
     NEW.created_at<>reservation.created_at OR NEW.status<>'running' THEN
   RAISE EXCEPTION 'AI reservation mismatch';
  END IF;
 ELSE
  IF OLD.status<>'running' OR NEW.status NOT IN ('completed','failed') OR
    ROW(NEW.request_id,NEW.revision_id,NEW.report_id,NEW.revision,NEW.report_checksum,
        NEW.model_id,NEW.prompt_version,NEW.created_at{new_context}) IS DISTINCT FROM
    ROW(OLD.request_id,OLD.revision_id,OLD.report_id,OLD.revision,OLD.report_checksum,
        OLD.model_id,OLD.prompt_version,OLD.created_at{old_context}) THEN
   RAISE EXCEPTION 'Frozen AI analysis identity or terminal result';
  END IF;
 END IF;
 RETURN NEW;
END; $$;
"""


def upgrade() -> None:
    op.add_column("ai_analyses", sa.Column("evidence_context", JSONB(none_as_null=True)))
    op.drop_constraint("ck_ai_analysis_prompt", "ai_analyses", type_="check")
    op.create_check_constraint(
        "ck_ai_analysis_prompt",
        "ai_analyses",
        "prompt_version IN ('report-synthesis-v1','report-history-v2')",
    )
    op.create_check_constraint("ck_ai_analysis_context", "ai_analyses", CONTEXT_CHECK)
    op.execute(guard_sql(True))


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled")
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE ai_analyses IN ACCESS EXCLUSIVE MODE NOWAIT"))
    if bind.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM ai_analyses WHERE "
            "prompt_version='report-history-v2' OR evidence_context IS NOT NULL)"
        )
    ):
        raise RuntimeError("Refusing to remove frozen AI historical evidence")
    op.execute(guard_sql(False))
    op.drop_constraint("ck_ai_analysis_context", "ai_analyses", type_="check")
    op.drop_constraint("ck_ai_analysis_prompt", "ai_analyses", type_="check")
    op.create_check_constraint(
        "ck_ai_analysis_prompt", "ai_analyses", "prompt_version='report-synthesis-v1'"
    )
    op.drop_column("ai_analyses", "evidence_context")
