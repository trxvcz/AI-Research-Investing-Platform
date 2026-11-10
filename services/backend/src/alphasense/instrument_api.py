"""Local registration and lookup; all metadata supplied explicitly by the client."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from alphasense.instrument_contracts import (
    InstrumentCreate,
    InstrumentPage,
    InstrumentRecord,
    InstrumentWrite,
    SearchQuery,
)
from alphasense.instruments import InstrumentStore, get_instrument_store
from alphasense.report_contracts import ReportUUID

router = APIRouter(prefix="/v1/instruments", tags=["instruments"])
InstrumentDependency = Annotated[InstrumentStore, Depends(get_instrument_store)]


@router.post(
    "", response_model=InstrumentWrite, status_code=201, responses={200: {"model": InstrumentWrite}}
)
def register(
    payload: InstrumentCreate, response: Response, store: InstrumentDependency
) -> InstrumentWrite:
    result = store.create(payload)
    response.status_code = 201 if result.created else 200
    return result


@router.get("", response_model=InstrumentPage)
def search(
    store: InstrumentDependency,
    query: Annotated[SearchQuery, Query()] = "",
    after_id: Annotated[ReportUUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    data_origin: Literal["synthetic", "live"] | None = None,
) -> InstrumentPage:
    return store.search(query=query, after_id=after_id, limit=limit, data_origin=data_origin)


@router.get("/{instrument_id}", response_model=InstrumentRecord)
def get(instrument_id: ReportUUID, store: InstrumentDependency) -> InstrumentRecord:
    return store.get(instrument_id)
