"""PostgreSQL queue: run-first locking, expiring ownership and fenced commits."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Connection, Engine, RowMapping, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.db_schema import research_runs, worker_claims, worker_jobs
from alphasense.report_contracts import ReportRevision, ReportUUID
from alphasense.run_contracts import (
    RunAdvance,
    RunCommand,
    RunEvent,
    RunEventWrite,
    RunFail,
    RunFinish,
    RunResume,
    RunStart,
)
from alphasense.runs import (
    RunConflict,
    RunNotFound,
    _Context,
    _context,
    _insert_event,
    _latest,
    _run_row,
    _transition,
)
from alphasense.worker_contracts import WorkerJobRecord, WorkerLease


class WorkerLeaseLost(RunConflict):
    """The caller no longer owns a live lease; its transaction must roll back."""


def _now(connection: Connection) -> datetime:
    return connection.execute(text("SELECT clock_timestamp()")).scalar_one()  # type: ignore[no-any-return]


def _job(connection: Connection, run_id: UUID) -> RowMapping:
    row = (
        connection.execute(
            select(worker_jobs).where(worker_jobs.c.run_id == run_id).with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise WorkerLeaseLost("Worker lease unavailable")
    return row


def _fence(connection: Connection, lease: WorkerLease, row: RowMapping) -> None:
    if (
        row["status"] != "running"
        or row["lease_token"] != lease.token
        or row["worker_id"] != lease.worker_id
        or row["attempts"] != lease.attempt
        or row["implementation_hash"] != lease.implementation_hash
        or row["pipeline_git_sha"] != lease.pipeline_git_sha
        or row["lease_expires_at"] is None
        or row["lease_expires_at"] <= _now(connection)
    ):
        raise WorkerLeaseLost("Worker lease unavailable")


def _event(connection: Connection, context: _Context, command: RunCommand) -> RunEventWrite:
    state = _latest(connection, context).state
    now = _now(connection)
    updated = _transition(connection, context, state, command, now)
    event = RunEvent(
        run_id=state.run_id,
        event_id=command.request_id,
        sequence=updated.sequence,
        kind=command.action,
        request=command,
        state=updated,
        created_at=now,
    )
    _insert_event(connection, event)
    return RunEventWrite(**event.model_dump(), created=True)


class WorkerStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    @contextmanager
    def _owned(
        self, lease: WorkerLease, *, terminal: str | None = None, code: str | None = None
    ) -> Iterator[tuple[Connection, _Context, RowMapping]]:
        lease = WorkerLease.model_validate(lease.model_dump())
        try:
            with self.engine.begin() as connection:
                context = _context(connection, _run_row(connection, lease.run_id, lock=True))
                row = _job(connection, lease.run_id)
                _fence(connection, lease, row)
                yield connection, context, row
                # The original expiry remains authoritative for this transaction, including
                # renewal. A pause past it must roll back rather than resurrect an expired lease.
                _fence(connection, lease, row)
                if terminal is not None:
                    status = terminal
                    if terminal == "result":
                        status = (
                            "dead"
                            if _latest(connection, context).state.status == "failed"
                            else "completed"
                        )
                    self._terminal(connection, lease.run_id, status, code)
        except SQLAlchemyError:
            raise StoreUnavailable("Worker storage unavailable") from None

    def claim(
        self,
        worker_id: str,
        implementation_hash: str,
        git_sha: str,
        lease_seconds: int = 60,
        *,
        run_id: UUID | None = None,
    ) -> WorkerLease | None:
        if type(lease_seconds) is not int or not 15 <= lease_seconds <= 300:
            raise ValueError("Lease must be 15 to 300 seconds")
        # Validate all caller-controlled fields even if the queue is empty.
        candidate = WorkerLease(
            run_id=uuid4(),
            worker_id=worker_id,
            token=uuid4(),
            attempt=1,
            expires_at=datetime.now().astimezone(),
            implementation_hash=implementation_hash,
            pipeline_git_sha=git_sha,
        )
        try:
            with self.engine.begin() as connection:
                # Candidate filter is advisory; ownership is rechecked after acquiring run lock.
                query = (
                    select(research_runs)
                    .outerjoin(worker_jobs)
                    .where(
                        research_runs.c.definition["pipeline_version"].astext.in_(
                            (
                                "deterministic-research-v1",
                                "sec-fundamentals-v1",
                                "sec-fundamentals-v2",
                            )
                        ),
                        or_(
                            worker_jobs.c.run_id.is_(None),
                            worker_jobs.c.status == "queued",
                            (worker_jobs.c.status == "running")
                            & (worker_jobs.c.lease_expires_at <= text("clock_timestamp()")),
                        ),
                    )
                    .order_by(research_runs.c.created_at, research_runs.c.run_id)
                    .with_for_update(skip_locked=True, of=research_runs)
                    .limit(1)
                )
                if run_id is not None:
                    checked_id = TypeAdapter(ReportUUID).validate_python(run_id)
                    query = query.where(research_runs.c.run_id == checked_id)
                run = connection.execute(query).mappings().one_or_none()
                if run is None:
                    return None
                context = _context(connection, run)
                state = _latest(connection, context).state
                now = _now(connection)
                row = (
                    connection.execute(
                        select(worker_jobs)
                        .where(worker_jobs.c.run_id == state.run_id)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    connection.execute(
                        worker_jobs.insert().values(
                            run_id=state.run_id,
                            status="queued",
                            attempts=0,
                            implementation_hash=implementation_hash,
                            pipeline_git_sha=git_sha,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    row = _job(connection, state.run_id)
                if row["status"] in ("completed", "dead"):
                    return None
                if row["lease_expires_at"] is not None and row["lease_expires_at"] > now:
                    return None
                code = None
                if row["attempts"] >= 3:
                    code = "WORKER_ATTEMPTS_EXHAUSTED"
                elif (row["implementation_hash"], row["pipeline_git_sha"]) != (
                    implementation_hash,
                    git_sha,
                ):
                    code = "WORKER_CODE_CHANGED"
                if state.report_revision_id is not None:
                    self._terminal(
                        connection,
                        state.run_id,
                        "dead" if state.status == "failed" else "completed",
                        code,
                    )
                    return None
                if code is not None:
                    if state.status == "running":
                        assert state.current_step is not None
                        _event(
                            connection,
                            context,
                            RunFail(
                                action="fail",
                                request_id=uuid4(),
                                expected_sequence=state.sequence,
                                actor=worker_id,
                                step=state.current_step,
                                error_code=code,
                                reason="Worker recovery cannot continue this immutable run",
                            ),
                        )
                    self._terminal(connection, state.run_id, "dead", code)
                    return None
                attempt = row["attempts"] + 1
                token = uuid4()
                expires = now + timedelta(seconds=lease_seconds)
                connection.execute(
                    worker_jobs.update()
                    .where(worker_jobs.c.run_id == state.run_id)
                    .values(
                        status="running",
                        attempts=attempt,
                        worker_id=worker_id,
                        lease_token=token,
                        lease_expires_at=expires,
                        updated_at=now,
                    )
                )
                connection.execute(
                    worker_claims.insert().values(
                        run_id=state.run_id,
                        attempt=attempt,
                        lease_token=token,
                        worker_id=worker_id,
                        implementation_hash=implementation_hash,
                        pipeline_git_sha=git_sha,
                        claimed_at=now,
                        initial_expires_at=expires,
                    )
                )
                if state.status in ("queued", "failed"):
                    command: RunCommand = (
                        RunStart(
                            action="start",
                            request_id=uuid4(),
                            expected_sequence=state.sequence,
                            actor=worker_id,
                        )
                        if state.status == "queued"
                        else RunResume(
                            action="resume",
                            request_id=uuid4(),
                            expected_sequence=state.sequence,
                            actor=worker_id,
                        )
                    )
                    _event(connection, context, command)
                lease = candidate.model_copy(
                    update=dict(
                        run_id=state.run_id,
                        token=token,
                        attempt=attempt,
                        expires_at=expires,
                    )
                )
                _fence(connection, lease, _job(connection, state.run_id))
                return lease
        except SQLAlchemyError:
            raise StoreUnavailable("Worker storage unavailable") from None

    def renew(self, lease: WorkerLease) -> WorkerLease:
        with self._owned(lease) as (connection, _context_value, row):
            # Preserve the original lease duration, bounded by the contract.
            claim = (
                connection.execute(
                    select(worker_claims).where(
                        worker_claims.c.run_id == lease.run_id,
                        worker_claims.c.attempt == lease.attempt,
                    )
                )
                .mappings()
                .one()
            )
            duration = claim["initial_expires_at"] - claim["claimed_at"]
            expiry = _now(connection) + duration
            connection.execute(
                worker_jobs.update()
                .where(worker_jobs.c.run_id == lease.run_id)
                .values(lease_expires_at=expiry, updated_at=_now(connection))
            )
            return lease.model_copy(update={"expires_at": expiry})

    def apply(self, lease: WorkerLease, command: RunCommand) -> RunEventWrite:
        checked = TypeAdapter(RunCommand).validate_python(command.model_dump())
        if checked.actor != lease.worker_id or not isinstance(checked, RunAdvance):
            raise RunConflict("Worker command requires an advance by its owner")
        if checked.step == "report":
            raise RunConflict("Report advancement requires atomic publication")
        with self._owned(lease) as (connection, context, _row):
            return _event(connection, context, checked)

    def publish(
        self, lease: WorkerLease, report: ReportRevision, command: RunAdvance
    ) -> RunEventWrite:
        if command.step != "report" or command.actor != lease.worker_id:
            raise RunConflict("Invalid report publication command")
        with self._owned(lease) as (connection, context, _row):
            ReportStore(self.engine).append(report, connection=connection)
            # Validate provenance before accepting a publication, not just at finish.
            from alphasense.runs import _final_report

            _final_report(connection, context, report.revision_id)
            return _event(connection, context, command)

    def _terminal(
        self, connection: Connection, run_id: UUID, status: str, code: str | None
    ) -> None:
        connection.execute(
            worker_jobs.update()
            .where(worker_jobs.c.run_id == run_id)
            .values(
                status=status,
                lease_token=None,
                lease_expires_at=None,
                last_error_code=code,
                updated_at=_now(connection),
            )
        )

    def fail(self, lease: WorkerLease, code: str, reason: str) -> None:
        with self._owned(lease, terminal="dead", code=code) as (connection, context, _row):
            state = _latest(connection, context).state
            if state.current_step is None:
                raise RunConflict("Research run is terminal")
            _event(
                connection,
                context,
                RunFail(
                    action="fail",
                    request_id=uuid4(),
                    expected_sequence=state.sequence,
                    actor=lease.worker_id,
                    step=state.current_step,
                    error_code=code,
                    reason=reason,
                ),
            )

    def finish(self, lease: WorkerLease, command: RunFinish) -> RunEventWrite:
        if command.actor != lease.worker_id:
            raise RunConflict("Invalid worker owner")
        with self._owned(lease, terminal="result") as (connection, context, _row):
            return _event(connection, context, command)

    def get_job(self, run_id: UUID) -> WorkerJobRecord:
        try:
            with self.engine.connect() as connection:
                row = (
                    connection.execute(select(worker_jobs).where(worker_jobs.c.run_id == run_id))
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise RunNotFound("Worker job not found")
                return WorkerJobRecord.model_validate(
                    {name: row[name] for name in WorkerJobRecord.model_fields}
                )
        except (SQLAlchemyError, ValidationError, ValueError, TypeError, KeyError):
            raise StoreUnavailable("Worker storage unavailable") from None


def get_worker_store() -> WorkerStore:
    return WorkerStore(get_store().engine)
