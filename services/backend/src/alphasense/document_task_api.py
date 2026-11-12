"""Local queue submission only: no document worker or model runs inside HTTP."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from alphasense.db import ReportStore, get_store
from alphasense.document_archive import (
    DocumentArchiveConflict,
    DocumentArchiveInvalid,
    DocumentArchiveNotFound,
)
from alphasense.document_archive_api import _call
from alphasense.document_task_contracts import (
    DocumentTaskCreate,
    DocumentTaskDetail,
    DocumentTaskPage,
    DocumentTaskRecord,
)
from alphasense.document_tasks import (
    DocumentTaskConflict,
    DocumentTaskInvalid,
    DocumentTaskNotFound,
    DocumentTaskStore,
)
from alphasense.panel_launch import verify_panel_request
from alphasense.report_contracts import ReportUUID

router = APIRouter(prefix="/v1/panel/document-tasks", tags=["document-tasks"])
Store = Annotated[ReportStore, Depends(get_store)]


def _tasks_call[T](action: Callable[[], T]) -> T:
    def invoke() -> T:
        try:
            return action()
        except DocumentTaskNotFound:
            raise DocumentArchiveNotFound() from None
        except DocumentTaskConflict:
            raise DocumentArchiveConflict() from None
        except DocumentTaskInvalid:
            raise DocumentArchiveInvalid() from None

    return _call(invoke)


@router.post("")
def create(payload: DocumentTaskCreate, request: Request, store: Store) -> DocumentTaskRecord:
    verify_panel_request(request)
    store.check_ready()
    return _tasks_call(lambda: DocumentTaskStore(store.engine).create(payload))


@router.get("")
def page(
    store: Store, after_id: ReportUUID | None = None, limit: Annotated[int, Query(ge=1, le=50)] = 50
) -> DocumentTaskPage:
    return _tasks_call(lambda: DocumentTaskStore(store.engine).page(after_id, limit))


@router.get("/{job_id}")
def detail(job_id: ReportUUID, store: Store) -> DocumentTaskDetail:
    return _tasks_call(lambda: DocumentTaskStore(store.engine).detail(job_id))
