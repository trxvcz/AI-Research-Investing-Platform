"""Immutable offline document imports; human decisions never publish observations."""

import base64
import binascii
import hashlib
import json
from uuid import UUID

from sqlalchemy import Connection, Engine, RowMapping, select
from sqlalchemy.dialects.postgresql import insert

from alphasense.db import StoreUnavailable, _contains_nul
from alphasense.db_schema import document_archives, document_reviews, instruments
from alphasense.document_agent import validate_draft
from alphasense.document_archive_contracts import (
    DocumentArchiveCreate,
    DocumentArchivePage,
    DocumentArchiveRecord,
    DocumentArchiveSummary,
    DocumentReviewCommand,
    DocumentReviewEvent,
)
from alphasense.document_contracts import DocumentAgentResult, DocumentPacket
from alphasense.document_readers import read_text_document


class DocumentArchiveNotFound(Exception):
    pass


class DocumentArchiveConflict(Exception):
    pass


class DocumentArchiveInvalid(ValueError):
    pass


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _prepare(
    request: DocumentArchiveCreate,
) -> tuple[bytes, DocumentPacket, DocumentAgentResult]:
    try:
        raw = base64.b64decode(request.content_base64, validate=True)
        if not 1 <= len(raw) <= 1048576:
            raise ValueError("size")
        if base64.b64encode(raw).decode("ascii") != request.content_base64:
            raise ValueError("Noncanonical base64")
        if len(request.draft_json.encode("utf-8")) > 262144:
            raise ValueError("draft size")
        if _contains_nul(request.model_dump(mode="json")):
            raise ValueError("Unstorable text")
        # Validate every metadata string as UTF-8 before either hashing or SQL.
        _hash(request.model_dump(mode="json"))
        packet = read_text_document(
            raw,
            document_id=request.archive_id,
            classification=request.classification,
            format=request.format,
            reader_version=request.reader_version,
            number_locale=request.number_locale,
        )
        if _contains_nul(packet.model_dump(mode="json")):
            raise ValueError("Unstorable packet")
        result = validate_draft(packet, request.draft_json, request.provider_id)
        if _contains_nul(result.model_dump(mode="json")):
            raise ValueError("Unstorable result")
        _hash(result.model_dump(mode="json"))
        return raw, packet, result
    except (ValueError, UnicodeError, binascii.Error):
        raise DocumentArchiveInvalid("Invalid document import") from None


def _reviews(
    connection: Connection, archive_id: UUID, result: DocumentAgentResult
) -> list[DocumentReviewEvent]:
    rows = (
        connection.execute(
            select(document_reviews)
            .where(document_reviews.c.archive_id == archive_id)
            .order_by(document_reviews.c.revision)
        )
        .mappings()
        .all()
    )
    events: list[DocumentReviewEvent] = []
    for revision, row in enumerate(rows, 1):
        command = DocumentReviewCommand.model_validate(row["command"])
        if (
            row["revision"] != revision
            or command.expected_revision != revision - 1
            or row["command_id"] != command.command_id
            or row["command_sha256"] != _hash(command.model_dump(mode="json"))
        ):
            raise StoreUnavailable("Document review integrity failure")
        _check_review(command, result)
        if events and row["reviewed_at"] < events[-1].reviewed_at:
            raise StoreUnavailable("Document review integrity failure")
        events.append(
            DocumentReviewEvent(revision=revision, command=command, reviewed_at=row["reviewed_at"])
        )
    return events


def _check_review(command: DocumentReviewCommand, result: DocumentAgentResult) -> None:
    if command.fact_index >= len(result.facts):
        raise DocumentArchiveInvalid("Fact not available for review")
    if command.verdict == "accepted" and result.facts[command.fact_index].status != "needs_review":
        raise DocumentArchiveInvalid("Rejected fact cannot be accepted")


def _decode(connection: Connection, row: RowMapping) -> DocumentArchiveRecord:
    try:
        metadata = dict(row["request"])
        metadata["content_base64"] = base64.b64encode(bytes(row["raw_content"])).decode("ascii")
        request = DocumentArchiveCreate.model_validate(metadata)
        raw, packet, result = _prepare(request)
        if (
            row["archive_id"] != request.archive_id
            or row["instrument_id"] != request.instrument_id
            or row["request_sha256"] != _hash(request.model_dump(mode="json"))
            or row["document_sha256"] != hashlib.sha256(raw).hexdigest()
            or row["draft_sha256"] != hashlib.sha256(request.draft_json.encode("utf-8")).hexdigest()
            or row["packet"] != packet.model_dump(mode="json")
            or row["result"] != result.model_dump(mode="json")
        ):
            raise StoreUnavailable("Document archive integrity failure")
        events = _reviews(connection, request.archive_id, result)
        return DocumentArchiveRecord(
            **{
                key: getattr(request, key)
                for key in (
                    "archive_id",
                    "title",
                    "instrument_id",
                    "format",
                    "reader_version",
                    "number_locale",
                    "classification",
                    "provider_id",
                    "model_id",
                    "prompt_version",
                    "source_available_at",
                    "as_of",
                )
            },
            document_sha256=row["document_sha256"],
            draft_sha256=row["draft_sha256"],
            created_at=row["created_at"],
            validation_status=result.status,
            fact_count=len(result.facts),
            review_revision=len(events),
            packet=packet,
            draft_json=request.draft_json,
            result=result,
            reviews=events,
        )
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise StoreUnavailable("Document archive integrity failure") from None


class DocumentArchiveStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def create(self, request: DocumentArchiveCreate) -> DocumentArchiveRecord:
        checked = DocumentArchiveCreate.model_validate(request.model_dump())
        raw, packet, result = _prepare(checked)
        payload = checked.model_dump(mode="json")
        with self.engine.begin() as connection:
            if (
                checked.instrument_id is not None
                and connection.scalar(
                    select(instruments.c.instrument_id).where(
                        instruments.c.instrument_id == checked.instrument_id
                    )
                )
                is None
            ):
                raise DocumentArchiveInvalid("Unknown instrument")
            connection.execute(
                insert(document_archives)
                .values(
                    archive_id=checked.archive_id,
                    instrument_id=checked.instrument_id,
                    request={
                        key: value for key, value in payload.items() if key != "content_base64"
                    },
                    request_sha256=_hash(payload),
                    raw_content=raw,
                    document_sha256=packet.sha256,
                    draft_sha256=hashlib.sha256(checked.draft_json.encode("utf-8")).hexdigest(),
                    packet=packet.model_dump(mode="json"),
                    result=result.model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=[document_archives.c.archive_id])
            )
            row = (
                connection.execute(
                    select(document_archives).where(
                        document_archives.c.archive_id == checked.archive_id
                    )
                )
                .mappings()
                .one()
            )
            if row["request_sha256"] != _hash(payload):
                raise DocumentArchiveConflict("Frozen document identity conflict")
            return _decode(connection, row)

    def get(self, archive_id: UUID) -> DocumentArchiveRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(document_archives).where(document_archives.c.archive_id == archive_id)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise DocumentArchiveNotFound("Document not found")
            return _decode(connection, row)

    def content(self, archive_id: UUID) -> bytes:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(document_archives).where(document_archives.c.archive_id == archive_id)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise DocumentArchiveNotFound("Document not found")
            _decode(connection, row)
            return bytes(row["raw_content"])

    def page(
        self, after_id: UUID | None = None, limit: int = 50, instrument_id: UUID | None = None
    ) -> DocumentArchivePage:
        if not 1 <= limit <= 50:
            raise DocumentArchiveInvalid("Invalid page limit")
        query = select(document_archives).order_by(document_archives.c.archive_id).limit(limit + 1)
        if after_id is not None:
            query = query.where(document_archives.c.archive_id > after_id)
        if instrument_id is not None:
            query = query.where(document_archives.c.instrument_id == instrument_id)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
            records = [_decode(connection, row) for row in rows[:limit]]
        items = [
            DocumentArchiveSummary.model_validate(
                {key: getattr(record, key) for key in DocumentArchiveSummary.model_fields}
            )
            for record in records
        ]
        return DocumentArchivePage(
            items=items, next_after_id=items[-1].archive_id if len(rows) > limit else None
        )

    def review(self, archive_id: UUID, command: DocumentReviewCommand) -> DocumentReviewEvent:
        checked = DocumentReviewCommand.model_validate(command.model_dump())
        if _contains_nul(checked.model_dump(mode="json")):
            raise DocumentArchiveInvalid("Invalid review")
        try:
            _hash(checked.model_dump(mode="json"))
        except UnicodeError:
            raise DocumentArchiveInvalid("Invalid review") from None
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(document_archives)
                    .where(document_archives.c.archive_id == archive_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if row is None:
                raise DocumentArchiveNotFound("Document not found")
            record = _decode(connection, row)
            for event in record.reviews:
                if event.command.command_id == checked.command_id:
                    if event.command != checked:
                        raise DocumentArchiveConflict("Review command identity conflict")
                    return event
            if (
                record.review_revision != checked.expected_revision
                or record.review_revision >= 10000
            ):
                raise DocumentArchiveConflict("Review revision conflict")
            _check_review(checked, record.result)
            inserted = (
                connection.execute(
                    insert(document_reviews)
                    .values(
                        archive_id=archive_id,
                        revision=record.review_revision + 1,
                        command_id=checked.command_id,
                        command=checked.model_dump(mode="json"),
                        command_sha256=_hash(checked.model_dump(mode="json")),
                    )
                    .returning(document_reviews)
                )
                .mappings()
                .one()
            )
            return DocumentReviewEvent(
                revision=inserted["revision"], command=checked, reviewed_at=inserted["reviewed_at"]
            )
