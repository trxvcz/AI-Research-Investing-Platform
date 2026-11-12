"""Shared explicit mutation allowlist for local and authenticated private hosts."""

import re

from fastapi import Request
from starlette.datastructures import MutableHeaders

WRITE_PATHS = frozenset(
    {
        "/v1/panel/analyses",
        "/v1/panel/tasks",
        "/v1/panel/catalog/refresh",
        "/v1/panel/documents",
        "/v1/panel/document-preview",
        "/v1/panel/ai-analyses",
        "/v1/panel/document-tasks",
        "/v1/panel/schedules",
    }
)
_UUID = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"


def is_panel_write_path(path: str) -> bool:
    return (
        path in WRITE_PATHS
        or re.fullmatch(
            rf"/v1/panel/(?:documents/{_UUID}/reviews|schedules/{_UUID}/commands)", path
        )
        is not None
    )


def panel_request_allowed(request: Request) -> bool:
    if (
        any(
            len(request.headers.getlist(name)) != 1
            for name in ("origin", "x-alphasense-panel", "content-type")
        )
        or len(request.headers.getlist("sec-fetch-site")) > 1
    ):
        return False
    trusted = request.scope.get("alphasense.panel_origin")
    origin = trusted if isinstance(trusted, str) else str(request.base_url).rstrip("/")
    return (
        (isinstance(trusted, str) or request.url.hostname in {"127.0.0.1", "localhost"})
        and request.headers.get("origin") == origin
        and request.headers.get("x-alphasense-panel") == "1"
        and request.headers.get("sec-fetch-site") in {None, "same-origin"}
        and request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        == "application/json"
    )


def security_headers(headers: MutableHeaders, path: str) -> None:
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    if path.startswith("/panel/"):
        headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
