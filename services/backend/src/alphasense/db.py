"""Transactional PostgreSQL append/read operations. No implicit migrations."""

import os
from contextlib import nullcontext
from functools import lru_cache
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, RowMapping, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from alphasense.db_schema import (
    MIGRATION_HEAD,
    ai_analyses,
    ai_budget_controls,
    ai_budget_reservations,
    document_archives,
    document_reviews,
    document_task_audits,
    document_task_events,
    document_tasks,
    import_task_events,
    import_tasks,
    instruments,
    provider_quota_windows,
    raw_snapshots,
    report_revisions,
    report_streams,
    research_runs,
    run_events,
    run_snapshots,
    sec_ingestions,
    sec_schedule_commands,
    sec_schedule_occurrences,
    sec_schedules,
    worker_claims,
    worker_jobs,
    worker_sessions,
)
from alphasense.instrument_records import decode_instrument
from alphasense.report_contracts import ReportRevision
from alphasense.storage_contracts import RevisionInfo, RevisionPage, StoredRevisionInfo


class StoreUnavailable(Exception):
    """Storage configuration, connection or schema is unavailable."""


class RevisionConflict(Exception):
    """A requested append conflicts with the existing report history."""


class ReportNotFound(Exception):
    """The requested report or revision does not exist."""


class CorruptReport(StoreUnavailable):
    """Persisted payload or metadata failed integrity verification."""


class UnstorableReport(ValueError):
    """Valid envelope contains text that PostgreSQL JSONB cannot represent."""


def _contains_nul(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_nul(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


def create_postgres_engine(url: str) -> Engine:
    if not url.startswith("postgresql+psycopg://"):
        raise StoreUnavailable("PostgreSQL configuration required")
    try:
        return create_engine(
            url,
            hide_parameters=True,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000"},
        )
    except (SQLAlchemyError, ValueError):
        raise StoreUnavailable("Report storage unavailable") from None


def _decode(row: RowMapping) -> ReportRevision:
    try:
        report = ReportRevision.model_validate(row["payload"])
        expected = {
            "report_id": report.report_id,
            "revision_id": report.revision_id,
            "revision": report.revision,
            "parent_revision_id": report.parent_revision_id,
            "generated_at_utc": report.generated_at_utc,
            "checksum": report.checksum,
            "input_sha256": report.input_sha256,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise CorruptReport("Report integrity check failed")
        return report
    except (ValidationError, ValueError, TypeError, KeyError):
        raise CorruptReport("Report integrity check failed") from None


def _info(report: ReportRevision) -> RevisionInfo:
    return RevisionInfo(
        report_id=report.report_id,
        revision_id=report.revision_id,
        revision=report.revision,
        checksum=report.checksum,
        status=report.status,
        generated_at_utc=report.generated_at_utc,
    )


class ReportStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def check_ready(self) -> None:
        try:
            with self.engine.connect() as connection:
                versions = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars()
                if list(versions) != [MIGRATION_HEAD]:
                    raise StoreUnavailable("Report schema unavailable")
                connection.execute(select(report_streams.c.report_id).limit(0))
                connection.execute(select(report_revisions.c.revision_id).limit(0))
                connection.execute(select(instruments.c.instrument_id).limit(0))
                for table in (
                    ai_analyses,
                    ai_budget_controls,
                    ai_budget_reservations,
                    raw_snapshots,
                    research_runs,
                    run_snapshots,
                    run_events,
                    worker_jobs,
                    worker_claims,
                    provider_quota_windows,
                    sec_ingestions,
                    import_tasks,
                    import_task_events,
                    sec_schedules,
                    sec_schedule_commands,
                    sec_schedule_occurrences,
                    document_archives,
                    document_reviews,
                    document_tasks,
                    document_task_events,
                    document_task_audits,
                    worker_sessions,
                ):
                    connection.execute(select(table).limit(0))
        except SQLAlchemyError:
            raise StoreUnavailable("Report storage unavailable") from None

    def append(
        self, report: ReportRevision, *, connection: Connection | None = None
    ) -> StoredRevisionInfo:
        # Revalidate instances and nested mutable data before starting a transaction.
        checked = ReportRevision.model_validate(report.model_dump(mode="python"))
        payload = checked.model_dump(mode="json")
        if _contains_nul(payload):
            raise UnstorableReport("Invalid report data")
        created = False
        if connection is not None and (
            connection.engine is not self.engine or not connection.in_transaction()
        ):
            raise ValueError("Active connection from the same engine required")
        try:
            with (
                self.engine.begin() if connection is None else nullcontext(connection)
            ) as connection:
                known_stream = connection.execute(
                    select(report_streams.c.report_id)
                    .where(report_streams.c.report_id == checked.report_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if known_stream is None:
                    try:
                        candidate = UUID(checked.input.instrument_id)
                        registry_id = (
                            candidate if str(candidate) == checked.input.instrument_id else None
                        )
                    except ValueError:
                        registry_id = None
                    if registry_id is not None:
                        instrument = (
                            connection.execute(
                                select(instruments).where(
                                    instruments.c.instrument_id == registry_id
                                )
                            )
                            .mappings()
                            .one_or_none()
                        )
                        if instrument is None:
                            raise RevisionConflict("Registered instrument identity required")
                        try:
                            registered = decode_instrument(dict(instrument))
                        except (ValueError, TypeError, KeyError):
                            raise CorruptReport("Instrument integrity check failed") from None
                        if (registered.asset_type, registered.data_origin) != (
                            checked.input.asset_type,
                            checked.input.data_origin,
                        ):
                            raise RevisionConflict("Registered instrument identity required")
                    connection.execute(
                        insert(report_streams)
                        .values(
                            report_id=checked.report_id,
                            instrument_id=checked.input.instrument_id,
                            asset_type=checked.input.asset_type,
                            data_origin=checked.input.data_origin,
                            registry_instrument_id=registry_id,
                        )
                        .on_conflict_do_nothing(index_elements=["report_id"])
                    )
                stream = (
                    connection.execute(
                        select(report_streams)
                        .where(report_streams.c.report_id == checked.report_id)
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                identity = (stream["instrument_id"], stream["asset_type"], stream["data_origin"])
                if identity != (
                    checked.input.instrument_id,
                    checked.input.asset_type,
                    checked.input.data_origin,
                ):
                    raise RevisionConflict("Report identity conflict")
                existing = (
                    connection.execute(
                        select(report_revisions).where(
                            report_revisions.c.revision_id == checked.revision_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    if _decode(existing).model_dump(mode="json") != payload:
                        raise RevisionConflict("Revision identity conflict")
                else:
                    latest = (
                        connection.execute(
                            select(report_revisions)
                            .where(report_revisions.c.report_id == checked.report_id)
                            .order_by(report_revisions.c.revision.desc())
                            .limit(1)
                        )
                        .mappings()
                        .one_or_none()
                    )
                    previous = _decode(latest) if latest is not None else None
                    expected_revision = 1 if previous is None else previous.revision + 1
                    expected_parent = None if previous is None else previous.revision_id
                    if (
                        checked.revision != expected_revision
                        or checked.parent_revision_id != expected_parent
                    ):
                        raise RevisionConflict("Revision history conflict")
                    if previous and checked.generated_at_utc < previous.generated_at_utc:
                        raise RevisionConflict("Revision time conflict")
                    connection.execute(
                        report_revisions.insert().values(
                            revision_id=checked.revision_id,
                            report_id=checked.report_id,
                            revision=checked.revision,
                            parent_revision_id=checked.parent_revision_id,
                            generated_at_utc=checked.generated_at_utc,
                            checksum=checked.checksum,
                            input_sha256=checked.input_sha256,
                            payload=payload,
                        )
                    )
                    created = True
        except IntegrityError:
            raise RevisionConflict("Revision conflict") from None
        except SQLAlchemyError:
            raise StoreUnavailable("Report storage unavailable") from None
        return StoredRevisionInfo(**_info(checked).model_dump(), created=created)

    def get_report(self, report_id: UUID, revision: int | None = None) -> ReportRevision:
        query = select(report_revisions).where(report_revisions.c.report_id == report_id)
        if revision is None:
            query = query.order_by(report_revisions.c.revision.desc()).limit(1)
        else:
            if revision < 1:
                raise ValueError("revision must be positive")
            query = query.where(report_revisions.c.revision == revision)
        try:
            with self.engine.connect() as connection:
                row = connection.execute(query).mappings().one_or_none()
                if row is None:
                    raise ReportNotFound("Report not found")
                return _decode(row)
        except SQLAlchemyError:
            raise StoreUnavailable("Report storage unavailable") from None

    def list_revisions(
        self, report_id: UUID, after_revision: int = 0, limit: int = 50
    ) -> RevisionPage:
        if after_revision < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid pagination")
        try:
            with self.engine.connect() as connection:
                if (
                    connection.execute(
                        select(report_streams.c.report_id).where(
                            report_streams.c.report_id == report_id
                        )
                    ).scalar_one_or_none()
                    is None
                ):
                    raise ReportNotFound("Report not found")
                rows = (
                    connection.execute(
                        select(report_revisions)
                        .where(
                            report_revisions.c.report_id == report_id,
                            report_revisions.c.revision > after_revision,
                        )
                        .order_by(report_revisions.c.revision)
                        .limit(limit + 1)
                    )
                    .mappings()
                    .all()
                )
                # Verify even the lookahead row before reporting a next page.
                reports = [_decode(row) for row in rows]
                items = [_info(report) for report in reports[:limit]]
                cursor = items[-1].revision if len(reports) > limit else None
                return RevisionPage(items=items, next_after_revision=cursor)
        except SQLAlchemyError:
            raise StoreUnavailable("Report storage unavailable") from None


@lru_cache(maxsize=4)
def _configured_store(url: str) -> ReportStore:
    return ReportStore(create_postgres_engine(url))


def get_store() -> ReportStore:
    url = os.environ.get("ALPHASENSE_DATABASE_URL")
    if not url:
        raise StoreUnavailable("Report storage not configured")
    return _configured_store(url)
