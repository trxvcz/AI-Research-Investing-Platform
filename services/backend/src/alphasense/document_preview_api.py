"""Guarded local preview, independent of database and model configuration."""

from fastapi import APIRouter, HTTPException, Request, Response

from alphasense.document_preview import (
    DocumentPreviewCreate,
    DocumentPreviewInvalid,
    DocumentPreviewResult,
    preview_document,
)
from alphasense.panel_launch import verify_panel_request

router = APIRouter(prefix="/v1/panel/document-preview", tags=["document-preview"])


@router.post("")
def preview(
    payload: DocumentPreviewCreate, request: Request, response: Response
) -> DocumentPreviewResult:
    verify_panel_request(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    try:
        return preview_document(payload)
    except DocumentPreviewInvalid:
        raise HTTPException(422, detail={"code": "DOCUMENT_PREVIEW_INVALID"}) from None
