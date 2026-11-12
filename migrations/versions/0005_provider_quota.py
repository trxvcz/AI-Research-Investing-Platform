"""Durable, non-refundable provider quota windows.

Revision ID: 0005_provider_quota
Revises: 0004_worker
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_provider_quota"
down_revision = "0004_worker"
branch_labels = None
depends_on = None


CHECK_CHANGE_SQL = """
CREATE FUNCTION provider_quota_check_change() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    -- Advisory locking cannot refresh an older repeatable-read snapshot. Refuse
    -- that mode rather than admitting an overlapping window invisible to its snapshot.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Quota requires read committed isolation' USING ERRCODE='23514';
    END IF;
    IF TG_OP='INSERT' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(NEW.quota_scope, 0));
        IF NEW.used <> 0 THEN
            RAISE EXCEPTION 'Quota must start unused' USING ERRCODE='23514';
        END IF;
        IF EXISTS(SELECT 1 FROM provider_quota_windows WHERE quota_scope=NEW.quota_scope
                  AND window_start < NEW.window_end AND window_end > NEW.window_start) THEN
            RAISE EXCEPTION 'Quota window overlaps existing history' USING ERRCODE='23514';
        END IF;
    ELSE
        IF NEW.quota_scope IS DISTINCT FROM OLD.quota_scope
           OR NEW.window_start IS DISTINCT FROM OLD.window_start
           OR NEW.window_end IS DISTINCT FROM OLD.window_end
           OR NEW.quota_limit IS DISTINCT FROM OLD.quota_limit
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.used IS DISTINCT FROM OLD.used + 1
           OR NEW.updated_at < OLD.updated_at THEN
            RAISE EXCEPTION 'Quota history cannot be rewritten' USING ERRCODE='23514';
        END IF;
        IF clock_timestamp() < NEW.window_start OR clock_timestamp() >= NEW.window_end THEN
            RAISE EXCEPTION 'Quota window is inactive' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$
"""

DENY_DELETE_SQL = """
CREATE FUNCTION provider_quota_deny_delete() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'Quota history cannot be removed' USING ERRCODE='23514';
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "provider_quota_windows",
        sa.Column("quota_scope", sa.String(128), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quota_limit", sa.Integer, nullable=False),
        sa.Column("used", sa.Integer, nullable=False),
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
            "length(btrim(quota_scope)) BETWEEN 1 AND 128 AND quota_scope=btrim(quota_scope) "
            "AND quota_scope !~ '[[:cntrl:]]'",
            name="ck_provider_quota_scope",
        ),
        sa.CheckConstraint("window_start < window_end", name="ck_provider_quota_window"),
        sa.CheckConstraint("quota_limit BETWEEN 0 AND 1000000", name="ck_provider_quota_limit"),
        sa.CheckConstraint("used BETWEEN 0 AND quota_limit", name="ck_provider_quota_used"),
        sa.CheckConstraint("updated_at >= created_at", name="ck_provider_quota_time"),
    )
    op.execute(CHECK_CHANGE_SQL)
    op.execute(DENY_DELETE_SQL)
    op.execute(
        "CREATE TRIGGER provider_quota_check_change BEFORE INSERT OR UPDATE "
        "ON provider_quota_windows FOR EACH ROW EXECUTE FUNCTION provider_quota_check_change()"
    )
    op.execute(
        "CREATE TRIGGER provider_quota_deny_delete BEFORE DELETE ON provider_quota_windows "
        "FOR EACH ROW EXECUTE FUNCTION provider_quota_deny_delete()"
    )
    op.execute(
        "CREATE TRIGGER provider_quota_deny_truncate BEFORE TRUNCATE ON provider_quota_windows "
        "FOR EACH STATEMENT EXECUTE FUNCTION provider_quota_deny_delete()"
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade is disabled to protect quota history")
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE provider_quota_windows IN ACCESS EXCLUSIVE MODE NOWAIT"))
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM provider_quota_windows)")):
        raise RuntimeError("Refusing to remove non-empty provider quota history")
    op.drop_table("provider_quota_windows")
    op.execute("DROP FUNCTION provider_quota_check_change()")
    op.execute("DROP FUNCTION provider_quota_deny_delete()")
