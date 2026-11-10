"""Read-only queries and downloads for the research panel."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select, true
from sqlalchemy.exc import SQLAlchemyError

from alphasense.contracts import Contract, Timestamp
from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.db_schema import report_revisions, research_runs, run_events
from alphasense.report_contracts import ReportUUID
from alphasense.report_export import report_html
from alphasense.run_contracts import Step

router = APIRouter(prefix="/v1/panel", tags=["panel"])
Store = Annotated[ReportStore, Depends(get_store)]


class PanelRun(Contract):
    run_id: ReportUUID
    status: Literal["queued", "running", "failed", "completed"]
    current_step: Step | None
    error_reason: str | None
    report_id: ReportUUID | None
    revision: int | None
    created_at: Timestamp


class PanelRunPage(Contract):
    items: list[PanelRun]
    next_after_id: ReportUUID | None


@router.get("/runs")
def panel_runs(
    instrument_id: ReportUUID,
    store: Store,
    after_id: ReportUUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PanelRunPage:
    latest = (
        select(run_events.c.state, run_events.c.report_revision_id)
        .where(run_events.c.run_id == research_runs.c.run_id)
        .order_by(run_events.c.sequence.desc())
        .limit(1)
        .lateral()
    )
    query = (
        select(
            research_runs.c.run_id,
            research_runs.c.created_at,
            latest.c.state["status"].astext.label("status"),
            latest.c.state["current_step"].astext.label("current_step"),
            latest.c.state["error_reason"].astext.label("error_reason"),
            report_revisions.c.report_id,
            report_revisions.c.revision,
        )
        .select_from(
            research_runs.join(latest, true()).outerjoin(
                report_revisions, report_revisions.c.revision_id == latest.c.report_revision_id
            )
        )
        .where(research_runs.c.instrument_id == instrument_id)
        .order_by(research_runs.c.run_id)
        .limit(limit + 1)
    )
    if after_id is not None:
        query = query.where(research_runs.c.run_id > after_id)
    try:
        with store.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        items = [PanelRun.model_validate(dict(row)) for row in rows[:limit]]
    except (SQLAlchemyError, ValueError):
        raise StoreUnavailable("Panel storage unavailable") from None
    return PanelRunPage(items=items, next_after_id=items[-1].run_id if len(rows) > limit else None)


@router.get("/reports/{report_id}/{revision}/html", response_class=HTMLResponse)
def panel_report_html(
    report_id: ReportUUID, revision: Annotated[int, Path(ge=1)], store: Store
) -> HTMLResponse:
    report = store.get_report(report_id, revision)
    return HTMLResponse(
        report_html(report),
        headers={
            "Content-Disposition": f'attachment; filename="report-{report.revision_id}.html"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
