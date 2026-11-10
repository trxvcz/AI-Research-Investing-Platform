"""Local panel host protections do not depend on a frontend build."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from alphasense.panel_server import app


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_host_rejects_writes(method: str) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.request(method, "/v1/instruments", json={})
        assert response.status_code == 405
        assert response.headers["allow"] == "GET, HEAD"


def test_host_rejects_foreign_host_and_redirects_local_root() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/panel/"


def test_static_panel_has_security_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "index.html").write_text("<html>Panel fixture</html>", encoding="utf-8")
    mount = next(
        route for route in app.routes if isinstance(route, Mount) and route.path == "/panel"
    )
    assert isinstance(mount.app, StaticFiles)
    monkeypatch.setattr(mount.app, "directory", str(tmp_path))
    monkeypatch.setattr(mount.app, "all_directories", [str(tmp_path)])
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/panel/")
        assert response.status_code == 200
        assert "Panel fixture" in response.text
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
        policy = response.headers["content-security-policy"]
        assert "script-src 'self'" in policy
        assert "connect-src 'self'" in policy
        assert "frame-ancestors 'none'" in policy
        assert client.head("/panel/").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://attacker.example", "X-AlphaSense-Panel": "1"},
        {"Origin": "null", "X-AlphaSense-Panel": "1"},
        {"Origin": "http://127.0.0.1"},
        {"Origin": "http://127.0.0.1:9999", "X-AlphaSense-Panel": "1"},
    ],
)
@pytest.mark.parametrize(
    "path",
    [
        "/v1/panel/analyses",
        "/v1/panel/catalog/refresh",
        "/v1/panel/tasks",
        "/v1/panel/documents",
        "/v1/panel/document-tasks",
        "/v1/panel/schedules",
        "/v1/panel/schedules/91f9692a-c3cc-4835-96ec-d6902dac00ec/commands",
        "/v1/panel/documents/91f9692a-c3cc-4835-96ec-d6902dac00ec/reviews",
    ],
)
def test_launch_rejects_cross_origin_or_missing_guard(headers: dict[str, str], path: str) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post(path, json={}, headers=headers).status_code == 403


def test_launch_rejects_simple_form_content_type() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/v1/panel/analyses",
            content="symbol=AAPL",
            headers={
                "Origin": "http://127.0.0.1",
                "X-AlphaSense-Panel": "1",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert response.status_code == 403
