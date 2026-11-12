"""Authenticated private host behind a trusted TLS terminator; no anonymous API paths."""

import base64
import binascii
import hashlib
import hmac
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from alphasense.api import app as research_api
from alphasense.panel_boundary import (
    is_panel_write_path,
    panel_request_allowed,
    security_headers,
)
from alphasense.private_settings import PrivateSettings, load_private_settings

DIST = Path(__file__).resolve().parents[4] / "apps" / "panel" / "dist"


def _authorized(scope: Scope, settings: PrivateSettings) -> bool:
    values = [value for name, value in scope["headers"] if name.lower() == b"authorization"]
    if len(values) != 1 or len(values[0]) > 2048:
        return False
    try:
        scheme, encoded = values[0].split(b" ", 1)
        if scheme.lower() != b"basic" or not encoded:
            return False
        decoded = base64.b64decode(encoded, validate=True)
        if len(decoded) > 1024:
            return False
        username, token = decoded.split(b":", 1)
        if re.fullmatch(rb"[A-Za-z0-9_-]{43}", token) is None:
            return False
        expected_username = settings.username.encode("ascii")
        name_ok = hmac.compare_digest(username, expected_username)
        token_ok = hmac.compare_digest(hashlib.sha256(token).hexdigest(), settings.token_sha256)
        return name_ok & token_ok
    except (ValueError, UnicodeError, binascii.Error):
        return False


class PrivateBoundary:
    def __init__(self, app: ASGIApp, settings: PrivateSettings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # The application has no authenticated websocket interface.
            await send({"type": "websocket.close", "code": 1008})
            return

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                security_headers(headers, scope.get("path", ""))
                headers["Cache-Control"] = "no-store"
            await send(message)

        if not _authorized(scope, self.settings):
            await JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="AlphaSense Private", charset="UTF-8"'},
            )(scope, receive, secured_send)
            return
        hosts = [value for name, value in scope["headers"] if name.lower() == b"host"]
        if len(hosts) != 1 or hosts[0] != self.settings.authority.encode("ascii"):
            await JSONResponse({"detail": "Invalid host"}, status_code=400)(
                scope, receive, secured_send
            )
            return
        trusted = dict(scope)
        trusted["scheme"] = "https"
        trusted["alphasense.panel_origin"] = self.settings.origin
        request = Request(trusted)
        if request.method not in {"GET", "HEAD"}:
            if request.method != "POST" or not is_panel_write_path(request.url.path):
                await Response(status_code=405, headers={"Allow": "GET, HEAD"})(
                    trusted, receive, secured_send
                )
                return
            if not panel_request_allowed(request):
                await JSONResponse({"detail": "Panel origin required"}, status_code=403)(
                    trusted, receive, secured_send
                )
                return
        await self.app(trusted, receive, secured_send)


def create_app() -> ASGIApp:
    settings = load_private_settings()
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/panel/")

    app.mount("/panel", StaticFiles(directory=DIST, html=True, check_dir=False))
    app.mount("/", research_api)
    return PrivateBoundary(app, settings)
