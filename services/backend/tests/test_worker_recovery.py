"""Recovery drills use isolated PostgreSQL state and never a developer database."""

import getpass
import os
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import make_url
from test_store import database as database
from test_worker import (
    GIT_SHA,
    IMPLEMENTATION,
    claim,
    expire,
    packet_run,
    publication_command,
    to_report,
)

from alphasense import worker_store
from alphasense.db import ReportStore
from alphasense.db_schema import report_revisions, worker_claims, worker_jobs
from alphasense.instruments import InstrumentStore
from alphasense.runs import ResearchStore
from alphasense.snapshots import SnapshotStore
from alphasense.worker import process_once
from alphasense.worker_engine import compile_report
from alphasense.worker_store import WorkerLeaseLost, WorkerStore

pytestmark = pytest.mark.postgres


def test_renew_cannot_resurrect_lease_expired_during_transaction(
    database: tuple[Engine, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _schema = database
    definition = packet_run(engine)
    jobs = WorkerStore(engine)
    lease = claim(jobs)
    before = jobs.get_job(definition.run_id)
    calls = 0

    def advancing_clock(_connection):
        nonlocal calls
        calls += 1
        return lease.expires_at + timedelta(seconds=-1 if calls == 1 else 1)

    monkeypatch.setattr(worker_store, "_now", advancing_clock)
    with pytest.raises(WorkerLeaseLost):
        jobs.renew(lease)
    assert calls >= 4  # entry fence, extension, update time, original-expiry exit fence
    assert jobs.get_job(definition.run_id) == before
    assert ResearchStore(engine).get(definition.run_id).sequence == 2


def test_backup_restore_reclaims_published_run_without_duplicate_report(
    database: tuple[Engine, str], tmp_path: Path
) -> None:
    engine, schema = database
    tools = os.environ.get("ALPHASENSE_PG_BIN", "")
    suffix = ".exe" if os.name == "nt" else ""
    dump_tool = str(Path(tools) / ("pg_dump" + suffix)) if tools else shutil.which("pg_dump")
    restore_tool = str(Path(tools) / ("psql" + suffix)) if tools else shutil.which("psql")
    if not dump_tool or not restore_tool:
        pytest.skip("pg_dump/psql are required for backup verification")

    definition = packet_run(engine)
    jobs = WorkerStore(engine)
    lease = claim(jobs)
    to_report(jobs, lease, engine)
    state = ResearchStore(engine).get(definition.run_id)
    snapshots = [SnapshotStore(engine).content(key) for key in state.snapshot_ids]
    report = compile_report(
        state, InstrumentStore(engine).get(state.instrument_id), snapshots, GIT_SHA, IMPLEMENTATION
    )
    jobs.publish(lease, report, publication_command(engine, lease))
    checkpoint = ResearchStore(engine).get(definition.run_id)
    assert checkpoint.current_step == "review"
    before_job = jobs.get_job(definition.run_id)
    with engine.connect() as connection:
        before_claims = connection.execute(select(worker_claims)).mappings().all()

    target = "worker_restore_test_" + uuid4().hex
    assert re.fullmatch(r"worker_restore_test_[a-f0-9]{32}", target)
    url = make_url(engine.url.render_as_string(hide_password=False))
    env = os.environ.copy()
    env.update(
        PGHOST=url.host or "",
        PGPORT=str(url.port or 5432),
        PGUSER=url.username or getpass.getuser(),
        PGPASSWORD=url.password or "",
        PGDATABASE=url.database or "postgres",
    )
    archive = tmp_path / "worker-recovery.sql"

    def run_tool(arguments: list[str]) -> None:
        try:
            subprocess.run(arguments, env=env, check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as error:
            pytest.fail(f"Backup command failed ({type(error).__name__})", pytrace=False)

    run_tool([dump_tool, "--format=plain", "--schema", schema, "--file", str(archive)])
    admin = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    restored = create_engine(
        url.set(database=target),
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema}"},
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{target}"'))
        env["PGDATABASE"] = target
        run_tool(
            [
                restore_tool,
                "--no-psqlrc",
                "--set",
                "ON_ERROR_STOP=1",
                "--dbname",
                target,
                "--file",
                str(archive),
            ]
        )
        restored_jobs = WorkerStore(restored)
        assert restored_jobs.get_job(definition.run_id) == before_job
        assert ResearchStore(restored).get(definition.run_id) == checkpoint
        with restored.connect() as connection:
            assert connection.execute(select(worker_claims)).mappings().all() == before_claims
        for record, raw in snapshots:
            assert SnapshotStore(restored).content(record.snapshot_id) == (record, raw)
        assert ReportStore(restored).get_report(report.report_id) == report

        expire(restored, lease)
        assert process_once(restored, "restored-worker", GIT_SHA, IMPLEMENTATION)
        final = ResearchStore(restored).get(definition.run_id)
        assert final.status == "completed" and final.report_revision_id == report.revision_id
        assert final.sequence == checkpoint.sequence + 1
        assert restored_jobs.get_job(definition.run_id).attempts == 2
        assert restored_jobs.get_job(definition.run_id).status == "completed"
        with restored.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(report_revisions)) == 1
            assert connection.scalar(select(func.count()).select_from(worker_claims)) == 2
        assert ReportStore(restored).get_report(report.report_id) == report
        assert not process_once(restored, "restored-worker", GIT_SHA, IMPLEMENTATION)

        # Recovery operates on the restored copy; the original checkpoint stays untouched.
        assert jobs.get_job(definition.run_id) == before_job
        assert ResearchStore(engine).get(definition.run_id) == checkpoint
        with engine.connect() as connection:
            assert connection.scalar(select(worker_jobs.c.lease_token)) == lease.token
            assert connection.execute(select(worker_claims)).mappings().all() == before_claims
    finally:
        restored.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)'))
        admin.dispose()
