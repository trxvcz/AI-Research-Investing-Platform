"""Fenced deterministic worker queue and immutable claim provenance.

Revision ID: 0004_worker
Revises: 0003_runs_snapshots
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_worker"
down_revision = "0003_runs_snapshots"
branch_labels = None
depends_on = None


def _ledger_guards(automatic: bool) -> tuple[str, str]:
    """Reuse the immutable historical snapshot, never runtime implementation."""
    previous_path = Path(__file__).with_name("0003_runs_snapshots.py")
    spec = importlib.util.spec_from_file_location("worker_previous_migration", previous_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Historical ledger migration is unavailable")
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    run_sql: str = previous.CHECK_RUN_SQL
    event_sql: str = previous.CHECK_EVENT_SQL
    if automatic:
        run_pattern = "OR NEW.definition->>'pipeline_version' IS DISTINCT FROM 'manual-research-v1'"
        event_pattern = "OR NEW.state->>'pipeline_version' IS DISTINCT FROM 'manual-research-v1'"
        if run_pattern not in run_sql or event_pattern not in event_sql:
            raise RuntimeError("Historical pipeline guard differs from the expected snapshot")
        run_sql = run_sql.replace(
            run_pattern,
            "OR NEW.definition->>'pipeline_version' IS NULL "
            "OR NEW.definition->>'pipeline_version' NOT IN "
            "('manual-research-v1','deterministic-research-v1')",
        )
        event_sql = event_sql.replace(
            event_pattern,
            "OR NEW.state->>'pipeline_version' IS DISTINCT FROM "
            "definition_row.definition->>'pipeline_version'",
        )
    return (
        run_sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
        event_sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
    )


CHECK_JOB_SQL = """
CREATE FUNCTION worker_jobs_check_change() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE pipeline text;
BEGIN
    SELECT definition->>'pipeline_version' INTO pipeline FROM research_runs
        WHERE run_id=NEW.run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown worker run' USING ERRCODE='23503';
    END IF;
    IF pipeline IS DISTINCT FROM 'deterministic-research-v1' THEN
        RAISE EXCEPTION 'Worker requires deterministic pipeline' USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE' THEN
        IF NEW.run_id IS DISTINCT FROM OLD.run_id
           OR NEW.implementation_hash IS DISTINCT FROM OLD.implementation_hash
           OR NEW.pipeline_git_sha IS DISTINCT FROM OLD.pipeline_git_sha
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.updated_at < OLD.updated_at
           OR NEW.attempts < OLD.attempts OR NEW.attempts > OLD.attempts + 1
           OR OLD.status IN ('completed','dead') THEN
            RAISE EXCEPTION 'Worker job identity or history conflict' USING ERRCODE='23514';
        END IF;
        IF NEW.attempts > OLD.attempts THEN
            IF NEW.status<>'running' OR NEW.lease_token IS NOT DISTINCT FROM OLD.lease_token
               OR (OLD.status='running' AND OLD.lease_expires_at > clock_timestamp()) THEN
                RAISE EXCEPTION 'Worker claim is not eligible' USING ERRCODE='23514';
            END IF;
        ELSIF NEW.worker_id IS DISTINCT FROM OLD.worker_id
           OR (NEW.status='running' AND NEW.lease_token IS DISTINCT FROM OLD.lease_token) THEN
            RAISE EXCEPTION 'Worker lease owner changed without a claim' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$
"""

CHECK_CLAIM_SQL = """
CREATE FUNCTION worker_claims_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE job worker_jobs%ROWTYPE;
BEGIN
    SELECT * INTO job FROM worker_jobs WHERE run_id=NEW.run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown worker job' USING ERRCODE='23503';
    END IF;
    IF job.status IS DISTINCT FROM 'running'
       OR NEW.attempt IS DISTINCT FROM job.attempts
       OR NEW.lease_token IS DISTINCT FROM job.lease_token
       OR NEW.worker_id IS DISTINCT FROM job.worker_id
       OR NEW.implementation_hash IS DISTINCT FROM job.implementation_hash
       OR NEW.pipeline_git_sha IS DISTINCT FROM job.pipeline_git_sha
       OR NEW.claimed_at IS DISTINCT FROM job.updated_at
       OR NEW.initial_expires_at IS DISTINCT FROM job.lease_expires_at THEN
        RAISE EXCEPTION 'Worker claim provenance mismatch' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$
"""

CHECK_COMMIT_SQL = """
CREATE FUNCTION worker_jobs_check_commit() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    job worker_jobs%ROWTYPE;
    claim worker_claims%ROWTYPE;
BEGIN
    -- Deferred events can carry an earlier NEW row: verify the final job state.
    SELECT * INTO job FROM worker_jobs WHERE run_id=NEW.run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Worker job disappeared' USING ERRCODE='23514';
    END IF;
    IF job.attempts > 0 THEN
        SELECT * INTO claim FROM worker_claims
            WHERE run_id=job.run_id AND attempt=job.attempts;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Worker claim history missing' USING ERRCODE='23514';
        END IF;
        IF job.worker_id IS DISTINCT FROM claim.worker_id
           OR job.implementation_hash IS DISTINCT FROM claim.implementation_hash
           OR job.pipeline_git_sha IS DISTINCT FROM claim.pipeline_git_sha
           OR (job.status='running' AND job.lease_token IS DISTINCT FROM claim.lease_token) THEN
            RAISE EXCEPTION 'Worker job and claim conflict' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$$
"""

DENY_DELETE_SQL = """
CREATE FUNCTION worker_history_deny_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'Worker identity and claim history cannot be removed' USING ERRCODE='23514';
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "worker_jobs",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.run_id"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("implementation_hash", sa.String(64), nullable=False),
        sa.Column("pipeline_git_sha", sa.String(64), nullable=False),
        sa.Column("last_error_code", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','dead')", name="ck_worker_job_status"
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_worker_job_attempts"),
        sa.CheckConstraint("implementation_hash ~ '^[a-f0-9]{64}$'", name="ck_worker_job_hash"),
        sa.CheckConstraint(
            "pipeline_git_sha ~ '^([a-f0-9]{40}|[a-f0-9]{64})$'", name="ck_worker_job_git"
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_worker_job_time"),
        sa.CheckConstraint(
            "worker_id IS NULL OR (length(btrim(worker_id)) > 0 AND worker_id !~ '[[:cntrl:]]')",
            name="ck_worker_job_owner",
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR (length(btrim(last_error_code)) > 0 "
            "AND last_error_code !~ '[[:cntrl:]]')",
            name="ck_worker_job_error",
        ),
        sa.CheckConstraint(
            "(status='queued' AND attempts=0 AND worker_id IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(status='running' AND attempts BETWEEN 1 AND 3 AND worker_id IS NOT NULL "
            "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status IN ('completed','dead') AND lease_token IS NULL AND lease_expires_at IS NULL "
            "AND (status='dead' OR attempts >= 1) AND (attempts=0 OR worker_id IS NOT NULL))",
            name="ck_worker_job_lease_shape",
        ),
    )
    op.create_table(
        "worker_claims",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("worker_jobs.run_id"),
            primary_key=True,
        ),
        sa.Column("attempt", sa.Integer, primary_key=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("implementation_hash", sa.String(64), nullable=False),
        sa.Column("pipeline_git_sha", sa.String(64), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt BETWEEN 1 AND 3", name="ck_worker_claim_attempt"),
        sa.CheckConstraint("implementation_hash ~ '^[a-f0-9]{64}$'", name="ck_worker_claim_hash"),
        sa.CheckConstraint(
            "pipeline_git_sha ~ '^([a-f0-9]{40}|[a-f0-9]{64})$'", name="ck_worker_claim_git"
        ),
        sa.CheckConstraint(
            "length(btrim(worker_id)) > 0 AND worker_id !~ '[[:cntrl:]]'",
            name="ck_worker_claim_owner",
        ),
        sa.CheckConstraint(
            "initial_expires_at BETWEEN claimed_at + INTERVAL '15 seconds' "
            "AND claimed_at + INTERVAL '300 seconds'",
            name="ck_worker_claim_lease",
        ),
    )
    for sql in (CHECK_JOB_SQL, CHECK_CLAIM_SQL, CHECK_COMMIT_SQL, DENY_DELETE_SQL):
        op.execute(sql)
    op.execute(
        "CREATE TRIGGER worker_jobs_check_change BEFORE INSERT OR UPDATE ON worker_jobs "
        "FOR EACH ROW EXECUTE FUNCTION worker_jobs_check_change()"
    )
    op.execute(
        "CREATE TRIGGER worker_claims_check_insert BEFORE INSERT ON worker_claims "
        "FOR EACH ROW EXECUTE FUNCTION worker_claims_check_insert()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER worker_jobs_check_commit AFTER INSERT OR UPDATE "
        "ON worker_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION worker_jobs_check_commit()"
    )
    op.execute(
        "CREATE TRIGGER worker_claims_deny_changes BEFORE UPDATE OR DELETE ON worker_claims "
        "FOR EACH ROW EXECUTE FUNCTION worker_history_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER worker_claims_deny_truncate BEFORE TRUNCATE ON worker_claims "
        "FOR EACH STATEMENT EXECUTE FUNCTION worker_history_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER worker_jobs_deny_delete BEFORE DELETE ON worker_jobs "
        "FOR EACH ROW EXECUTE FUNCTION worker_history_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER worker_jobs_deny_truncate BEFORE TRUNCATE ON worker_jobs "
        "FOR EACH STATEMENT EXECUTE FUNCTION worker_history_deny_mutation()"
    )
    for sql in _ledger_guards(automatic=True):
        op.execute(sql)


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade is disabled to protect worker history")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE research_runs, run_events, worker_jobs, worker_claims "
            "IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if (
        bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM worker_jobs)"))
        or bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM worker_claims)"))
        or bind.scalar(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM research_runs WHERE "
                "definition->>'pipeline_version'='deterministic-research-v1')"
            )
        )
    ):
        raise RuntimeError("Refusing to remove non-empty worker or automatic run history")
    for sql in _ledger_guards(automatic=False):
        op.execute(sql)
    op.drop_table("worker_claims")
    op.drop_table("worker_jobs")
    for function in (
        "worker_jobs_check_commit",
        "worker_claims_check_insert",
        "worker_jobs_check_change",
        "worker_history_deny_mutation",
    ):
        op.execute(f"DROP FUNCTION {function}()")
