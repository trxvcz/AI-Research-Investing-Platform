"""Explicit owner-triggered paid synthesis with durable deduplication and budget."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from alphasense.ai_analysis import MODEL_ID, AiAnalysisDenied
from alphasense.ai_analysis_contracts import AiAnalysisCreate, AiAnalysisRecord, AiBudget
from alphasense.ai_analysis_store import (
    AiAnalysisStore,
    AiBudgetExceeded,
    AiRequestConflict,
    AiStoreUnavailable,
)
from alphasense.ai_history_analysis import (
    PROMPT_VERSION,
)
from alphasense.ai_history_analysis import (
    build_history_request as build_analysis_request,
)
from alphasense.ai_history_analysis import (
    check_history_activation as check_activation,
)
from alphasense.ai_history_analysis import (
    generate_history_analysis as generate_analysis,
)
from alphasense.ai_history_context import AiHistoryInvalid, build_history_context
from alphasense.ai_history_contracts import AiHistoryContext
from alphasense.db import ReportNotFound, ReportStore, StoreUnavailable, get_store
from alphasense.financial_history import FinancialHistoryInvalid, build_financial_history
from alphasense.financial_history_api import METRICS
from alphasense.panel_launch import verify_panel_request
from alphasense.report_contracts import ReportRevision
from alphasense.snapshots import SnapshotNotFound, SnapshotStore

router = APIRouter(prefix="/v1/panel", tags=["ai-analysis"])


def get_ai_store(store: Annotated[ReportStore, Depends(get_store)]) -> AiAnalysisStore:
    return AiAnalysisStore(store.engine)


def prepare_history_context(report: ReportRevision, reports: ReportStore) -> AiHistoryContext:
    wanted = {
        (item.source_id, item.snapshot_id)
        for item in report.input.observations
        if item.status == "available" and item.metric in METRICS
    }
    try:
        snapshots = [
            SnapshotStore(reports.engine).content(UUID(source.snapshot_id))
            for source in report.sources
            if (source.source_id, source.snapshot_id) in wanted
        ]
        return build_history_context(report, build_financial_history(report, snapshots))
    except SnapshotNotFound:
        raise StoreUnavailable("AI history archive unavailable") from None
    except (FinancialHistoryInvalid, ValueError, TypeError):
        raise AiAnalysisDenied("AI_HISTORY_UNAVAILABLE") from None


def _error(status: int, code: str) -> HTTPException:
    messages = {
        "AI_NOT_CONFIGURED": "Generowanie AI nie jest jeszcze aktywne dla tego projektu i limitu.",
        "AI_BUDGET_EXHAUSTED": "Wyczerpano limit AI. Zapisane analizy pozostają dostępne.",
        "AI_REQUEST_CONFLICT": "Ta próba należy do innego raportu. Nie wywołano modelu.",
        "AI_NO_AVAILABLE_DATA": "Brakuje dostępnych danych do analizy AI.",
        "AI_PUBLIC_SEC_DATA_REQUIRED": "Ten etap obsługuje raporty z publicznych danych SEC.",
        "AI_INPUT_TOO_LARGE": "Raport przekracza limit wejścia jednej analizy AI.",
    }
    return HTTPException(
        status,
        detail={
            "code": code,
            "message": messages.get(code, "Nie można wykonać tej operacji analizy AI."),
        },
    )


@router.get("/ai-budget")
def budget(
    response: Response, store: Annotated[AiAnalysisStore, Depends(get_ai_store)]
) -> AiBudget:
    response.headers["Cache-Control"] = "no-store"
    try:
        values = store.budget()
    except AiStoreUnavailable:
        raise _error(503, "AI_STORAGE_UNAVAILABLE") from None
    try:
        check_activation()
        enabled, reason = values["remaining_pln"] != "0.00", None
        if not enabled:
            reason = "Wyczerpano łączny limit analiz AI."
    except AiAnalysisDenied:
        enabled, reason = False, "Generowanie AI oczekuje na konfigurację i odbiór jakości."
    return AiBudget.model_validate({**values, "enabled": enabled, "reason": reason})


@router.get("/ai-analyses")
def analyses(
    report_id: UUID,
    response: Response,
    revision: Annotated[int, Query(ge=1)],
    store: Annotated[AiAnalysisStore, Depends(get_ai_store)],
) -> list[AiAnalysisRecord]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return store.list(report_id, revision)
    except AiStoreUnavailable:
        raise _error(503, "AI_STORAGE_UNAVAILABLE") from None


@router.get("/ai-analyses/{request_id}")
def analysis(
    request_id: UUID,
    response: Response,
    store: Annotated[AiAnalysisStore, Depends(get_ai_store)],
) -> AiAnalysisRecord:
    response.headers["Cache-Control"] = "no-store"
    try:
        saved = store.get(request_id)
    except AiStoreUnavailable:
        raise _error(503, "AI_STORAGE_UNAVAILABLE") from None
    if saved is None:
        raise _error(404, "AI_ANALYSIS_NOT_FOUND")
    return saved


@router.post("/ai-analyses")
def create_analysis(
    payload: AiAnalysisCreate,
    request: Request,
    response: Response,
    reports: Annotated[ReportStore, Depends(get_store)],
    store: Annotated[AiAnalysisStore, Depends(get_ai_store)],
) -> AiAnalysisRecord:
    verify_panel_request(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        report = reports.get_report(payload.report_id, payload.revision)
        existing = store.get(payload.request_id)
        if existing is not None:
            if (existing.report_id, existing.revision, existing.report_checksum) != (
                report.report_id,
                report.revision,
                report.checksum,
            ):
                raise AiRequestConflict()
            return existing
        check_activation()
        if report.input.data_origin != "live":
            raise AiAnalysisDenied("AI_PUBLIC_SEC_DATA_REQUIRED")
        context = prepare_history_context(report, reports)
        prompt = build_analysis_request(report, context)
        if not store.reserve(
            payload.request_id,
            report,
            MODEL_ID,
            prompt_version=PROMPT_VERSION,
            evidence_context=context,
        ):
            saved = store.get(payload.request_id)
            if saved is None:
                raise AiStoreUnavailable()
            return saved
    except ReportNotFound:
        raise _error(404, "AI_REPORT_NOT_FOUND") from None
    except AiBudgetExceeded:
        raise _error(409, "AI_BUDGET_EXHAUSTED") from None
    except AiRequestConflict:
        raise _error(409, "AI_REQUEST_CONFLICT") from None
    except (StoreUnavailable, AiStoreUnavailable):
        raise _error(503, "AI_STORAGE_UNAVAILABLE") from None
    except AiAnalysisDenied as error:
        raise _error(422, error.code) from None
    except AiHistoryInvalid as error:
        raise _error(422, error.code) from None
    # Reservation is committed; failures remain charged against the application cap.
    try:
        check_activation()
        narrative, audit = generate_analysis(report, context, prompt)
        return store.finish(payload.request_id, narrative, None, audit)
    except AiAnalysisDenied as error:
        try:
            return store.finish(
                payload.request_id,
                None,
                error.code,
                error.audit or {"usage": None, "error_code": error.code},
            )
        except (AiStoreUnavailable, AiRequestConflict):
            raise _error(503, "AI_STORAGE_UNAVAILABLE") from None
    except (AiStoreUnavailable, AiRequestConflict):
        # Never repeat an uncertain paid invocation, even if persisting it failed.
        raise _error(503, "AI_STORAGE_UNAVAILABLE") from None
