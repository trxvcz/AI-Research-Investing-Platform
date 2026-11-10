"""Guarded local controls for schedules; HTTP never dispatches or fetches SEC."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.panel_launch import (
    PanelAnalysisRequest,
    resolve_analysis_request,
    verify_panel_request,
)
from alphasense.report_contracts import ReportUUID
from alphasense.schedule_contracts import (
    ScheduleCommand,
    ScheduleCreate,
    ScheduleOccurrencePage,
    SchedulePage,
    ScheduleRecord,
)
from alphasense.sec_schedules import (
    ScheduleConflict,
    ScheduleInvalid,
    ScheduleNotFound,
    ScheduleStore,
)

router = APIRouter(prefix="/v1/panel/schedules", tags=["sec-schedules"])
Store = Annotated[ReportStore, Depends(get_store)]


def _call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except ScheduleNotFound:
        raise HTTPException(404, detail={"code": "SCHEDULE_NOT_FOUND"}) from None
    except ScheduleConflict:
        raise HTTPException(409, detail={"code": "SCHEDULE_CONFLICT"}) from None
    except ScheduleInvalid:
        raise HTTPException(422, detail={"code": "SCHEDULE_INVALID"}) from None
    except SQLAlchemyError:
        raise StoreUnavailable("Schedule storage unavailable") from None


@router.post("")
def create(payload: ScheduleCreate, request: Request, store: Store) -> ScheduleRecord:
    verify_panel_request(request)
    store.check_ready()
    schedules = ScheduleStore(store.engine)

    def execute() -> ScheduleRecord:
        try:
            existing = schedules.get(payload.schedule_id)
        except ScheduleNotFound:
            existing = None
        if existing is not None:
            return schedules.create(payload, existing.template)
        if payload.exchange_mic == "XWAR":
            raise HTTPException(422, detail={"code": "UNSUPPORTED_MARKET"})
        template = resolve_analysis_request(
            PanelAnalysisRequest(symbol=payload.symbol, run_id=payload.schedule_id), store
        )
        if payload.exchange_mic is not None and payload.exchange_mic != template.exchange_mic:
            raise HTTPException(422, detail={"code": "MARKET_IDENTITY_CONFLICT"})
        template = template.model_copy(update={"refresh": payload.refresh})
        return schedules.create(payload, template)

    return _call(execute)


@router.get("")
def page(
    store: Store, after_id: ReportUUID | None = None, limit: Annotated[int, Query(ge=1, le=50)] = 50
) -> SchedulePage:
    return _call(lambda: ScheduleStore(store.engine).page(after_id, limit))


@router.post("/{schedule_id}/commands")
def command(
    schedule_id: ReportUUID, payload: ScheduleCommand, request: Request, store: Store
) -> ScheduleRecord:
    verify_panel_request(request)
    store.check_ready()
    return _call(lambda: ScheduleStore(store.engine).command(schedule_id, payload))


@router.get("/{schedule_id}")
def get(schedule_id: ReportUUID, store: Store) -> ScheduleRecord:
    return _call(lambda: ScheduleStore(store.engine).get(schedule_id))


@router.get("/{schedule_id}/occurrences")
def occurrences(
    schedule_id: ReportUUID,
    store: Store,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> ScheduleOccurrencePage:
    return _call(
        lambda: ScheduleStore(store.engine).occurrences(schedule_id, after_sequence, limit)
    )
