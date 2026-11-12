"""Queue API; enqueue never invokes a provider or research worker."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.panel_launch import (
    PanelAnalysisRequest,
    resolve_analysis_request,
    verify_panel_request,
)
from alphasense.report_contracts import ReportUUID
from alphasense.runs import RunConflict, RunNotFound
from alphasense.task_contracts import ImportTaskEventPage, TaskCreate, TaskPage, TaskRecord
from alphasense.tasks import TaskStore

router = APIRouter(prefix="/v1/panel/tasks", tags=["tasks"])
Store = Annotated[ReportStore, Depends(get_store)]


@router.post("")
def enqueue(payload: TaskCreate, request: Request, response: Response, store: Store) -> TaskRecord:
    verify_panel_request(request)
    store.check_ready()
    tasks = TaskStore(store.engine)
    try:
        try:
            existing = tasks.get(payload.run_id)
        except RunNotFound:
            existing = None
        if existing is not None:
            if existing.symbol != payload.symbol.strip().upper() or (
                payload.exchange_mic is not None and payload.exchange_mic != existing.exchange_mic
            ):
                raise RunConflict("Frozen task identity conflict")
            return existing
        if payload.exchange_mic == "XWAR":
            raise HTTPException(
                422,
                detail={
                    "code": "UNSUPPORTED_MARKET",
                    "message": "Adapter GPW jest niedostępny. Nie pobrano danych.",
                },
            )
        frozen = resolve_analysis_request(
            PanelAnalysisRequest(symbol=payload.symbol, run_id=payload.run_id), store
        )
        if payload.exchange_mic is not None and payload.exchange_mic != frozen.exchange_mic:
            raise HTTPException(
                422,
                detail={
                    "code": "MARKET_IDENTITY_CONFLICT",
                    "message": "Wybrany rynek nie odpowiada instrumentowi z katalogu.",
                },
            )
        result = tasks.create(frozen)
        response.status_code = 202
        return result
    except SQLAlchemyError:
        raise StoreUnavailable("Task storage unavailable") from None


@router.get("")
def task_page(
    store: Store,
    after_id: ReportUUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TaskPage:
    try:
        return TaskStore(store.engine).page(after_id, limit)
    except SQLAlchemyError:
        raise StoreUnavailable("Task storage unavailable") from None


@router.get("/{run_id}")
def task(run_id: ReportUUID, store: Store) -> TaskRecord:
    try:
        return TaskStore(store.engine).get(run_id)
    except SQLAlchemyError:
        raise StoreUnavailable("Task storage unavailable") from None


@router.get("/{run_id}/events")
def events(
    run_id: ReportUUID,
    store: Store,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> ImportTaskEventPage:
    try:
        return TaskStore(store.engine).history(run_id, after_sequence, limit)
    except SQLAlchemyError:
        raise StoreUnavailable("Task history unavailable") from None
