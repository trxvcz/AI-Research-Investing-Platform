"""Read-only worker observations; registration is internal to worker processes."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.report_contracts import ReportUUID
from alphasense.worker_session_contracts import WorkerKind, WorkerSessionPage, WorkerSessionRecord
from alphasense.worker_sessions import WorkerSessionNotFound, WorkerSessionStore

router = APIRouter(prefix="/v1/panel/workers", tags=["worker-sessions"])
Store = Annotated[ReportStore, Depends(get_store)]


def _read[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except WorkerSessionNotFound:
        raise HTTPException(404, detail={"code": "WORKER_SESSION_NOT_FOUND"}) from None
    except SQLAlchemyError:
        raise StoreUnavailable("Worker registry unavailable") from None


@router.get("")
def page(
    store: Store,
    after_id: ReportUUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    kind: WorkerKind | None = None,
) -> WorkerSessionPage:
    return _read(lambda: WorkerSessionStore(store.engine).page(after_id, limit, kind))


@router.get("/{session_id}")
def session(session_id: ReportUUID, store: Store) -> WorkerSessionRecord:
    return _read(lambda: WorkerSessionStore(store.engine).get(session_id))
