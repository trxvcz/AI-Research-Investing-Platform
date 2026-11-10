"""User-selected SEC schedules enqueue frozen research intentions only."""

from typing import Annotated, Literal

from pydantic import Field

from alphasense.contracts import Contract, Timestamp
from alphasense.report_contracts import ReportUUID
from alphasense.sec_contracts import SecImportRequest

ScheduleOutcome = Literal["enqueued", "skipped_busy"]


class ScheduleCreate(Contract):
    schedule_id: ReportUUID
    symbol: Annotated[str, Field(strict=True, min_length=1, max_length=16)]
    exchange_mic: Literal["XNAS", "XNYS", "XWAR"] | None = None
    interval_seconds: Annotated[int, Field(strict=True, ge=3600, le=2592000)]
    first_run_at: Timestamp
    enabled: Annotated[bool, Field(strict=True)] = False
    refresh: Annotated[bool, Field(strict=True)] = False


class ScheduleCommand(Contract):
    command_id: ReportUUID
    expected_revision: Annotated[int, Field(strict=True, ge=0, le=10000)]
    enabled: Annotated[bool, Field(strict=True)]


class ScheduleRecord(Contract):
    schedule_id: ReportUUID
    template: SecImportRequest
    interval_seconds: Annotated[int, Field(strict=True, ge=3600, le=2592000)]
    first_run_at: Timestamp
    next_run_at: Timestamp
    enabled: bool
    revision: Annotated[int, Field(strict=True, ge=0, le=10000)]
    created_at: Timestamp
    updated_at: Timestamp
    last_scheduled_for: Timestamp | None
    last_outcome: ScheduleOutcome | None
    last_run_id: ReportUUID | None


class SchedulePage(Contract):
    items: Annotated[list[ScheduleRecord], Field(max_length=50)]
    next_after_id: ReportUUID | None


class ScheduleOccurrence(Contract):
    schedule_id: ReportUUID
    sequence: Annotated[int, Field(strict=True, ge=1)]
    scheduled_for: Timestamp
    dispatched_at: Timestamp
    skipped_slots: Annotated[int, Field(strict=True, ge=0)]
    outcome: ScheduleOutcome
    run_id: ReportUUID | None


class ScheduleOccurrencePage(Contract):
    schedule_id: ReportUUID
    items: Annotated[list[ScheduleOccurrence], Field(max_length=50)]
    next_after_sequence: int | None
