"""Local dashboard host with one explicitly guarded analysis command."""

import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from alphasense.api import app as research_api

DIST = Path(__file__).resolve().parents[4] / "apps" / "panel" / "dist"
app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def panel_boundary(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.method not in {"GET", "HEAD"}:
        document_review = re.fullmatch(
            r"/v1/panel/documents/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}"
            r"-[a-f0-9]{4}-[a-f0-9]{12}/reviews",
            request.url.path,
        )
        if request.method != "POST" or (
            request.url.path
            not in {
                "/v1/panel/analyses",
                "/v1/panel/tasks",
                "/v1/panel/catalog/refresh",
                "/v1/panel/documents",
            }
            and document_review is None
        ):
            return Response(status_code=405, headers={"Allow": "GET, HEAD"})
        if (
            request.url.hostname not in {"127.0.0.1", "localhost"}
            or request.headers.get("origin") != str(request.base_url).rstrip("/")
            or request.headers.get("x-alphasense-panel") != "1"
            or request.headers.get("content-type", "").split(";")[0] != "application/json"
        ):
            return Response(status_code=403)
    result = await call_next(request)
    result.headers["X-Content-Type-Options"] = "nosniff"
    result.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/panel/"):
        result.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
    return result


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/panel/")


app.mount("/panel", StaticFiles(directory=DIST, html=True, check_dir=False))
app.mount("/", research_api)
