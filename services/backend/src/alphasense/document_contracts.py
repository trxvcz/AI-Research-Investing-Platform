"""Company-neutral document packets and untrusted financial extraction drafts."""

import re
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Currency, Identifier, Metric
from alphasense.provider_contracts import DataClassification
from alphasense.report_contracts import ReportUUID, Sha256

MAX_DOCUMENT_TEXT_BYTES = 2 * 1024 * 1024
ReaderVersion = Literal["table-text-v2"]
NumberLocale = Literal["en-US"]
BoundedText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=32768)]
Locator = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
Quote = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)]
DecimalText = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=128, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"
    ),
]


def _date_input(value: object) -> str | date:
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("ISO calendar date required")
    return value


CalendarDate = Annotated[date, BeforeValidator(_date_input)]


def _scale_input(value: object) -> object:
    if type(value) is not int:
        raise ValueError("Explicit integer scale required")
    return value


class DocumentBlock(Contract):
    block_id: Identifier
    locator: Locator
    text: BoundedText


def validate_reader_options(
    format: str, reader_version: ReaderVersion | None, number_locale: NumberLocale | None
) -> None:
    """Options are explicit trusted inputs, never inferred from source contents."""
    if reader_version not in (None, "table-text-v2") or number_locale not in (None, "en-US"):
        raise ValueError("Unsupported document reader options")
    if (reader_version is not None or number_locale is not None) and format != "html":
        raise ValueError("Reader options require HTML")
    if number_locale is not None and reader_version != "table-text-v2":
        raise ValueError("Number locale requires versioned reader")


class DocumentPacket(Contract):
    schema_version: Literal["1.0"] = "1.0"
    document_id: ReportUUID
    sha256: Sha256
    format: Literal["text", "html", "xlsx", "pdf"]
    classification: DataClassification
    blocks: Annotated[list[DocumentBlock], Field(min_length=1, max_length=512)]
    reader_version: ReaderVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    number_locale: NumberLocale | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def bounded_unique_blocks(self) -> Self:
        validate_reader_options(self.format, self.reader_version, self.number_locale)
        if len({item.block_id for item in self.blocks}) != len(self.blocks):
            raise ValueError("Duplicate block identity")
        if sum(len(item.text.encode("utf-8")) for item in self.blocks) > MAX_DOCUMENT_TEXT_BYTES:
            raise ValueError("Document text limit exceeded")
        return self


class FactEvidence(Contract):
    block_id: Identifier
    quote: Quote


class CandidateFact(Contract):
    metric: Metric
    value_token: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    value: DecimalText
    scale: Annotated[Literal[1, 1000, 1000000], BeforeValidator(_scale_input)]
    currency: Currency
    period_start: CalendarDate
    period_end: CalendarDate
    scope: Literal["consolidated", "separate", "unknown"]
    evidence: Annotated[list[FactEvidence], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def ordered_period(self) -> Self:
        if self.period_start > self.period_end:
            raise ValueError("Period start exceeds period end")
        return self


class ExtractionDraft(Contract):
    schema_version: Literal["1.0"]
    facts: Annotated[list[CandidateFact], Field(max_length=64)]


class FactReview(Contract):
    fact: CandidateFact
    status: Literal["needs_review", "rejected"]
    reason_code: Identifier


class DocumentAgentResult(Contract):
    document_id: ReportUUID
    provider_id: Identifier
    status: Literal["blocked", "rejected", "needs_review"]
    facts: Annotated[list[FactReview], Field(max_length=64)]
    error_code: Identifier | None
