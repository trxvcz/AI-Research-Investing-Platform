"""Bounded uploads and metadata APIs; raw content is attachment-only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from starlette._utils import get_route_path
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from alphasense.report_contracts import ReportUUID
from alphasense.run_contracts import (
    RunCommand,
    RunCreate,
    RunEventPage,
    RunEventWrite,
    RunState,
    RunWrite,
)
from alphasense.runs import ResearchStore, get_research_store
from alphasense.snapshot_contracts import (
    MAX_UPLOAD_BODY,
    SnapshotCreate,
    SnapshotPage,
    SnapshotRecord,
    SnapshotWrite,
)
from alphasense.snapshots import SnapshotStore, get_snapshot_store
from alphasense.worker_contracts import WorkerJobRecord
from alphasense.worker_store import WorkerStore, get_worker_store

router = APIRouter(tags=["research-archive"])
SnapshotDependency = Annotated[SnapshotStore, Depends(get_snapshot_store)]
RunDependency = Annotated[ResearchStore, Depends(get_research_store)]
WorkerDependency = Annotated[WorkerStore, Depends(get_worker_store)]


class SnapshotBodyLimit:
    """Buffer at most the bounded upload size before JSON parsing, including chunked input."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or get_route_path(scope).rstrip("/") != "/v1/snapshots"
        ):
            await self.app(scope, receive, send)
            return
        buffered = bytearray()
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > MAX_UPLOAD_BODY:
                await JSONResponse(
                    status_code=413, content={"detail": "Snapshot upload too large"}
                )(scope, receive, send)
                return
            buffered.extend(body)
            if not message.get("more_body", False):
                break
        delivered = False
        raw = bytes(buffered)

        async def buffered_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, send)


@router.post(
    "/v1/snapshots",
    response_model=SnapshotWrite,
    status_code=201,
    responses={200: {"model": SnapshotWrite}},
)
def archive(
    payload: SnapshotCreate, response: Response, store: SnapshotDependency
) -> SnapshotWrite:
    result = store.create(payload)
    response.status_code = 201 if result.created else 200
    return result


@router.get("/v1/snapshots/{snapshot_id}", response_model=SnapshotRecord)
def snapshot(snapshot_id: ReportUUID, store: SnapshotDependency) -> SnapshotRecord:
    return store.get(snapshot_id)


@router.get("/v1/snapshots/{snapshot_id}/content")
def download(snapshot_id: ReportUUID, store: SnapshotDependency) -> Response:
    record, raw = store.content(snapshot_id)
    return Response(
        content=raw,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="snapshot-{record.snapshot_id}.bin"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "ETag": f'"{record.sha256}"',
        },
    )


@router.get("/v1/instruments/{instrument_id}/snapshots", response_model=SnapshotPage)
def snapshots(
    instrument_id: ReportUUID,
    store: SnapshotDependency,
    after_id: Annotated[ReportUUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SnapshotPage:
    return store.list(instrument_id, after_id=after_id, limit=limit)


@router.post(
    "/v1/research-runs",
    response_model=RunWrite,
    status_code=201,
    responses={200: {"model": RunWrite}},
)
def create_run(payload: RunCreate, response: Response, store: RunDependency) -> RunWrite:
    result = store.create(payload)
    response.status_code = 201 if result.created else 200
    return result


@router.get("/v1/research-runs/{run_id}", response_model=RunState)
def run(run_id: ReportUUID, store: RunDependency) -> RunState:
    return store.get(run_id)


@router.get("/v1/research-runs/{run_id}/worker-job", response_model=WorkerJobRecord)
def worker_job(run_id: ReportUUID, store: WorkerDependency) -> WorkerJobRecord:
    return store.get_job(run_id)


@router.post(
    "/v1/research-runs/{run_id}/events",
    response_model=RunEventWrite,
    status_code=201,
    responses={200: {"model": RunEventWrite}},
)
def apply(
    run_id: ReportUUID, payload: RunCommand, response: Response, store: RunDependency
) -> RunEventWrite:
    result = store.apply(run_id, payload)
    response.status_code = 201 if result.created else 200
    return result


@router.get("/v1/research-runs/{run_id}/events", response_model=RunEventPage)
def events(
    run_id: ReportUUID,
    store: RunDependency,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RunEventPage:
    return store.events(run_id, after_sequence=after_sequence, limit=limit)
