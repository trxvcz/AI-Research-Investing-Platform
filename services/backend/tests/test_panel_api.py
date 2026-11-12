"""Panel queries preserve run boundaries and immutable report revisions."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from test_runs import common, database, instrument, report, setup_run, snapshot, to_review  # noqa: F401
from test_store import next_revision

from alphasense.api import app
from alphasense.db import ReportStore, get_store
from alphasense.run_contracts import RunCreate, RunFinish
from alphasense.runs import ResearchStore


@pytest.mark.postgres
def test_panel_pages_latest_state_and_exact_revision(database: Engine) -> None:  # noqa: F811
    definition, archived = setup_run(database)
    runs = ResearchStore(database)
    state = to_review(runs, definition)
    first = report(database, definition, archived)
    runs.apply(
        definition.run_id,
        RunFinish(action="finish", report_revision_id=first.revision_id, **common(state.sequence)),
    )
    second = next_revision(first)
    store = ReportStore(database)
    store.append(second)
    other_run = definition.model_copy(update={"run_id": uuid4()})
    runs.create(other_run)
    unrelated_instrument = instrument(database, symbol="OTHER-PANEL")
    unrelated_snapshot = snapshot(database, unrelated_instrument)
    unrelated = RunCreate(
        schema_version="1.0",
        run_id=uuid4(),
        instrument_id=unrelated_instrument.instrument_id,
        as_of=definition.as_of,
        snapshot_ids=[unrelated_snapshot.snapshot_id],
    )
    runs.create(unrelated)
    app.dependency_overrides[get_store] = lambda: store
    try:
        with TestClient(app) as client:
            params = {"instrument_id": str(definition.instrument_id), "limit": 1}
            page = client.get("/v1/panel/runs", params=params)
            assert page.status_code == 200
            body = page.json()
            assert len(body["items"]) == 1
            assert body["next_after_id"] == body["items"][0]["run_id"]
            next_page = client.get(
                "/v1/panel/runs", params={**params, "after_id": body["next_after_id"]}
            ).json()
            assert next_page["next_after_id"] is None
            items = body["items"] + next_page["items"]
            assert {item["run_id"] for item in items} == {
                str(definition.run_id),
                str(other_run.run_id),
            }
            completed = next(item for item in items if item["status"] == "completed")
            assert completed["revision"] == 1
            assert completed["report_id"] == str(first.report_id)
            queued = next(item for item in items if item["status"] == "queued")
            assert queued["report_id"] is None and queued["revision"] is None
            path = f"/v1/panel/reports/{first.report_id}"
            html = client.get(path + "/1/html")
            assert html.status_code == 200
            assert str(first.revision_id) in html.text
            assert str(second.revision_id) not in html.text
            assert html.headers["content-disposition"].startswith("attachment;")
            assert html.headers["cache-control"] == "no-store"
            assert html.headers["x-content-type-options"] == "nosniff"
            assert client.get(path + "/999/html").status_code == 404
            assert client.get(path + "/0/html").status_code == 422
            assert client.get("/v1/panel/runs", params={**params, "limit": 101}).status_code == 422
    finally:
        app.dependency_overrides.clear()
