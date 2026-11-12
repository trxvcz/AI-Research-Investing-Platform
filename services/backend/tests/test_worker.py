"""Real PostgreSQL ownership, recovery and deterministic-worker acceptance tests."""

import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from test_runs import database as database
from test_runs import instrument, setup_run

from alphasense.api import app
from alphasense.db import ReportStore, StoreUnavailable
from alphasense.db_schema import report_revisions, research_runs, worker_claims, worker_jobs
from alphasense.instrument_contracts import InstrumentCreate
from alphasense.instruments import InstrumentStore
from alphasense.report_contracts import ReportContent, ReportRevision, seal_report
from alphasense.run_contracts import STEPS, RunAdvance, RunCreate, RunFinish, RunStart
from alphasense.runs import ResearchStore, RunConflict, get_research_store
from alphasense.snapshot_contracts import SnapshotCreate, SnapshotRecord
from alphasense.snapshots import SnapshotStore
from alphasense.worker import process_once
from alphasense.worker_contracts import WorkerLease
from alphasense.worker_engine import compile_report
from alphasense.worker_store import WorkerLeaseLost, WorkerStore, get_worker_store

pytestmark = pytest.mark.postgres
FIXTURES = Path(__file__).parent / "fixtures"
IMPLEMENTATION = hashlib.sha256(b"synthetic-worker-test-implementation").hexdigest()
GIT_SHA = "6d7e7269fe72199c365b157a456ddab399f85e93"


def auto_definition(engine: Engine) -> tuple[RunCreate, SnapshotRecord]:
    definition, snapshot = setup_run(engine)
    payload = definition.model_dump(mode="python")
    payload["pipeline_version"] = "deterministic-research-v1"
    return RunCreate.model_validate(payload), snapshot


def claim(store: WorkerStore, worker: str = "synthetic-worker") -> WorkerLease:
    lease = store.claim(worker, IMPLEMENTATION, GIT_SHA)
    assert lease is not None
    return lease


def expire(engine: Engine, lease: WorkerLease) -> None:
    # Operational job state is mutable by design. Do not sleep or alter immutable claims.
    with engine.begin() as connection:
        connection.execute(
            worker_jobs.update()
            .where(worker_jobs.c.run_id == lease.run_id)
            .values(lease_expires_at=text("clock_timestamp() - INTERVAL '1 second'"))
        )


def advance(store: WorkerStore, lease: WorkerLease, engine: Engine, step: str) -> Any:
    state = ResearchStore(engine).get(lease.run_id)
    return store.apply(
        lease,
        RunAdvance(
            action="advance",
            step=step,
            actor=lease.worker_id,
            request_id=uuid4(),
            expected_sequence=state.sequence,
        ),
    )


def to_report(store: WorkerStore, lease: WorkerLease, engine: Engine) -> None:
    for step in STEPS[:4]:
        advance(store, lease, engine, step)


def report_for_run(definition: RunCreate, snapshot: SnapshotRecord) -> ReportRevision:
    payload = json.loads((FIXTURES / "report.synthetic.json").read_text("utf-8"))
    payload.pop("checksum")
    payload.pop("input_sha256")
    payload.update(report_id=str(uuid4()), revision_id=str(uuid4()))
    payload["input"]["instrument_id"] = str(definition.instrument_id)
    payload["input"]["as_of"] = definition.as_of.isoformat()
    payload["input"]["observations"][0]["snapshot_id"] = str(snapshot.snapshot_id)
    payload["sources"][0].update(
        snapshot_id=str(snapshot.snapshot_id),
        source_id=snapshot.source_id,
        sha256=snapshot.sha256,
        retrieved_at=snapshot.retrieved_at.isoformat(),
        url=str(snapshot.source_url) if snapshot.source_url is not None else None,
        license=snapshot.license,
    )
    return seal_report(ReportContent.model_validate(payload))


def publication_command(engine: Engine, lease: WorkerLease) -> RunAdvance:
    return RunAdvance(
        action="advance",
        step="report",
        actor=lease.worker_id,
        request_id=uuid4(),
        expected_sequence=ResearchStore(engine).get(lease.run_id).sequence,
    )


def packet_run(
    engine: Engine, *, blocked: bool = False, invalid: bool = False, unstorable: bool = False
) -> RunCreate:
    identity: InstrumentCreate = instrument(engine)
    snapshot_id = uuid4()
    payload = json.loads((FIXTURES / "research-input.synthetic.json").read_text("utf-8"))
    payload["instrument_id"] = str(identity.instrument_id)
    payload["observations"][0]["snapshot_id"] = str(snapshot_id)
    payload["observations"][0]["unit"] = "currency"
    if unstorable:
        payload["observations"][1]["reason"] = "Synthetic missing input\x00private"
    if blocked:
        payload["observations"] = payload["observations"][1:]
    raw = (
        b'{"not":"a research packet"}'
        if invalid
        else json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    )
    snapshot = SnapshotCreate(
        schema_version="1.0",
        snapshot_id=snapshot_id,
        instrument_id=identity.instrument_id,
        data_origin="synthetic",
        source_id="synthetic-demo",
        source_url=None,
        license="generated fixture",
        as_of=payload["as_of"],
        available_at="2024-01-16T00:00:00Z",
        retrieved_at="2024-01-17T00:00:00Z",
        media_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        content_base64=base64.b64encode(raw).decode("ascii"),
    )
    SnapshotStore(engine).create(snapshot)
    definition = RunCreate(
        schema_version="1.0",
        run_id=uuid4(),
        instrument_id=identity.instrument_id,
        as_of=payload["as_of"],
        snapshot_ids=[snapshot_id],
        pipeline_version="deterministic-research-v1",
    )
    ResearchStore(engine).create(definition)
    return definition


def test_claim_ignores_manual_and_public_mutation_rejects_automatic(database: Engine) -> None:
    manual, _snapshot = setup_run(database)
    runs = ResearchStore(database)
    runs.create(manual)
    jobs = WorkerStore(database)
    assert jobs.claim("synthetic-worker", IMPLEMENTATION, GIT_SHA) is None
    auto = RunCreate.model_validate(
        {**manual.model_dump(), "run_id": uuid4(), "pipeline_version": "deterministic-research-v1"}
    )
    runs.create(auto)
    with pytest.raises(RunConflict):
        runs.apply(
            auto.run_id,
            RunStart(
                action="start", actor="public-operator", request_id=uuid4(), expected_sequence=1
            ),
        )
    lease = claim(jobs)
    assert lease.run_id == auto.run_id
    with database.connect() as connection:
        assert (
            connection.scalar(
                select(worker_jobs.c.run_id).where(worker_jobs.c.run_id == manual.run_id)
            )
            is None
        )
    assert runs.get(manual.run_id).status == "queued"
    assert runs.get(auto.run_id).status == "running"


def test_parallel_claims_have_exactly_one_owner(database: Engine) -> None:
    definition, _snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    barrier = Barrier(2)

    def attempt(index: int) -> WorkerLease | None:
        barrier.wait(timeout=10)
        return WorkerStore(database).claim(f"synthetic-worker-{index}", IMPLEMENTATION, GIT_SHA)

    with ThreadPoolExecutor(max_workers=2) as threads:
        leases = list(threads.map(attempt, range(2)))
    winners = [lease for lease in leases if lease is not None]
    assert len(winners) == 1 and winners[0].attempt == 1
    with database.connect() as connection:
        assert len(connection.execute(select(worker_claims)).all()) == 1
    assert ResearchStore(database).get(definition.run_id).sequence == 2


def test_skip_locked_claims_next_run_without_waiting(database: Engine) -> None:
    first, _snapshot = auto_definition(database)
    second = RunCreate.model_validate({**first.model_dump(), "run_id": uuid4()})
    runs = ResearchStore(database)
    runs.create(first)
    runs.create(second)
    with database.connect() as locked:
        locked.execute(
            select(research_runs).where(research_runs.c.run_id == first.run_id).with_for_update()
        )
        lease = claim(WorkerStore(database))
        assert lease.run_id == second.run_id
    assert runs.get(first.run_id).status == "queued"


def test_renew_and_expired_takeover_fence_stale_owner(database: Engine) -> None:
    definition, _snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    first = claim(jobs, "first-worker")
    renewed = jobs.renew(first)
    assert renewed.token == first.token and renewed.attempt == 1
    assert renewed.expires_at > first.expires_at
    assert jobs.claim("other-worker", IMPLEMENTATION, GIT_SHA) is None
    expire(database, renewed)
    second = claim(jobs, "second-worker")
    assert second.attempt == 2 and second.token != first.token
    before = ResearchStore(database).get(definition.run_id).sequence
    with pytest.raises(WorkerLeaseLost):
        jobs.renew(first)
    with pytest.raises(WorkerLeaseLost):
        advance(jobs, first, database, "data")
    assert ResearchStore(database).get(definition.run_id).sequence == before
    assert advance(jobs, second, database, "data").state.current_step == "validate"


def test_three_expired_claims_end_dead_without_unbounded_retry(database: Engine) -> None:
    definition, _snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    for attempt in (1, 2, 3):
        lease = claim(jobs)
        assert lease.attempt == attempt
        expire(database, lease)
    assert jobs.claim("synthetic-worker", IMPLEMENTATION, GIT_SHA) is None
    job = jobs.get_job(definition.run_id)
    assert job.status == "dead" and job.attempts == 3
    assert job.last_error_code == "WORKER_ATTEMPTS_EXHAUSTED"
    state = ResearchStore(database).get(definition.run_id)
    assert state.status == "failed" and state.current_step == "data"
    assert jobs.claim("synthetic-worker", IMPLEMENTATION, GIT_SHA) is None


@pytest.mark.parametrize("field", ["implementation", "git_sha"])
def test_expired_provenance_change_is_dead_not_reinterpreted(database: Engine, field: str) -> None:
    definition, _snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    lease = claim(jobs)
    expire(database, lease)
    implementation = hashlib.sha256(b"different fixture implementation").hexdigest()
    git_sha = "a" * 40
    assert (
        jobs.claim(
            "new-worker",
            implementation if field == "implementation" else IMPLEMENTATION,
            git_sha if field == "git_sha" else GIT_SHA,
        )
        is None
    )
    assert jobs.get_job(definition.run_id).status == "dead"
    assert jobs.get_job(definition.run_id).last_error_code == "WORKER_CODE_CHANGED"
    assert ResearchStore(database).get(definition.run_id).error_code == "WORKER_CODE_CHANGED"


def test_stale_publish_leaves_no_report_or_step(database: Engine) -> None:
    definition, snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    lease = claim(jobs)
    to_report(jobs, lease, database)
    report = report_for_run(definition, snapshot)
    command = publication_command(database, lease)
    expire(database, lease)
    replacement = claim(jobs, "replacement-worker")
    assert replacement.token != lease.token
    with pytest.raises(WorkerLeaseLost):
        jobs.publish(lease, report, command)
    with database.connect() as connection:
        assert connection.execute(select(report_revisions)).all() == []
    assert ResearchStore(database).get(definition.run_id).current_step == "report"


def lose_second_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    from alphasense import worker_store

    original = worker_store._fence
    calls = 0

    def fenced(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise WorkerLeaseLost("Simulated loss at the post-write fence")
        original(*args, **kwargs)

    monkeypatch.setattr(worker_store, "_fence", fenced)


def test_post_write_fence_rolls_back_report_and_advance(
    database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition, snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    lease = claim(jobs)
    to_report(jobs, lease, database)
    report = report_for_run(definition, snapshot)
    command = publication_command(database, lease)
    before = ResearchStore(database).get(definition.run_id)
    lose_second_fence(monkeypatch)
    with pytest.raises(WorkerLeaseLost):
        jobs.publish(lease, report, command)
    assert ResearchStore(database).get(definition.run_id).model_dump() == before.model_dump()
    with database.connect() as connection:
        assert connection.execute(select(report_revisions)).all() == []
    assert jobs.get_job(definition.run_id).status == "running"


@pytest.mark.parametrize("operation", ["finish", "fail"])
def test_terminal_update_rolls_back_with_failed_post_fence(
    database: Engine, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    definition, snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    lease = claim(jobs)
    if operation == "finish":
        to_report(jobs, lease, database)
        report = report_for_run(definition, snapshot)
        jobs.publish(lease, report, publication_command(database, lease))
    before = ResearchStore(database).get(definition.run_id)
    lose_second_fence(monkeypatch)
    with pytest.raises(WorkerLeaseLost):
        if operation == "fail":
            jobs.fail(lease, "SYNTHETIC_FAILURE", "Synthetic rejected input")
        else:
            jobs.finish(
                lease,
                RunFinish(
                    action="finish",
                    report_revision_id=report.revision_id,
                    request_id=uuid4(),
                    expected_sequence=before.sequence,
                    actor=lease.worker_id,
                ),
            )
    assert ResearchStore(database).get(definition.run_id).model_dump() == before.model_dump()
    assert jobs.get_job(definition.run_id).status == "running"


@pytest.mark.parametrize("blocked", [False, True])
def test_process_once_completes_without_inventing_full_research(
    database: Engine, blocked: bool
) -> None:
    definition = packet_run(database, blocked=blocked)
    assert process_once(database, "synthetic-worker", GIT_SHA, IMPLEMENTATION)
    state = ResearchStore(database).get(definition.run_id)
    assert state.status == "completed" and state.completed_steps == list(STEPS)
    assert state.report_status == ("blocked" if blocked else "partial")
    assert WorkerStore(database).get_job(definition.run_id).status == "completed"
    with database.connect() as connection:
        rows = connection.execute(select(report_revisions)).mappings().all()
    assert len(rows) == 1
    stored = ReportRevision.model_validate(rows[0]["payload"])
    assert stored.model_provenance is None and stored.chart_artifact_ids == []
    assert not process_once(database, "synthetic-worker", GIT_SHA, IMPLEMENTATION)


def test_invalid_packet_is_dead_with_failure_manifest_and_no_report(database: Engine) -> None:
    definition = packet_run(database, invalid=True)
    assert process_once(database, "synthetic-worker", GIT_SHA, IMPLEMENTATION)
    state = ResearchStore(database).get(definition.run_id)
    assert state.status == "failed" and state.current_step == "validate"
    assert state.completed_steps == ["data"] and state.report_revision_id is None
    assert state.error_code is not None
    assert WorkerStore(database).get_job(definition.run_id).status == "dead"
    with database.connect() as connection:
        assert connection.execute(select(report_revisions)).all() == []


def test_unstorable_packet_is_dead_after_first_attempt_and_raw_bytes_remain(
    database: Engine,
) -> None:
    definition = packet_run(database, unstorable=True)
    original = SnapshotStore(database).content(definition.snapshot_ids[0])[1]
    assert process_once(database, "synthetic-worker", GIT_SHA, IMPLEMENTATION)
    state = ResearchStore(database).get(definition.run_id)
    assert state.status == "failed" and state.error_code == "INPUT_UNSTORABLE"
    assert state.current_step == "report" and state.report_revision_id is None
    job = WorkerStore(database).get_job(definition.run_id)
    assert job.status == "dead" and job.attempts == 1
    assert SnapshotStore(database).content(definition.snapshot_ids[0])[1] == original
    with database.connect() as connection:
        assert connection.execute(select(report_revisions)).all() == []


def test_restart_after_publication_finishes_without_duplicate_revision(database: Engine) -> None:
    definition = packet_run(database)
    jobs = WorkerStore(database)
    lease = claim(jobs, "first-worker")
    to_report(jobs, lease, database)
    state = ResearchStore(database).get(definition.run_id)
    identity = InstrumentStore(database).get(state.instrument_id)
    snapshots = [SnapshotStore(database).content(identifier) for identifier in state.snapshot_ids]
    report = compile_report(state, identity, snapshots, GIT_SHA, IMPLEMENTATION)
    jobs.publish(lease, report, publication_command(database, lease))
    assert ResearchStore(database).get(definition.run_id).current_step == "review"
    expire(database, lease)
    assert process_once(database, "replacement-worker", GIT_SHA, IMPLEMENTATION)
    assert jobs.get_job(definition.run_id).attempts == 2
    assert jobs.get_job(definition.run_id).status == "completed"
    with database.connect() as connection:
        assert len(connection.execute(select(report_revisions)).all()) == 1
    assert ReportStore(database).get_report(report.report_id).checksum == report.checksum


def test_worker_job_api_has_no_token_and_http_cannot_mutate_auto_run(database: Engine) -> None:
    definition, _snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    lease = claim(jobs)
    app.dependency_overrides[get_worker_store] = lambda: jobs
    app.dependency_overrides[get_research_store] = lambda: ResearchStore(database)
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/research-runs/{definition.run_id}/worker-job")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
            assert "lease_token" not in response.json() and "token" not in response.json()
            assert str(lease.token) not in response.text
            state = ResearchStore(database).get(definition.run_id)
            request = RunAdvance(
                action="advance",
                step="data",
                request_id=uuid4(),
                actor="public-client",
                expected_sequence=state.sequence,
            )
            rejected = client.post(
                f"/v1/research-runs/{definition.run_id}/events",
                json=request.model_dump(mode="json"),
            )
            assert rejected.status_code == 409
            assert str(lease.token) not in rejected.text
        assert ResearchStore(database).get(definition.run_id).sequence == state.sequence
    finally:
        app.dependency_overrides.pop(get_worker_store, None)
        app.dependency_overrides.pop(get_research_store, None)


def test_job_read_sanitizes_invalid_operational_metadata(database: Engine) -> None:
    definition, _snapshot = auto_definition(database)
    ResearchStore(database).create(definition)
    jobs = WorkerStore(database)
    claim(jobs)
    with database.begin() as connection:
        connection.execute(text("ALTER TABLE worker_jobs DISABLE TRIGGER USER"))
        connection.execute(
            worker_jobs.update()
            .where(worker_jobs.c.run_id == definition.run_id)
            .values(worker_id=" leading-space")
        )
        connection.execute(text("ALTER TABLE worker_jobs ENABLE TRIGGER USER"))
    with pytest.raises(StoreUnavailable):
        jobs.get_job(definition.run_id)


def test_documented_worker_fixtures_produce_reproducible_partial_report(database: Engine) -> None:
    identity = InstrumentCreate.model_validate_json(
        (FIXTURES / "worker-instrument.synthetic.json").read_bytes()
    )
    archived = SnapshotCreate.model_validate_json(
        (FIXTURES / "worker-snapshot.synthetic.json").read_bytes()
    )
    definition = RunCreate.model_validate_json(
        (FIXTURES / "worker-run.synthetic.json").read_bytes()
    )
    InstrumentStore(database).create(identity)
    SnapshotStore(database).create(archived)
    ResearchStore(database).create(definition)
    assert process_once(database, "documented-worker", GIT_SHA, IMPLEMENTATION)
    state = ResearchStore(database).get(definition.run_id)
    assert state.status == "completed" and state.report_status == "partial"
    with database.connect() as connection:
        report = ReportRevision.model_validate(
            connection.execute(select(report_revisions.c.payload)).scalar_one()
        )
    assert "net_margin=0.25" in report.fundamental_section.findings[-1].text
    assert "last3_observation_sma=2.0" in report.technical_section.findings[0].text
    assert not process_once(database, "documented-worker", GIT_SHA, IMPLEMENTATION)


def test_cli_once_uses_workspace_provenance_and_exits_cleanly(
    database: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from alphasense import worker

    definition = packet_run(database)
    monkeypatch.setattr(worker, "get_store", lambda: ReportStore(database))
    assert worker.main(["--once", "--worker-id", "cli-test"]) == 0
    assert "processed one run" in capsys.readouterr().out
    job = WorkerStore(database).get_job(definition.run_id)
    assert job.implementation_hash == worker.implementation_fingerprint()
    assert job.pipeline_git_sha == worker.current_git_sha()
    assert job.status == "completed"


def test_targeted_execution_preserves_other_queued_runs(database: Engine) -> None:
    first = packet_run(database)
    second = RunCreate.model_validate({**first.model_dump(), "run_id": uuid4()})
    ResearchStore(database).create(second)
    assert process_once(database, "targeted-worker", GIT_SHA, IMPLEMENTATION, run_id=second.run_id)
    assert ResearchStore(database).get(second.run_id).status == "completed"
    assert ResearchStore(database).get(first.run_id).status == "queued"
    assert not process_once(
        database, "targeted-worker", GIT_SHA, IMPLEMENTATION, run_id=second.run_id
    )
