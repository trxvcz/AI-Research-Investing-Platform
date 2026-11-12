"""Durable queue uses real isolated PostgreSQL; no external data is fetched."""

from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_panel_launch import client as client
from test_panel_launch import prepared as prepared
from test_runs import database as database
from test_sec_import import SyntheticTransport

from alphasense import panel_launch, task_api, task_worker
from alphasense.api import app
from alphasense.db import ReportStore, get_store
from alphasense.panel_launch import CATALOG
from alphasense.provider_policy import ProviderDenied
from alphasense.runs import RunConflict
from alphasense.sec_contracts import SecImportRequest
from alphasense.tasks import TaskLeaseLost, TaskStore

pytestmark = pytest.mark.postgres
HEADERS = {"Origin": "http://127.0.0.1", "X-AlphaSense-Panel": "1"}


def request() -> SecImportRequest:
    return SecImportRequest(
        cik="0000320193",
        symbol="AAPL",
        exchange_mic="XNAS",
        instrument_id=uuid5(NAMESPACE_URL, "task-test-aapl"),
        run_id=uuid4(),
        pipeline_version="sec-fundamentals-v2",
    )


def test_task_is_durable_idempotent_and_identity_is_frozen(database: Engine) -> None:
    tasks = TaskStore(database)
    frozen = request()
    first = tasks.create(frozen)
    assert first.status == "queued" and first.attempt == 0
    assert TaskStore(database).get(frozen.run_id) == first
    assert tasks.create(frozen) == first
    with pytest.raises(RunConflict):
        tasks.create(frozen.model_copy(update={"symbol": "GOOGL"}))
    with pytest.raises(DBAPIError):
        with database.begin() as connection:
            connection.execute(text("UPDATE import_tasks SET symbol='GOOGL'"))


def test_claim_recovery_fences_old_owner_and_exhausts_only_crashed_leases(database: Engine) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)
    old = tasks.claim("first")
    assert old is not None
    assert tasks.claim("second") is None
    for attempt in (2, 3):
        with database.begin() as connection:
            connection.execute(
                text(
                    "UPDATE import_tasks SET lease_expires_at=clock_timestamp()-INTERVAL '1 second'"
                )
            )
        new = tasks.claim("recovery")
        assert new is not None
        assert tasks.get(frozen.run_id).attempt == attempt
        with pytest.raises(TaskLeaseLost):
            tasks.heartbeat(frozen.run_id, old[0])
        with pytest.raises(TaskLeaseLost):
            tasks.finish(
                frozen.run_id,
                old[0],
                instrument_id=frozen.instrument_id,
                report_id=uuid4(),
                revision=1,
            )
        old = new
    with database.begin() as connection:
        connection.execute(
            text("UPDATE import_tasks SET lease_expires_at=clock_timestamp()-INTERVAL '1 second'")
        )
    assert tasks.claim("fourth") is None
    assert tasks.get(frozen.run_id).error_code == "RECOVERY_EXHAUSTED"


def test_provider_error_is_terminal_and_never_auto_retried(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = TaskStore(database)
    frozen = request()
    tasks.create(frozen)

    def denied():
        raise ProviderDenied("QUOTA_EXHAUSTED")

    monkeypatch.setattr(task_worker, "load_policy", denied)
    assert task_worker.process_task_once(database, "test-worker")
    state = tasks.get(frozen.run_id)
    assert state.status == "failed" and state.error_code == "SOURCE_POLICY_DENIED"
    assert state.attempt == 1 and state.lease_expires_at is None
    assert not task_worker.process_task_once(database, "test-worker")


def test_enqueue_has_no_import_and_retry_ignores_changed_catalog(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    payload = {"symbol": "AAPL", "run_id": str(uuid4())}
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            assert client.post("/v1/panel/tasks", json=payload).status_code == 403
            response = client.post("/v1/panel/tasks", json=payload, headers=HEADERS)
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "queued"
            monkeypatch.delitem(CATALOG, "AAPL")
            replay = client.post("/v1/panel/tasks", json=payload, headers=HEADERS)
            assert replay.status_code == 200 and replay.json() == response.json()
            assert client.get("/v1/panel/tasks").json()["items"] == [response.json()]
            assert client.get("/v1/panel/tasks/" + payload["run_id"]).status_code == 200
            assert (
                client.post(
                    "/v1/panel/tasks", json={**payload, "symbol": "GOOGL"}, headers=HEADERS
                ).status_code
                == 409
            )
            with database.connect() as connection:
                assert connection.scalar(text("SELECT count(*) FROM research_runs")) == 0
                assert connection.scalar(text("SELECT count(*) FROM raw_snapshots")) == 0
    finally:
        app.dependency_overrides.clear()


def test_worker_completes_only_after_persisted_report(
    database: Engine,
    prepared: tuple[TestClient, SyntheticTransport],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, transport = prepared
    monkeypatch.setattr(task_worker, "load_policy", panel_launch.load_policy)
    body = {"symbol": "AAPL", "run_id": str(uuid4())}
    result = client.post("/v1/panel/tasks", json=body, headers=HEADERS)
    assert result.status_code == 202 and result.json()["status"] == "queued"
    assert transport.calls == []
    # A legacy synchronous call holding its lock cannot prevent task recovery.
    with database.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('panel-analysis-launch-v1',0))")
        )
        assert task_worker.process_task_once(database, "task-test")
    state = client.get("/v1/panel/tasks/" + body["run_id"]).json()
    assert state["status"] == "completed" and state["stage"] == "completed"
    assert state["report_id"] and state["revision"] == 1
    assert len(transport.calls) == 8
    assert not task_worker.process_task_once(database, "task-test")
    assert len(transport.calls) == 8


def test_explicit_market_is_frozen_and_legacy_retry_remains_valid(database: Engine) -> None:
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    body = {"symbol": "AAPL", "run_id": str(uuid4()), "exchange_mic": "XNAS"}
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            result = client.post("/v1/panel/tasks", json=body, headers=HEADERS)
            assert result.status_code == 202
            assert result.json()["exchange_mic"] == "XNAS"
            for market in ("XNYS", "XWAR"):
                assert (
                    client.post(
                        "/v1/panel/tasks", json={**body, "exchange_mic": market}, headers=HEADERS
                    ).status_code
                    == 409
                )
            legacy = {key: value for key, value in body.items() if key != "exchange_mic"}
            assert (
                client.post("/v1/panel/tasks", json=legacy, headers=HEADERS).json() == result.json()
            )
            assert client.get("/v1/panel/tasks/" + body["run_id"]).json()["exchange_mic"] == "XNAS"
    finally:
        app.dependency_overrides.clear()


def test_gpw_never_resolves_sec_or_enqueues(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args):
        raise AssertionError("GPW must not resolve a SEC issuer")

    monkeypatch.setattr(task_api, "resolve_analysis_request", forbidden)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            body = {"symbol": "AAPL", "run_id": str(uuid4()), "exchange_mic": "XWAR"}
            assert client.post("/v1/panel/tasks", json=body).status_code == 403
            response = client.post("/v1/panel/tasks", json=body, headers=HEADERS)
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "UNSUPPORTED_MARKET"
            assert client.get("/v1/panel/tasks").json()["items"] == []
    finally:
        app.dependency_overrides.clear()


def test_wrong_us_market_is_rejected_without_enqueue(database: Engine) -> None:
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            response = client.post(
                "/v1/panel/tasks",
                json={"symbol": "AAPL", "run_id": str(uuid4()), "exchange_mic": "XNYS"},
                headers=HEADERS,
            )
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == "MARKET_IDENTITY_CONFLICT"
            assert client.get("/v1/panel/tasks").json()["items"] == []
    finally:
        app.dependency_overrides.clear()
