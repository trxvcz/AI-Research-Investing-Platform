"""Read-only derived ratios; archive and source admission are inherited from history."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from alphasense.financial_history import FinancialHistory
from alphasense.financial_history_api import financial_history
from alphasense.financial_ratios import (
    FinancialRatios,
    FinancialRatiosInvalid,
    build_financial_ratios,
)

router = APIRouter(prefix="/v1/panel/reports", tags=["financial-ratios"])


@router.get("/{report_id}/{revision}/financial-ratios")
def financial_ratios(
    response: Response,
    history: Annotated[FinancialHistory, Depends(financial_history)],
) -> FinancialRatios:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    try:
        return build_financial_ratios(history)
    except FinancialRatiosInvalid as error:
        raise HTTPException(
            422,
            detail={
                "code": error.code,
                "message": "Nie można bezpiecznie wyliczyć wskaźników z tych danych.",
            },
        ) from None
