"""Metadata returned by the append-only PostgreSQL report store."""

from typing import Annotated

from pydantic import Field

from alphasense.contracts import Contract, Timestamp
from alphasense.report_contracts import ReportStatus, ReportUUID, RevisionNumber, Sha256


class RevisionInfo(Contract):
    report_id: ReportUUID
    revision_id: ReportUUID
    revision: RevisionNumber
    checksum: Sha256
    status: ReportStatus
    generated_at_utc: Timestamp


class StoredRevisionInfo(RevisionInfo):
    created: bool


class RevisionPage(Contract):
    items: Annotated[list[RevisionInfo], Field(max_length=100)]
    next_after_revision: RevisionNumber | None
