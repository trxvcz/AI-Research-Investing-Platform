"""Stateless bounded document inspection; no store, provider or model invocation."""

import base64
import binascii
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from alphasense.contracts import Contract
from alphasense.document_contracts import (
    DocumentPacket,
    NumberLocale,
    ReaderVersion,
    validate_reader_options,
)
from alphasense.document_readers import read_text_document
from alphasense.provider_contracts import DataClassification
from alphasense.report_contracts import ReportUUID


class DocumentPreviewCreate(Contract):
    document_id: ReportUUID
    format: Literal["text", "html", "xlsx", "pdf"]
    classification: DataClassification = "private"
    reader_version: ReaderVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    number_locale: NumberLocale | None = Field(default=None, exclude_if=lambda value: value is None)
    content_base64: Annotated[str, StringConstraints(strict=True, min_length=4, max_length=1398104)]

    @model_validator(mode="after")
    def reader_options(self) -> Self:
        validate_reader_options(self.format, self.reader_version, self.number_locale)
        return self


class DocumentPreviewResult(Contract):
    packet: DocumentPacket
    byte_length: Annotated[int, Field(strict=True, ge=1, le=1048576)]
    model_called: Literal[False] = False
    persisted: Literal[False] = False


class DocumentPreviewInvalid(ValueError):
    """Stable refusal without reflecting source bytes or parser diagnostics."""


def preview_document(payload: DocumentPreviewCreate) -> DocumentPreviewResult:
    try:
        checked = DocumentPreviewCreate.model_validate(
            payload.model_dump(mode="python", warnings=False)
        )
        raw = base64.b64decode(checked.content_base64, validate=True)
        if (
            not 1 <= len(raw) <= 1048576
            or base64.b64encode(raw).decode("ascii") != checked.content_base64
        ):
            raise ValueError("Invalid original bytes")
        packet = read_text_document(
            raw,
            document_id=checked.document_id,
            classification=checked.classification,
            format=checked.format,
            reader_version=checked.reader_version,
            number_locale=checked.number_locale,
        )
        return DocumentPreviewResult(packet=packet, byte_length=len(raw))
    except (ValueError, TypeError, UnicodeError, binascii.Error, AttributeError):
        raise DocumentPreviewInvalid("DOCUMENT_PREVIEW_INVALID") from None
