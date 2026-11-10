"""Every private route authenticates before storage, parsing or static file access."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from alphasense import private_server
from alphasense.panel_launch import verify_panel_request
from alphasense.private_server import PrivateBoundary
from alphasense.private_settings import PrivateSettings

TOKEN = "a" * 43
ORIGIN = "https://research.example"
AUTH = "Basic " + base64.b64encode(("owner:" + TOKEN).encode()).decode()
WRITE_HEADERS = {"Authorization": AUTH, "Origin": ORIGIN, "X-Alphasense-Panel": "1"}


@pytest.fixture
def protected():
    calls: list[str] = []
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "DELETE", "OPTIONS"])
    def target(request: Request, path: str):
        calls.append(path)
        if request.method == "POST":
            verify_panel_request(request)
        return {
            "scheme": request.url.scheme,
            "host": request.url.hostname,
            "origin": request.scope.get("alphasense.panel_origin"),
        }

    private = PrivateBoundary(
        app,
        PrivateSettings(
            ORIGIN, "research.example", "owner", hashlib.sha256(TOKEN.encode()).hexdigest()
        ),
    )
    with TestClient(private, base_url=ORIGIN) as client:
        yield client, calls


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/panel/",
        "/health",
        "/ready",
        "/openapi.json",
        "/v1/reports/private",
        "/v1/snapshots/private/content",
        "/v1/panel/documents/private/content",
        "/v1/panel/tasks",
        "/v1/panel/workers",
        "/v1/panel/schedules",
        "/unknown/private",
    ],
)
def test_all_paths_require_auth_before_backend(protected, path: str) -> None:
    client, calls = protected
    response = client.get(path)
    assert response.status_code == 401 and not calls
    assert response.headers["www-authenticate"].startswith("Basic ")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "private" not in response.text and TOKEN not in response.text


@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT", "DELETE", "OPTIONS"])
def test_unauthorized_methods_do_not_reach_application(protected, method: str) -> None:
    client, calls = protected
    assert client.request(method, "/v1/panel/tasks", content=b"invalid-json").status_code == 401
    assert not calls


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer secret",
        "Basic %%%private",
        "Basic " + "x" * 3000,
        "Basic " + base64.b64encode(b"owner:human-password").decode(),
        "Basic " + base64.b64encode(("owner:" + "b" * 43).encode()).decode(),
        "Basic " + base64.b64encode(("other:" + TOKEN).encode()).decode(),
        "Basic "
        + base64.b64encode(
            b"owner:",
        ).decode(),
    ],
)
def test_bad_credentials_are_bounded_and_redacted(protected, authorization: str) -> None:
    client, calls = protected
    response = client.get("/health", headers={"Authorization": authorization})
    assert response.status_code == 401 and not calls
    assert response.json() == {"detail": "Authentication required"}


def test_duplicate_authorization_is_rejected(protected) -> None:
    client, calls = protected
    response = client.get("/health", headers=[("Authorization", AUTH), ("Authorization", AUTH)])
    assert response.status_code == 401 and not calls


def test_authenticated_reads_use_only_canonical_origin_not_forwarded_headers(protected) -> None:
    client, calls = protected
    result = client.get(
        "/v1/reports/private",
        headers={
            "Authorization": AUTH,
            "X-Forwarded-Host": "attacker.example",
            "X-Forwarded-Proto": "http",
            "Forwarded": "host=attacker.example;proto=http",
        },
    )
    assert result.status_code == 200 and calls == ["v1/reports/private"]
    assert result.json() == {"scheme": "https", "host": "research.example", "origin": ORIGIN}
    assert result.headers["cache-control"] == "no-store"


def test_authenticated_forged_or_duplicate_host_is_rejected(protected) -> None:
    client, calls = protected
    assert (
        client.get(
            "/health", headers={"Authorization": AUTH, "Host": "attacker.example"}
        ).status_code
        == 400
    )
    assert (
        client.get(
            "/health",
            headers=[
                ("Authorization", AUTH),
                ("Host", "research.example"),
                ("Host", "attacker.example"),
            ],
        ).status_code
        == 400
    )
    assert not calls


def test_guarded_canonical_write_reaches_existing_guard(protected) -> None:
    client, calls = protected
    response = client.post("/v1/panel/tasks", json={}, headers=WRITE_HEADERS)
    assert response.status_code == 200 and calls == ["v1/panel/tasks"]


@pytest.mark.parametrize(
    "changes",
    [
        {"Origin": "http://research.example"},
        {"Origin": "null"},
        {"Origin": "https://attacker.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-Alphasense-Panel": "0"},
        {"Content-Type": "text/plain"},
    ],
)
def test_private_writes_still_require_same_origin_json_and_panel_guard(protected, changes) -> None:
    client, calls = protected
    response = client.post("/v1/panel/tasks", json={}, headers=WRITE_HEADERS | changes)
    assert response.status_code == 403 and not calls


def test_duplicate_origin_cannot_satisfy_guard(protected) -> None:
    client, calls = protected
    headers = list(WRITE_HEADERS.items()) + [("Origin", "https://attacker.example")]
    assert client.post("/v1/panel/tasks", json={}, headers=headers).status_code == 403
    assert not calls


@pytest.mark.parametrize(
    "path", ["/v1/instruments", "/v1/reports", "/v1/panel/workers", "/anything"]
)
def test_valid_auth_does_not_expand_write_permissions(protected, path: str) -> None:
    client, calls = protected
    assert client.post(path, json={}, headers=WRITE_HEADERS).status_code == 405 and not calls


def test_factory_protects_actual_health_static_and_openapi(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "access.json"
    path.write_text(
        json.dumps(
            {"username": "owner", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHASENSE_PRIVATE_AUTH_FILE", str(path))
    monkeypatch.setenv("ALPHASENSE_PRIVATE_ORIGIN", ORIGIN)
    (tmp_path / "index.html").write_text("<html>Private fixture</html>", encoding="utf-8")
    monkeypatch.setattr(private_server, "DIST", tmp_path)
    with TestClient(private_server.create_app(), base_url=ORIGIN) as client:
        for path in ("/health", "/panel/", "/openapi.json"):
            assert client.get(path).status_code == 401
            response = client.get(path, headers={"Authorization": AUTH})
            assert response.status_code == 200
        response = client.get("/panel/", headers={"Authorization": AUTH})
        assert "Private fixture" in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_factory_does_not_start_without_private_settings(monkeypatch) -> None:
    monkeypatch.delenv("ALPHASENSE_PRIVATE_AUTH_FILE", raising=False)
    monkeypatch.delenv("ALPHASENSE_PRIVATE_ORIGIN", raising=False)
    with pytest.raises(ValueError, match="^Invalid private access configuration$"):
        private_server.create_app()
