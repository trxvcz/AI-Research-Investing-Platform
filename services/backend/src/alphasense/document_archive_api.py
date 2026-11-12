"""Local offline archive API; no source fetching or model inference."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.document_archive import (
    DocumentArchiveConflict,
    DocumentArchiveInvalid,
    DocumentArchiveNotFound,
    DocumentArchiveStore,
)
from alphasense.document_archive_contracts import (
    DocumentArchiveCreate,
    DocumentArchivePage,
    DocumentArchiveRecord,
    DocumentReviewCommand,
    DocumentReviewEvent,
)
from alphasense.panel_launch import verify_panel_request
from alphasense.report_contracts import ReportUUID

router = APIRouter(prefix="/v1/panel/documents", tags=["documents"])
Store = Annotated[ReportStore, Depends(get_store)]


def _call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except DocumentArchiveNotFound:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND"}) from None
    except DocumentArchiveConflict:
        raise HTTPException(409, detail={"code": "DOCUMENT_CONFLICT"}) from None
    except DocumentArchiveInvalid:
        raise HTTPException(422, detail={"code": "DOCUMENT_INVALID"}) from None
    except SQLAlchemyError:
        raise StoreUnavailable("Document storage unavailable") from None


@router.post("")
def create(payload: DocumentArchiveCreate, request: Request, store: Store) -> DocumentArchiveRecord:
    verify_panel_request(request)
    store.check_ready()
    return _call(lambda: DocumentArchiveStore(store.engine).create(payload))


@router.get("")
def page(
    store: Store,
    after_id: ReportUUID | None = None,
    instrument_id: ReportUUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> DocumentArchivePage:
    return _call(lambda: DocumentArchiveStore(store.engine).page(after_id, limit, instrument_id))


@router.get("/{archive_id}")
def get(archive_id: ReportUUID, store: Store) -> DocumentArchiveRecord:
    return _call(lambda: DocumentArchiveStore(store.engine).get(archive_id))


@router.post("/{archive_id}/reviews")
def review(
    archive_id: ReportUUID, payload: DocumentReviewCommand, request: Request, store: Store
) -> DocumentReviewEvent:
    verify_panel_request(request)
    store.check_ready()
    return _call(lambda: DocumentArchiveStore(store.engine).review(archive_id, payload))


@router.get("/{archive_id}/content")
def content(archive_id: ReportUUID, store: Store) -> Response:
    raw = _call(lambda: DocumentArchiveStore(store.engine).content(archive_id))
    return Response(
        raw,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="document-{archive_id}.bin"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
