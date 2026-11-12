"""Read-only downloads of exact report, archives and explicitly selected saved AI."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from fastapi.responses import HTMLResponse

from alphasense.ai_analysis_api import get_ai_store
from alphasense.ai_analysis_store import AiAnalysisStore, AiStoreUnavailable
from alphasense.db import ReportStore, get_store
from alphasense.financial_ratios import FinancialRatios
from alphasense.financial_ratios_api import financial_ratios
from alphasense.research_export import ResearchExport, ResearchExportInvalid, build_research_export
from alphasense.research_export_html import render_research_export_html

router = APIRouter(prefix="/v1/panel/reports", tags=["research-export"])
CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


def export_bundle(
    report_id: UUID,
    revision: Annotated[int, Path(ge=1)],
    reports: Annotated[ReportStore, Depends(get_store)],
    ratios: Annotated[FinancialRatios, Depends(financial_ratios)],
    ai_store: Annotated[AiAnalysisStore, Depends(get_ai_store)],
    ai_request_id: UUID | None = None,
) -> ResearchExport:
    report = reports.get_report(report_id, revision)
    try:
        ai = ai_store.get(ai_request_id) if ai_request_id is not None else None
    except AiStoreUnavailable:
        raise HTTPException(503, detail={"code": "EXPORT_STORAGE_UNAVAILABLE"}) from None
    if ai_request_id is not None and ai is None:
        raise HTTPException(404, detail={"code": "EXPORT_AI_NOT_FOUND"})
    if ai is not None:
        if (ai.report_id, ai.revision, ai.report_checksum) != (
            report.report_id,
            report.revision,
            report.checksum,
        ):
            raise HTTPException(409, detail={"code": "EXPORT_AI_MISMATCH"})
        if ai.status != "completed" or ai.analysis is None:
            raise HTTPException(409, detail={"code": "EXPORT_AI_NOT_COMPLETED"})
    try:
        return build_research_export(report, ratios, ai)
    except ResearchExportInvalid as error:
        raise HTTPException(409, detail={"code": error.code}) from None
    except (ValueError, TypeError):
        raise HTTPException(422, detail={"code": "EXPORT_EVIDENCE_INVALID"}) from None


def _headers(bundle: ResearchExport, extension: str) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": CSP,
        "Content-Disposition": (
            f'attachment; filename="research-{bundle.report.report_id}'
            f'-r{bundle.report.revision}.{extension}"'
        ),
    }


@router.get("/{report_id}/{revision}/research-export")
def research_export_json(
    response: Response, bundle: Annotated[ResearchExport, Depends(export_bundle)]
) -> ResearchExport:
    response.headers.update(_headers(bundle, "json"))
    return bundle


@router.get("/{report_id}/{revision}/research-export/html", response_class=HTMLResponse)
def research_export_html(bundle: Annotated[ResearchExport, Depends(export_bundle)]) -> HTMLResponse:
    return HTMLResponse(render_research_export_html(bundle), headers=_headers(bundle, "html"))
