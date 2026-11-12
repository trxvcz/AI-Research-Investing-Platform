"""PDF bytes, page evidence and offline receipts survive the existing archive flow."""

import base64
import hashlib
import io
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import Engine, func, select
from test_document_archive import database as database
from test_document_archive import request

from alphasense.db import ReportStore, get_store
from alphasense.db_schema import report_revisions
from alphasense.document_agent import validate_draft
from alphasense.document_archive import DocumentArchiveInvalid, DocumentArchiveStore
from alphasense.document_archive_api import router
from alphasense.document_readers import read_text_document
from alphasense.document_task_contracts import DocumentTaskCreate
from alphasense.document_task_worker import process_document_once
from alphasense.document_tasks import DocumentTaskStore


def synthetic_pdf(*pages: str) -> bytes:
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                                NameObject("/BaseFont"): NameObject("/Helvetica"),
                            }
                        )
                    }
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 40 700 Td (" + text.encode("ascii") + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_packet_keeps_page_evidence_and_exact_decimal_without_model():
    raw = synthetic_pdf("Issuer A", "Consolidated revenue 2025: 12.5 million PLN.")
    original = request(format="pdf", content_base64=base64.b64encode(raw).decode())
    draft = json.loads(original.draft_json)
    draft["facts"][0]["evidence"][0]["block_id"] = "block-2"
    packet = read_text_document(
        raw, document_id=original.archive_id, classification="private", format="pdf"
    )
    assert packet.sha256 == hashlib.sha256(raw).hexdigest()
    assert packet.blocks[1].locator == "pdf:page:2:block:1"
    assert "12.5 million PLN" in packet.blocks[1].text
    assert packet == read_text_document(
        raw, document_id=original.archive_id, classification="private", format="pdf"
    )
    result = validate_draft(packet, json.dumps(draft), "offline-import")
    assert result.status == "needs_review"
    assert result.facts[0].fact.value == "12500000"
    assert result.facts[0].fact.evidence[0].block_id == "block-2"


def test_pdf_archive_api_and_offline_worker_preserve_raw_and_never_publish(database: Engine):
    raw = synthetic_pdf("Consolidated revenue 2025: 12.5 million PLN.")
    original = request(format="pdf", content_base64=base64.b64encode(raw).decode())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    headers = {"Origin": "http://localhost", "X-AlphaSense-Panel": "1"}
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/v1/panel/documents", json=original.model_dump(mode="json"), headers=headers
        )
        assert response.status_code == 200
        saved = response.json()
        assert saved["packet"]["blocks"][0]["locator"] == "pdf:page:1:block:1"
        assert saved["validation_status"] == "needs_review"
        content = client.get(f"/v1/panel/documents/{original.archive_id}/content")
        assert content.status_code == 200 and content.content == raw
        assert content.headers["content-type"] == "application/octet-stream"
        assert content.headers["x-content-type-options"] == "nosniff"
        assert content.headers["content-disposition"].startswith("attachment;")
    store = DocumentArchiveStore(database)
    assert store.create(original) == store.get(original.archive_id)
    tasks = DocumentTaskStore(database)
    tasks.create(DocumentTaskCreate(job_id=uuid4(), archive_id=original.archive_id))
    assert process_document_once(database, "synthetic-pdf-worker") is True
    job = tasks.page().items[0]
    assert job.status == "completed"
    assert tasks.detail(job.job_id).audits[0].provider_called is False
    with database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(report_revisions)) == 0


def test_invalid_pdf_cannot_create_an_archive(database: Engine):
    original = request(format="pdf", content_base64=base64.b64encode(b"broken PDF").decode())
    with pytest.raises(DocumentArchiveInvalid):
        DocumentArchiveStore(database).create(original)
    assert DocumentArchiveStore(database).page().items == []
