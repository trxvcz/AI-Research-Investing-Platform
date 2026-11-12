"""Admit explicitly selected SEC fundamentals runs without changing old histories.

Revision ID: 0006_sec_pipeline
Revises: 0005_provider_quota
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0006_sec_pipeline"
down_revision = "0005_provider_quota"
branch_labels = None
depends_on = None


def _guards(sec: bool) -> tuple[str, str, str]:
    path = Path(__file__).with_name("0004_worker.py")
    spec = importlib.util.spec_from_file_location("sec_historical_worker_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Historical worker migration is unavailable")
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    run_sql, event_sql = previous._ledger_guards(automatic=True)
    job_sql: str = previous.CHECK_JOB_SQL.replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )
    if sec:
        allowed = "('manual-research-v1','deterministic-research-v1')"
        job_condition = "IF pipeline IS DISTINCT FROM 'deterministic-research-v1' THEN"
        if run_sql.count(allowed) != 1 or job_sql.count(job_condition) != 1:
            raise RuntimeError("Historical pipeline guard differs from the expected snapshot")
        run_sql = run_sql.replace(
            allowed, "('manual-research-v1','deterministic-research-v1','sec-fundamentals-v1')"
        )
        job_sql = job_sql.replace(
            job_condition,
            "IF pipeline IS NULL OR pipeline NOT IN "
            "('deterministic-research-v1','sec-fundamentals-v1') THEN",
        )
    return run_sql, event_sql, job_sql


def upgrade() -> None:
    for sql in _guards(sec=True):
        op.execute(sql)


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade is disabled to protect SEC history")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE research_runs, run_events, worker_jobs, worker_claims "
            "IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if bind.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM research_runs WHERE "
            "definition->>'pipeline_version'='sec-fundamentals-v1')"
        )
    ):
        raise RuntimeError("Refusing to remove SEC pipeline support with non-empty SEC history")
    for sql in _guards(sec=False):
        op.execute(sql)
