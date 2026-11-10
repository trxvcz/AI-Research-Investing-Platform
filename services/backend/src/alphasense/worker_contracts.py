"""Public worker status and private fencing capability."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from alphasense.contracts import Contract, Timestamp
from alphasense.report_contracts import GitSha, ReportUUID, Sha256
from alphasense.run_contracts import Actor


class WorkerLease(Contract):
    run_id: ReportUUID
    worker_id: Actor
    token: ReportUUID
    attempt: Annotated[int, Field(strict=True, ge=1, le=3)]
    expires_at: Timestamp
    implementation_hash: Sha256
    pipeline_git_sha: GitSha


class WorkerJobRecord(Contract):
    run_id: ReportUUID
    status: Literal["queued", "running", "completed", "dead"]
    attempts: Annotated[int, Field(strict=True, ge=0, le=3)]
    worker_id: Actor | None
    lease_expires_at: Timestamp | None
    implementation_hash: Sha256
    pipeline_git_sha: GitSha
    last_error_code: Actor | None
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("Worker job clock conflict")
        if self.status == "queued":
            if (
                self.attempts != 0
                or self.worker_id is not None
                or self.lease_expires_at is not None
            ):
                raise ValueError("Queued job cannot have an owner")
        elif self.status == "running":
            if self.attempts == 0 or self.worker_id is None or self.lease_expires_at is None:
                raise ValueError("Running job requires a lease")
        elif self.lease_expires_at is not None:
            raise ValueError("Terminal job cannot retain a lease")
        if self.status == "completed" and (self.attempts == 0 or self.worker_id is None):
            raise ValueError("Completed job requires claim provenance")
        return self
