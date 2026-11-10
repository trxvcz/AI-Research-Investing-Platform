"""Observed process liveness, separate from queue ownership and model activity."""

from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from alphasense.contracts import Contract, Identifier, Timestamp
from alphasense.report_contracts import ReportUUID, Sha256

WorkerKind = Literal["sec_import", "document_validation", "sec_scheduler"]
WorkerMode = Literal["once", "forever"]
WorkerStopReason = Literal["completed", "interrupted", "error"]
WorkerErrorCode = Literal["WORKER_RUNTIME_FAILED", "WORKER_MONITOR_FAILED"]
WORKER_STALE_SECONDS = 45


class WorkerSessionStart(Contract):
    session_id: ReportUUID
    worker_id: Identifier
    kind: WorkerKind
    mode: WorkerMode
    process_id: Annotated[int, Field(strict=True, ge=1, le=2147483647)]
    implementation_sha256: Sha256


class WorkerSessionRecord(WorkerSessionStart):
    started_at: Timestamp
    heartbeat_at: Timestamp
    stopped_at: Timestamp | None
    stop_reason: WorkerStopReason | None
    error_code: WorkerErrorCode | None
    status: Literal["online", "stale", "stopped"]
    observed_at: Timestamp
    contact_expires_at: Timestamp

    @model_validator(mode="after")
    def consistent_observation(self) -> Self:
        if self.contact_expires_at != self.heartbeat_at + timedelta(seconds=WORKER_STALE_SECONDS):
            raise ValueError("Invalid contact deadline")
        if self.heartbeat_at < self.started_at or self.observed_at < self.heartbeat_at:
            raise ValueError("Invalid session chronology")
        if (self.stopped_at is None) != (self.stop_reason is None):
            raise ValueError("Incomplete session stop")
        if (
            self.stopped_at is not None
            and not self.heartbeat_at <= self.stopped_at <= self.observed_at
        ):
            raise ValueError("Invalid stop chronology")
        if (self.stop_reason == "error") != (self.error_code is not None):
            raise ValueError("Invalid runtime error metadata")
        expected = (
            "stopped"
            if self.stopped_at is not None
            else "stale"
            if self.observed_at >= self.contact_expires_at
            else "online"
        )
        if self.status != expected:
            raise ValueError("Invalid observed liveness")
        return self


class WorkerSessionPage(Contract):
    items: Annotated[list[WorkerSessionRecord], Field(max_length=50)]
    next_after_id: ReportUUID | None
    observed_at: Timestamp
    stale_after_seconds: Literal[45] = 45
