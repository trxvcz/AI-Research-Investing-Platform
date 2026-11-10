"""Durable import commands and worker supervision, not model-agent claims."""

from typing import Annotated, Literal

from pydantic import Field

from alphasense.contracts import Contract, Timestamp
from alphasense.report_contracts import ReportUUID


class TaskCreate(Contract):
    symbol: Annotated[str, Field(strict=True, min_length=1, max_length=16)]
    run_id: ReportUUID
    exchange_mic: Literal["XNAS", "XNYS", "XWAR"] | None = None


class TaskRecord(Contract):
    run_id: ReportUUID
    symbol: str
    exchange_mic: Literal["XNAS", "XNYS"]
    status: Literal["queued", "running", "completed", "failed"]
    stage: Literal["queued", "import", "analysis", "completed", "failed"]
    attempt: int
    error_code: str | None
    error_reason: str | None
    created_at: Timestamp
    updated_at: Timestamp
    heartbeat_at: Timestamp | None
    lease_expires_at: Timestamp | None
    worker_id: str | None
    instrument_id: ReportUUID | None
    report_id: ReportUUID | None
    revision: int | None


class TaskPage(Contract):
    items: list[TaskRecord]
    next_after_id: ReportUUID | None


class ImportTaskEvent(Contract):
    run_id: ReportUUID
    sequence: Annotated[int, Field(strict=True, ge=1)]
    kind: Literal["created", "transition", "legacy_snapshot"]
    recorded_at: Timestamp
    task: TaskRecord


class ImportTaskEventPage(Contract):
    run_id: ReportUUID
    coverage: Literal["complete", "legacy_snapshot"]
    items: Annotated[list[ImportTaskEvent], Field(max_length=100)]
    next_after_sequence: int | None
