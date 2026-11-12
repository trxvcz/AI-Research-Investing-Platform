"""Bounded exact-byte archive contracts; URLs and bytes are never executed."""

import base64
import binascii
import hashlib
import re
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Timestamp
from alphasense.instrument_contracts import CONTROL_PATTERN, InstrumentURL, License, SourceID
from alphasense.report_contracts import ReportUUID, Sha256

MAX_BYTES = 1048576
MAX_BASE64 = 4 * ((MAX_BYTES + 2) // 3)
MAX_UPLOAD_BODY = 1500000
ByteLength = Annotated[int, Field(strict=True, ge=1, le=MAX_BYTES)]


class SnapshotMetadata(Contract):
    schema_version: Literal["1.0"]
    snapshot_id: ReportUUID
    instrument_id: ReportUUID
    data_origin: Literal["synthetic", "live"]
    source_id: SourceID
    source_url: InstrumentURL | None
    license: License
    as_of: Timestamp
    available_at: Timestamp | None
    retrieved_at: Timestamp
    media_type: Literal[
        "application/json", "text/plain", "text/csv", "application/pdf", "application/octet-stream"
    ]
    sha256: Sha256
    byte_length: ByteLength

    @model_validator(mode="after")
    def check_metadata(self) -> Self:
        if self.available_at is not None and (
            self.available_at > self.as_of or self.available_at > self.retrieved_at
        ):
            raise ValueError("snapshot availability conflicts with cutoff or retrieval")
        if self.data_origin == "live" and self.source_url is None:
            raise ValueError("live source URL required")
        if any(re.search(CONTROL_PATTERN, value) for value in (self.source_id, self.license)):
            raise ValueError("metadata contains ASCII controls")
        return self


class SnapshotCreate(SnapshotMetadata):
    content_base64: Annotated[
        str,
        StringConstraints(
            strict=True, min_length=4, max_length=MAX_BASE64, pattern=r"^[A-Za-z0-9+/]*={0,2}$"
        ),
        Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
    ]

    def raw_bytes(self) -> bytes:
        try:
            content = base64.b64decode(self.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("invalid base64 content") from None
        if base64.b64encode(content).decode("ascii") != self.content_base64:
            raise ValueError("canonical base64 required")
        if not 1 <= len(content) <= MAX_BYTES or len(content) != self.byte_length:
            raise ValueError("snapshot length mismatch")
        if hashlib.sha256(content).hexdigest() != self.sha256:
            raise ValueError("snapshot hash mismatch")
        return content

    @model_validator(mode="after")
    def check_content(self) -> Self:
        self.raw_bytes()
        return self


class SnapshotRecord(SnapshotMetadata):
    created_at: Timestamp


class SnapshotWrite(SnapshotRecord):
    created: bool


class SnapshotPage(Contract):
    items: Annotated[list[SnapshotRecord], Field(max_length=100)]
    next_after_id: ReportUUID | None
