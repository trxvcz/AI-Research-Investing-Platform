"""Read-only comparisons from report-bound immutable archives; never fetches data."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.financial_history import (
    FinancialHistory,
    FinancialHistoryInvalid,
    build_financial_history,
)
from alphasense.snapshots import SnapshotNotFound, SnapshotStore, get_snapshot_store

router = APIRouter(prefix="/v1/panel/reports", tags=["financial-history"])
METRICS = frozenset({"revenue", "net_income", "operating_cash_flow", "capital_expenditures"})


@router.get("/{report_id}/{revision}/financial-history")
def financial_history(
    report_id: UUID,
    revision: Annotated[int, Path(ge=1)],
    response: Response,
    reports: Annotated[ReportStore, Depends(get_store)],
    snapshots: Annotated[SnapshotStore, Depends(get_snapshot_store)],
) -> FinancialHistory:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    report = reports.get_report(report_id, revision)
    wanted = {
        (item.source_id, item.snapshot_id)
        for item in report.input.observations
        if item.status == "available" and item.metric in METRICS
    }
    try:
        archived = [
            snapshots.content(UUID(source.snapshot_id))
            for source in report.sources
            if (source.source_id, source.snapshot_id) in wanted
        ]
        return build_financial_history(report, archived)
    except (SnapshotNotFound, StoreUnavailable):
        raise HTTPException(
            503,
            detail={
                "code": "HISTORY_ARCHIVE_UNAVAILABLE",
                "message": "Archiwum źródeł jest niedostępne.",
            },
        ) from None
    except FinancialHistoryInvalid as error:
        raise HTTPException(
            422,
            detail={
                "code": error.code,
                "message": "Nie można odtworzyć porównania z tych danych raportu.",
            },
        ) from None
    except (ValueError, TypeError):
        raise HTTPException(
            422,
            detail={
                "code": "HISTORY_SOURCE_INVALID",
                "message": "Raport nie wskazuje obsługiwanego archiwum.",
            },
        ) from None
