"""Explicit synchronous panel launch; persisted runs remain retryable by the same UUID.

Import failures before run creation may leave trusted raw snapshots but no run.
There is no background scheduler and no automatic retry after transport failure.
"""

import os
import subprocess
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from alphasense.contracts import Contract
from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.db_schema import report_revisions
from alphasense.instruments import InstrumentStore
from alphasense.panel_boundary import panel_request_allowed
from alphasense.provider_policy import ProviderDenied, load_policy
from alphasense.report_contracts import ReportUUID
from alphasense.runs import ResearchStore, RunConflict, RunNotFound
from alphasense.sec_catalog import CatalogError, resolve_symbol
from alphasense.sec_contracts import (
    SEC_PIPELINE,
    SEC_PIPELINE_V2,
    SEC_SOURCE_IDS,
    RevenueConcept,
    SecImportRequest,
)
from alphasense.sec_fundamentals import SecInputError
from alphasense.sec_import import SecImporter
from alphasense.sec_receipts import _request_for_url
from alphasense.sec_transport import SecResponse, SecTransport, SecTransportError
from alphasense.snapshots import SnapshotStore
from alphasense.worker import current_git_sha, implementation_fingerprint, process_once

router = APIRouter(prefix="/v1/panel", tags=["panel"])

# Small explicit pilot catalog, still verified against SEC submissions on import.
CATALOG = {"AAPL": "0000320193", "GOOGL": "0001652044", "GOOG": "0001652044"}
REVENUE_CONCEPTS: dict[str, RevenueConcept] = {
    "AAPL": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "GOOGL": "Revenues",
    "GOOG": "Revenues",
}


class PanelAnalysisRequest(Contract):
    symbol: Annotated[str, Field(strict=True, min_length=1, max_length=16)]
    run_id: ReportUUID


class PanelAnalysisResult(Contract):
    run_id: ReportUUID
    instrument_id: ReportUUID
    status: Literal["queued", "running", "failed", "completed"]
    error_reason: str | None
    report_id: ReportUUID | None
    revision: int | None


def denied(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def verify_panel_request(request: Request) -> None:
    if not panel_request_allowed(request):
        raise denied(403, "PANEL_ORIGIN_REQUIRED", "Uruchom analizę z lokalnego panelu.")


def fetch_sec(payload: object) -> SecResponse:
    # Construct only when the admitted importer actually needs network access.
    # Trusted archives and replaying a persisted run need no contact header.
    return SecTransport(os.environ.get("ALPHASENSE_SEC_USER_AGENT", ""))(payload)


@router.get("/analyses/{run_id}")
def analysis_state(
    run_id: ReportUUID, store: Annotated[ReportStore, Depends(get_store)]
) -> PanelAnalysisResult:
    state = ResearchStore(store.engine).get(run_id)
    report_id, revision = None, None
    if state.report_revision_id is not None:
        try:
            with store.engine.connect() as connection:
                row = connection.execute(
                    select(report_revisions.c.report_id, report_revisions.c.revision).where(
                        report_revisions.c.revision_id == state.report_revision_id
                    )
                ).one()
                report_id, revision = row.report_id, row.revision
        except SQLAlchemyError:
            raise StoreUnavailable("Panel analysis storage unavailable") from None
    return PanelAnalysisResult(
        run_id=state.run_id,
        instrument_id=state.instrument_id,
        status=state.status,
        error_reason=state.error_reason,
        report_id=report_id,
        revision=revision,
    )


def resolve_analysis_request(payload: PanelAnalysisRequest, store: ReportStore) -> SecImportRequest:
    """Freeze a validated identity without fetching or creating a run."""
    symbol = payload.symbol.strip().upper()
    # Replay is bound to the original archived tag, even after catalog changes.
    try:
        existing = ResearchStore(store.engine).get(payload.run_id)
    except RunNotFound:
        existing = None
    if existing is not None:
        identity = InstrumentStore(store.engine).get(existing.instrument_id)
        if (
            existing.pipeline_version not in {SEC_PIPELINE, SEC_PIPELINE_V2}
            or identity.symbol != symbol
        ):
            raise RunConflict("SEC immutable run identity conflict")
        archive = SnapshotStore(store.engine)
        sources = [archive.get(key) for key in existing.snapshot_ids]
        revenues = [s for s in sources if s.source_id == SEC_SOURCE_IDS["revenue"]]
        submissions = [s for s in sources if s.source_id == SEC_SOURCE_IDS["submissions"]]
        if len(revenues) != 1 or len(submissions) != 1:
            raise SecInputError("SEC_REPLAY_SOURCE_IDENTITY")
        frozen = _request_for_url(str(revenues[0].source_url))
        cik = _request_for_url(str(submissions[0].source_url)).cik
        mic = identity.exchange_mic
        if mic not in {"XNAS", "XNYS"}:
            raise SecInputError("SEC_REPLAY_LISTING_IDENTITY")
        request = SecImportRequest(
            symbol=symbol,
            cik=cik,
            exchange_mic="XNAS" if mic == "XNAS" else "XNYS",
            instrument_id=existing.instrument_id,
            run_id=payload.run_id,
            pipeline_version=existing.pipeline_version,
            refresh=False,
            revenue_concept=frozen.revenue_concept,
        )
    else:
        selected_cik = CATALOG.get(symbol)
        selected_mic: Literal["XNAS", "XNYS"] = "XNAS"
        if selected_cik is None:
            try:
                listing = resolve_symbol(symbol)
                selected_cik, selected_mic = listing.cik, listing.exchange_mic
            except CatalogError:
                raise denied(
                    422,
                    "SYMBOL_UNSUPPORTED",
                    "Wybierz jednoznaczną spółkę z odświeżonego katalogu SEC.",
                ) from None
        request = SecImportRequest(
            symbol=symbol,
            cik=selected_cik,
            exchange_mic=selected_mic,
            instrument_id=uuid5(
                NAMESPACE_URL,
                f"alphasense:sec-listing:{selected_cik}:{selected_mic}:{symbol}",
            ),
            run_id=payload.run_id,
            pipeline_version=SEC_PIPELINE_V2,
            refresh=False,
            revenue_concept=REVENUE_CONCEPTS.get(
                symbol, "RevenueFromContractWithCustomerExcludingAssessedTax"
            ),
        )
    return request


@router.post("/analyses")
def launch_analysis(
    payload: PanelAnalysisRequest,
    request_context: Request,
    store: Annotated[ReportStore, Depends(get_store)],
) -> PanelAnalysisResult:
    verify_panel_request(request_context)
    store.check_ready()
    try:
        # A transaction-scoped lock is released even on connection/process failure.
        # One panel launch at a time bounds pool demand and serializes duplicate clicks.
        with store.engine.begin() as lock:
            acquired = lock.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "panel-analysis-launch-v1"},
            )
            if not acquired:
                raise denied(409, "ANALYSIS_BUSY", "Inna analiza już trwa. Ponów próbę później.")
            request = resolve_analysis_request(payload, store)
            git_sha = current_git_sha()
            fingerprint = implementation_fingerprint()
            importer = SecImporter(
                store.engine,
                load_policy(),
                fetch_sec,
            )
            state = importer.import_run(request)
            if state.status in {"queued", "running"}:
                process_once(
                    store.engine,
                    "panel-worker",
                    git_sha,
                    fingerprint,
                    run_id=state.run_id,
                )
                state = ResearchStore(store.engine).get(state.run_id)
            return analysis_state(state.run_id, store)
    except ProviderDenied:
        raise denied(
            403,
            "SOURCE_POLICY_DENIED",
            "Pobranie zablokowane przez politykę źródła lub limit. Sprawdź dopuszczenie SEC.",
        ) from None
    except SecTransportError:
        raise denied(
            502,
            "SEC_UNAVAILABLE",
            "Nie udało się pobrać danych SEC. Sprawdź konfigurację i dostęp.",
        ) from None
    except SecInputError:
        raise denied(
            422, "SEC_INPUT_UNSUPPORTED", "Dane SEC nie spełniają wymagań tego pilota analizy."
        ) from None
    except SQLAlchemyError:
        raise StoreUnavailable("Panel analysis storage unavailable") from None
    except (OSError, subprocess.SubprocessError, ValidationError, ValueError):
        raise denied(
            503,
            "ANALYSIS_CONFIGURATION",
            "Nie można uruchomić analizy. Sprawdź konfigurację serwera.",
        ) from None
