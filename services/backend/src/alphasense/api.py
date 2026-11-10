"""Local research validation and optional PostgreSQL report storage."""

import os
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from alphasense.archive_api import SnapshotBodyLimit
from alphasense.archive_api import router as archive_router
from alphasense.contracts import HealthResult, ResearchInput, ValidationResult, summarize
from alphasense.db import (
    ReportNotFound,
    ReportStore,
    RevisionConflict,
    StoreUnavailable,
    UnstorableReport,
    get_store,
)
from alphasense.document_archive_api import router as document_router
from alphasense.document_body_limit import DocumentBodyLimit
from alphasense.document_task_api import router as document_task_router
from alphasense.instrument_api import router as instrument_router
from alphasense.instruments import InstrumentConflict, InstrumentNotFound
from alphasense.legacy import InvalidReportError, ReportInspection, inspect_report
from alphasense.panel_api import router as panel_router
from alphasense.panel_launch import router as panel_launch_router
from alphasense.report_contracts import ReportRevision, ReportUUID
from alphasense.runs import RunConflict, RunNotFound
from alphasense.schedule_api import router as schedule_router
from alphasense.sec_catalog import router as sec_catalog_router
from alphasense.snapshots import SnapshotConflict, SnapshotNotFound
from alphasense.storage_contracts import RevisionPage, StoredRevisionInfo
from alphasense.task_api import router as task_router
from alphasense.worker_session_api import router as worker_session_router

app = FastAPI(
    title="AlphaSense Research API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)
app.include_router(instrument_router)
app.include_router(archive_router)
app.include_router(panel_router)
app.include_router(panel_launch_router)
app.include_router(sec_catalog_router)
app.include_router(task_router)
app.include_router(schedule_router)
app.include_router(document_router)
app.include_router(document_task_router)
app.include_router(worker_session_router)
app.add_middleware(SnapshotBodyLimit)
app.add_middleware(DocumentBodyLimit)

# Validation locations can contain arbitrary extra-field names supplied by a client.
# Keep useful known field paths without reflecting those names into the response.
_SAFE_LOCATIONS = frozenset(
    {
        "body",
        "query",
        "path",
        "schema_version",
        "instrument_id",
        "asset_type",
        "as_of",
        "data_origin",
        "observations",
        "metric",
        "unit",
        "currency",
        "period_start",
        "period_end",
        "status",
        "value",
        "source_id",
        "snapshot_id",
        "event_time",
        "available_at",
        "reason",
        "available",
        "missing",
        "not_applicable",
    }
)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
    """Do not echo client input, validator context or custom error messages."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "loc": [
                        part if isinstance(part, int) or part in _SAFE_LOCATIONS else "<field>"
                        for part in item["loc"]
                    ],
                    "type": item["type"],
                    "msg": "Invalid request data",
                }
                for item in error.errors()
            ]
        },
    )


@app.get("/health", response_model=HealthResult)
def health() -> HealthResult:
    """Liveness never opens a database connection."""
    return HealthResult(
        status="ok",
        mode="postgresql" if os.environ.get("ALPHASENSE_DATABASE_URL") else "validation-only",
        research_only=True,
        external_providers_enabled=False,
    )


@app.get("/ready", response_model=HealthResult)
def ready() -> HealthResult:
    if os.environ.get("ALPHASENSE_DATABASE_URL"):
        get_store().check_ready()
    return health()


@app.exception_handler(StoreUnavailable)
async def unavailable(_request: Request, _error: StoreUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Report storage unavailable"})


@app.exception_handler(RevisionConflict)
async def conflict(_request: Request, _error: RevisionConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Revision conflict"})


@app.exception_handler(ReportNotFound)
async def not_found(_request: Request, _error: ReportNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Report not found"})


@app.exception_handler(UnstorableReport)
async def invalid_report(_request: Request, _error: UnstorableReport) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Invalid report data"})


@app.exception_handler(InstrumentConflict)
async def instrument_conflict(_request: Request, _error: InstrumentConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Instrument conflict"})


@app.exception_handler(InstrumentNotFound)
async def instrument_not_found(_request: Request, _error: InstrumentNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Instrument not found"})


@app.exception_handler(SnapshotConflict)
async def snapshot_conflict(_request: Request, _error: SnapshotConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Snapshot conflict"})


@app.exception_handler(SnapshotNotFound)
async def snapshot_not_found(_request: Request, _error: SnapshotNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Snapshot not found"})


@app.exception_handler(RunConflict)
async def run_conflict(_request: Request, _error: RunConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Run conflict"})


@app.exception_handler(RunNotFound)
async def run_not_found(_request: Request, _error: RunNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Run not found"})


@app.post("/v1/validate", response_model=ValidationResult)
def validate(payload: ResearchInput) -> ValidationResult:
    """Validate declared observations without fetching, persisting or analyzing."""
    return summarize(payload)


@app.post("/v1/reports/inspect", response_model=ReportInspection)
def inspect(payload: dict[str, Any]) -> ReportInspection:
    """Inspect supplied JSON only; never load a client path, fetch or migrate."""
    try:
        return inspect_report(payload)
    except InvalidReportError:
        raise HTTPException(status_code=422, detail="Invalid report data") from None


StoreDependency = Annotated[ReportStore, Depends(get_store)]


@app.post(
    "/v1/reports",
    response_model=StoredRevisionInfo,
    status_code=201,
    responses={200: {"model": StoredRevisionInfo}},
)
def append_report(
    payload: ReportRevision, response: Response, store: StoreDependency
) -> StoredRevisionInfo:
    result = store.append(payload)
    response.status_code = 201 if result.created else 200
    return result


@app.get("/v1/reports/{report_id}", response_model=ReportRevision)
def latest_report(report_id: ReportUUID, store: StoreDependency) -> ReportRevision:
    return store.get_report(report_id)


@app.get("/v1/reports/{report_id}/revisions", response_model=RevisionPage)
def revisions(
    report_id: ReportUUID,
    store: StoreDependency,
    after_revision: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RevisionPage:
    return store.list_revisions(report_id, after_revision=after_revision, limit=limit)


@app.get("/v1/reports/{report_id}/revisions/{revision}", response_model=ReportRevision)
def specific_revision(
    report_id: ReportUUID, revision: Annotated[int, Path(ge=1)], store: StoreDependency
) -> ReportRevision:
    return store.get_report(report_id, revision)
