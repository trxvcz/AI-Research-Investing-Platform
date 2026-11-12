"""Immutable report-bound AI results and a non-renewing 50 PLN reservation ledger."""

import json
import re
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, RowMapping, select, text
from sqlalchemy.exc import SQLAlchemyError

from alphasense.ai_analysis_contracts import AiAnalysisRecord, AiNarrative
from alphasense.ai_history_context import validate_history_context, validate_history_narrative
from alphasense.ai_history_contracts import AiHistoryContext, AiHistoryNarrative
from alphasense.db_schema import (
    ai_analyses,
    ai_budget_controls,
    ai_budget_reservations,
    report_revisions,
)
from alphasense.report_contracts import ReportRevision

BUDGET_SCOPE = "ai-analysis-pilot-20261111"
MAX_AUDIT_BYTES = 1024 * 1024


class AiBudgetExceeded(Exception):
    pass


class AiRequestConflict(Exception):
    pass


class AiStoreUnavailable(Exception):
    pass


def _failure(error: SQLAlchemyError) -> None:
    if getattr(getattr(error, "orig", None), "sqlstate", None) == "P5000":
        raise AiBudgetExceeded("AI budget exhausted") from None
    raise AiStoreUnavailable("AI storage unavailable") from None


def _lock(connection: Connection) -> None:
    if (
        connection.scalar(text("SELECT current_setting('transaction_isolation')"))
        != "read committed"
    ):
        raise AiStoreUnavailable("AI transaction isolation unavailable")
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
        {"scope": BUDGET_SCOPE},
    )


def _record(row: RowMapping) -> AiAnalysisRecord:
    try:
        return AiAnalysisRecord.model_validate(
            {
                key: row[key]
                for key in (
                    "request_id",
                    "report_id",
                    "revision",
                    "report_checksum",
                    "status",
                    "created_at",
                    "finished_at",
                    "model_id",
                    "prompt_version",
                    "analysis",
                    "error_code",
                    "evidence_context",
                )
            }
        )
    except (ValidationError, ValueError, TypeError, KeyError):
        raise AiStoreUnavailable("AI result integrity unavailable") from None


def _report(connection: Connection, report: ReportRevision) -> None:
    row = (
        connection.execute(
            select(report_revisions).where(report_revisions.c.revision_id == report.revision_id)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise AiRequestConflict("Unknown AI source revision")
    if (row["report_id"], row["revision"], row["checksum"], row["payload"]) != (
        report.report_id,
        report.revision,
        report.checksum,
        report.model_dump(mode="json"),
    ):
        raise AiRequestConflict("AI source revision conflict")


def _read_record(connection: Connection, row: RowMapping) -> AiAnalysisRecord:
    checked = _record(row)
    if checked.evidence_context is not None:
        try:
            payload = connection.scalar(
                select(report_revisions.c.payload).where(
                    report_revisions.c.revision_id == row["revision_id"]
                )
            )
            report = ReportRevision.model_validate(payload)
            validate_history_context(checked.evidence_context, report)
        except (ValueError, TypeError, AttributeError):
            raise AiStoreUnavailable("AI frozen source integrity unavailable") from None
    return checked


def _reserve(connection: Connection, request_id: UUID, kind: str) -> object:
    return connection.execute(
        ai_budget_reservations.insert()
        .values(request_id=request_id, scope=BUDGET_SCOPE, kind=kind, amount_grosz=100)
        .returning(ai_budget_reservations.c.created_at)
    ).scalar_one()


class AiAnalysisStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise AiStoreUnavailable("PostgreSQL required")
        self.engine = engine

    def reserve(
        self,
        request_id: UUID,
        report: ReportRevision,
        model_id: str,
        *,
        prompt_version: str = "report-synthesis-v1",
        evidence_context: AiHistoryContext | None = None,
    ) -> bool:
        try:
            checked = ReportRevision.model_validate(report.model_dump(mode="python"))
            if (
                not isinstance(request_id, UUID)
                or not isinstance(model_id, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model_id)
            ):
                raise ValueError("Invalid AI reservation")
            if prompt_version == "report-history-v2":
                if evidence_context is None:
                    raise ValueError("Missing history evidence")
                context = validate_history_context(evidence_context, checked)
                context_data = context.model_dump(mode="json")
                if len(json.dumps(context_data, ensure_ascii=False).encode()) > 256 * 1024:
                    raise ValueError("AI context is too large")
            elif prompt_version == "report-synthesis-v1" and evidence_context is None:
                context_data = None
            else:
                raise ValueError("Invalid AI prompt or evidence version")
        except (ValueError, TypeError, AttributeError):
            raise AiRequestConflict("Invalid AI reservation") from None
        try:
            with self.engine.begin() as connection:
                _lock(connection)
                _report(connection, checked)
                existing = (
                    connection.execute(
                        select(ai_budget_reservations).where(
                            ai_budget_reservations.c.request_id == request_id
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing is not None:
                    row = (
                        connection.execute(
                            select(ai_analyses).where(ai_analyses.c.request_id == request_id)
                        )
                        .mappings()
                        .first()
                    )
                    if (
                        existing["kind"] != "analysis"
                        or row is None
                        or (
                            row["report_id"],
                            row["revision_id"],
                            row["revision"],
                            row["report_checksum"],
                            row["model_id"],
                            row["prompt_version"],
                            row["evidence_context"],
                        )
                        != (
                            checked.report_id,
                            checked.revision_id,
                            checked.revision,
                            checked.checksum,
                            model_id,
                            prompt_version,
                            context_data,
                        )
                    ):
                        raise AiRequestConflict("AI request identity conflict")
                    return False
                created_at = _reserve(connection, request_id, "analysis")
                connection.execute(
                    ai_analyses.insert().values(
                        request_id=request_id,
                        revision_id=checked.revision_id,
                        report_id=checked.report_id,
                        revision=checked.revision,
                        report_checksum=checked.checksum,
                        model_id=model_id,
                        prompt_version=prompt_version,
                        evidence_context=context_data,
                        status="running",
                        created_at=created_at,
                    )
                )
                return True
        except SQLAlchemyError as error:
            _failure(error)
        raise AiStoreUnavailable("AI storage unavailable")

    def reserve_qualification(self, request_id: UUID) -> bool:
        if not isinstance(request_id, UUID):
            raise AiRequestConflict("Invalid qualification identity")
        try:
            with self.engine.begin() as connection:
                _lock(connection)
                existing = connection.execute(
                    select(ai_budget_reservations.c.kind).where(
                        ai_budget_reservations.c.request_id == request_id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    if existing != "qualification":
                        raise AiRequestConflict("AI request identity conflict")
                    return False
                _reserve(connection, request_id, "qualification")
                return True
        except SQLAlchemyError as error:
            _failure(error)
        raise AiStoreUnavailable("AI storage unavailable")

    def get(self, request_id: UUID) -> AiAnalysisRecord | None:
        try:
            with self.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(ai_analyses).where(ai_analyses.c.request_id == request_id)
                    )
                    .mappings()
                    .first()
                )
                return _read_record(connection, row) if row is not None else None
        except SQLAlchemyError as error:
            _failure(error)
        raise AiStoreUnavailable("AI storage unavailable")

    def list(self, report_id: UUID, revision: int) -> list[AiAnalysisRecord]:
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    select(ai_analyses)
                    .where(
                        ai_analyses.c.report_id == report_id,
                        ai_analyses.c.revision == revision,
                    )
                    .order_by(ai_analyses.c.created_at.desc(), ai_analyses.c.request_id.desc())
                    .limit(20)
                )
                return [_read_record(connection, row) for row in rows.mappings()]
        except SQLAlchemyError as error:
            _failure(error)
        raise AiStoreUnavailable("AI storage unavailable")

    def budget(self) -> dict[str, str]:
        try:
            with self.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(ai_budget_controls)
                        .where(ai_budget_controls.c.scope == BUDGET_SCOPE)
                        .with_for_update(read=True)
                    )
                    .mappings()
                    .one()
                )
                reserved = row["reserved_grosz"]
                # A matching aggregate also detects missing ledger rows after an invalid restore.
                ledger = connection.scalar(
                    text(
                        "SELECT COALESCE(SUM(amount_grosz),0) FROM ai_budget_reservations "
                        "WHERE scope=:scope"
                    ),
                    {"scope": BUDGET_SCOPE},
                )
                if row["budget_grosz"] != 5000 or reserved != ledger:
                    raise AiStoreUnavailable("AI budget integrity unavailable")
                return {
                    "budget_pln": "50.00",
                    "reserved_pln": f"{reserved // 100}.00",
                    "remaining_pln": f"{(5000 - reserved) // 100}.00",
                    "reservation_per_attempt_pln": "1.00",
                }
        except SQLAlchemyError as error:
            _failure(error)
        raise AiStoreUnavailable("AI storage unavailable")

    def finish(
        self,
        request_id: UUID,
        analysis: AiNarrative | AiHistoryNarrative | None,
        error_code: str | None,
        audit: dict[str, object],
    ) -> AiAnalysisRecord:
        try:
            checked: AiNarrative | AiHistoryNarrative | None = None
            if isinstance(analysis, AiHistoryNarrative):
                checked = AiHistoryNarrative.model_validate(analysis.model_dump(mode="python"))
            elif analysis is not None:
                checked = AiNarrative.model_validate(analysis.model_dump(mode="python"))
            if (checked is None) == (error_code is None) or (
                error_code is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error_code)
            ):
                raise ValueError("Invalid AI terminal state")
            if (
                not isinstance(audit, dict)
                or len(json.dumps(audit, allow_nan=False, ensure_ascii=False).encode())
                > MAX_AUDIT_BYTES
            ):
                raise ValueError("Invalid AI audit")
        except (ValueError, TypeError, AttributeError, RecursionError, UnicodeError):
            raise AiRequestConflict("Invalid AI completion") from None
        try:
            with self.engine.begin() as connection:
                row = (
                    connection.execute(
                        select(ai_analyses)
                        .where(ai_analyses.c.request_id == request_id)
                        .with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if row is None or row["status"] != "running":
                    raise AiRequestConflict("AI completion identity conflict")
                if row["prompt_version"] == "report-history-v2":
                    source = connection.scalar(
                        select(report_revisions.c.payload).where(
                            report_revisions.c.revision_id == row["revision_id"]
                        )
                    )
                    context = validate_history_context(
                        AiHistoryContext.model_validate(row["evidence_context"]),
                        ReportRevision.model_validate(source),
                    )
                    if checked is not None:
                        if not isinstance(checked, AiHistoryNarrative):
                            raise AiRequestConflict("AI narrative version conflict")
                        try:
                            checked = validate_history_narrative(context, checked.model_dump_json())
                        except ValueError:
                            raise AiRequestConflict("AI history evidence conflict") from None
                    if (
                        audit.get("context_sha256", context.context_sha256)
                        != context.context_sha256
                    ):
                        raise AiRequestConflict("AI audit context mismatch")
                    audit = {**audit, "context_sha256": context.context_sha256}
                elif checked is not None:
                    if not isinstance(checked, AiNarrative):
                        raise AiRequestConflict("AI narrative version conflict")
                    source = connection.scalar(
                        select(report_revisions.c.payload).where(
                            report_revisions.c.revision_id == row["revision_id"]
                        )
                    )
                    report = ReportRevision.model_validate(source)
                    claims = [
                        *checked.summary,
                        *checked.strengths,
                        *checked.risks,
                        *checked.questions,
                    ]
                    if any(
                        index >= len(report.input.observations)
                        or report.input.observations[index].status != "available"
                        for claim in claims
                        for index in claim.observation_indexes
                    ):
                        raise AiRequestConflict("AI evidence conflict")
                completed = (
                    connection.execute(
                        ai_analyses.update()
                        .where(ai_analyses.c.request_id == request_id)
                        .values(
                            status="completed" if checked is not None else "failed",
                            finished_at=connection.scalar(text("SELECT clock_timestamp()")),
                            analysis=checked.model_dump(mode="json")
                            if checked is not None
                            else None,
                            error_code=error_code,
                            audit=audit,
                        )
                        .returning(*ai_analyses.c)
                    )
                    .mappings()
                    .one()
                )
                return _read_record(connection, completed)
        except SQLAlchemyError as error:
            _failure(error)
        except (ValidationError, ValueError, TypeError):
            raise AiStoreUnavailable("AI source integrity unavailable") from None
        raise AiStoreUnavailable("AI storage unavailable")
