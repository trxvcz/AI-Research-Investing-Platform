"""Bound local document JSON before parsing, including streamed request bodies."""

from starlette._utils import get_route_path
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_DOCUMENT_IMPORT_BODY = 4 * 1024 * 1024
MAX_DOCUMENT_REVIEW_BODY = 16 * 1024


class DocumentBodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = get_route_path(scope).rstrip("/") if scope["type"] == "http" else ""
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not (path == "/v1/panel/documents" or path.startswith("/v1/panel/documents/"))
        ):
            await self.app(scope, receive, send)
            return
        limit = (
            MAX_DOCUMENT_IMPORT_BODY if path == "/v1/panel/documents" else MAX_DOCUMENT_REVIEW_BODY
        )
        buffered = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            if len(buffered) + len(body) > limit:
                await JSONResponse(
                    status_code=413, content={"detail": "Document request too large"}
                )(scope, receive, send)
                return
            buffered.extend(body)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(buffered), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
