"""Fenced PostgreSQL jobs for replaying immutable local document drafts."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from alphasense.contracts import Identifier
from alphasense.db import StoreUnavailable
from alphasense.db_schema import (
    document_archives,
    document_task_audits,
    document_task_events,
    document_tasks,
)
from alphasense.document_archive import _decode as decode_archive
from alphasense.document_archive import _hash
from alphasense.document_archive_contracts import DocumentArchiveRecord
from alphasense.document_contracts import DocumentAgentResult
from alphasense.document_task_contracts import (
    DocumentTaskAudit,
    DocumentTaskCreate,
    DocumentTaskDetail,
    DocumentTaskEvent,
    DocumentTaskPage,
    DocumentTaskRecord,
    DocumentTaskStage,
)


class DocumentTaskNotFound(Exception):
    pass


class DocumentTaskConflict(Exception):
    pass


class DocumentTaskInvalid(ValueError):
    pass


class DocumentTaskLeaseLost(Exception):
    pass


def input_hash(archive: DocumentArchiveRecord) -> str:
    return _hash(
        {"packet": archive.packet.model_dump(mode="json"), "draft_json": archive.draft_json}
    )


def _source(connection: Connection, archive_id: UUID) -> DocumentArchiveRecord:
    row = (
        connection.execute(
            select(document_archives).where(document_archives.c.archive_id == archive_id)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise DocumentTaskNotFound("Document not found")
    return decode_archive(connection, row)


def _now(connection: Connection) -> datetime:
    return connection.execute(text("SELECT clock_timestamp()")).scalar_one()  # type: ignore[no-any-return]


def _row(connection: Connection, job_id: UUID, lock: bool = False) -> RowMapping:
    query = select(document_tasks).where(document_tasks.c.job_id == job_id)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    if row is None:
        raise DocumentTaskNotFound("Document task not found")
    return row


def _event(
    connection: Connection, row: RowMapping, stage: DocumentTaskStage, error: str | None = None
) -> None:
    previous = (
        connection.scalar(
            select(document_task_events.c.sequence)
            .where(document_task_events.c.job_id == row["job_id"])
            .order_by(document_task_events.c.sequence.desc())
            .limit(1)
        )
        or 0
    )
    event = DocumentTaskEvent(
        sequence=previous + 1,
        attempt=row["attempt"],
        stage=stage,
        recorded_at=_now(connection),
        error_code=error,
    )
    payload = event.model_dump(mode="json")
    connection.execute(
        document_task_events.insert().values(
            job_id=row["job_id"], sequence=event.sequence, payload=payload, sha256=_hash(payload)
        )
    )


def _audit(
    connection: Connection,
    row: RowMapping,
    outcome: Literal["completed", "blocked", "failed", "interrupted"],
    error: str | None,
    result: DocumentAgentResult | None,
) -> None:
    mode = row["request"]["mode"]
    audit = DocumentTaskAudit(
        attempt=row["attempt"],
        worker_id=row["worker_id"],
        started_at=row["started_at"],
        finished_at=_now(connection),
        outcome=outcome,
        error_code=error,
        execution="offline-validation-v1"
        if mode == "validate_saved_draft"
        else "model-disabled-v1",
        implementation_sha256=row["implementation_sha256"],
        request_sha256=row["input_sha256"],
        output_sha256=_hash(result.model_dump(mode="json")) if result is not None else None,
        result=result,
    )
    payload = audit.model_dump(mode="json")
    connection.execute(
        document_task_audits.insert().values(
            job_id=row["job_id"], attempt=row["attempt"], payload=payload, sha256=_hash(payload)
        )
    )


def _detail(connection: Connection, row: RowMapping) -> DocumentTaskDetail:
    try:
        request = DocumentTaskCreate.model_validate(row["request"])
        source = _source(connection, request.archive_id)
        if (
            row["job_id"] != request.job_id
            or row["archive_id"] != request.archive_id
            or row["input_sha256"] != input_hash(source)
            or row["document_sha256"] != source.document_sha256
            or row["draft_sha256"] != source.draft_sha256
        ):
            raise ValueError("Frozen input mismatch")
        events: list[DocumentTaskEvent] = []
        for sequence, event_row in enumerate(
            connection.execute(
                select(document_task_events)
                .where(document_task_events.c.job_id == request.job_id)
                .order_by(document_task_events.c.sequence)
            ).mappings(),
            1,
        ):
            event = DocumentTaskEvent.model_validate(event_row["payload"])
            if (
                event.sequence != sequence
                or event_row["sequence"] != sequence
                or event_row["sha256"] != _hash(event.model_dump(mode="json"))
            ):
                raise ValueError("Event mismatch")
            if events and (
                event.recorded_at < events[-1].recorded_at
                or event.attempt not in {events[-1].attempt, events[-1].attempt + 1}
            ):
                raise ValueError("Event chronology mismatch")
            events.append(event)
        if (
            not events
            or events[0].stage != "queued"
            or events[0].attempt != 0
            or events[-1].stage != row["stage"]
            or events[-1].attempt != row["attempt"]
            or events[-1].error_code != row["error_code"]
        ):
            raise ValueError("Current event mismatch")
        audits: list[DocumentTaskAudit] = []
        for attempt, audit_row in enumerate(
            connection.execute(
                select(document_task_audits)
                .where(document_task_audits.c.job_id == request.job_id)
                .order_by(document_task_audits.c.attempt)
            ).mappings(),
            1,
        ):
            audit = DocumentTaskAudit.model_validate(audit_row["payload"])
            if (
                audit.attempt != attempt
                or audit_row["attempt"] != attempt
                or audit_row["sha256"] != _hash(audit.model_dump(mode="json"))
                or audit.request_sha256 != row["input_sha256"]
                or audit.started_at > audit.finished_at
                or audit.execution
                != (
                    "offline-validation-v1"
                    if request.mode == "validate_saved_draft"
                    else "model-disabled-v1"
                )
            ):
                raise ValueError("Audit mismatch")
            if audit.outcome == "completed":
                if (
                    request.mode != "validate_saved_draft"
                    or audit.result != source.result
                    or audit.error_code is not None
                ):
                    raise ValueError("Completed validation mismatch")
            elif audit.result is not None or audit.error_code is None:
                raise ValueError("Invalid failed attempt")
            expected_output = _hash(audit.result.model_dump(mode="json")) if audit.result else None
            if audit.output_sha256 != expected_output or (
                audit.result is not None and audit.result.document_id != request.archive_id
            ):
                raise ValueError("Audit output mismatch")
            if audits and (
                audits[-1].outcome != "interrupted" or audit.started_at < audits[-1].finished_at
            ):
                raise ValueError("Audit recovery mismatch")
            audits.append(audit)
        record = DocumentTaskRecord(
            job_id=request.job_id,
            archive_id=request.archive_id,
            title=source.title,
            mode=request.mode,
            status=row["status"],
            stage=row["stage"],
            attempt=row["attempt"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            heartbeat_at=row["heartbeat_at"],
            lease_expires_at=row["lease_expires_at"],
            worker_id=row["worker_id"],
            error_code=row["error_code"],
            document_sha256=row["document_sha256"],
            draft_sha256=row["draft_sha256"],
            input_sha256=row["input_sha256"],
            result=row["result"],
        )
        expected_audits = record.attempt - (1 if record.status == "running" else 0)
        if len(audits) != expected_audits or record.updated_at < record.created_at:
            raise ValueError("Audit count mismatch")
        if record.status in {"completed", "blocked", "failed"}:
            last = audits[-1]
            # A crashed final lease ends with an interrupted receipt.
            expected_outcome = (
                "interrupted" if record.error_code == "RECOVERY_EXHAUSTED" else record.status
            )
            if (
                last.outcome != expected_outcome
                or last.result != record.result
                or (
                    record.error_code != "RECOVERY_EXHAUSTED"
                    and last.error_code != record.error_code
                )
            ):
                raise ValueError("Terminal receipt mismatch")
        elif record.result is not None:
            raise ValueError("Unfinished output")
        if record.status == "running" and (
            row["lease_token"] is None
            or row["started_at"] is None
            or row["implementation_sha256"] is None
        ):
            raise ValueError("Missing running owner")
        return DocumentTaskDetail(task=record, events=events, audits=audits)
    except (ValueError, TypeError, KeyError, IndexError, DocumentTaskNotFound):
        raise StoreUnavailable("Document task integrity failure") from None


def _fence(connection: Connection, row: RowMapping, token: UUID) -> None:
    if (
        row["status"] != "running"
        or row["lease_token"] != token
        or row["lease_expires_at"] <= _now(connection)
    ):
        raise DocumentTaskLeaseLost("Document task lease lost")


class DocumentTaskStore:
    def __init__(self, engine: Engine):
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def create(self, request: DocumentTaskCreate) -> DocumentTaskRecord:
        checked = DocumentTaskCreate.model_validate(request.model_dump())
        with self.engine.begin() as connection:
            source = _source(connection, checked.archive_id)
            inserted = connection.execute(
                insert(document_tasks)
                .values(
                    job_id=checked.job_id,
                    archive_id=checked.archive_id,
                    request=checked.model_dump(mode="json"),
                    input_sha256=input_hash(source),
                    document_sha256=source.document_sha256,
                    draft_sha256=source.draft_sha256,
                    status="queued",
                    stage="queued",
                    attempt=0,
                )
                .on_conflict_do_nothing(index_elements=[document_tasks.c.job_id])
                .returning(document_tasks.c.job_id)
            ).scalar_one_or_none()
            row = _row(connection, checked.job_id, True)
            if row["request"] != checked.model_dump(mode="json"):
                raise DocumentTaskConflict("Frozen task identity conflict")
            if inserted is not None:
                _event(connection, row, "queued")
            return _detail(connection, row).task

    def get(self, job_id: UUID) -> DocumentTaskRecord:
        return self.detail(job_id).task

    def detail(self, job_id: UUID) -> DocumentTaskDetail:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            return _detail(connection, _row(connection, job_id))

    def page(self, after_id: UUID | None = None, limit: int = 50) -> DocumentTaskPage:
        if not 1 <= limit <= 50:
            raise DocumentTaskInvalid("Invalid page limit")
        query = select(document_tasks).order_by(document_tasks.c.job_id).limit(limit + 1)
        if after_id is not None:
            query = query.where(document_tasks.c.job_id > after_id)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            rows = connection.execute(query).mappings().all()
            items = [_detail(connection, row).task for row in rows[:limit]]
        return DocumentTaskPage(
            items=items, next_after_id=items[-1].job_id if len(rows) > limit else None
        )

    def claim(
        self, worker_id: str, implementation_sha256: str, lease_seconds: int = 120
    ) -> tuple[UUID, DocumentTaskRecord] | None:
        from pydantic import TypeAdapter

        from alphasense.report_contracts import Sha256

        if not 15 <= lease_seconds <= 300:
            raise DocumentTaskInvalid("Invalid lease duration")
        TypeAdapter(Identifier).validate_python(worker_id)
        TypeAdapter(Sha256).validate_python(implementation_sha256)
        if any(not char.isprintable() for char in worker_id):
            raise DocumentTaskInvalid("Invalid worker")
        with self.engine.begin() as connection:
            now = _now(connection)
            row = (
                connection.execute(
                    select(document_tasks)
                    .where(
                        or_(
                            document_tasks.c.status == "queued",
                            (document_tasks.c.status == "running")
                            & (document_tasks.c.lease_expires_at <= now),
                        )
                    )
                    .order_by(document_tasks.c.created_at, document_tasks.c.job_id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            _detail(connection, row)
            if row["status"] == "running":
                _audit(connection, row, "interrupted", "LEASE_EXPIRED", None)
                _event(connection, row, "failed", "LEASE_EXPIRED")
            if row["attempt"] >= 3:
                connection.execute(
                    document_tasks.update()
                    .where(document_tasks.c.job_id == row["job_id"])
                    .values(
                        status="failed",
                        stage="failed",
                        lease_token=None,
                        lease_expires_at=None,
                        error_code="RECOVERY_EXHAUSTED",
                        updated_at=_now(connection),
                    )
                )
                _event(connection, _row(connection, row["job_id"]), "failed", "RECOVERY_EXHAUSTED")
                return None
            now = _now(connection)
            token = uuid4()
            connection.execute(
                document_tasks.update()
                .where(document_tasks.c.job_id == row["job_id"])
                .values(
                    status="running",
                    stage="reading",
                    attempt=row["attempt"] + 1,
                    worker_id=worker_id,
                    implementation_sha256=implementation_sha256,
                    lease_token=token,
                    started_at=now,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    error_code=None,
                    updated_at=now,
                )
            )
            claimed = _row(connection, row["job_id"])
            _event(connection, claimed, "reading")
            _fence(connection, claimed, token)
            return token, _detail(connection, claimed).task

    def renew(self, job_id: UUID, token: UUID, lease_seconds: int = 120) -> None:
        if not 15 <= lease_seconds <= 300:
            raise DocumentTaskInvalid("Invalid lease duration")
        with self.engine.begin() as connection:
            row = _row(connection, job_id, True)
            _fence(connection, row, token)
            now = _now(connection)
            connection.execute(
                document_tasks.update()
                .where(document_tasks.c.job_id == job_id)
                .values(
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    updated_at=now,
                )
            )
            if row["lease_expires_at"] <= _now(connection):
                raise DocumentTaskLeaseLost("Lease expired during renewal")

    def stage(self, job_id: UUID, token: UUID, stage: DocumentTaskStage) -> None:
        with self.engine.begin() as connection:
            row = _row(connection, job_id, True)
            _fence(connection, row, token)
            if (row["stage"], stage) not in {
                ("reading", "validating"),
                ("validating", "archiving"),
            }:
                raise DocumentTaskConflict("Invalid stage progression")
            connection.execute(
                document_tasks.update()
                .where(document_tasks.c.job_id == job_id)
                .values(stage=stage, updated_at=_now(connection))
            )
            updated = _row(connection, job_id)
            _event(connection, updated, stage)
            _fence(connection, updated, token)

    def finish(
        self,
        job_id: UUID,
        token: UUID,
        outcome: Literal["completed", "blocked", "failed"],
        result: DocumentAgentResult | None = None,
        error_code: str | None = None,
    ) -> None:
        if outcome not in {"completed", "blocked", "failed"}:
            raise DocumentTaskInvalid("Invalid outcome")
        with self.engine.begin() as connection:
            row = _row(connection, job_id, True)
            _fence(connection, row, token)
            detail = _detail(connection, row)
            if outcome == "completed":
                if (
                    detail.task.mode != "validate_saved_draft"
                    or row["stage"] != "archiving"
                    or result is None
                    or error_code is not None
                ):
                    raise DocumentTaskInvalid("Incomplete document result")
                checked = DocumentAgentResult.model_validate(result.model_dump())
                source = _source(connection, detail.task.archive_id)
                if checked != source.result:
                    raise DocumentTaskInvalid("Result differs from frozen validation")
            else:
                if result is not None or error_code is None:
                    raise DocumentTaskInvalid("Invalid terminal error")
                checked = None
            _audit(connection, row, outcome, error_code, checked)
            _event(connection, row, outcome, error_code)
            _fence(connection, row, token)
            connection.execute(
                document_tasks.update()
                .where(document_tasks.c.job_id == job_id)
                .values(
                    status=outcome,
                    stage=outcome,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code=error_code,
                    result=checked.model_dump(mode="json") if checked else None,
                    updated_at=_now(connection),
                )
            )
            if row["lease_expires_at"] <= _now(connection):
                raise DocumentTaskLeaseLost("Lease expired during completion")
