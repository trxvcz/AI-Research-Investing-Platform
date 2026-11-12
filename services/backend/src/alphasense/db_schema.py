"""PostgreSQL Core tables. Runtime never creates or migrates these implicitly."""

from sqlalchemy import (
    Boolean,
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

MIGRATION_HEAD = "0016_ai_history_context"
metadata = MetaData()

ai_budget_controls = Table(
    "ai_budget_controls",
    metadata,
    Column("scope", String(64), primary_key=True),
    Column("budget_grosz", Integer, nullable=False),
    Column("reserved_grosz", Integer, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    CheckConstraint("scope='ai-analysis-pilot-20261111'", name="ck_ai_budget_scope"),
    CheckConstraint("budget_grosz=5000", name="ck_ai_budget_limit"),
    CheckConstraint(
        "reserved_grosz BETWEEN 0 AND 5000 AND reserved_grosz % 100=0", name="ck_ai_budget_reserved"
    ),
)

ai_budget_reservations = Table(
    "ai_budget_reservations",
    metadata,
    Column("request_id", UUID(as_uuid=True), primary_key=True),
    Column("scope", String(64), ForeignKey("ai_budget_controls.scope"), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("amount_grosz", Integer, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    CheckConstraint("kind IN ('analysis','qualification')", name="ck_ai_reservation_kind"),
    CheckConstraint("amount_grosz=100", name="ck_ai_reservation_amount"),
)

ai_analyses = Table(
    "ai_analyses",
    metadata,
    Column(
        "request_id",
        UUID(as_uuid=True),
        ForeignKey("ai_budget_reservations.request_id"),
        primary_key=True,
    ),
    Column(
        "revision_id",
        UUID(as_uuid=True),
        ForeignKey("report_revisions.revision_id"),
        nullable=False,
    ),
    Column("report_id", UUID(as_uuid=True), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("report_checksum", String(64), nullable=False),
    Column("model_id", String(128), nullable=False),
    Column("prompt_version", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("analysis", JSONB(none_as_null=True)),
    Column("evidence_context", JSONB(none_as_null=True)),
    Column("error_code", String(64)),
    Column("audit", JSONB(none_as_null=True)),
    CheckConstraint("revision >= 1", name="ck_ai_analysis_revision"),
    CheckConstraint("report_checksum ~ '^[a-f0-9]{64}$'", name="ck_ai_analysis_checksum"),
    CheckConstraint("model_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'", name="ck_ai_analysis_model"),
    CheckConstraint(
        "prompt_version IN ('report-synthesis-v1','report-history-v2')",
        name="ck_ai_analysis_prompt",
    ),
    CheckConstraint(
        "(prompt_version='report-synthesis-v1' AND evidence_context IS NULL) OR "
        "(prompt_version='report-history-v2' AND evidence_context IS NOT NULL AND "
        "jsonb_typeof(evidence_context)='object' AND "
        "octet_length(evidence_context::text)<=262144 AND "
        "evidence_context ?& ARRAY['context_version','report_id','revision','report_checksum',"
        "'as_of','evidence','limitations','context_sha256','methodology_version'] AND "
        "jsonb_typeof(evidence_context->'context_version')='string' AND "
        "evidence_context->>'context_version'='report-history-context-v1' AND "
        "jsonb_typeof(evidence_context->'methodology_version')='string' AND "
        "evidence_context->>'methodology_version'='sec-comparatives-v1' AND "
        "jsonb_typeof(evidence_context->'report_id')='string' AND "
        "evidence_context->>'report_id'=report_id::text AND "
        "evidence_context->'revision'=to_jsonb(revision) AND "
        "jsonb_typeof(evidence_context->'report_checksum')='string' AND "
        "evidence_context->>'report_checksum'=report_checksum AND "
        "jsonb_typeof(evidence_context->'as_of')='string' AND "
        "jsonb_typeof(evidence_context->'context_sha256')='string' AND "
        "evidence_context->>'context_sha256' ~ '^[a-f0-9]{64}$' AND "
        "jsonb_typeof(evidence_context->'evidence')='array' AND "
        "jsonb_array_length(evidence_context->'evidence') BETWEEN 1 AND 64 AND "
        "jsonb_typeof(evidence_context->'limitations')='array')",
        name="ck_ai_analysis_context",
    ),
    CheckConstraint("status IN ('running','completed','failed')", name="ck_ai_analysis_status"),
    CheckConstraint("finished_at IS NULL OR finished_at >= created_at", name="ck_ai_analysis_time"),
    CheckConstraint(
        "(status='running' AND finished_at IS NULL AND analysis IS NULL AND "
        "error_code IS NULL AND audit IS NULL) OR (status='completed' AND "
        "finished_at IS NOT NULL AND analysis IS NOT NULL AND "
        "jsonb_typeof(analysis)='object' AND error_code IS NULL AND audit IS NOT NULL AND "
        "jsonb_typeof(audit)='object') OR (status='failed' AND finished_at IS NOT NULL AND "
        "analysis IS NULL AND error_code IS NOT NULL AND "
        "error_code ~ '^[A-Z][A-Z0-9_]{0,63}$' AND audit IS NOT NULL AND "
        "jsonb_typeof(audit)='object')",
        name="ck_ai_analysis_result",
    ),
    Index("ix_ai_analysis_report", "report_id", "revision", "created_at"),
)

worker_sessions = Table(
    "worker_sessions",
    metadata,
    Column("session_id", UUID(as_uuid=True), primary_key=True),
    Column("worker_id", String(128), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("mode", String(16), nullable=False),
    Column("process_id", Integer, nullable=False),
    Column("implementation_sha256", String(64), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("heartbeat_at", DateTime(timezone=True), nullable=False),
    Column("stopped_at", DateTime(timezone=True)),
    Column("stop_reason", String(16)),
    Column("error_code", String(32)),
    CheckConstraint(
        "kind IN ('sec_import','document_validation','sec_scheduler')",
        name="ck_worker_session_kind",
    ),
    CheckConstraint("mode IN ('once','forever')", name="ck_worker_session_mode"),
    CheckConstraint("process_id > 0", name="ck_worker_session_pid"),
    CheckConstraint("implementation_sha256 ~ '^[a-f0-9]{64}$'", name="ck_worker_session_hash"),
    CheckConstraint(
        "length(btrim(worker_id)) BETWEEN 1 AND 128 AND worker_id=btrim(worker_id) "
        "AND worker_id !~ '[[:cntrl:]]'",
        name="ck_worker_session_name",
    ),
    CheckConstraint("heartbeat_at >= started_at", name="ck_worker_session_heartbeat"),
    CheckConstraint(
        "(stopped_at IS NULL AND stop_reason IS NULL AND error_code IS NULL) OR "
        "(stopped_at IS NOT NULL AND stop_reason IS NOT NULL AND stopped_at >= heartbeat_at "
        "AND stop_reason IN ('completed','interrupted') "
        "AND error_code IS NULL) OR (stopped_at IS NOT NULL AND stop_reason IS NOT NULL "
        "AND error_code IS NOT NULL AND stopped_at >= heartbeat_at AND stop_reason='error' "
        "AND error_code IN ('WORKER_RUNTIME_FAILED','WORKER_MONITOR_FAILED'))",
        name="ck_worker_session_stop",
    ),
    Index("ix_worker_session_kind", "kind", "session_id"),
)

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


document_tasks = Table(
    "document_tasks",
    metadata,
    Column("job_id", UUID(as_uuid=True), primary_key=True),
    Column(
        "archive_id", UUID(as_uuid=True), ForeignKey("document_archives.archive_id"), nullable=False
    ),
    Column("request", JSONB, nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("draft_sha256", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("stage", String(16), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("worker_id", String(128)),
    Column("implementation_sha256", String(64)),
    Column("lease_token", UUID(as_uuid=True)),
    Column("started_at", DateTime(timezone=True)),
    Column("heartbeat_at", DateTime(timezone=True)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("error_code", String(128)),
    Column("result", JSONB),
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
    CheckConstraint("attempt BETWEEN 0 AND 3", name="ck_document_task_attempt"),
    CheckConstraint(
        "status IN ('queued','running','completed','blocked','failed')",
        name="ck_document_task_status",
    ),
    CheckConstraint(
        "stage IN ('queued','reading','validating','archiving','completed','blocked','failed')",
        name="ck_document_task_stage",
    ),
    CheckConstraint(
        "(status='running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
        name="ck_document_task_lease",
    ),
    CheckConstraint(
        "input_sha256 ~ '^[a-f0-9]{64}$' AND document_sha256 ~ '^[a-f0-9]{64}$' "
        "AND draft_sha256 ~ '^[a-f0-9]{64}$'",
        name="ck_document_task_hash",
    ),
    Index("ix_document_task_claim", "status", "created_at"),
)

document_task_events = Table(
    "document_task_events",
    metadata,
    Column("job_id", UUID(as_uuid=True), ForeignKey("document_tasks.job_id"), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("payload", JSONB, nullable=False),
    Column("sha256", String(64), nullable=False),
    CheckConstraint("sequence BETWEEN 1 AND 32", name="ck_document_task_event_sequence"),
    CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_document_task_event_hash"),
)

document_task_audits = Table(
    "document_task_audits",
    metadata,
    Column("job_id", UUID(as_uuid=True), ForeignKey("document_tasks.job_id"), primary_key=True),
    Column("attempt", Integer, primary_key=True),
    Column("payload", JSONB, nullable=False),
    Column("sha256", String(64), nullable=False),
    CheckConstraint("attempt BETWEEN 1 AND 3", name="ck_document_task_audit_attempt"),
    CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_document_task_audit_hash"),
)

import_task_events = Table(
    "import_task_events",
    metadata,
    Column("run_id", UUID(as_uuid=True), ForeignKey("import_tasks.run_id"), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("kind", String(24), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    CheckConstraint("sequence > 0", name="ck_import_task_event_sequence"),
    CheckConstraint(
        "kind IN ('created','transition','legacy_snapshot')", name="ck_import_task_event_kind"
    ),
)

sec_schedules = Table(
    "sec_schedules",
    metadata,
    Column("schedule_id", UUID(as_uuid=True), primary_key=True),
    Column("template", JSONB, nullable=False),
    Column("create_request", JSONB, nullable=False),
    Column("interval_seconds", Integer, nullable=False),
    Column("first_run_at", DateTime(timezone=True), nullable=False),
    Column("next_run_at", DateTime(timezone=True), nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("revision", Integer, nullable=False, server_default="0"),
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
    Column("last_scheduled_for", DateTime(timezone=True)),
    Column("last_outcome", String(16)),
    Column("last_run_id", UUID(as_uuid=True), ForeignKey("import_tasks.run_id")),
    CheckConstraint("interval_seconds BETWEEN 3600 AND 2592000", name="ck_sec_schedule_interval"),
    CheckConstraint("revision BETWEEN 0 AND 10000", name="ck_sec_schedule_revision"),
    CheckConstraint("next_run_at >= first_run_at", name="ck_sec_schedule_next"),
    CheckConstraint(
        "last_outcome IS NULL OR last_outcome IN ('enqueued','skipped_busy')",
        name="ck_sec_schedule_outcome",
    ),
    Index("ix_sec_schedule_due", "enabled", "next_run_at"),
)

sec_schedule_commands = Table(
    "sec_schedule_commands",
    metadata,
    Column(
        "schedule_id", UUID(as_uuid=True), ForeignKey("sec_schedules.schedule_id"), primary_key=True
    ),
    Column("revision", Integer, primary_key=True),
    Column("command_id", UUID(as_uuid=True), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    UniqueConstraint("schedule_id", "command_id", name="uq_sec_schedule_command"),
    CheckConstraint("revision BETWEEN 1 AND 10000", name="ck_sec_schedule_command_revision"),
)

sec_schedule_occurrences = Table(
    "sec_schedule_occurrences",
    metadata,
    Column(
        "schedule_id", UUID(as_uuid=True), ForeignKey("sec_schedules.schedule_id"), primary_key=True
    ),
    Column("sequence", Integer, primary_key=True),
    Column("scheduled_for", DateTime(timezone=True), nullable=False),
    Column("dispatched_at", DateTime(timezone=True), nullable=False),
    Column("skipped_slots", Integer, nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("run_id", UUID(as_uuid=True), ForeignKey("import_tasks.run_id")),
    UniqueConstraint("schedule_id", "scheduled_for", name="uq_sec_schedule_slot"),
    CheckConstraint(
        "sequence > 0 AND skipped_slots >= 0", name="ck_sec_schedule_occurrence_counts"
    ),
    CheckConstraint(
        "outcome IN ('enqueued','skipped_busy')", name="ck_sec_schedule_occurrence_outcome"
    ),
    CheckConstraint(
        "(outcome='enqueued') = (run_id IS NOT NULL)", name="ck_sec_schedule_occurrence_task"
    ),
    CheckConstraint("dispatched_at >= scheduled_for", name="ck_sec_schedule_occurrence_time"),
)
