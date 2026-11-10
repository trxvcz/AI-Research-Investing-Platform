"""Durable, explicitly offline document runs; no paid invocation permission."""

from typing import Annotated, Literal

from pydantic import Field

from alphasense.contracts import Contract, Identifier, Timestamp
from alphasense.document_contracts import DocumentAgentResult
from alphasense.report_contracts import ReportUUID, Sha256

DocumentTaskMode = Literal["validate_saved_draft", "model_extract"]
DocumentTaskStatus = Literal["queued", "running", "completed", "blocked", "failed"]
DocumentTaskStage = Literal[
    "queued", "reading", "validating", "archiving", "completed", "blocked", "failed"
]


class DocumentTaskCreate(Contract):
    job_id: ReportUUID
    archive_id: ReportUUID
    mode: DocumentTaskMode = "validate_saved_draft"


class DocumentTaskRecord(Contract):
    job_id: ReportUUID
    archive_id: ReportUUID
    title: str
    mode: DocumentTaskMode
    status: DocumentTaskStatus
    stage: DocumentTaskStage
    attempt: Annotated[int, Field(strict=True, ge=0, le=3)]
    created_at: Timestamp
    updated_at: Timestamp
    heartbeat_at: Timestamp | None
    lease_expires_at: Timestamp | None
    worker_id: Identifier | None
    error_code: Identifier | None
    document_sha256: Sha256
    draft_sha256: Sha256
    input_sha256: Sha256
    result: DocumentAgentResult | None


class DocumentTaskPage(Contract):
    items: Annotated[list[DocumentTaskRecord], Field(max_length=50)]
    next_after_id: ReportUUID | None


class DocumentTaskEvent(Contract):
    sequence: Annotated[int, Field(strict=True, ge=1)]
    attempt: Annotated[int, Field(strict=True, ge=0, le=3)]
    stage: DocumentTaskStage
    recorded_at: Timestamp
    error_code: Identifier | None


class DocumentTaskAudit(Contract):
    attempt: Annotated[int, Field(strict=True, ge=1, le=3)]
    worker_id: Identifier
    started_at: Timestamp
    finished_at: Timestamp
    outcome: Literal["completed", "blocked", "failed", "interrupted"]
    error_code: Identifier | None
    execution: Literal["offline-validation-v1", "model-disabled-v1"]
    implementation_sha256: Sha256
    request_sha256: Sha256
    output_sha256: Sha256 | None
    result: DocumentAgentResult | None
    # These values must never imply an actual model call in this increment.
    provider_called: Literal[False] = False
    model_id: None = None
    prompt_version: None = None
    response_sha256: None = None
    input_tokens: None = None
    output_tokens: None = None
    usage_status: Literal["not_applicable"] = "not_applicable"
    cost_usd: Literal["0"] = "0"


class DocumentTaskDetail(Contract):
    task: DocumentTaskRecord
    events: Annotated[list[DocumentTaskEvent], Field(max_length=32)]
    audits: Annotated[list[DocumentTaskAudit], Field(max_length=3)]
