"""Manual research ledger contracts; transition attestations are not computations."""

import re
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from alphasense.contracts import Contract, Timestamp
from alphasense.instrument_contracts import CONTROL_PATTERN, License, SourceID
from alphasense.report_contracts import ReportStatus, ReportUUID

STEPS = ("data", "validate", "fundamental", "technical", "report", "review")
Step = Literal["data", "validate", "fundamental", "technical", "report", "review"]
Sequence = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Pipeline = Literal[
    "manual-research-v1", "deterministic-research-v1", "sec-fundamentals-v1", "sec-fundamentals-v2"
]
SnapshotIDs = Annotated[list[ReportUUID], Field(min_length=1, max_length=32)]


def clean_text(value: object) -> object:
    if isinstance(value, str) and re.search(CONTROL_PATTERN, value):
        raise ValueError("text contains ASCII controls")
    return value


Actor = Annotated[SourceID, BeforeValidator(clean_text)]
FailureReason = Annotated[License, BeforeValidator(clean_text)]


class RunCreate(Contract):
    action: Literal["create"] = "create"
    schema_version: Literal["1.0"]
    run_id: ReportUUID
    instrument_id: ReportUUID
    as_of: Timestamp
    snapshot_ids: SnapshotIDs
    pipeline_version: Pipeline = "manual-research-v1"

    @model_validator(mode="after")
    def unique_snapshots(self) -> Self:
        if len(set(self.snapshot_ids)) != len(self.snapshot_ids):
            raise ValueError("duplicate snapshot IDs")
        return self


class CommandBase(Contract):
    request_id: ReportUUID
    expected_sequence: Sequence
    actor: Actor


class RunStart(CommandBase):
    action: Literal["start"]


class RunAdvance(CommandBase):
    action: Literal["advance"]
    step: Step


class RunFail(CommandBase):
    action: Literal["fail"]
    step: Step
    error_code: Actor
    reason: FailureReason


class RunResume(CommandBase):
    action: Literal["resume"]


class RunFinish(CommandBase):
    action: Literal["finish"]
    report_revision_id: ReportUUID


RunCommand = Annotated[
    RunStart | RunAdvance | RunFail | RunResume | RunFinish, Field(discriminator="action")
]
EventRequest = Annotated[
    RunCreate | RunStart | RunAdvance | RunFail | RunResume | RunFinish,
    Field(discriminator="action"),
]


class RunState(Contract):
    run_id: ReportUUID
    instrument_id: ReportUUID
    as_of: Timestamp
    snapshot_ids: SnapshotIDs
    pipeline_version: Pipeline
    data_origin: Literal["synthetic", "live"]
    sequence: Sequence
    status: Literal["queued", "running", "failed", "completed"]
    current_step: Step | None
    completed_steps: Annotated[list[Step], Field(max_length=6)]
    error_code: Actor | None
    error_reason: FailureReason | None
    report_revision_id: ReportUUID | None
    report_status: ReportStatus | None
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def check_state(self) -> Self:
        if len(set(self.snapshot_ids)) != len(self.snapshot_ids):
            raise ValueError("duplicate snapshot IDs")
        count = len(self.completed_steps)
        if tuple(self.completed_steps) != STEPS[:count]:
            raise ValueError("completed steps must be a prefix")
        if self.report_revision_id is not None:
            if count != len(STEPS) or self.current_step is not None or self.report_status is None:
                raise ValueError("finalized run requires completed plan and report status")
            expected = "failed" if self.report_status == "failed" else "completed"
            if self.status != expected:
                raise ValueError("terminal run status conflicts with report")
        else:
            if count >= len(STEPS) or self.report_status is not None or self.status == "completed":
                raise ValueError("run cannot finish without a report")
            if self.current_step != STEPS[count]:
                raise ValueError("current step must follow completed steps")
            if self.status == "queued" and count:
                raise ValueError("queued run cannot contain completed steps")
        if self.status == "failed":
            if self.error_code is None or self.error_reason is None:
                raise ValueError("failed run requires explicit error")
        elif self.error_code is not None or self.error_reason is not None:
            raise ValueError("non-failed run cannot retain an active error")
        return self


class RunEvent(Contract):
    run_id: ReportUUID
    event_id: ReportUUID
    sequence: Sequence
    kind: Literal["created", "start", "advance", "fail", "resume", "finish"]
    request: EventRequest
    state: RunState
    created_at: Timestamp

    @model_validator(mode="after")
    def consistent_event(self) -> Self:
        if self.run_id != self.state.run_id or self.sequence != self.state.sequence:
            raise ValueError("event identity conflicts with state")
        if self.created_at != self.state.updated_at:
            raise ValueError("event time conflicts with state")
        if isinstance(self.request, RunCreate):
            if (
                self.kind != "created"
                or self.sequence != 1
                or self.event_id != self.run_id
                or self.request.run_id != self.run_id
            ):
                raise ValueError("invalid creation event")
        elif (
            self.kind != self.request.action
            or self.event_id != self.request.request_id
            or self.sequence != self.request.expected_sequence + 1
        ):
            raise ValueError("event conflicts with command")
        return self


class RunWrite(RunState):
    created: bool


class RunEventWrite(RunEvent):
    created: bool


class RunEventPage(Contract):
    items: Annotated[list[RunEvent], Field(max_length=100)]
    next_after_sequence: Sequence | None
