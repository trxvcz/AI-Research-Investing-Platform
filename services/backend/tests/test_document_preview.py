"""Document-only preview is bounded, guarded and independent of persistence/providers."""

import base64
import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_document_readers import workbook
from test_pdf_workflow import synthetic_pdf

from alphasense.api import app
from alphasense.db import get_store
from alphasense.document_preview import (
    DocumentPreviewCreate,
    DocumentPreviewInvalid,
    preview_document,
)
from alphasense.document_readers import read_text_document
from alphasense.private_server import PrivateBoundary
from alphasense.private_settings import PrivateSettings
from alphasense.provider_policy import FreeOnlyGateway

HEADERS = {"Origin": "http://localhost", "X-AlphaSense-Panel": "1"}


def payload(raw=b"Revenue 100 PLN", format="text", **options):
    return DocumentPreviewCreate(
        document_id=uuid4(), format=format, content_base64=base64.b64encode(raw).decode(), **options
    )


@pytest.mark.parametrize(
    "raw,format,options",
    [
        (b"Revenue 100 PLN", "text", {}),
        (
            b"<table><tr><td>Revenue</td><td>281,724</td></tr></table>",
            "html",
            {"reader_version": "table-text-v2", "number_locale": "en-US"},
        ),
        (workbook(), "xlsx", {}),
        (synthetic_pdf("Revenue 100 PLN"), "pdf", {}),
    ],
)
def test_preview_matches_archive_reader_without_draft(raw, format, options):
    request = payload(raw, format, **options)
    result = preview_document(request)
    assert result.packet == read_text_document(
        raw, document_id=request.document_id, classification="private", format=format, **options
    )
    assert result.packet.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.byte_length == len(raw)
    assert result.model_called is False and result.persisted is False


@pytest.mark.parametrize("content", ["YQ=", "YR==", "!invalid!", "", "YQ==" * 400000])
def test_preview_revalidates_even_mutated_input(content):
    request = payload().model_copy(update={"content_base64": content})
    with pytest.raises(DocumentPreviewInvalid, match="^DOCUMENT_PREVIEW_INVALID$"):
        preview_document(request)


@pytest.mark.parametrize("raw,format", [(b"not a PDF", "pdf"), (b"\x00bad", "text")])
def test_reader_errors_do_not_reflect_source(raw, format):
    with pytest.raises(DocumentPreviewInvalid, match="^DOCUMENT_PREVIEW_INVALID$"):
        preview_document(payload(raw, format))


def test_http_preview_has_no_database_or_model_dependency(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Preview attempted persistence or provider execution")

    app.dependency_overrides[get_store] = forbidden
    monkeypatch.setattr(FreeOnlyGateway, "invoke", forbidden)
    try:
        with TestClient(app, base_url="http://localhost") as client:
            request = payload(b"<script>untrusted()</script>Revenue 100 PLN", "text")
            response = client.post(
                "/v1/panel/document-preview", headers=HEADERS, json=request.model_dump(mode="json")
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["pragma"] == "no-cache"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.json()["packet"]["blocks"][0]["text"].startswith("<script>")
            assert response.json()["model_called"] is False
            assert response.json()["persisted"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_http_preview_refuses_missing_or_foreign_origin(origin):
    headers = {"X-AlphaSense-Panel": "1"}
    if origin:
        headers["Origin"] = origin
    with TestClient(app, base_url="http://localhost") as client:
        assert (
            client.post(
                "/v1/panel/document-preview",
                headers=headers,
                json=payload().model_dump(mode="json"),
            ).status_code
            == 403
        )


def test_http_preview_rejects_oversized_body_before_json():
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/v1/panel/document-preview",
            headers=HEADERS | {"Content-Type": "application/json"},
            content=b"x" * (4 * 1024 * 1024 + 1),
        )
        assert response.status_code == 413


def test_preview_schema_and_reader_errors_are_redacted():
    with TestClient(app, base_url="http://localhost") as client:
        original = payload().model_dump(mode="json")
        for update in (
            {"content_base64": "PRIVATE-NOT-BASE64"},
            {"draft_json": "PRIVATE-UNEXPECTED-DRAFT"},
            {"source_url": "https://PRIVATE.example/report"},
        ):
            response = client.post(
                "/v1/panel/document-preview", headers=HEADERS, json=original | update
            )
            assert response.status_code == 422
            assert "PRIVATE" not in response.text


def test_private_preview_authenticates_before_reading_and_uses_trusted_origin():
    token = "a" * 43
    origin = "https://research.example"
    protected = PrivateBoundary(
        app,
        PrivateSettings(
            origin, "research.example", "owner", hashlib.sha256(token.encode()).hexdigest()
        ),
    )
    auth = "Basic " + base64.b64encode(("owner:" + token).encode()).decode()
    with TestClient(protected, base_url=origin) as client:
        assert client.post("/v1/panel/document-preview", content=b"invalid").status_code == 401
        headers = {"Authorization": auth, "Origin": origin, "X-AlphaSense-Panel": "1"}
        response = client.post(
            "/v1/panel/document-preview", headers=headers, json=payload().model_dump(mode="json")
        )
        assert response.status_code == 200
        assert response.json()["persisted"] is False
        assert response.headers["cache-control"] == "no-store"
        assert (
            client.post(
                "/v1/panel/document-preview",
                headers=headers | {"Origin": "https://evil.example"},
                json=payload().model_dump(mode="json"),
            ).status_code
            == 403
        )


@pytest.mark.parametrize("prefixed", [False, True])
def test_streamed_preview_body_limit_handles_root_path(prefixed):
    prefix = "/prefix" if prefixed else ""
    with TestClient(app, base_url="http://localhost", root_path=prefix) as client:
        response = client.post(
            prefix + "/v1/panel/document-preview",
            headers=HEADERS | {"Content-Type": "application/json"},
            content=iter([b"x" * (4 * 1024 * 1024), b"y"]),
        )
        assert response.status_code == 413
