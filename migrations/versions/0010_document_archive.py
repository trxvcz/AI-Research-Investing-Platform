"""Immutable local document archives and append-only human decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0010_document_archive"
down_revision = "0009_import_tasks"
branch_labels = None
depends_on = None

TABLE_SQL = """
CREATE TABLE document_archives (
	archive_id UUID NOT NULL,
	instrument_id UUID,
	request JSONB NOT NULL,
	request_sha256 VARCHAR(64) NOT NULL,
	raw_content BYTEA NOT NULL,
	document_sha256 VARCHAR(64) NOT NULL,
	draft_sha256 VARCHAR(64) NOT NULL,
	packet JSONB NOT NULL,
	result JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (archive_id),
	CONSTRAINT ck_document_archive_raw_size CHECK
    (octet_length(raw_content) BETWEEN 1 AND 1048576),
	CONSTRAINT ck_document_archive_hashes CHECK (request_sha256 ~ '^[a-f0-9]{64}$'
    AND document_sha256 ~ '^[a-f0-9]{64}$'
    AND draft_sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(instrument_id) REFERENCES instruments (instrument_id)
)

;

CREATE TABLE document_reviews (
	archive_id UUID NOT NULL,
	revision INTEGER NOT NULL,
	command_id UUID NOT NULL,
	command JSONB NOT NULL,
	command_sha256 VARCHAR(64) NOT NULL,
	reviewed_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (archive_id, revision),
	CONSTRAINT uq_document_review_command UNIQUE (archive_id, command_id),
	CONSTRAINT ck_document_review_revision CHECK (revision BETWEEN 1 AND 10000),
	CONSTRAINT ck_document_review_hash CHECK (command_sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(archive_id) REFERENCES document_archives (archive_id)
)

;
CREATE INDEX ix_document_archive_instrument ON document_archives (instrument_id, archive_id);
"""


def upgrade() -> None:
    op.execute(TABLE_SQL)
    op.execute(GUARD_SQL)


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled")
    bind = op.get_bind()
    # Dropping the archive FK also locks its referenced instrument table.
    # Acquire that lock explicitly with NOWAIT so an in-flight source import
    # makes downgrade fail promptly instead of waiting behind its transaction.
    bind.execute(
        sa.text(
            "LOCK TABLE instruments, document_archives, document_reviews "
            "IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if bind.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM document_archives) "
            "OR EXISTS(SELECT 1 FROM document_reviews)"
        )
    ):
        raise RuntimeError("Refusing to remove non-empty document history")
    op.drop_table("document_reviews")
    op.drop_table("document_archives")
    op.execute(
        "DROP FUNCTION document_history_immutable(); DROP FUNCTION document_review_sequence()"
    )


GUARD_SQL = r"""
CREATE FUNCTION document_history_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN RAISE EXCEPTION 'Document history is immutable'; END; $$;
CREATE TRIGGER document_archives_immutable BEFORE UPDATE OR DELETE ON document_archives
FOR EACH ROW EXECUTE FUNCTION document_history_immutable();
CREATE TRIGGER document_archives_no_truncate BEFORE TRUNCATE ON document_archives
FOR EACH STATEMENT EXECUTE FUNCTION document_history_immutable();
CREATE TRIGGER document_reviews_immutable BEFORE UPDATE OR DELETE ON document_reviews
FOR EACH ROW EXECUTE FUNCTION document_history_immutable();
CREATE TRIGGER document_reviews_no_truncate BEFORE TRUNCATE ON document_reviews
FOR EACH STATEMENT EXECUTE FUNCTION document_history_immutable();
CREATE FUNCTION document_review_sequence() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE previous_revision integer; previous_time timestamptz;
BEGIN
 PERFORM 1 FROM document_archives WHERE archive_id=NEW.archive_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Document does not exist'; END IF;
 SELECT COALESCE(MAX(revision),0),MAX(reviewed_at) INTO previous_revision,previous_time
 FROM document_reviews WHERE archive_id=NEW.archive_id;
 IF NEW.revision<>previous_revision+1 OR
    (NEW.command->>'expected_revision')::integer IS DISTINCT FROM previous_revision OR
    (NEW.command->>'command_id')::uuid IS DISTINCT FROM NEW.command_id OR
    (previous_time IS NOT NULL AND NEW.reviewed_at<previous_time) THEN
  RAISE EXCEPTION 'Document review sequence conflict';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER document_reviews_sequence BEFORE INSERT ON document_reviews
FOR EACH ROW EXECUTE FUNCTION document_review_sequence();
"""
