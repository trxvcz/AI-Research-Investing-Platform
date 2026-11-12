"""Separate AI interpretations bound to immutable research report revisions."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from alphasense.ai_history_contracts import AiHistoryContext, AiHistoryNarrative
from alphasense.contracts import Contract, Timestamp
from alphasense.report_contracts import ReportUUID, Sha256

ClaimText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1200)]


class AiClaim(Contract):
    text: ClaimText
    observation_indexes: Annotated[
        list[Annotated[int, Field(strict=True, ge=0, le=999)]], Field(min_length=1, max_length=20)
    ]

    @model_validator(mode="after")
    def unique_references(self) -> "AiClaim":
        if len(set(self.observation_indexes)) != len(self.observation_indexes):
            raise ValueError("Duplicate observation reference")
        return self


class AiNarrative(Contract):
    summary: Annotated[list[AiClaim], Field(min_length=1, max_length=6)]
    strengths: Annotated[list[AiClaim], Field(max_length=6)]
    risks: Annotated[list[AiClaim], Field(max_length=6)]
    questions: Annotated[list[AiClaim], Field(max_length=6)]
    limitations: Annotated[list[ClaimText], Field(min_length=1, max_length=12)]


class AiAnalysisCreate(Contract):
    request_id: ReportUUID
    report_id: ReportUUID
    revision: Annotated[int, Field(strict=True, ge=1)]


class AiAnalysisRecord(Contract):
    request_id: ReportUUID
    report_id: ReportUUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    report_checksum: Sha256
    status: Literal["running", "completed", "failed"]
    created_at: Timestamp
    finished_at: Timestamp | None
    model_id: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    prompt_version: Literal["report-synthesis-v1", "report-history-v2"] = "report-synthesis-v1"
    analysis: AiNarrative | AiHistoryNarrative | None
    evidence_context: AiHistoryContext | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    error_code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")] | None
    reserved_pln: Literal["1.00"] = "1.00"

    @model_validator(mode="after")
    def consistent_state(self) -> "AiAnalysisRecord":
        if self.prompt_version == "report-synthesis-v1":
            if self.evidence_context is not None or (
                self.analysis is not None and not isinstance(self.analysis, AiNarrative)
            ):
                raise ValueError("Legacy AI record cannot contain history evidence")
        else:
            from alphasense.ai_history_context import (
                validate_history_context,
                validate_history_narrative,
            )

            if self.evidence_context is None:
                raise ValueError("History AI record requires frozen evidence")
            context = validate_history_context(self.evidence_context)
            if (context.report_id, context.revision, context.report_checksum) != (
                self.report_id,
                self.revision,
                self.report_checksum,
            ):
                raise ValueError("History AI context belongs to another report")
            if self.analysis is not None:
                if not isinstance(self.analysis, AiHistoryNarrative):
                    raise ValueError("History AI record requires a history narrative")
                validate_history_narrative(context, self.analysis.model_dump_json())
        if self.status == "running":
            if (
                self.finished_at is not None
                or self.analysis is not None
                or self.error_code is not None
            ):
                raise ValueError("Running record has terminal data")
        else:
            if self.finished_at is None or self.finished_at < self.created_at:
                raise ValueError("Invalid completion time")
            if self.status == "completed":
                if self.analysis is None or self.error_code is not None:
                    raise ValueError("Completed record requires a narrative")
            elif self.analysis is not None or self.error_code is None:
                raise ValueError("Failed record requires an error")
        return self


class AiBudget(Contract):
    budget_pln: Literal["50.00"] = "50.00"
    reserved_pln: Annotated[str, StringConstraints(pattern=r"^(?:[0-9]|[1-4][0-9]|50)\.00$")]
    remaining_pln: Annotated[str, StringConstraints(pattern=r"^(?:[0-9]|[1-4][0-9]|50)\.00$")]
    reservation_per_attempt_pln: Literal["1.00"] = "1.00"
    enabled: bool
    reason: str | None
