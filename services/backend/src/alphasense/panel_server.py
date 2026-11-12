"""Local dashboard host with one explicitly guarded analysis command."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from alphasense.api import app as research_api
from alphasense.panel_boundary import is_panel_write_path, panel_request_allowed, security_headers

DIST = Path(__file__).resolve().parents[4] / "apps" / "panel" / "dist"
app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def panel_boundary(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.method not in {"GET", "HEAD"}:
        if request.method != "POST" or not is_panel_write_path(request.url.path):
            return Response(status_code=405, headers={"Allow": "GET, HEAD"})
        if not panel_request_allowed(request):
            return Response(status_code=403)
    result = await call_next(request)
    security_headers(result.headers, request.url.path)
    return result


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/panel/")


app.mount("/panel", StaticFiles(directory=DIST, html=True, check_dir=False))
app.mount("/", research_api)
