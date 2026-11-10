"""PostgreSQL Core tables. Runtime never creates or migrates these implicitly."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

MIGRATION_HEAD = "0010_document_archive"
metadata = MetaData()

instruments = Table(
    "instruments",
    metadata,
    Column("instrument_id", UUID(as_uuid=True), primary_key=True),
    Column("symbol", String(32), nullable=False),
    Column("exchange_mic", String(4), nullable=True),
    Column("currency", String(3), nullable=False),
    Column("asset_type", String(16), nullable=False),
    Column("data_origin", String(16), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint(
        "exchange_mic",
        "symbol",
        "data_origin",
        name="uq_instrument_listing",
        postgresql_nulls_not_distinct=True,
    ),
    CheckConstraint("symbol ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name="ck_instrument_symbol"),
    CheckConstraint(
        "exchange_mic IS NULL OR exchange_mic ~ '^[A-Z0-9]{4}$'",
        name="ck_instrument_exchange",
    ),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_instrument_currency"),
    CheckConstraint("asset_type IN ('equity','etf','commodity')", name="ck_instrument_type"),
    CheckConstraint("data_origin IN ('synthetic','live')", name="ck_instrument_origin"),
    CheckConstraint(
        "asset_type = 'commodity' OR exchange_mic IS NOT NULL", name="ck_instrument_listing_mic"
    ),
    CheckConstraint("available_at <= as_of", name="ck_instrument_availability"),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_instrument_payload"),
)

report_streams = Table(
    "report_streams",
    metadata,
    Column("report_id", UUID(as_uuid=True), primary_key=True),
    Column("instrument_id", String(128), nullable=False),
    Column("asset_type", String(16), nullable=False),
    Column("data_origin", String(16), nullable=False),
    Column(
        "registry_instrument_id",
        UUID(as_uuid=True),
        ForeignKey("instruments.instrument_id", name="fk_stream_registry_instrument"),
        nullable=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("length(btrim(instrument_id)) > 0", name="ck_stream_instrument"),
    CheckConstraint("asset_type IN ('equity','etf','commodity')", name="ck_stream_asset_type"),
    CheckConstraint("data_origin IN ('synthetic','live')", name="ck_stream_origin"),
)

report_revisions = Table(
    "report_revisions",
    metadata,
    Column("revision_id", UUID(as_uuid=True), primary_key=True),
    Column("report_id", UUID(as_uuid=True), ForeignKey("report_streams.report_id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("parent_revision_id", UUID(as_uuid=True), nullable=True),
    Column("generated_at_utc", DateTime(timezone=True), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("stored_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("report_id", "revision", name="uq_report_revision_number"),
    UniqueConstraint("report_id", "revision_id", name="uq_report_revision_identity"),
    ForeignKeyConstraint(
        ["report_id", "parent_revision_id"],
        ["report_revisions.report_id", "report_revisions.revision_id"],
        name="fk_revision_parent_same_report",
    ),
    CheckConstraint("revision > 0", name="ck_revision_positive"),
    CheckConstraint(
        "(revision = 1 AND parent_revision_id IS NULL) OR "
        "(revision > 1 AND parent_revision_id IS NOT NULL)",
        name="ck_revision_parent_required",
    ),
    CheckConstraint("parent_revision_id IS DISTINCT FROM revision_id", name="ck_not_own_parent"),
    CheckConstraint("checksum ~ '^[a-f0-9]{64}$'", name="ck_revision_checksum"),
    CheckConstraint("input_sha256 ~ '^[a-f0-9]{64}$'", name="ck_revision_input_checksum"),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_revision_payload_object"),
)

raw_snapshots = Table(
    "raw_snapshots",
    metadata,
    Column("snapshot_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "instrument_id", UUID(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False
    ),
    Column("data_origin", String(16), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=True),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("byte_length", Integer, nullable=False),
    Column("metadata", JSONB, nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("data_origin IN ('synthetic','live')", name="ck_snapshot_origin"),
    CheckConstraint("length(btrim(source_id)) > 0", name="ck_snapshot_source"),
    CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_snapshot_sha256"),
    CheckConstraint("byte_length BETWEEN 1 AND 1048576", name="ck_snapshot_size"),
    CheckConstraint(
        "available_at IS NULL OR (available_at <= as_of AND available_at <= retrieved_at)",
        name="ck_snapshot_availability",
    ),
    CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_snapshot_metadata"),
    Index("ix_raw_snapshots_instrument_snapshot", "instrument_id", "snapshot_id"),
)

research_runs = Table(
    "research_runs",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "instrument_id", UUID(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False
    ),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("definition", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("jsonb_typeof(definition) = 'object'", name="ck_run_definition"),
)

run_snapshots = Table(
    "run_snapshots",
    metadata,
    Column("run_id", UUID(as_uuid=True), ForeignKey("research_runs.run_id"), primary_key=True),
    Column(
        "snapshot_id", UUID(as_uuid=True), ForeignKey("raw_snapshots.snapshot_id"), primary_key=True
    ),
)

run_events = Table(
    "run_events",
    metadata,
    Column("run_id", UUID(as_uuid=True), ForeignKey("research_runs.run_id"), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("event_id", UUID(as_uuid=True), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("request", JSONB, nullable=False),
    Column("state", JSONB, nullable=False),
    Column(
        "report_revision_id",
        UUID(as_uuid=True),
        ForeignKey("report_revisions.revision_id"),
        nullable=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("run_id", "event_id", name="uq_run_event_identity"),
    CheckConstraint("sequence BETWEEN 1 AND 2147483647", name="ck_run_event_sequence"),
    CheckConstraint(
        "kind IN ('created','start','advance','fail','resume','finish')", name="ck_run_event_kind"
    ),
    CheckConstraint("jsonb_typeof(request) = 'object'", name="ck_run_event_request"),
    CheckConstraint("jsonb_typeof(state) = 'object'", name="ck_run_event_state"),
)

worker_jobs = Table(
    "worker_jobs",
    metadata,
    Column("run_id", UUID(as_uuid=True), ForeignKey("research_runs.run_id"), primary_key=True),
    Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("worker_id", String(128), nullable=True),
    Column("lease_token", UUID(as_uuid=True), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("implementation_hash", String(64), nullable=False),
    Column("pipeline_git_sha", String(64), nullable=False),
    Column("last_error_code", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "status IN ('queued','running','completed','dead')", name="ck_worker_job_status"
    ),
    CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_worker_job_attempts"),
    CheckConstraint("implementation_hash ~ '^[a-f0-9]{64}$'", name="ck_worker_job_hash"),
    CheckConstraint("pipeline_git_sha ~ '^([a-f0-9]{40}|[a-f0-9]{64})$'", name="ck_worker_job_git"),
    CheckConstraint("updated_at >= created_at", name="ck_worker_job_time"),
    CheckConstraint(
        "worker_id IS NULL OR (length(btrim(worker_id)) > 0 AND worker_id !~ '[[:cntrl:]]')",
        name="ck_worker_job_owner",
    ),
    CheckConstraint(
        "last_error_code IS NULL OR (length(btrim(last_error_code)) > 0 "
        "AND last_error_code !~ '[[:cntrl:]]')",
        name="ck_worker_job_error",
    ),
    CheckConstraint(
        "(status='queued' AND attempts=0 AND worker_id IS NULL AND lease_token IS NULL "
        "AND lease_expires_at IS NULL) OR "
        "(status='running' AND attempts BETWEEN 1 AND 3 AND worker_id IS NOT NULL "
        "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
        "(status IN ('completed','dead') AND lease_token IS NULL AND lease_expires_at IS NULL "
        "AND (status='dead' OR attempts >= 1) AND (attempts=0 OR worker_id IS NOT NULL))",
        name="ck_worker_job_lease_shape",
    ),
)

worker_claims = Table(
    "worker_claims",
    metadata,
    Column("run_id", UUID(as_uuid=True), ForeignKey("worker_jobs.run_id"), primary_key=True),
    Column("attempt", Integer, primary_key=True),
    Column("lease_token", UUID(as_uuid=True), nullable=False, unique=True),
    Column("worker_id", String(128), nullable=False),
    Column("implementation_hash", String(64), nullable=False),
    Column("pipeline_git_sha", String(64), nullable=False),
    Column("claimed_at", DateTime(timezone=True), nullable=False),
    Column("initial_expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("attempt BETWEEN 1 AND 3", name="ck_worker_claim_attempt"),
    CheckConstraint("implementation_hash ~ '^[a-f0-9]{64}$'", name="ck_worker_claim_hash"),
    CheckConstraint(
        "pipeline_git_sha ~ '^([a-f0-9]{40}|[a-f0-9]{64})$'", name="ck_worker_claim_git"
    ),
    CheckConstraint(
        "length(btrim(worker_id)) > 0 AND worker_id !~ '[[:cntrl:]]'",
        name="ck_worker_claim_owner",
    ),
    CheckConstraint(
        "initial_expires_at BETWEEN claimed_at + INTERVAL '15 seconds' "
        "AND claimed_at + INTERVAL '300 seconds'",
        name="ck_worker_claim_lease",
    ),
)

provider_quota_windows = Table(
    "provider_quota_windows",
    metadata,
    Column("quota_scope", String(128), primary_key=True),
    Column("window_start", DateTime(timezone=True), primary_key=True),
    Column("window_end", DateTime(timezone=True), nullable=False),
    Column("quota_limit", Integer, nullable=False),
    Column("used", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "length(btrim(quota_scope)) BETWEEN 1 AND 128 AND quota_scope=btrim(quota_scope) "
        "AND quota_scope !~ '[[:cntrl:]]'",
        name="ck_provider_quota_scope",
    ),
    CheckConstraint("window_start < window_end", name="ck_provider_quota_window"),
    CheckConstraint("quota_limit BETWEEN 0 AND 1000000", name="ck_provider_quota_limit"),
    CheckConstraint("used BETWEEN 0 AND quota_limit", name="ck_provider_quota_used"),
    CheckConstraint("updated_at >= created_at", name="ck_provider_quota_time"),
)

sec_ingestions = Table(
    "sec_ingestions",
    metadata,
    Column(
        "snapshot_id", UUID(as_uuid=True), ForeignKey("raw_snapshots.snapshot_id"), primary_key=True
    ),
    Column(
        "instrument_id", UUID(as_uuid=True), ForeignKey("instruments.instrument_id"), nullable=False
    ),
    Column("cik", String(10), nullable=False),
    Column("resource", String(16), nullable=False),
    Column("source_url", String(256), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("instrument_id", "source_url", "sha256", name="uq_sec_ingestion_content"),
    CheckConstraint("cik ~ '^[0-9]{10}$' AND cik <> '0000000000'", name="ck_sec_ingestion_cik"),
    CheckConstraint(
        "resource IN ('submissions','revenue','net_income','cash','debt_current',"
        "'debt_noncurrent','operating_cf','capex')",
        name="ck_sec_ingestion_resource",
    ),
    CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_sec_ingestion_hash"),
    Index("ix_sec_ingestions_lookup", "instrument_id", "source_url", "retrieved_at"),
)


import_tasks = Table(
    "import_tasks",
    metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True),
    Column("symbol", String(16), nullable=False),
    Column("request", JSONB, nullable=False),
    Column("status", String(16), nullable=False, server_default="queued"),
    Column("stage", String(16), nullable=False, server_default="queued"),
    Column("attempt", Integer, nullable=False, server_default="0"),
    Column("lease_token", UUID(as_uuid=True)),
    Column("worker_id", String(128)),
    Column("heartbeat_at", DateTime(timezone=True)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("error_code", String(64)),
    Column("error_reason", String(512)),
    Column("instrument_id", UUID(as_uuid=True)),
    Column("report_id", UUID(as_uuid=True)),
    Column("revision", Integer),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    CheckConstraint(
        "status IN ('queued','running','completed','failed')", name="ck_import_task_status"
    ),
    CheckConstraint(
        "stage IN ('queued','import','analysis','completed','failed')", name="ck_import_task_stage"
    ),
    CheckConstraint("attempt BETWEEN 0 AND 3", name="ck_import_task_attempt"),
    CheckConstraint(
        "(status='running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
        name="ck_import_task_lease",
    ),
    CheckConstraint("(report_id IS NULL) = (revision IS NULL)", name="ck_import_task_report"),
    Index("ix_import_task_claim", "status", "created_at"),
)


document_archives = Table(
    "document_archives",
    metadata,
    Column("archive_id", UUID(as_uuid=True), primary_key=True),
    Column("instrument_id", UUID(as_uuid=True), ForeignKey("instruments.instrument_id")),
    Column("request", JSONB, nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("raw_content", LargeBinary, nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("draft_sha256", String(64), nullable=False),
    Column("packet", JSONB, nullable=False),
    Column("result", JSONB, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    CheckConstraint(
        "octet_length(raw_content) BETWEEN 1 AND 1048576", name="ck_document_archive_raw_size"
    ),
    CheckConstraint(
        "request_sha256 ~ '^[a-f0-9]{64}$' AND "
        "document_sha256 ~ '^[a-f0-9]{64}$' AND draft_sha256 ~ '^[a-f0-9]{64}$'",
        name="ck_document_archive_hashes",
    ),
    Index("ix_document_archive_instrument", "instrument_id", "archive_id"),
)


document_reviews = Table(
    "document_reviews",
    metadata,
    Column(
        "archive_id",
        UUID(as_uuid=True),
        ForeignKey("document_archives.archive_id"),
        primary_key=True,
    ),
    Column("revision", Integer, primary_key=True),
    Column("command_id", UUID(as_uuid=True), nullable=False),
    Column("command", JSONB, nullable=False),
    Column("command_sha256", String(64), nullable=False),
    Column(
        "reviewed_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    UniqueConstraint("archive_id", "command_id", name="uq_document_review_command"),
    CheckConstraint("revision BETWEEN 1 AND 10000", name="ck_document_review_revision"),
    CheckConstraint("command_sha256 ~ '^[a-f0-9]{64}$'", name="ck_document_review_hash"),
)
