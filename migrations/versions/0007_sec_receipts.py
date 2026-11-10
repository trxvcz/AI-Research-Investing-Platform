"""Internal SEC ingestion receipts bind trusted retrieval to immutable raw bytes.

Revision ID: 0007_sec_receipts
Revises: 0006_sec_pipeline
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_sec_receipts"
down_revision = "0006_sec_pipeline"
branch_labels = None
depends_on = None

CHECK_INSERT_SQL = """
CREATE FUNCTION sec_ingestions_check_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    raw raw_snapshots%ROWTYPE;
    expected_source text;
    valid_url boolean;
BEGIN
    SELECT * INTO raw FROM raw_snapshots WHERE snapshot_id=NEW.snapshot_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown SEC raw snapshot' USING ERRCODE='23503';
    END IF;
    expected_source := CASE NEW.resource
        WHEN 'submissions' THEN 'sec-edgar-submissions-v1'
        WHEN 'revenue' THEN 'sec-edgar-revenue-v1'
        WHEN 'net_income' THEN 'sec-edgar-net-income-v1' END;
    valid_url := CASE NEW.resource
        WHEN 'submissions' THEN NEW.source_url =
            'https://data.sec.gov/submissions/CIK' || NEW.cik || '.json'
        WHEN 'net_income' THEN NEW.source_url =
            'https://data.sec.gov/api/xbrl/companyconcept/CIK' || NEW.cik ||
            '/us-gaap/NetIncomeLoss.json'
        WHEN 'revenue' THEN NEW.source_url IN (
            'https://data.sec.gov/api/xbrl/companyconcept/CIK' || NEW.cik ||
            '/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax.json',
            'https://data.sec.gov/api/xbrl/companyconcept/CIK' || NEW.cik ||
            '/us-gaap/Revenues.json',
            'https://data.sec.gov/api/xbrl/companyconcept/CIK' || NEW.cik ||
            '/us-gaap/SalesRevenueNet.json') ELSE false END;
    IF valid_url IS DISTINCT FROM true OR expected_source IS NULL
       OR NEW.instrument_id IS DISTINCT FROM raw.instrument_id
       OR NEW.sha256 IS DISTINCT FROM raw.sha256
       OR NEW.retrieved_at IS DISTINCT FROM raw.retrieved_at
       OR raw.data_origin IS DISTINCT FROM 'live'
       OR raw.source_id IS DISTINCT FROM expected_source
       OR raw.available_at IS DISTINCT FROM raw.retrieved_at
       OR raw.as_of IS DISTINCT FROM raw.retrieved_at
       OR raw.metadata->>'source_url' IS DISTINCT FROM NEW.source_url
       OR raw.metadata->>'media_type' IS DISTINCT FROM 'application/json'
       OR raw.metadata->>'license' IS DISTINCT FROM
          'SEC website dissemination policy; https://www.sec.gov/about/privacy-information'
       OR encode(sha256(raw.content),'hex') IS DISTINCT FROM NEW.sha256 THEN
        RAISE EXCEPTION 'SEC ingestion receipt identity conflict' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$
"""

DENY_MUTATION_SQL = """
CREATE FUNCTION sec_ingestions_deny_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    RAISE EXCEPTION 'SEC ingestion receipts are immutable' USING ERRCODE='23514';
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "sec_ingestions",
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_snapshots.snapshot_id"),
            primary_key=True,
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.instrument_id"),
            nullable=False,
        ),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("resource", sa.String(16), nullable=False),
        sa.Column("source_url", sa.String(256), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "instrument_id", "source_url", "sha256", name="uq_sec_ingestion_content"
        ),
        sa.CheckConstraint(
            "cik ~ '^[0-9]{10}$' AND cik <> '0000000000'", name="ck_sec_ingestion_cik"
        ),
        sa.CheckConstraint(
            "resource IN ('submissions','revenue','net_income')", name="ck_sec_ingestion_resource"
        ),
        sa.CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_sec_ingestion_hash"),
    )
    op.create_index(
        "ix_sec_ingestions_lookup",
        "sec_ingestions",
        ["instrument_id", "source_url", "retrieved_at"],
    )
    op.execute(CHECK_INSERT_SQL)
    op.execute(DENY_MUTATION_SQL)
    op.execute(
        "CREATE TRIGGER sec_ingestions_check_insert BEFORE INSERT ON sec_ingestions "
        "FOR EACH ROW EXECUTE FUNCTION sec_ingestions_check_insert()"
    )
    op.execute(
        "CREATE TRIGGER sec_ingestions_deny_changes BEFORE UPDATE OR DELETE "
        "ON sec_ingestions FOR EACH ROW EXECUTE FUNCTION sec_ingestions_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER sec_ingestions_deny_truncate BEFORE TRUNCATE ON sec_ingestions "
        "FOR EACH STATEMENT EXECUTE FUNCTION sec_ingestions_deny_mutation()"
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade is disabled to protect SEC receipt history")
    bind = op.get_bind()
    # DROP also locks referenced tables while removing foreign keys. Acquire them
    # up front with NOWAIT so an in-flight raw upload cannot hang a downgrade.
    bind.execute(
        sa.text(
            "LOCK TABLE instruments, raw_snapshots, sec_ingestions IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if bind.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM sec_ingestions)")):
        raise RuntimeError("Refusing to remove non-empty SEC ingestion receipts")
    op.drop_table("sec_ingestions")
    op.execute("DROP FUNCTION sec_ingestions_check_insert()")
    op.execute("DROP FUNCTION sec_ingestions_deny_mutation()")
