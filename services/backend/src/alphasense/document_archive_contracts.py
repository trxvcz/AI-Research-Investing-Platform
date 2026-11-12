"""Local, immutable document imports and append-only human review decisions."""

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Identifier, Timestamp
from alphasense.document_contracts import (
    DocumentAgentResult,
    DocumentPacket,
    NumberLocale,
    ReaderVersion,
    validate_reader_options,
)
from alphasense.provider_contracts import DataClassification
from alphasense.report_contracts import ReportUUID, Sha256

Title = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
Note = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
Revision = Annotated[int, Field(strict=True, ge=0, le=10000)]


class DocumentArchiveCreate(Contract):
    archive_id: ReportUUID
    title: Title
    instrument_id: ReportUUID | None = None
    format: Literal["text", "html", "xlsx", "pdf"]
    reader_version: ReaderVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    number_locale: NumberLocale | None = Field(default=None, exclude_if=lambda value: value is None)
    classification: DataClassification = "private"
    content_base64: Annotated[str, StringConstraints(strict=True, min_length=4, max_length=1398104)]
    draft_json: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=262144)]
    # These are user-declared provenance, never proof of a provider invocation.
    provider_id: Identifier = "offline-import"
    model_id: Identifier | None = None
    prompt_version: Identifier | None = None
    source_available_at: Timestamp
    as_of: Timestamp

    @model_validator(mode="after")
    def chronology(self) -> Self:
        validate_reader_options(self.format, self.reader_version, self.number_locale)
        if self.source_available_at > self.as_of:
            raise ValueError("Source was not available as of the requested time")
        if not self.title.strip():
            raise ValueError("Title required")
        return self


class DocumentReviewCommand(Contract):
    command_id: ReportUUID
    expected_revision: Revision
    fact_index: Annotated[int, Field(strict=True, ge=0, le=63)]
    verdict: Literal["accepted", "rejected"]
    note: Note

    @model_validator(mode="after")
    def meaningful_note(self) -> Self:
        if not self.note.strip():
            raise ValueError("Review note required")
        return self


class DocumentReviewEvent(Contract):
    revision: Annotated[int, Field(strict=True, ge=1, le=10000)]
    command: DocumentReviewCommand
    reviewed_at: Timestamp


class DocumentArchiveSummary(Contract):
    archive_id: ReportUUID
    title: Title
    instrument_id: ReportUUID | None
    format: Literal["text", "html", "xlsx", "pdf"]
    reader_version: ReaderVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    number_locale: NumberLocale | None = Field(default=None, exclude_if=lambda value: value is None)
    classification: DataClassification
    document_sha256: Sha256
    draft_sha256: Sha256
    provenance: Literal["unverified_offline_import"] = "unverified_offline_import"
    provider_id: Identifier
    model_id: Identifier | None
    prompt_version: Identifier | None
    source_available_at: Timestamp
    as_of: Timestamp
    created_at: Timestamp
    validation_status: Literal["blocked", "rejected", "needs_review"]
    fact_count: Annotated[int, Field(strict=True, ge=0, le=64)]
    review_revision: Revision

    @model_validator(mode="after")
    def reader_options(self) -> Self:
        validate_reader_options(self.format, self.reader_version, self.number_locale)
        return self


class DocumentArchiveRecord(DocumentArchiveSummary):
    packet: DocumentPacket
    draft_json: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=262144)]
    result: DocumentAgentResult
    reviews: Annotated[list[DocumentReviewEvent], Field(max_length=10000)]


class DocumentArchivePage(Contract):
    items: Annotated[list[DocumentArchiveSummary], Field(max_length=50)]
    next_after_id: ReportUUID | None
