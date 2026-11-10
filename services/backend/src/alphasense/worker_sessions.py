"""Observed worker process sessions; never grants ownership of queued work."""

import unicodedata
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import Connection, Engine, RowMapping, select, text
from sqlalchemy.dialects.postgresql import insert

from alphasense.db import StoreUnavailable
from alphasense.db_schema import worker_sessions
from alphasense.worker_session_contracts import (
    WORKER_STALE_SECONDS,
    WorkerErrorCode,
    WorkerKind,
    WorkerSessionPage,
    WorkerSessionRecord,
    WorkerSessionStart,
    WorkerStopReason,
)


class WorkerSessionNotFound(Exception):
    pass


class WorkerSessionConflict(Exception):
    pass


class WorkerSessionInvalid(ValueError):
    pass


def _now(connection: Connection) -> datetime:
    return connection.execute(text("SELECT clock_timestamp()")).scalar_one()  # type: ignore[no-any-return]


def _identity(payload: WorkerSessionStart) -> WorkerSessionStart:
    try:
        checked = WorkerSessionStart.model_validate(payload.model_dump())
        checked.worker_id.encode("utf-8")
        if any(unicodedata.category(char) in {"Cc", "Cf"} for char in checked.worker_id):
            raise ValueError("control")
        return checked
    except (ValueError, TypeError):
        raise WorkerSessionInvalid("Invalid worker session") from None


def _decode(row: RowMapping, observed_at: datetime) -> WorkerSessionRecord:
    try:
        identity = _identity(
            WorkerSessionStart.model_validate(
                {name: row[name] for name in WorkerSessionStart.model_fields}
            )
        )
    except (ValueError, KeyError, TypeError):
        raise StoreUnavailable("Worker session integrity failure") from None
    try:
        expires = row["heartbeat_at"] + timedelta(seconds=WORKER_STALE_SECONDS)
        status: Literal["online", "stale", "stopped"] = (
            "stopped"
            if row["stopped_at"] is not None
            else ("stale" if observed_at >= expires else "online")
        )
        return WorkerSessionRecord(
            **identity.model_dump(),
            started_at=row["started_at"],
            heartbeat_at=row["heartbeat_at"],
            stopped_at=row["stopped_at"],
            stop_reason=row["stop_reason"],
            error_code=row["error_code"],
            status=status,
            observed_at=observed_at,
            contact_expires_at=expires,
        )
    except (ValueError, KeyError, TypeError):
        raise StoreUnavailable("Worker session integrity failure") from None


def _row(connection: Connection, session_id: UUID, lock: bool = False) -> RowMapping:
    query = select(worker_sessions).where(worker_sessions.c.session_id == session_id)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    if row is None:
        raise WorkerSessionNotFound("Worker session not found")
    return row


class WorkerSessionStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def start(self, payload: WorkerSessionStart) -> WorkerSessionRecord:
        checked = _identity(payload)
        identity = checked.model_dump()
        with self.engine.begin() as connection:
            now = _now(connection)
            connection.execute(
                insert(worker_sessions)
                .values(
                    **identity,
                    started_at=now,
                    heartbeat_at=now,
                )
                .on_conflict_do_nothing(index_elements=[worker_sessions.c.session_id])
            )
            row = _row(connection, checked.session_id, True)
            if any(row[key] != value for key, value in identity.items()):
                raise WorkerSessionConflict("Frozen worker session identity conflict")
            return _decode(row, _now(connection))

    def heartbeat(self, session_id: UUID) -> WorkerSessionRecord:
        with self.engine.begin() as connection:
            row = _row(connection, session_id, True)
            _decode(row, _now(connection))
            if row["stopped_at"] is not None:
                raise WorkerSessionConflict("Worker session already stopped")
            connection.execute(
                worker_sessions.update()
                .where(worker_sessions.c.session_id == session_id)
                .values(heartbeat_at=_now(connection))
            )
            return _decode(_row(connection, session_id), _now(connection))

    def stop(
        self, session_id: UUID, reason: WorkerStopReason, error_code: WorkerErrorCode | None = None
    ) -> WorkerSessionRecord:
        if (
            reason not in {"completed", "interrupted", "error"}
            or ((reason == "error") != (error_code is not None))
            or error_code not in {None, "WORKER_RUNTIME_FAILED", "WORKER_MONITOR_FAILED"}
        ):
            raise WorkerSessionInvalid("Invalid worker stop")
        with self.engine.begin() as connection:
            row = _row(connection, session_id, True)
            _decode(row, _now(connection))
            if row["stopped_at"] is not None:
                if row["stop_reason"] != reason or row["error_code"] != error_code:
                    raise WorkerSessionConflict("Worker stop identity conflict")
                return _decode(row, _now(connection))
            connection.execute(
                worker_sessions.update()
                .where(worker_sessions.c.session_id == session_id)
                .values(stopped_at=_now(connection), stop_reason=reason, error_code=error_code)
            )
            return _decode(_row(connection, session_id), _now(connection))

    def get(self, session_id: UUID) -> WorkerSessionRecord:
        with self.engine.connect() as connection:
            row = _row(connection, session_id)
            return _decode(row, _now(connection))

    def page(
        self, after_id: UUID | None = None, limit: int = 50, kind: WorkerKind | None = None
    ) -> WorkerSessionPage:
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or kind not in {None, "sec_import", "document_validation", "sec_scheduler"}
        ):
            raise WorkerSessionInvalid("Invalid worker page")
        query = select(worker_sessions).order_by(worker_sessions.c.session_id).limit(limit + 1)
        if after_id is not None:
            query = query.where(worker_sessions.c.session_id > after_id)
        if kind is not None:
            query = query.where(worker_sessions.c.kind == kind)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
            observed_at = _now(connection)
            items = [_decode(row, observed_at) for row in rows[:limit]]
        return WorkerSessionPage(
            items=items,
            observed_at=observed_at,
            next_after_id=items[-1].session_id if len(rows) > limit else None,
        )
