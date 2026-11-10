"""HTTP/manual ledger/archive integration on real PostgreSQL, using synthetic data."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_run_snapshot_contracts import snapshot_payload
from test_runs import database as database
from test_runs import instrument, report

from alphasense.api import app
from alphasense.db import ReportStore, get_store
from alphasense.run_contracts import STEPS, RunCreate
from alphasense.runs import ResearchStore, get_research_store
from alphasense.snapshot_contracts import SnapshotCreate, SnapshotRecord
from alphasense.snapshots import SnapshotStore, get_snapshot_store

pytestmark = pytest.mark.postgres


def test_http_archive_fail_resume_and_final_provenance(database) -> None:
    identity = instrument(database)
    archive = SnapshotStore(database)
    ledger = ResearchStore(database)
    reports = ReportStore(database)
    raw = (Path(__file__).parent / "fixtures/source-snapshot.synthetic.json").read_bytes()
    payload = snapshot_payload(raw)
    payload["instrument_id"] = str(identity.instrument_id)
    # Use the existing JSON fixture's exact raw content expected by the report helper.
    snapshot = SnapshotCreate.model_validate(payload)
    app.dependency_overrides[get_snapshot_store] = lambda: archive
    app.dependency_overrides[get_research_store] = lambda: ledger
    app.dependency_overrides[get_store] = lambda: reports
    try:
        with TestClient(app) as client:
            saved = client.post("/v1/snapshots", json=snapshot.model_dump(mode="json"))
            assert saved.status_code == 201
            metadata = saved.json()
            metadata.pop("created")
            archived = SnapshotRecord.model_validate(metadata)
            assert (
                client.get(f"/v1/snapshots/{archived.snapshot_id}/content").content
                == snapshot.raw_bytes()
            )
            definition = RunCreate(
                schema_version="1.0",
                run_id=uuid4(),
                instrument_id=identity.instrument_id,
                as_of=snapshot.as_of,
                snapshot_ids=[archived.snapshot_id],
            )
            created = client.post("/v1/research-runs", json=definition.model_dump(mode="json"))
            assert created.status_code == 201
            state = created.json()
            assert state["status"] == "queued"
            endpoint = f"/v1/research-runs/{definition.run_id}/events"

            def apply(action, **fields):
                command = {
                    "action": action,
                    "request_id": str(uuid4()),
                    "expected_sequence": state["sequence"],
                    "actor": "synthetic-http-test",
                    **fields,
                }
                response = client.post(endpoint, json=command)
                assert response.status_code == 201, response.text
                return response.json()["state"], command

            state, _ = apply("start")
            state, _ = apply("advance", step="data")
            state, _ = apply(
                "fail", step="validate", error_code="SYNTHETIC_FAILURE", reason="Resume checkpoint"
            )
            assert state["completed_steps"] == ["data"] and state["status"] == "failed"
            state, _ = apply("resume")
            for step in STEPS[1:-1]:
                state, _ = apply("advance", step=step)
            persisted = report(database, definition, archived)
            state, last = apply("finish", report_revision_id=str(persisted.revision_id))
            assert state["status"] == "completed" and state["report_status"] == "partial"
            assert client.get(f"/v1/research-runs/{definition.run_id}").json() == state
            assert client.post(endpoint, json=last).status_code == 200
            history = client.get(endpoint, params={"limit": 2}).json()
            assert [event["sequence"] for event in history["items"]] == [1, 2]
            assert history["next_after_sequence"] == 2
    finally:
        app.dependency_overrides.clear()
