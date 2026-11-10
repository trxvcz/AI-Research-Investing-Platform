"""Transactional SEC schedule dispatch; no fetching, worker or model invocation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, RowMapping, func, select, text
from sqlalchemy.dialects.postgresql import insert

from alphasense.db import StoreUnavailable
from alphasense.db_schema import (
    import_tasks,
    sec_schedule_commands,
    sec_schedule_occurrences,
    sec_schedules,
)
from alphasense.schedule_contracts import (
    ScheduleCommand,
    ScheduleCreate,
    ScheduleOccurrence,
    ScheduleOccurrencePage,
    SchedulePage,
    ScheduleRecord,
)
from alphasense.sec_contracts import SecImportRequest


class ScheduleNotFound(Exception):
    pass


class ScheduleConflict(Exception):
    pass


class ScheduleInvalid(ValueError):
    pass


def _now(connection: Connection) -> datetime:
    return connection.execute(text("SELECT clock_timestamp()")).scalar_one()  # type: ignore[no-any-return]


def slot_run_id(schedule_id: UUID, scheduled_for: datetime) -> UUID:
    return uuid5(schedule_id, scheduled_for.astimezone(UTC).isoformat())


def _row(connection: Connection, schedule_id: UUID, lock: bool = False) -> RowMapping:
    query = select(sec_schedules).where(sec_schedules.c.schedule_id == schedule_id)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    if row is None:
        raise ScheduleNotFound("Schedule not found")
    return row


def _normalize(payload: ScheduleCreate, template: SecImportRequest) -> ScheduleCreate:
    checked = ScheduleCreate.model_validate(payload.model_dump())
    if checked.exchange_mic == "XWAR":
        raise ScheduleInvalid("Unsupported schedule market")
    return checked.model_copy(
        update={
            "symbol": checked.symbol.strip().upper(),
            "exchange_mic": checked.exchange_mic or template.exchange_mic,
        }
    )


def _occurrence(row: RowMapping) -> ScheduleOccurrence:
    return ScheduleOccurrence.model_validate(
        {key: row[key] for key in ScheduleOccurrence.model_fields}
    )


def _binding(
    connection: Connection, occurrence: ScheduleOccurrence, template: SecImportRequest
) -> None:
    if occurrence.dispatched_at < occurrence.scheduled_for or (
        (occurrence.outcome == "enqueued") != (occurrence.run_id is not None)
    ):
        raise ValueError("Schedule occurrence mismatch")
    if occurrence.run_id is not None:
        expected = template.model_copy(
            update={"run_id": slot_run_id(occurrence.schedule_id, occurrence.scheduled_for)}
        )
        frozen = connection.scalar(
            select(import_tasks.c.request).where(import_tasks.c.run_id == occurrence.run_id)
        )
        if occurrence.run_id != expected.run_id or frozen != expected.model_dump(mode="json"):
            raise ValueError("Schedule task binding mismatch")


def _decode(connection: Connection, row: RowMapping) -> ScheduleRecord:
    try:
        initial = ScheduleCreate.model_validate(row["create_request"])
        record = ScheduleRecord.model_validate(
            {key: row[key] for key in ScheduleRecord.model_fields}
        )
        template = record.template
        if (
            initial.schedule_id != record.schedule_id
            or initial.symbol != template.symbol
            or initial.exchange_mic != template.exchange_mic
            or initial.refresh != template.refresh
            or template.run_id != record.schedule_id
            or initial.interval_seconds != record.interval_seconds
            or initial.first_run_at != record.first_run_at
            or record.created_at > record.updated_at
        ):
            raise ValueError("Frozen schedule mismatch")
        enabled = initial.enabled
        commands = (
            connection.execute(
                select(sec_schedule_commands)
                .where(sec_schedule_commands.c.schedule_id == record.schedule_id)
                .order_by(sec_schedule_commands.c.revision)
            )
            .mappings()
            .all()
        )
        for revision, command_row in enumerate(commands, 1):
            command = ScheduleCommand.model_validate(command_row["payload"])
            if (
                command_row["revision"] != revision
                or command.expected_revision != revision - 1
                or command.command_id != command_row["command_id"]
            ):
                raise ValueError("Schedule command mismatch")
            enabled = command.enabled
        if len(commands) != record.revision or enabled != record.enabled:
            raise ValueError("Schedule control mismatch")
        count, maximum, skipped = connection.execute(
            select(
                func.count(),
                func.max(sec_schedule_occurrences.c.sequence),
                func.sum(sec_schedule_occurrences.c.skipped_slots),
            ).where(sec_schedule_occurrences.c.schedule_id == record.schedule_id)
        ).one()
        if count != (maximum or 0):
            raise ValueError("Schedule occurrence sequence mismatch")
        latest = (
            connection.execute(
                select(sec_schedule_occurrences)
                .where(sec_schedule_occurrences.c.schedule_id == record.schedule_id)
                .order_by(sec_schedule_occurrences.c.sequence.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        previous = _occurrence(latest) if latest is not None else None
        if previous is not None:
            if previous.scheduled_for != record.first_run_at + timedelta(
                seconds=record.interval_seconds * (count - 1 + (skipped or 0))
            ):
                raise ValueError("Schedule occurrence anchor mismatch")
            _binding(connection, previous, template)
        if previous is None:
            if (
                any(
                    value is not None
                    for value in (
                        record.last_scheduled_for,
                        record.last_outcome,
                        record.last_run_id,
                    )
                )
                or record.next_run_at != record.first_run_at
            ):
                raise ValueError("Unexpected schedule dispatch state")
        elif (
            record.last_scheduled_for != previous.scheduled_for
            or record.last_outcome != previous.outcome
            or record.last_run_id != previous.run_id
            or record.next_run_at
            != previous.scheduled_for + timedelta(seconds=record.interval_seconds)
        ):
            raise ValueError("Schedule latest dispatch mismatch")
        return record
    except (ValueError, TypeError, KeyError, OverflowError):
        raise StoreUnavailable("Schedule integrity failure") from None


class ScheduleStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def get(self, schedule_id: UUID) -> ScheduleRecord:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            return _decode(connection, _row(connection, schedule_id))

    def create(self, payload: ScheduleCreate, template: SecImportRequest) -> ScheduleRecord:
        frozen = SecImportRequest.model_validate(template.model_dump())
        checked = _normalize(payload, frozen)
        if (
            frozen.run_id != checked.schedule_id
            or frozen.symbol != checked.symbol
            or frozen.exchange_mic != checked.exchange_mic
            or frozen.refresh != checked.refresh
        ):
            raise ScheduleConflict("Schedule template identity conflict")
        with self.engine.begin() as connection:
            connection.execute(
                insert(sec_schedules)
                .values(
                    schedule_id=checked.schedule_id,
                    template=frozen.model_dump(mode="json"),
                    create_request=checked.model_dump(mode="json"),
                    interval_seconds=checked.interval_seconds,
                    first_run_at=checked.first_run_at,
                    next_run_at=checked.first_run_at,
                    enabled=checked.enabled,
                    revision=0,
                )
                .on_conflict_do_nothing(index_elements=[sec_schedules.c.schedule_id])
            )
            row = _row(connection, checked.schedule_id, True)
            if row["create_request"] != checked.model_dump(mode="json") or row[
                "template"
            ] != frozen.model_dump(mode="json"):
                raise ScheduleConflict("Frozen schedule identity conflict")
            return _decode(connection, row)

    def page(self, after_id: UUID | None = None, limit: int = 50) -> SchedulePage:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ScheduleInvalid("Invalid schedule page")
        query = select(sec_schedules).order_by(sec_schedules.c.schedule_id).limit(limit + 1)
        if after_id is not None:
            query = query.where(sec_schedules.c.schedule_id > after_id)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            rows = connection.execute(query).mappings().all()
            items = [_decode(connection, row) for row in rows[:limit]]
        return SchedulePage(
            items=items, next_after_id=items[-1].schedule_id if len(rows) > limit else None
        )

    def command(self, schedule_id: UUID, command: ScheduleCommand) -> ScheduleRecord:
        checked = ScheduleCommand.model_validate(command.model_dump())
        with self.engine.begin() as connection:
            row = _row(connection, schedule_id, True)
            record = _decode(connection, row)
            existing = (
                connection.execute(
                    select(sec_schedule_commands).where(
                        sec_schedule_commands.c.schedule_id == schedule_id,
                        sec_schedule_commands.c.command_id == checked.command_id,
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if existing["payload"] != checked.model_dump(mode="json"):
                    raise ScheduleConflict("Schedule command identity conflict")
                return record
            if record.revision != checked.expected_revision or record.revision >= 10000:
                raise ScheduleConflict("Schedule revision conflict")
            connection.execute(
                sec_schedule_commands.insert().values(
                    schedule_id=schedule_id,
                    revision=record.revision + 1,
                    command_id=checked.command_id,
                    payload=checked.model_dump(mode="json"),
                )
            )
            connection.execute(
                sec_schedules.update()
                .where(sec_schedules.c.schedule_id == schedule_id)
                .values(
                    enabled=checked.enabled,
                    revision=record.revision + 1,
                    updated_at=_now(connection),
                )
            )
            return _decode(connection, _row(connection, schedule_id))

    def occurrences(
        self, schedule_id: UUID, after_sequence: int = 0, limit: int = 50
    ) -> ScheduleOccurrencePage:
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ScheduleInvalid("Invalid occurrence page")
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            record = _decode(connection, _row(connection, schedule_id))
            rows = (
                connection.execute(
                    select(sec_schedule_occurrences)
                    .where(
                        sec_schedule_occurrences.c.schedule_id == schedule_id,
                        sec_schedule_occurrences.c.sequence > after_sequence,
                    )
                    .order_by(sec_schedule_occurrences.c.sequence)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
            try:
                items = [_occurrence(row) for row in rows[:limit]]
                if items:
                    previous = (
                        connection.execute(
                            select(sec_schedule_occurrences).where(
                                sec_schedule_occurrences.c.schedule_id == schedule_id,
                                sec_schedule_occurrences.c.sequence == items[0].sequence - 1,
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if items[0].sequence != 1 and previous is None:
                        raise ValueError("Missing occurrence predecessor")
                    anchor = (
                        record.first_run_at
                        if previous is None
                        else (
                            previous["scheduled_for"] + timedelta(seconds=record.interval_seconds)
                        )
                    )
                    expected_sequence = items[0].sequence
                    for item in items:
                        if (
                            item.sequence != expected_sequence
                            or item.scheduled_for
                            != anchor
                            + timedelta(seconds=record.interval_seconds * item.skipped_slots)
                        ):
                            raise ValueError("Historical occurrence mismatch")
                        _binding(connection, item, record.template)
                        expected_sequence += 1
                        anchor = item.scheduled_for + timedelta(seconds=record.interval_seconds)
            except (ValueError, TypeError, KeyError, OverflowError):
                raise StoreUnavailable("Schedule history integrity failure") from None
        return ScheduleOccurrencePage(
            schedule_id=schedule_id,
            items=items,
            next_after_sequence=items[-1].sequence if len(rows) > limit else None,
        )

    def dispatch_due(self, limit: int = 20) -> list[ScheduleOccurrence]:
        from alphasense.tasks import create_task

        if type(limit) is not int or not 1 <= limit <= 20:
            raise ScheduleInvalid("Invalid dispatch limit")
        dispatched = []
        for _ in range(limit):
            # One schedule/instrument per transaction avoids cross-batch advisory lock cycles.
            with self.engine.begin() as connection:
                now = _now(connection)
                row = (
                    connection.execute(
                        select(sec_schedules)
                        .where(
                            sec_schedules.c.enabled.is_(True),
                            sec_schedules.c.next_run_at <= now,
                        )
                        .order_by(sec_schedules.c.next_run_at, sec_schedules.c.schedule_id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    break
                record = _decode(connection, row)
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                    {
                        "key": "alphasense:scheduled-instrument:"
                        + str(record.template.instrument_id)
                    },
                )
                now = _now(connection)
                busy = (
                    connection.scalar(
                        select(import_tasks.c.run_id)
                        .where(
                            import_tasks.c.status.in_(("queued", "running")),
                            import_tasks.c.request["instrument_id"].astext
                            == str(record.template.instrument_id),
                        )
                        .limit(1)
                    )
                    is not None
                )
                skipped = (now - record.next_run_at) // timedelta(seconds=record.interval_seconds)
                scheduled_for = record.next_run_at + timedelta(
                    seconds=skipped * record.interval_seconds
                )
                sequence = (
                    connection.scalar(
                        select(sec_schedule_occurrences.c.sequence)
                        .where(
                            sec_schedule_occurrences.c.schedule_id == record.schedule_id,
                        )
                        .order_by(sec_schedule_occurrences.c.sequence.desc())
                        .limit(1)
                    )
                    or 0
                )
                run_id = None if busy else slot_run_id(record.schedule_id, scheduled_for)
                if run_id is not None:
                    create_task(connection, record.template.model_copy(update={"run_id": run_id}))
                occurrence = ScheduleOccurrence(
                    schedule_id=record.schedule_id,
                    sequence=sequence + 1,
                    scheduled_for=scheduled_for,
                    dispatched_at=now,
                    skipped_slots=skipped,
                    outcome="skipped_busy" if busy else "enqueued",
                    run_id=run_id,
                )
                connection.execute(
                    sec_schedule_occurrences.insert().values(**occurrence.model_dump())
                )
                connection.execute(
                    sec_schedules.update()
                    .where(sec_schedules.c.schedule_id == record.schedule_id)
                    .values(
                        next_run_at=scheduled_for + timedelta(seconds=record.interval_seconds),
                        last_scheduled_for=scheduled_for,
                        last_outcome=occurrence.outcome,
                        last_run_id=run_id,
                        updated_at=_now(connection),
                    )
                )
                _decode(connection, _row(connection, record.schedule_id))
                dispatched.append(occurrence)
        return dispatched
