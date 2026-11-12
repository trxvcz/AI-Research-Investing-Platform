"""Real PostgreSQL compatibility and downgrade protection for the SEC pipeline."""

import io
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import DBAPIError
from test_worker_migration import (
    claim_values,
    config,
    new_run,
    queued_job,
    update_for_claim,
)
from test_worker_migration import (
    database as database,
)

from alphasense.db_schema import (
    MIGRATION_HEAD,
    raw_snapshots,
    research_runs,
    run_events,
    run_snapshots,
    worker_claims,
    worker_jobs,
)


def history(connection: Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        table.name: [dict(row) for row in connection.execute(select(table)).mappings()]
        for table in (
            research_runs,
            run_events,
            run_snapshots,
            raw_snapshots,
            worker_jobs,
            worker_claims,
        )
    }


def test_offline_upgrade_explicitly_adds_sec_to_existing_pipeline_guards(monkeypatch) -> None:
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "postgresql+psycopg://unused/unused")
    output = io.StringIO()
    migration = config()
    migration.output_buffer = output
    command.upgrade(migration, "head", sql=True)
    sql = output.getvalue()
    assert "'manual-research-v1','deterministic-research-v1','sec-fundamentals-v1'" in sql
    assert "pipeline NOT IN ('deterministic-research-v1','sec-fundamentals-v1')" in sql
    assert "CREATE OR REPLACE FUNCTION worker_jobs_check_change()" in sql


@pytest.mark.postgres
def test_populated_old_pipeline_upgrade_preserves_full_history(database: Connection) -> None:
    command.downgrade(config(database), "0005_provider_quota")
    database.commit()
    manual = new_run(database, pipeline="manual-research-v1")
    identity = database.scalar(
        select(research_runs.c.instrument_id).where(research_runs.c.run_id == manual)
    )
    automatic = new_run(database, instrument_id=identity)
    queued_job(database, automatic)
    claim = claim_values(database, automatic)
    update_for_claim(database, claim)
    database.execute(worker_claims.insert().values(**claim))
    database.commit()
    before = history(database)
    database.commit()
    command.upgrade(config(database), "head")
    database.commit()
    assert history(database) == before
    assert database.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD
    sec = new_run(database, pipeline="sec-fundamentals-v1", instrument_id=identity)
    queued_job(database, sec)
    sec_claim = claim_values(database, sec)
    update_for_claim(database, sec_claim)
    database.execute(worker_claims.insert().values(**sec_claim))
    database.commit()
    assert database.scalar(select(worker_jobs.c.attempts).where(worker_jobs.c.run_id == sec)) == 1


@pytest.mark.postgres
def test_downgrade_preserves_populated_old_pipelines_and_rejects_new_sec(
    database: Connection,
) -> None:
    manual = new_run(database, pipeline="manual-research-v1")
    identity = database.scalar(
        select(research_runs.c.instrument_id).where(research_runs.c.run_id == manual)
    )
    automatic = new_run(database, instrument_id=identity)
    queued_job(database, automatic)
    database.commit()
    before = history(database)
    database.commit()
    command.downgrade(config(database), "0005_provider_quota")
    database.commit()
    assert history(database) == before
    database.commit()
    with pytest.raises(DBAPIError), database.begin_nested():
        new_run(database, pipeline="sec-fundamentals-v1", instrument_id=identity)
    command.upgrade(config(database), "head")
    database.commit()
    assert history(database) == before


@pytest.mark.postgres
@pytest.mark.parametrize("claimed", [False, True])
def test_downgrade_refuses_any_sec_history(database: Connection, claimed: bool) -> None:
    sec = new_run(database, pipeline="sec-fundamentals-v1")
    if claimed:
        queued_job(database, sec)
        claim = claim_values(database, sec)
        update_for_claim(database, claim)
        database.execute(worker_claims.insert().values(**claim))
    database.commit()
    before = history(database)
    database.commit()
    with pytest.raises(RuntimeError, match="non-empty SEC history"):
        command.downgrade(config(database), "0005_provider_quota")
    database.rollback()
    assert database.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD
    assert history(database) == before


@pytest.mark.postgres
def test_sec_state_must_match_immutable_run_definition(database: Connection) -> None:
    sec = new_run(database, pipeline="sec-fundamentals-v1")
    row = dict(
        database.execute(select(run_events).where(run_events.c.run_id == sec)).mappings().one()
    )
    changed = deepcopy(row)
    event_id = uuid4()
    changed.update(sequence=2, event_id=event_id, kind="start")
    changed["request"] = dict(
        action="start", request_id=str(event_id), expected_sequence=1, actor="synthetic-sec-test"
    )
    changed["state"].update(
        sequence=2, status="running", pipeline_version="deterministic-research-v1"
    )
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(run_events.insert().values(**changed))


@pytest.mark.postgres
def test_unknown_pipeline_is_not_admitted(database: Connection) -> None:
    with pytest.raises(DBAPIError), database.begin_nested():
        new_run(database, pipeline="arbitrary-network-runner")


@pytest.mark.postgres
def test_manual_job_is_still_rejected(database: Connection) -> None:
    manual = new_run(database, pipeline="manual-research-v1")
    with pytest.raises(DBAPIError), database.begin_nested():
        queued_job(database, manual)


def test_offline_upgrade_explicitly_adds_v2_resources_and_pipeline(monkeypatch) -> None:
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "postgresql+psycopg://unused/unused")
    output = io.StringIO()
    migration = config()
    migration.output_buffer = output
    command.upgrade(migration, "head", sql=True)
    sql = output.getvalue()
    assert "'sec-fundamentals-v1','sec-fundamentals-v2'" in sql
    for role, tag in {
        "cash": "CashAndCashEquivalentsAtCarryingValue",
        "debt_current": "LongTermDebtCurrent",
        "debt_noncurrent": "LongTermDebtNoncurrent",
        "operating_cf": "NetCashProvidedByUsedInOperatingActivities",
        "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    }.items():
        assert f"WHEN '{role}' THEN 'sec-edgar-{role}-v2'" in sql
        assert f"/us-gaap/{tag}.json" in sql
