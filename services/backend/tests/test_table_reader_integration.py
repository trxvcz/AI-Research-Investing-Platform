"""New read options are immutable inputs; old archives and benchmark hashes stay stable."""

import base64
import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, select
from test_document_archive import database as database
from test_document_archive import request

from alphasense.benchmark_corpus import CorpusManifest, prepare_corpus, verify_corpus
from alphasense.db_schema import document_archives
from alphasense.document_archive import DocumentArchiveConflict, DocumentArchiveStore
from alphasense.document_benchmark import canonical_hash, evaluate
from alphasense.document_benchmark_contracts import BenchmarkResponses, BenchmarkSuite
from alphasense.document_readers import read_text_document
from alphasense.document_task_contracts import DocumentTaskCreate
from alphasense.document_task_worker import process_document_once
from alphasense.document_tasks import DocumentTaskStore

RAW = (
    b"<table><tr><th>In millions USD</th></tr>"
    b"<tr><td>Consolidated revenue 2025</td><td>281,724</td>"
    b"<td>245,122</td><td>211,915</td></tr></table>"
)


def table_request(**updates):
    original = request(format="html", content_base64=base64.b64encode(RAW).decode())
    draft = json.loads(original.draft_json)
    draft["facts"][0].update(
        value_token="281,724",
        value="281724000000",
        currency="USD",
        period_start="2024-07-01",
        period_end="2025-06-30",
        evidence=[
            {"block_id": "block-2", "quote": "281,724"},
            {"block_id": "block-1", "quote": "In millions USD"},
        ],
    )
    return request(
        format="html",
        content_base64=original.content_base64,
        draft_json=json.dumps(draft),
        **updates,
    )


def test_legacy_archive_roundtrip_omits_new_fields_and_keeps_original_result(database: Engine):
    raw = b"<p>Consolidated revenue 2025: 12.5 million PLN.</p>"
    original = request(format="html", content_base64=base64.b64encode(raw).decode())
    assert "reader_version" not in original.model_dump(mode="json")
    assert "number_locale" not in original.model_dump(mode="json")
    store = DocumentArchiveStore(database)
    saved = store.create(original)
    assert saved.result.status == "needs_review"
    assert saved.packet.blocks[0].text == raw.decode()[3:-4]
    assert saved == store.get(saved.archive_id) == store.create(original)
    assert "reader_version" not in saved.packet.model_dump(mode="json")
    with database.connect() as connection:
        row = connection.execute(select(document_archives)).mappings().one()
        assert "reader_version" not in row["request"] and "number_locale" not in row["packet"]


def test_new_options_survive_archive_and_offline_worker(database: Engine):
    original = table_request(reader_version="table-text-v2", number_locale="en-US")
    store = DocumentArchiveStore(database)
    saved = store.create(original)
    assert saved.reader_version == saved.packet.reader_version == "table-text-v2"
    assert saved.number_locale == saved.packet.number_locale == "en-US"
    assert saved.result.status == "needs_review"
    assert "281,724 | 245,122 | 211,915" in saved.packet.blocks[1].text
    assert store.get(saved.archive_id) == saved
    tasks = DocumentTaskStore(database)
    job = tasks.create(DocumentTaskCreate(job_id=uuid4(), archive_id=saved.archive_id))
    assert process_document_once(database, "reader-v2-test")
    detail = tasks.detail(job.job_id)
    assert detail.task.status == "completed"
    assert detail.audits[0].provider_called is False
    assert detail.task.result.status == "needs_review"


def test_reader_settings_cannot_silently_replace_frozen_import(database: Engine):
    original = table_request()
    store = DocumentArchiveStore(database)
    saved = store.create(original)
    assert saved.result.status == "rejected"
    changed = original.model_copy(
        update={"reader_version": "table-text-v2", "number_locale": "en-US"}
    )
    with pytest.raises(DocumentArchiveConflict):
        store.create(changed)
    assert store.get(original.archive_id) == saved


def test_new_options_preserve_old_synthetic_benchmark_identity():
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    suite = BenchmarkSuite.model_validate_json(
        (fixtures / "document-benchmark.synthetic.json").read_text("utf-8")
    )
    responses = BenchmarkResponses.model_validate_json(
        (fixtures / "document-benchmark-reference.synthetic.json").read_text("utf-8")
    )
    assert (
        canonical_hash(suite) == "933e6b64ff63d09a0e7b90bbf72287b462ab6c02144cdbd09fb5b58ad3f3154a"
    )
    assert evaluate(suite, responses).true_positives == 7


def test_corpus_transports_and_replays_reader_options(tmp_path):
    (tmp_path / "source.html").write_bytes(RAW)
    manifest = CorpusManifest.model_validate(
        {
            "schema_version": "1.0",
            "suite_id": "reader-v2-corpus",
            "cases": [
                {
                    "case_id": "sample",
                    "issuer_label": "Synthetic issuer",
                    "format": "html",
                    "reader_version": "table-text-v2",
                    "number_locale": "en-US",
                    "source_file": "source.html",
                    "source_url": "https://issuer.example/source.html",
                    "source_sha256": hashlib.sha256(RAW).hexdigest(),
                    "first_seen_at": "2026-01-01T00:00:00Z",
                    "as_of": "2026-01-02T00:00:00Z",
                    "title": "Synthetic table",
                    "source_locator": "Table",
                    "gold": [],
                }
            ],
        }
    )
    output = tmp_path / "prepared"
    assert prepare_corpus(manifest, tmp_path, output) == verify_corpus(output)
    suite = BenchmarkSuite.model_validate_json((output / "suite.json").read_text("utf-8"))
    case = suite.cases[0]
    assert case.reader_version == "table-text-v2" and case.number_locale == "en-US"
    packet = read_text_document(
        RAW,
        document_id=uuid4(),
        classification="private",
        format="html",
        reader_version=case.reader_version,
        number_locale=case.number_locale,
    )
    assert "281,724 | 245,122 | 211,915" in packet.blocks[1].text


@pytest.mark.parametrize("format", ["text", "pdf", "xlsx"])
def test_archive_refuses_html_reader_settings_for_other_formats(format):
    with pytest.raises(ValidationError):
        request(format=format, reader_version="table-text-v2", number_locale="en-US")
