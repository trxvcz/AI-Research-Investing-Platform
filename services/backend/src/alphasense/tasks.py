"""PostgreSQL queue. Each command is durable before the first external request."""

from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import StoreUnavailable
from alphasense.db_schema import import_task_events, import_tasks
from alphasense.runs import RunConflict, RunNotFound
from alphasense.sec_contracts import SecImportRequest
from alphasense.task_contracts import ImportTaskEvent, ImportTaskEventPage, TaskPage, TaskRecord


class TaskLeaseLost(Exception):
    pass


def record(row: RowMapping) -> TaskRecord:
    try:
        data = dict(row)
        frozen = SecImportRequest.model_validate(data["request"])
        if frozen.run_id != data["run_id"] or frozen.symbol != data["symbol"]:
            raise ValueError("Frozen task identity mismatch")
        data["exchange_mic"] = frozen.exchange_mic
        return TaskRecord.model_validate({k: data[k] for k in TaskRecord.model_fields})
    except (ValueError, TypeError, KeyError):
        raise StoreUnavailable("Task integrity failure") from None


def meaningful(task: TaskRecord) -> tuple[object, ...]:
    return tuple(
        getattr(task, name)
        for name in (
            "status",
            "stage",
            "attempt",
            "worker_id",
            "error_code",
            "error_reason",
            "instrument_id",
            "report_id",
            "revision",
        )
    )


def create_task(connection: Connection, request: SecImportRequest) -> TaskRecord:
    """Insert within the caller's transaction, including scheduler dispatch receipts."""
    checked = SecImportRequest.model_validate(request.model_dump())
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "alphasense:scheduled-instrument:" + str(checked.instrument_id)},
    )
    connection.execute(
        insert(import_tasks)
        .values(
            run_id=checked.run_id,
            symbol=checked.symbol,
            request=checked.model_dump(mode="json"),
            status="queued",
            stage="queued",
            attempt=0,
        )
        .on_conflict_do_nothing(index_elements=[import_tasks.c.run_id])
    )
    row = (
        connection.execute(
            select(import_tasks).where(import_tasks.c.run_id == checked.run_id).with_for_update()
        )
        .mappings()
        .one()
    )
    if row["request"] != checked.model_dump(mode="json"):
        raise RunConflict("Frozen task identity conflict")
    return record(row)


class TaskStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, run_id: UUID) -> TaskRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(import_tasks).where(import_tasks.c.run_id == run_id))
                .mappings()
                .first()
            )
        if row is None:
            raise RunNotFound("Task not found")
        return record(row)

    def create(self, request: SecImportRequest) -> TaskRecord:
        with self.engine.begin() as connection:
            return create_task(connection, request)

    def history(
        self, run_id: UUID, after_sequence: int = 0, limit: int = 100
    ) -> ImportTaskEventPage:
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("Invalid task history page")
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            current_row = (
                connection.execute(select(import_tasks).where(import_tasks.c.run_id == run_id))
                .mappings()
                .first()
            )
            if current_row is None:
                raise RunNotFound("Task not found")
            current = record(current_row)
            rows = (
                connection.execute(
                    select(import_task_events)
                    .where(import_task_events.c.run_id == run_id)
                    .order_by(import_task_events.c.sequence)
                    .limit(10001)
                )
                .mappings()
                .all()
            )
            try:
                if not rows or len(rows) > 10000:
                    raise ValueError("Missing or excessive history")
                events: list[ImportTaskEvent] = []
                for sequence, row in enumerate(rows, 1):
                    event = ImportTaskEvent(
                        run_id=row["run_id"],
                        sequence=row["sequence"],
                        kind=row["kind"],
                        recorded_at=row["recorded_at"],
                        task=row["payload"],
                    )
                    if (
                        event.sequence != sequence
                        or event.run_id != run_id
                        or event.task.run_id != run_id
                    ):
                        raise ValueError("History sequence mismatch")
                    if (event.task.symbol, event.task.exchange_mic, event.task.created_at) != (
                        current.symbol,
                        current.exchange_mic,
                        current.created_at,
                    ):
                        raise ValueError("History identity mismatch")
                    if sequence > 1 and (
                        event.kind != "transition" or event.recorded_at < events[-1].recorded_at
                    ):
                        raise ValueError("History chronology mismatch")
                    events.append(event)
                first = events[0]
                if first.kind not in {"created", "legacy_snapshot"}:
                    raise ValueError("History origin missing")
                if first.kind == "created" and (
                    first.task.status != "queued"
                    or first.task.stage != "queued"
                    or first.task.attempt != 0
                ):
                    raise ValueError("Invalid creation history")
                if meaningful(events[-1].task) != meaningful(current):
                    raise ValueError("History current state mismatch")
            except (ValueError, TypeError, KeyError):
                raise StoreUnavailable("Task history integrity failure") from None
        selected = [event for event in events if event.sequence > after_sequence]
        return ImportTaskEventPage(
            run_id=run_id,
            coverage="complete" if first.kind == "created" else "legacy_snapshot",
            items=selected[:limit],
            next_after_sequence=selected[limit - 1].sequence if len(selected) > limit else None,
        )

    def page(self, after_id: UUID | None = None, limit: int = 50) -> TaskPage:
        query = select(import_tasks).order_by(import_tasks.c.run_id).limit(limit + 1)
        if after_id is not None:
            query = query.where(import_tasks.c.run_id > after_id)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        items = [record(row) for row in rows[:limit]]
        return TaskPage(items=items, next_after_id=items[-1].run_id if len(rows) > limit else None)

    def claim(
        self, worker_id: str, lease_seconds: int = 120
    ) -> tuple[UUID, SecImportRequest] | None:
        if not 15 <= lease_seconds <= 300 or not 1 <= len(worker_id) <= 128:
            raise ValueError("Invalid lease configuration")
        with self.engine.begin() as connection:
            now = connection.scalar(text("SELECT clock_timestamp()"))
            row = (
                connection.execute(
                    select(import_tasks)
                    .where(
                        or_(
                            import_tasks.c.status == "queued",
                            (import_tasks.c.status == "running")
                            & (import_tasks.c.lease_expires_at <= now),
                        )
                    )
                    .order_by(import_tasks.c.created_at, import_tasks.c.run_id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            if row["attempt"] >= 3:
                connection.execute(
                    import_tasks.update()
                    .where(import_tasks.c.run_id == row["run_id"])
                    .values(
                        status="failed",
                        stage="failed",
                        error_code="RECOVERY_EXHAUSTED",
                        error_reason="Przekroczono limit odzyskiwania przerwanego zadania.",
                        lease_token=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                return None
            token = uuid4()
            connection.execute(
                import_tasks.update()
                .where(import_tasks.c.run_id == row["run_id"])
                .values(
                    status="running",
                    stage="import",
                    attempt=row["attempt"] + 1,
                    lease_token=token,
                    worker_id=worker_id,
                    heartbeat_at=now,
                    lease_expires_at=text(
                        f"clock_timestamp() + INTERVAL '{lease_seconds} seconds'"
                    ),
                    updated_at=now,
                )
            )
            return token, SecImportRequest.model_validate(row["request"])

    def change(self, run_id: UUID, token: UUID, **values: object) -> None:
        try:
            with self.engine.begin() as connection:
                now = connection.scalar(text("SELECT clock_timestamp()"))
                result = connection.execute(
                    import_tasks.update()
                    .where(
                        import_tasks.c.run_id == run_id,
                        import_tasks.c.status == "running",
                        import_tasks.c.lease_token == token,
                        import_tasks.c.lease_expires_at > now,
                    )
                    .values(**values, updated_at=now)
                )
                if result.rowcount != 1:
                    raise TaskLeaseLost()
        except SQLAlchemyError:
            raise StoreUnavailable("Task storage unavailable") from None

    def heartbeat(self, run_id: UUID, token: UUID) -> None:
        self.change(
            run_id,
            token,
            heartbeat_at=text("clock_timestamp()"),
            lease_expires_at=text("clock_timestamp() + INTERVAL '120 seconds'"),
        )

    def finish(
        self, run_id: UUID, token: UUID, *, instrument_id: UUID, report_id: UUID, revision: int
    ) -> None:
        self.change(
            run_id,
            token,
            status="completed",
            stage="completed",
            lease_token=None,
            lease_expires_at=None,
            instrument_id=instrument_id,
            report_id=report_id,
            revision=revision,
        )

    def fail(self, run_id: UUID, token: UUID, code: str, reason: str) -> None:
        self.change(
            run_id,
            token,
            status="failed",
            stage="failed",
            lease_token=None,
            lease_expires_at=None,
            error_code=code,
            error_reason=reason,
        )
