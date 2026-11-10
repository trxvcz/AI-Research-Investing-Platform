"""Worker receipts describe offline work, never a fictional model invocation."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from test_document_archive import database as database
from test_document_archive import request

from alphasense import document_task_worker
from alphasense.document_archive import DocumentArchiveStore
from alphasense.document_task_contracts import DocumentTaskCreate
from alphasense.document_tasks import DocumentTaskStore
from alphasense.gemini_transport import GeminiTransport
from alphasense.provider_policy import FreeOnlyGateway


@pytest.mark.postgres
def test_offline_worker_persists_result_and_never_calls_provider(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> str:
        pytest.fail("The offline worker attempted a provider call")

    monkeypatch.setattr(GeminiTransport, "__call__", forbidden)
    monkeypatch.setattr(FreeOnlyGateway, "invoke", forbidden)
    source = DocumentArchiveStore(database).create(request())
    jobs = DocumentTaskStore(database)
    task = jobs.create(DocumentTaskCreate(job_id=uuid4(), archive_id=source.archive_id))
    assert document_task_worker.process_document_once(database, "offline-worker")
    record = DocumentTaskStore(database).detail(task.job_id)
    assert record.task.status == "completed"
    assert record.task.result == source.result
    assert [event.stage for event in record.events] == [
        "queued",
        "reading",
        "validating",
        "archiving",
        "completed",
    ]
    audit = record.audits[0]
    assert audit.execution == "offline-validation-v1" and audit.provider_called is False
    assert audit.cost_usd == "0" and audit.input_tokens is None and audit.output_tokens is None
    assert audit.model_id is None and audit.prompt_version is None and audit.response_sha256 is None
    assert audit.request_sha256 == record.task.input_sha256
    assert audit.implementation_sha256 == document_task_worker.implementation_fingerprint()
    assert not document_task_worker.process_document_once(database, "idle-worker")


@pytest.mark.postgres
def test_model_mode_is_terminal_blocked_without_network(database: Engine) -> None:
    source = DocumentArchiveStore(database).create(request())
    jobs = DocumentTaskStore(database)
    task = jobs.create(
        DocumentTaskCreate(job_id=uuid4(), archive_id=source.archive_id, mode="model_extract")
    )
    assert document_task_worker.process_document_once(database, "blocked-worker")
    detail = jobs.detail(task.job_id)
    assert detail.task.status == "blocked" and detail.task.error_code == "MODEL_EXECUTION_DISABLED"
    assert detail.task.result is None
    assert detail.audits[0].execution == "model-disabled-v1"
    assert detail.audits[0].provider_called is False
    assert detail.audits[0].output_sha256 is None
    assert not document_task_worker.process_document_once(database, "no-auto-retry")


@pytest.mark.postgres
def test_queued_document_survives_new_worker_process(database: Engine) -> None:
    source = DocumentArchiveStore(database).create(request())
    jobs = DocumentTaskStore(database)
    task = jobs.create(DocumentTaskCreate(job_id=uuid4(), archive_id=source.archive_id))
    with database.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    env = os.environ.copy()
    # Supply a real schema-bound store: production connection options deliberately
    # override URL options, so passing search_path in the URL would hit public.
    env["DOCUMENT_WORKER_TEST_URL"] = database.url.render_as_string(hide_password=False)
    env["DOCUMENT_WORKER_TEST_SCHEMA"] = str(schema)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    program = """
import os,re
from sqlalchemy import create_engine
from alphasense import document_task_worker as worker
from alphasense.db import ReportStore
schema=os.environ['DOCUMENT_WORKER_TEST_SCHEMA']
assert re.fullmatch(r'document_archive_test_[a-f0-9]{32}',schema)
engine=create_engine(os.environ['DOCUMENT_WORKER_TEST_URL'],hide_parameters=True,
                     connect_args={'options':'-c search_path='+schema})
worker.get_store=lambda: ReportStore(engine)
raise SystemExit(worker.main(['--once','--worker-id','subprocess-document']))
"""
    try:
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                program,
            ],
            env=env,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.fail("Independent document worker did not finish", pytrace=False)
    assert process.returncode == 0, "Independent document worker failed"
    assert jobs.get(task.job_id).status == "completed"
    assert jobs.detail(task.job_id).audits[0].worker_id == "subprocess-document"
