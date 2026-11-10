"""Append-only manual research ledger over immutable, exact-byte inputs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Connection, Engine, RowMapping, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from alphasense.contracts import AvailableObservation
from alphasense.db import CorruptReport, StoreUnavailable, _decode, get_store
from alphasense.db_schema import (
    instruments,
    raw_snapshots,
    report_revisions,
    research_runs,
    run_events,
    run_snapshots,
    sec_ingestions,
)
from alphasense.instrument_records import decode_instrument
from alphasense.report_contracts import ReportRevision, ReportUUID
from alphasense.run_contracts import (
    STEPS,
    RunAdvance,
    RunCommand,
    RunCreate,
    RunEvent,
    RunEventPage,
    RunEventWrite,
    RunFail,
    RunResume,
    RunStart,
    RunState,
    RunWrite,
)
from alphasense.snapshot_contracts import SnapshotRecord
from alphasense.snapshots import decode_snapshot


class RunConflict(Exception):
    """The request conflicts with a frozen definition or ledger position."""


class RunNotFound(Exception):
    """The requested research run is not present."""


@dataclass(frozen=True)
class _Context:
    definition: RunCreate
    origin: Literal["synthetic", "live"]
    created_at: datetime
    snapshots: dict[UUID, SnapshotRecord]


def _identity_error(corrupt: bool) -> None:
    if corrupt:
        raise CorruptReport("Run input integrity check failed")
    raise RunConflict("Run input identity conflict")


def _inputs(
    connection: Connection, definition: RunCreate, corrupt: bool
) -> tuple[Literal["synthetic", "live"], dict[UUID, SnapshotRecord]]:
    row = (
        connection.execute(
            select(instruments).where(instruments.c.instrument_id == definition.instrument_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        _identity_error(corrupt)
    try:
        registered = decode_instrument(dict(row))  # type: ignore[arg-type]
    except (ValidationError, ValueError, TypeError, KeyError):
        raise CorruptReport("Instrument integrity check failed") from None
    rows = (
        connection.execute(
            select(raw_snapshots).where(raw_snapshots.c.snapshot_id.in_(definition.snapshot_ids))
        )
        .mappings()
        .all()
    )
    if len(rows) != len(definition.snapshot_ids):
        _identity_error(corrupt)
    snapshots: dict[UUID, SnapshotRecord] = {}
    for snapshot_row in rows:
        snapshot, _content = decode_snapshot(dict(snapshot_row))
        if (
            snapshot.instrument_id != definition.instrument_id
            or snapshot.data_origin != registered.data_origin
            or snapshot.available_at is None
            or snapshot.available_at > definition.as_of
            or snapshot.as_of > definition.as_of
        ):
            _identity_error(corrupt)
        snapshots[snapshot.snapshot_id] = snapshot
        if definition.pipeline_version in {"sec-fundamentals-v1", "sec-fundamentals-v2"}:
            receipt = connection.scalar(
                select(sec_ingestions.c.snapshot_id).where(
                    sec_ingestions.c.snapshot_id == snapshot.snapshot_id,
                    sec_ingestions.c.instrument_id == snapshot.instrument_id,
                    sec_ingestions.c.sha256 == snapshot.sha256,
                    sec_ingestions.c.retrieved_at == snapshot.retrieved_at,
                )
            )
            if receipt is None:
                _identity_error(corrupt)
    return registered.data_origin, snapshots


def _context(connection: Connection, row: RowMapping) -> _Context:
    try:
        definition = RunCreate.model_validate(row["definition"])
        if (
            row["run_id"] != definition.run_id
            or row["instrument_id"] != definition.instrument_id
            or row["as_of"] != definition.as_of
        ):
            raise ValueError("run metadata mismatch")
        bindings = set(
            connection.execute(
                select(run_snapshots.c.snapshot_id).where(
                    run_snapshots.c.run_id == definition.run_id
                )
            ).scalars()
        )
        if bindings != set(definition.snapshot_ids):
            raise ValueError("run binding mismatch")
        origin, snapshots = _inputs(connection, definition, corrupt=True)
        return _Context(definition, origin, row["created_at"], snapshots)
    except (ValidationError, ValueError, TypeError, KeyError):
        raise CorruptReport("Run definition integrity check failed") from None


def _final_report(
    connection: Connection, context: _Context, revision_id: UUID, corrupt: bool = False
) -> ReportRevision:
    row = (
        connection.execute(
            select(report_revisions).where(report_revisions.c.revision_id == revision_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        _identity_error(corrupt)
    report = _decode(row)  # type: ignore[arg-type]
    if (
        report.input.instrument_id != str(context.definition.instrument_id)
        or report.input.as_of != context.definition.as_of
        or report.input.data_origin != context.origin
    ):
        _identity_error(corrupt)
    archive = {str(key): value for key, value in context.snapshots.items()}
    for source in report.sources:
        snapshot = archive.get(source.snapshot_id)
        if snapshot is None or (
            source.source_id,
            source.sha256,
            str(source.url) if source.url is not None else None,
            source.license,
            source.retrieved_at,
        ) != (
            snapshot.source_id,
            snapshot.sha256,
            str(snapshot.source_url) if snapshot.source_url is not None else None,
            snapshot.license,
            snapshot.retrieved_at,
        ):
            _identity_error(corrupt)
    for observation in report.input.observations:
        if isinstance(observation, AvailableObservation):
            snapshot = archive.get(observation.snapshot_id)
            if (
                snapshot is None
                or snapshot.available_at is None
                or observation.available_at < snapshot.available_at
            ):
                _identity_error(corrupt)
    return report


def _decode_event(connection: Connection, row: RowMapping, context: _Context) -> RunEvent:
    try:
        event = RunEvent.model_validate(
            {
                key: row[key]
                for key in (
                    "run_id",
                    "event_id",
                    "sequence",
                    "kind",
                    "request",
                    "state",
                    "created_at",
                )
            }
        )
        state = event.state
        definition = context.definition
        if (
            state.run_id != definition.run_id
            or state.instrument_id != definition.instrument_id
            or state.as_of != definition.as_of
            or state.snapshot_ids != definition.snapshot_ids
            or state.pipeline_version != definition.pipeline_version
            or state.data_origin != context.origin
            or state.created_at != context.created_at
            or state.updated_at < state.created_at
            or row["report_revision_id"] != state.report_revision_id
        ):
            raise ValueError("event state metadata mismatch")
        request = event.request
        if isinstance(request, RunCreate):
            if (
                request.model_dump(mode="json") != definition.model_dump(mode="json")
                or state.status != "queued"
                or state.completed_steps
                or state.created_at != event.created_at
            ):
                raise ValueError("invalid creation state")
        elif isinstance(request, RunStart):
            if state.status != "running" or state.completed_steps:
                raise ValueError("invalid start state")
        elif isinstance(request, RunAdvance):
            if (
                request.step == "review"
                or state.status != "running"
                or len(state.completed_steps) != STEPS.index(request.step) + 1
            ):
                raise ValueError("invalid advancement state")
        elif isinstance(request, RunFail):
            if (
                state.status != "failed"
                or state.report_revision_id is not None
                or state.current_step != request.step
                or state.error_code != request.error_code
                or state.error_reason != request.reason
            ):
                raise ValueError("invalid failure state")
        elif isinstance(request, RunResume):
            if state.status != "running":
                raise ValueError("invalid resumed state")
        else:
            if state.report_revision_id != request.report_revision_id:
                raise ValueError("invalid finalized state")
            report = _final_report(connection, context, request.report_revision_id, corrupt=True)
            if state.report_status != report.status:
                raise ValueError("finalized report status mismatch")
        return event
    except (ValidationError, ValueError, TypeError, KeyError, IndexError):
        raise CorruptReport("Run event integrity check failed") from None


def _run_row(connection: Connection, run_id: UUID, lock: bool = False) -> RowMapping:
    statement = select(research_runs).where(research_runs.c.run_id == run_id)
    if lock:
        statement = statement.with_for_update()
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise RunNotFound("Research run not found")
    return row


def _latest(connection: Connection, context: _Context) -> RunEvent:
    row = (
        connection.execute(
            select(run_events)
            .where(run_events.c.run_id == context.definition.run_id)
            .order_by(run_events.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CorruptReport("Run history is missing")
    return _decode_event(connection, row, context)


def _insert_event(connection: Connection, event: RunEvent) -> None:
    connection.execute(
        run_events.insert().values(
            run_id=event.run_id,
            event_id=event.event_id,
            sequence=event.sequence,
            kind=event.kind,
            request=event.request.model_dump(mode="json"),
            state=event.state.model_dump(mode="json"),
            report_revision_id=event.state.report_revision_id,
            created_at=event.created_at,
        )
    )


def _transition(
    connection: Connection,
    context: _Context,
    state: RunState,
    command: RunCommand,
    now: datetime,
) -> RunState:
    if state.report_revision_id is not None or state.sequence >= 2147483647:
        raise RunConflict("Research run is terminal")
    if state.sequence != command.expected_sequence:
        raise RunConflict("Research sequence conflict")
    if now < state.updated_at:
        raise StoreUnavailable("Run clock unavailable")
    changed: dict[str, object] = {
        **state.model_dump(mode="python"),
        "sequence": state.sequence + 1,
        "updated_at": now,
    }
    if isinstance(command, RunStart):
        if state.status != "queued":
            raise RunConflict("Run is not queued")
        changed["status"] = "running"
    elif isinstance(command, RunAdvance):
        if (
            state.status != "running"
            or command.step != state.current_step
            or command.step == "review"
        ):
            raise RunConflict("Run step conflict")
        completed = [*state.completed_steps, command.step]
        changed.update(completed_steps=completed, current_step=STEPS[len(completed)])
    elif isinstance(command, RunFail):
        if state.status != "running" or command.step != state.current_step:
            raise RunConflict("Run step conflict")
        changed.update(status="failed", error_code=command.error_code, error_reason=command.reason)
    elif isinstance(command, RunResume):
        if state.status != "failed":
            raise RunConflict("Run is not resumable")
        changed.update(status="running", error_code=None, error_reason=None)
    else:
        if state.status != "running" or state.current_step != "review":
            raise RunConflict("Run is not ready for final review")
        report = _final_report(connection, context, command.report_revision_id)
        failed = report.status == "failed"
        changed.update(
            status="failed" if failed else "completed",
            completed_steps=list(STEPS),
            current_step=None,
            report_revision_id=report.revision_id,
            report_status=report.status,
            error_code="REPORT_FAILED" if failed else None,
            error_reason="Report result failed" if failed else None,
        )
    return RunState.model_validate(changed)


class ResearchStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def create(self, data: RunCreate) -> RunWrite:
        checked = RunCreate.model_validate(data.model_dump(mode="python"))
        definition = checked.model_dump(mode="json")
        try:
            with self.engine.begin() as connection:
                inserted = connection.execute(
                    insert(research_runs)
                    .values(
                        run_id=checked.run_id,
                        instrument_id=checked.instrument_id,
                        as_of=checked.as_of,
                        definition=definition,
                    )
                    .on_conflict_do_nothing(index_elements=["run_id"])
                    .returning(research_runs.c.run_id)
                ).scalar_one_or_none()
                row = _run_row(connection, checked.run_id, lock=True)
                stored = RunCreate.model_validate(row["definition"])
                if stored.model_dump(mode="json") != definition:
                    raise RunConflict("Run definition conflict")
                if inserted is not None:
                    origin, _snapshots = _inputs(connection, checked, corrupt=False)
                    connection.execute(
                        run_snapshots.insert(),
                        [
                            {"run_id": checked.run_id, "snapshot_id": snapshot_id}
                            for snapshot_id in checked.snapshot_ids
                        ],
                    )
                    state = RunState(
                        run_id=checked.run_id,
                        instrument_id=checked.instrument_id,
                        as_of=checked.as_of,
                        snapshot_ids=checked.snapshot_ids,
                        pipeline_version=checked.pipeline_version,
                        data_origin=origin,
                        sequence=1,
                        status="queued",
                        current_step="data",
                        completed_steps=[],
                        error_code=None,
                        error_reason=None,
                        report_revision_id=None,
                        report_status=None,
                        created_at=row["created_at"],
                        updated_at=row["created_at"],
                    )
                    _insert_event(
                        connection,
                        RunEvent(
                            run_id=checked.run_id,
                            event_id=checked.run_id,
                            sequence=1,
                            kind="created",
                            request=checked,
                            state=state,
                            created_at=row["created_at"],
                        ),
                    )
                context = _context(connection, row)
                return RunWrite(
                    **_latest(connection, context).state.model_dump(), created=inserted is not None
                )
        except IntegrityError:
            raise RunConflict("Run definition conflict") from None
        except SQLAlchemyError:
            raise StoreUnavailable("Research storage unavailable") from None
        except (ValidationError, ValueError, TypeError, KeyError):
            raise CorruptReport("Run definition integrity check failed") from None

    def get(self, run_id: UUID) -> RunState:
        checked = TypeAdapter(ReportUUID).validate_python(run_id)
        try:
            with self.engine.connect() as connection:
                context = _context(connection, _run_row(connection, checked))
                return _latest(connection, context).state
        except SQLAlchemyError:
            raise StoreUnavailable("Research storage unavailable") from None

    def apply(self, run_id: UUID, command: RunCommand) -> RunEventWrite:
        checked_id = TypeAdapter(ReportUUID).validate_python(run_id)
        checked = TypeAdapter(RunCommand).validate_python(command.model_dump(mode="python"))
        try:
            with self.engine.begin() as connection:
                context = _context(connection, _run_row(connection, checked_id, lock=True))
                if context.definition.pipeline_version != "manual-research-v1":
                    raise RunConflict("Automatic runs require a fenced worker")
                existing = (
                    connection.execute(
                        select(run_events).where(
                            run_events.c.run_id == checked_id,
                            run_events.c.event_id == checked.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    event = _decode_event(connection, existing, context)
                    if event.request.model_dump(mode="json") != checked.model_dump(mode="json"):
                        raise RunConflict("Run request identity conflict")
                    return RunEventWrite(**event.model_dump(), created=False)
                state = _latest(connection, context).state
                now = connection.scalar(text("SELECT clock_timestamp()"))
                updated = _transition(connection, context, state, checked, now)
                event = RunEvent(
                    run_id=checked_id,
                    event_id=checked.request_id,
                    sequence=updated.sequence,
                    kind=checked.action,
                    request=checked,
                    state=updated,
                    created_at=now,
                )
                _insert_event(connection, event)
                return RunEventWrite(**event.model_dump(), created=True)
        except IntegrityError:
            raise RunConflict("Run event conflict") from None
        except SQLAlchemyError:
            raise StoreUnavailable("Research storage unavailable") from None

    def events(self, run_id: UUID, after_sequence: int = 0, limit: int = 50) -> RunEventPage:
        checked = TypeAdapter(ReportUUID).validate_python(run_id)
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("invalid pagination")
        try:
            with self.engine.connect() as connection:
                context = _context(connection, _run_row(connection, checked))
                rows = (
                    connection.execute(
                        select(run_events)
                        .where(
                            run_events.c.run_id == checked, run_events.c.sequence > after_sequence
                        )
                        .order_by(run_events.c.sequence)
                        .limit(limit + 1)
                    )
                    .mappings()
                    .all()
                )
                events = [_decode_event(connection, row, context) for row in rows]
                items = events[:limit]
                cursor = items[-1].sequence if len(events) > limit else None
                return RunEventPage(items=items, next_after_sequence=cursor)
        except SQLAlchemyError:
            raise StoreUnavailable("Research storage unavailable") from None


def get_research_store() -> ResearchStore:
    return ResearchStore(get_store().engine)
