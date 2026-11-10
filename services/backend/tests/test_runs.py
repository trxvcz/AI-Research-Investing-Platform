"""Real PostgreSQL manual-ledger tests; no worker, fetch or model invocation."""

import base64
import hashlib
import json
import os
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text

from alphasense.db import CorruptReport, ReportStore, StoreUnavailable
from alphasense.db_schema import research_runs, run_events, run_snapshots
from alphasense.instrument_contracts import InstrumentCreate
from alphasense.instruments import InstrumentStore
from alphasense.report_contracts import ReportContent, ReportRevision, seal_report
from alphasense.run_contracts import (
    STEPS,
    RunAdvance,
    RunCreate,
    RunFail,
    RunFinish,
    RunResume,
    RunStart,
    RunState,
)
from alphasense.runs import ResearchStore, RunConflict, RunNotFound
from alphasense.snapshot_contracts import SnapshotCreate, SnapshotRecord
from alphasense.snapshots import SnapshotStore

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def database() -> Iterator[Engine]:
    dsn = os.environ.get("ALPHASENSE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real PostgreSQL requires ALPHASENSE_TEST_DATABASE_URL")
    schema = "research_test_" + uuid4().hex
    assert re.fullmatch(r"research_test_[a-f0-9]{32}", schema)
    admin = create_engine(dsn, hide_parameters=True)
    engine = create_engine(
        dsn, hide_parameters=True, connect_args={"options": f"-c search_path={schema}"}
    )
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.begin() as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def instrument(engine: Engine, **changes: Any) -> InstrumentCreate:
    payload = json.loads((FIXTURES / "instrument.synthetic.json").read_text("utf-8"))
    payload.update(instrument_id=str(uuid4()), symbol="SYNTH-RUN")
    payload.update(changes)
    data = InstrumentCreate.model_validate(payload)
    InstrumentStore(engine).create(data)
    return data


def snapshot(engine: Engine, identity: InstrumentCreate, **changes: Any) -> SnapshotRecord:
    content = b'{"synthetic":true,"revenue":0}\n'
    payload = {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "instrument_id": str(identity.instrument_id),
        "data_origin": identity.data_origin,
        "source_id": "synthetic-demo",
        "source_url": None,
        "license": "generated fixture",
        "as_of": "2024-01-31T00:00:00Z",
        "available_at": "2024-01-16T00:00:00Z",
        "retrieved_at": "2024-01-17T00:00:00Z",
        "media_type": "application/json",
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_length": len(content),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    payload.update(changes)
    written = SnapshotStore(engine).create(SnapshotCreate.model_validate(payload))
    return SnapshotRecord.model_validate(written.model_dump(exclude={"created"}))


def setup_run(engine: Engine) -> tuple[RunCreate, SnapshotRecord]:
    identity = instrument(engine)
    archived = snapshot(engine, identity)
    definition = RunCreate(
        schema_version="1.0",
        run_id=uuid4(),
        instrument_id=identity.instrument_id,
        as_of="2024-02-01T00:00:00Z",
        snapshot_ids=[archived.snapshot_id],
    )
    return definition, archived


def common(sequence: int, request_id: UUID | None = None) -> dict[str, Any]:
    return {
        "request_id": request_id or uuid4(),
        "expected_sequence": sequence,
        "actor": "synthetic-test-operator",
    }


def to_review(store: ResearchStore, definition: RunCreate) -> RunState:
    state = store.create(definition)
    state = store.apply(definition.run_id, RunStart(action="start", **common(state.sequence))).state
    for step in STEPS[:-1]:
        state = store.apply(
            definition.run_id, RunAdvance(action="advance", step=step, **common(state.sequence))
        ).state
    return state


def report(
    engine: Engine, definition: RunCreate, archived: SnapshotRecord, **changes: Any
) -> ReportRevision:
    payload = json.loads((FIXTURES / "report.synthetic.json").read_text("utf-8"))
    payload.pop("checksum")
    payload.pop("input_sha256")
    payload["report_id"] = str(uuid4())
    payload["revision_id"] = str(uuid4())
    payload["input"]["instrument_id"] = str(definition.instrument_id)
    payload["input"]["as_of"] = definition.as_of.isoformat()
    payload["input"]["observations"][0]["snapshot_id"] = str(archived.snapshot_id)
    payload["sources"][0].update(
        snapshot_id=str(archived.snapshot_id),
        source_id=archived.source_id,
        sha256=archived.sha256,
        retrieved_at=archived.retrieved_at.isoformat(),
        url=str(archived.source_url) if archived.source_url is not None else None,
        license=archived.license,
    )
    payload.update(changes)
    sealed = seal_report(ReportContent.model_validate(payload))
    ReportStore(engine).append(sealed)
    return sealed


def test_non_postgres_engine_is_rejected() -> None:
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(StoreUnavailable):
            ResearchStore(engine)
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_create_get_retry_and_frozen_inputs(database: Engine) -> None:
    definition, _snapshot = setup_run(database)
    store = ResearchStore(database)
    first = store.create(definition)
    assert first.created is True
    assert first.sequence == 1 and first.status == "queued"
    assert first.current_step == "data" and first.completed_steps == []
    retry = store.create(definition)
    assert retry.created is False
    assert retry.model_dump(exclude={"created"}) == first.model_dump(exclude={"created"})
    assert store.get(definition.run_id).snapshot_ids == definition.snapshot_ids
    modified = definition.model_dump()
    modified["as_of"] = "2024-02-02T00:00:00Z"
    with pytest.raises(RunConflict):
        store.create(RunCreate.model_validate(modified))
    with database.connect() as connection:
        assert len(connection.execute(select(run_snapshots)).all()) == 1
        assert len(connection.execute(select(run_events)).all()) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("case", ["unknown", "future", "future_cutoff", "other_instrument"])
def test_ineligible_snapshot_does_not_leave_partial_run(database: Engine, case: str) -> None:
    identity = instrument(database)
    changes: dict[str, Any] = {}
    if case == "unknown":
        changes["available_at"] = None
    elif case == "future":
        changes.update(
            available_at="2024-02-02T00:00:00Z",
            as_of="2024-02-03T00:00:00Z",
            retrieved_at="2024-02-04T00:00:00Z",
        )
    elif case == "future_cutoff":
        changes["as_of"] = "2024-02-03T00:00:00Z"
    else:
        identity = instrument(database, symbol="SYNTH-OTHER")
    archived = snapshot(database, identity, **changes)
    run_identity = identity if case != "other_instrument" else instrument(database, symbol="RUN3")
    definition = RunCreate(
        schema_version="1.0",
        run_id=uuid4(),
        instrument_id=run_identity.instrument_id,
        as_of="2024-02-01T00:00:00Z",
        snapshot_ids=[archived.snapshot_id],
    )
    with pytest.raises(RunConflict):
        ResearchStore(database).create(definition)
    with database.connect() as connection:
        assert connection.execute(select(research_runs)).all() == []
        assert connection.execute(select(run_snapshots)).all() == []
        assert connection.execute(select(run_events)).all() == []


@pytest.mark.postgres
def test_step_order_retry_and_expected_sequence(database: Engine) -> None:
    definition, _snapshot = setup_run(database)
    store = ResearchStore(database)
    store.create(definition)
    with pytest.raises(RunConflict):
        store.apply(definition.run_id, RunAdvance(action="advance", step="data", **common(1)))
    start = RunStart(action="start", **common(1))
    started = store.apply(definition.run_id, start)
    assert started.sequence == 2 and started.created is True
    with pytest.raises(RunConflict):
        store.apply(definition.run_id, RunAdvance(action="advance", step="data", **common(1)))
    with pytest.raises(RunConflict):
        store.apply(definition.run_id, RunAdvance(action="advance", step="validate", **common(2)))
    advanced = store.apply(
        definition.run_id, RunAdvance(action="advance", step="data", **common(2))
    )
    retry = store.apply(definition.run_id, start)
    assert retry.created is False and retry.sequence == 2
    assert retry.state.model_dump() == started.state.model_dump()
    assert store.get(definition.run_id).sequence == advanced.sequence == 3
    assert store.create(definition).sequence == 3
    changed = start.model_dump()
    changed["actor"] = "OTHER-ACTOR"
    with pytest.raises(RunConflict):
        store.apply(definition.run_id, RunStart.model_validate(changed))


@pytest.mark.postgres
def test_fail_resume_survives_new_engine_and_keeps_completed_prefix(database: Engine) -> None:
    definition, _snapshot = setup_run(database)
    store = ResearchStore(database)
    store.create(definition)
    store.apply(definition.run_id, RunStart(action="start", **common(1)))
    store.apply(definition.run_id, RunAdvance(action="advance", step="data", **common(2)))
    failed = store.apply(
        definition.run_id,
        RunFail(
            action="fail",
            step="validate",
            error_code="BAD_INPUT",
            reason="Synthetic failure",
            **common(3),
        ),
    )
    options = dict(database.url.query)
    _ = options  # Preserve the isolated schema through the original connection options.
    with database.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    replacement = create_engine(
        database.url, hide_parameters=True, connect_args={"options": f"-c search_path={schema}"}
    )
    try:
        resumed_store = ResearchStore(replacement)
        before = resumed_store.get(definition.run_id)
        assert before.status == "failed" and before.completed_steps == ["data"]
        assert before.updated_at == failed.state.updated_at
        resumed = resumed_store.apply(definition.run_id, RunResume(action="resume", **common(4)))
        assert resumed.state.status == "running" and resumed.state.current_step == "validate"
        assert resumed.state.completed_steps == ["data"] and resumed.state.error_code is None
    finally:
        replacement.dispose()


@pytest.mark.postgres
def test_parallel_expected_sequence_has_one_winner(database: Engine) -> None:
    definition, _snapshot = setup_run(database)
    ResearchStore(database).create(definition)
    barrier = Barrier(2)

    def start(_index: int) -> str:
        barrier.wait(timeout=10)
        try:
            ResearchStore(database).apply(definition.run_id, RunStart(action="start", **common(1)))
            return "created"
        except RunConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(start, range(2))) == ["conflict", "created"]
    assert ResearchStore(database).get(definition.run_id).sequence == 2


@pytest.mark.postgres
def test_finish_binds_existing_report_and_prevents_later_changes(database: Engine) -> None:
    definition, archived = setup_run(database)
    store = ResearchStore(database)
    state = to_review(store, definition)
    assert state.current_step == "review" and state.completed_steps == list(STEPS[:-1])
    with pytest.raises(RunConflict):
        store.apply(definition.run_id, RunAdvance(action="advance", step="review", **common(7)))
    sealed = report(database, definition, archived)
    finish = RunFinish(action="finish", report_revision_id=sealed.revision_id, **common(7))
    result = store.apply(definition.run_id, finish)
    assert result.state.status == "completed" and result.state.report_status == "partial"
    assert result.state.completed_steps == list(STEPS)
    assert store.get(definition.run_id).report_revision_id == sealed.revision_id
    assert store.apply(definition.run_id, finish).created is False
    with pytest.raises(RunConflict):
        store.apply(definition.run_id, RunResume(action="resume", **common(8)))


@pytest.mark.postgres
def test_failed_final_report_is_terminal_and_not_resumable(database: Engine) -> None:
    definition, archived = setup_run(database)
    store = ResearchStore(database)
    to_review(store, definition)
    sealed = report(
        database,
        definition,
        archived,
        status="failed",
        technical_section={
            "status": "failed",
            "findings": [],
            "reason": "Synthetic technical failure",
        },
    )
    result = store.apply(
        definition.run_id,
        RunFinish(action="finish", report_revision_id=sealed.revision_id, **common(7)),
    )
    assert result.state.status == "failed" and result.state.report_status == "failed"
    assert result.state.error_code == "REPORT_FAILED" and result.state.current_step is None
    with pytest.raises(RunConflict):
        store.apply(definition.run_id, RunResume(action="resume", **common(8)))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "case",
    ["extraneous_snapshot", "sha", "source_id", "license", "retrieved", "observation_available"],
)
def test_finalization_rejects_report_sources_outside_frozen_archive(
    database: Engine, case: str
) -> None:
    definition, archived = setup_run(database)
    store = ResearchStore(database)
    to_review(store, definition)
    sealed = report(database, definition, archived)
    payload = sealed.model_dump(mode="json", exclude={"checksum", "input_sha256"})
    payload["report_id"] = str(uuid4())
    payload["revision_id"] = str(uuid4())
    source = payload["sources"][0]
    if case == "extraneous_snapshot":
        other = snapshot(
            database,
            InstrumentCreate.model_validate(
                InstrumentStore(database)
                .get(definition.instrument_id)
                .model_dump(exclude={"created_at"})
            ),
        )
        source["snapshot_id"] = str(other.snapshot_id)
        payload["input"]["observations"][0]["snapshot_id"] = str(other.snapshot_id)
    elif case == "sha":
        source["sha256"] = "0" * 64
    elif case == "source_id":
        source["source_id"] = "OTHER-SOURCE"
        payload["input"]["observations"][0]["source_id"] = "OTHER-SOURCE"
    elif case == "license":
        source["license"] = "DIFFERENT-LICENSE"
    elif case == "observation_available":
        payload["input"]["observations"][0]["available_at"] = "2024-01-15T00:00:00Z"
    else:
        source["retrieved_at"] = "2024-01-18T00:00:00Z"
    changed = seal_report(ReportContent.model_validate(payload))
    ReportStore(database).append(changed)
    with pytest.raises(RunConflict):
        store.apply(
            definition.run_id,
            RunFinish(action="finish", report_revision_id=changed.revision_id, **common(7)),
        )
    assert store.get(definition.run_id).sequence == 7


@pytest.mark.postgres
def test_events_keyset_and_unknown_run(database: Engine) -> None:
    definition, _snapshot = setup_run(database)
    store = ResearchStore(database)
    with pytest.raises(RunNotFound):
        store.get(definition.run_id)
    store.create(definition)
    store.apply(definition.run_id, RunStart(action="start", **common(1)))
    first = store.events(definition.run_id, limit=1)
    assert [item.sequence for item in first.items] == [1] and first.next_after_sequence == 1
    second = store.events(definition.run_id, after_sequence=1, limit=1)
    assert [item.sequence for item in second.items] == [2] and second.next_after_sequence is None
    for kwargs in [{"after_sequence": -1}, {"limit": 0}, {"limit": True}]:
        with pytest.raises(ValueError):
            store.events(definition.run_id, **kwargs)


@pytest.mark.postgres
def test_event_reads_detect_metadata_corruption(database: Engine) -> None:
    definition, _snapshot = setup_run(database)
    store = ResearchStore(database)
    store.create(definition)
    with database.begin() as connection:
        state = dict(connection.scalar(select(run_events.c.state)))
        state["instrument_id"] = str(uuid4())
        connection.execute(text("ALTER TABLE run_events DISABLE TRIGGER USER"))
        connection.execute(run_events.update().values(state=state))
        connection.execute(text("ALTER TABLE run_events ENABLE TRIGGER USER"))
    for operation in [
        lambda: store.get(definition.run_id),
        lambda: store.events(definition.run_id),
        lambda: store.create(definition),
    ]:
        with pytest.raises(CorruptReport):
            operation()
