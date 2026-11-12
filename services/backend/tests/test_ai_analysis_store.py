"""Real PostgreSQL budget fencing, retry identity and immutable AI history."""

import getpass
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_document_archive import database as database
from test_financial_history import fixture as history_fixture
from test_instruments import sample as sample_instrument

from alphasense.ai_analysis_contracts import AiNarrative
from alphasense.ai_analysis_store import (
    BUDGET_SCOPE,
    AiAnalysisStore,
    AiBudgetExceeded,
    AiRequestConflict,
    AiStoreUnavailable,
)
from alphasense.ai_history_context import build_history_context
from alphasense.ai_history_contracts import AiHistoryContext, AiHistoryNarrative
from alphasense.db import ReportStore
from alphasense.db_schema import ai_analyses, ai_budget_reservations, metadata
from alphasense.financial_history import build_financial_history
from alphasense.instruments import InstrumentStore
from alphasense.report_contracts import ReportContent, ReportRevision, canonical_sha256, seal_report

MODEL = "gemini-3.1-flash-lite"
ROOT = Path(__file__).resolve().parents[3]


def source(database: Engine) -> ReportRevision:
    report = ReportRevision.model_validate_json(
        (Path(__file__).parent / "fixtures/report.synthetic.json").read_bytes()
    )
    ReportStore(database).append(report)
    return report


def narrative(index: int = 0) -> AiNarrative:
    return AiNarrative.model_validate(
        {
            "summary": [
                {
                    "text": "Dostępne dane wymagają ostrożnej interpretacji.",
                    "observation_indexes": [index],
                }
            ],
            "strengths": [],
            "risks": [],
            "questions": [],
            "limitations": ["Brak pełnego obrazu spółki."],
        }
    )


def history_source(database: Engine):
    report, snapshots = history_fixture()
    content = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    content.update(report_id=uuid4(), revision_id=uuid4())
    report = seal_report(ReportContent.model_validate(content))
    InstrumentStore(database).create(
        sample_instrument(
            instrument_id=report.input.instrument_id,
            data_origin=report.input.data_origin,
            source_url="https://www.sec.gov/Archives/synthetic-history-fixture",
            as_of=report.input.as_of,
            available_at=report.input.as_of,
        )
    )
    ReportStore(database).append(report)
    context = build_history_context(report, build_financial_history(report, snapshots))
    return report, context


def history_narrative(context: AiHistoryContext, index: int | None = None) -> AiHistoryNarrative:
    comparison = next(e for e in reversed(context.evidence) if e.kind == "comparison")
    return AiHistoryNarrative.model_validate(
        {
            "summary": [
                {
                    "kind": "trend",
                    "text": "Przychody wzrosły względem poprzedniego okresu.",
                    "evidence_indexes": [comparison.index if index is None else index],
                    "direction": "increase",
                }
            ],
            "strengths": [],
            "risks": [],
            "questions": [],
            "limitations": ["Zakres ograniczony do archiwalnych danych."],
        }
    )


def altered_context(context: AiHistoryContext) -> AiHistoryContext:
    data = context.model_dump(mode="json", exclude={"context_sha256"})
    data["limitations"].append("Dodatkowa uwaga kontrolna.")
    return AiHistoryContext.model_validate({**data, "context_sha256": canonical_sha256(data)})


def test_history_roundtrip_uses_frozen_comparison_indices_and_preserves_v1(database: Engine):
    store = AiAnalysisStore(database)
    legacy = source(database)
    old_id = uuid4()
    store.reserve(old_id, legacy, MODEL)
    old = store.finish(old_id, narrative(), None, {"usage": None})
    assert "evidence_context" not in old.model_dump(mode="json")
    report, context = history_source(database)
    identifier = uuid4()
    assert store.reserve(
        identifier, report, MODEL, prompt_version="report-history-v2", evidence_context=context
    )
    assert not store.reserve(
        identifier, report, MODEL, prompt_version="report-history-v2", evidence_context=context
    )
    draft = history_narrative(context)
    assert draft.summary[0].evidence_indexes[0] >= len(report.input.observations)
    completed = store.finish(identifier, draft, None, {"usage": None})
    assert completed.evidence_context == context and completed.analysis == draft
    assert AiAnalysisStore(database).get(identifier) == completed
    assert store.get(old_id).model_dump(mode="json") == old.model_dump(mode="json")
    assert store.budget()["reserved_pln"] == "2.00"
    with database.connect() as connection:
        assert (
            connection.scalar(
                select(ai_analyses.c.audit).where(ai_analyses.c.request_id == identifier)
            )["context_sha256"]
            == context.context_sha256
        )


def test_history_invalid_context_never_reserves_and_context_hash_fences_retry(database: Engine):
    store = AiAnalysisStore(database)
    report, context = history_source(database)
    for invalid in (
        None,
        context.model_copy(update={"context_sha256": "a" * 64}),
        context.model_copy(update={"report_checksum": "b" * 64}),
    ):
        with pytest.raises(AiRequestConflict):
            store.reserve(
                uuid4(), report, MODEL, prompt_version="report-history-v2", evidence_context=invalid
            )
    assert store.budget()["reserved_pln"] == "0.00"
    identifier = uuid4()
    store.reserve(
        identifier, report, MODEL, prompt_version="report-history-v2", evidence_context=context
    )
    with pytest.raises(AiRequestConflict):
        store.reserve(
            identifier,
            report,
            MODEL,
            prompt_version="report-history-v2",
            evidence_context=altered_context(context),
        )
    with pytest.raises(AiRequestConflict):
        store.reserve(identifier, report, MODEL)
    assert store.budget()["reserved_pln"] == "1.00"


def test_history_invalid_narrative_or_audit_cannot_finish(database: Engine):
    store = AiAnalysisStore(database)
    report, context = history_source(database)
    identifier = uuid4()
    store.reserve(
        identifier, report, MODEL, prompt_version="report-history-v2", evidence_context=context
    )
    for draft, audit in [
        (narrative(), {}),
        (history_narrative(context, 63), {}),
        (history_narrative(context), {"context_sha256": "a" * 64}),
    ]:
        with pytest.raises(AiRequestConflict):
            store.finish(identifier, draft, None, audit)
    assert store.get(identifier).status == "running"
    assert store.budget()["reserved_pln"] == "1.00"


def test_sql_cannot_replace_running_or_terminal_history_context(database: Engine):
    store = AiAnalysisStore(database)
    report, context = history_source(database)
    identifier = uuid4()
    store.reserve(
        identifier, report, MODEL, prompt_version="report-history-v2", evidence_context=context
    )
    replacement = altered_context(context).model_dump(mode="json")
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(
            ai_analyses.update()
            .where(ai_analyses.c.request_id == identifier)
            .values(
                status="failed",
                finished_at=text("clock_timestamp()"),
                error_code="TEST_FAILURE",
                audit={},
                evidence_context=replacement,
            )
        )
    completed = store.finish(identifier, history_narrative(context), None, {})
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(
            ai_analyses.update()
            .where(ai_analyses.c.request_id == identifier)
            .values(evidence_context=replacement)
        )
    assert store.get(identifier) == completed


def test_history_downgrade_refuses_frozen_context_but_v1_upgrade_preserves_json(database: Engine):
    store = AiAnalysisStore(database)
    legacy = source(database)
    old_id = uuid4()
    store.reserve(old_id, legacy, MODEL)
    old = store.finish(old_id, narrative(), None, {})
    config = Config(str(ROOT / "alembic.ini"))
    with database.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0015_ai_analysis")
        command.upgrade(config, "head")
    assert store.get(old_id).model_dump(mode="json") == old.model_dump(mode="json")
    report, context = history_source(database)
    store.reserve(
        uuid4(), report, MODEL, prompt_version="report-history-v2", evidence_context=context
    )
    with (
        pytest.raises(RuntimeError, match="frozen AI historical evidence"),
        database.begin() as connection,
    ):
        config.attributes["connection"] = connection
        command.downgrade(config, "0015_ai_analysis")


def test_retry_and_restart_keep_one_reservation_and_terminal_result(database: Engine) -> None:
    report = source(database)
    request_id = uuid4()
    store = AiAnalysisStore(database)
    assert store.reserve(request_id, report, MODEL)
    assert not store.reserve(request_id, report, MODEL)
    running = store.get(request_id)
    assert running and running.status == "running" and running.analysis is None
    assert store.budget()["remaining_pln"] == "49.00"
    audit = {"usage": None, "raw_response": "synthetic private response"}
    completed = store.finish(request_id, narrative(), None, audit)
    restarted = AiAnalysisStore(database)
    assert restarted.get(request_id) == completed
    assert restarted.list(report.report_id, report.revision) == [completed]
    assert not restarted.reserve(request_id, report, MODEL)
    assert restarted.budget()["reserved_pln"] == "1.00"
    assert "raw_response" not in completed.model_dump()
    assert "audit" not in completed.model_dump()
    with pytest.raises(AiRequestConflict):
        restarted.finish(request_id, narrative(), None, audit)


def test_failed_and_abandoned_attempts_are_not_refunded(database: Engine) -> None:
    report = source(database)
    store = AiAnalysisStore(database)
    failed, abandoned = uuid4(), uuid4()
    store.reserve(failed, report, MODEL)
    store.finish(failed, None, "GEMINI_HTTP_429", {"usage": None})
    store.reserve(abandoned, report, MODEL)
    assert not AiAnalysisStore(database).reserve(abandoned, report, MODEL)
    assert store.get(failed).error_code == "GEMINI_HTTP_429"
    assert store.get(abandoned).status == "running"
    assert store.budget()["remaining_pln"] == "48.00"


def test_qualification_is_private_and_shares_budget_and_request_namespace(database: Engine) -> None:
    store = AiAnalysisStore(database)
    identifier = uuid4()
    assert store.reserve_qualification(identifier)
    assert not store.reserve_qualification(identifier)
    assert store.get(identifier) is None
    assert store.budget()["reserved_pln"] == "1.00"
    report = source(database)
    assert store.list(report.report_id, report.revision) == []
    with pytest.raises(AiRequestConflict):
        store.reserve(identifier, report, MODEL)
    actual = uuid4()
    store.reserve(actual, report, MODEL)
    with pytest.raises(AiRequestConflict):
        store.reserve_qualification(actual)
    assert store.budget()["reserved_pln"] == "2.00"


def test_conflicting_identity_or_unpersisted_report_never_consumes_budget(database: Engine) -> None:
    store = AiAnalysisStore(database)
    report = source(database)
    identifier = uuid4()
    store.reserve(identifier, report, MODEL)
    with pytest.raises(AiRequestConflict):
        store.reserve(identifier, report, "another-model")
    with pytest.raises(AiRequestConflict):
        store.reserve(uuid4(), report.model_copy(update={"revision_id": uuid4()}), MODEL)
    with pytest.raises(AiRequestConflict):
        store.reserve(uuid4(), report.model_copy(update={"checksum": "a" * 64}), MODEL)
    assert store.budget()["reserved_pln"] == "1.00"


def test_concurrent_repeated_uuid_reserves_once(database: Engine) -> None:
    store = AiAnalysisStore(database)
    identifier = uuid4()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.reserve_qualification(identifier), range(16)))
    assert results.count(True) == 1
    assert store.budget()["reserved_pln"] == "1.00"


def test_concurrent_global_cap_cannot_be_exceeded(database: Engine) -> None:
    store = AiAnalysisStore(database)

    def attempt(_: int) -> bool:
        try:
            return store.reserve_qualification(uuid4())
        except AiBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(64)))
    assert results.count(True) == 50
    assert store.budget() == {
        "budget_pln": "50.00",
        "reserved_pln": "50.00",
        "remaining_pln": "0.00",
        "reservation_per_attempt_pln": "1.00",
    }
    with pytest.raises(AiBudgetExceeded):
        AiAnalysisStore(database).reserve_qualification(uuid4())
    # A failed extra attempt rolled back its tentative counter and ledger insert.
    with database.connect() as connection:
        assert len(connection.execute(select(ai_budget_reservations)).all()) == 50


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ai_budget_controls SET reserved_grosz=0",
        "UPDATE ai_budget_controls SET budget_grosz=10000",
        "DELETE FROM ai_budget_controls",
        "TRUNCATE ai_budget_controls CASCADE",
        "UPDATE ai_budget_reservations SET amount_grosz=0",
        "DELETE FROM ai_budget_reservations",
        "TRUNCATE ai_budget_reservations CASCADE",
    ],
)
def test_sql_cannot_reset_or_refund_budget(database: Engine, sql: str) -> None:
    store = AiAnalysisStore(database)
    store.reserve_qualification(uuid4())
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(text(sql))
    assert store.budget()["reserved_pln"] == "1.00"


def test_direct_ledger_insert_is_also_capped(database: Engine) -> None:
    store = AiAnalysisStore(database)
    for _ in range(50):
        store.reserve_qualification(uuid4())
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(
            ai_budget_reservations.insert().values(
                request_id=uuid4(),
                scope=BUDGET_SCOPE,
                kind="qualification",
                amount_grosz=100,
            )
        )
    assert store.budget()["reserved_pln"] == "50.00"


def test_invalid_finish_preserves_running_state_and_its_reservation(database: Engine) -> None:
    report = source(database)
    store = AiAnalysisStore(database)
    identifier = uuid4()
    store.reserve(identifier, report, MODEL)
    for analysis, error, audit in [
        (narrative(), "FAILURE", {}),
        (None, None, {}),
        (None, "secret error message", {}),
        (narrative(999), None, {}),
        (narrative(), None, {"invalid": float("nan")}),
    ]:
        with pytest.raises(AiRequestConflict):
            store.finish(identifier, analysis, error, audit)
    assert store.get(identifier).status == "running"
    assert store.budget()["reserved_pln"] == "1.00"


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM ai_analyses",
        "TRUNCATE ai_analyses",
        "UPDATE ai_analyses SET status='running'",
        "UPDATE ai_analyses SET audit='{}'::jsonb",
        "UPDATE ai_analyses SET report_checksum=repeat('a',64)",
    ],
)
def test_terminal_sql_history_is_immutable(database: Engine, sql: str) -> None:
    store = AiAnalysisStore(database)
    identifier = uuid4()
    store.reserve(identifier, source(database), MODEL)
    completed = store.finish(identifier, narrative(), None, {"synthetic": True})
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(text(sql))
    assert store.get(identifier) == completed


def test_schema_matches_metadata_and_empty_downgrade_only(database: Engine) -> None:
    with database.begin() as connection:
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0014_sec_schedules")
        command.upgrade(config, "head")
    AiAnalysisStore(database).reserve_qualification(uuid4())
    with pytest.raises(RuntimeError, match="non-empty AI spending history"):
        with database.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0014_sec_schedules")


def test_unavailable_database_is_redacted_and_sqlite_refused() -> None:
    with pytest.raises(AiStoreUnavailable, match="PostgreSQL required"):
        AiAnalysisStore(create_engine("sqlite://"))


@pytest.mark.postgres
def test_backup_restore_preserves_audit_qualification_and_remaining_budget(
    database: Engine,
    tmp_path: Path,
) -> None:
    """Restore the complete isolated schema into a fresh throwaway database."""
    tools = os.environ.get("ALPHASENSE_PG_BIN", "")
    suffix = ".exe" if os.name == "nt" else ""
    dump_tool = str(Path(tools) / ("pg_dump" + suffix)) if tools else shutil.which("pg_dump")
    restore_tool = str(Path(tools) / ("psql" + suffix)) if tools else shutil.which("psql")
    if not dump_tool or not restore_tool:
        pytest.skip("pg_dump/psql are required for backup verification")

    store = AiAnalysisStore(database)
    report = source(database)
    completed_id, failed_id, qualification_id, history_id = uuid4(), uuid4(), uuid4(), uuid4()
    store.reserve(completed_id, report, MODEL)
    audit = {
        "request_sha256": "a" * 64,
        "raw_response": "synthetic private response",
        "usage": {"promptTokenCount": 123, "candidatesTokenCount": 45},
    }
    completed = store.finish(completed_id, narrative(), None, audit)
    store.reserve(failed_id, report, MODEL)
    failed = store.finish(failed_id, None, "GEMINI_HTTP_429", {"usage": None})
    assert store.reserve_qualification(qualification_id)
    history_report, context = history_source(database)
    store.reserve(
        history_id,
        history_report,
        MODEL,
        prompt_version="report-history-v2",
        evidence_context=context,
    )
    history_completed = store.finish(history_id, history_narrative(context), None, {"usage": None})
    before_budget = store.budget()
    assert before_budget["reserved_pln"] == "4.00"
    with database.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
        before_ledger = (
            connection.execute(
                select(ai_budget_reservations).order_by(ai_budget_reservations.c.request_id)
            )
            .mappings()
            .all()
        )
        before_analyses = (
            connection.execute(select(ai_analyses).order_by(ai_analyses.c.request_id))
            .mappings()
            .all()
        )
    assert re.fullmatch(r"document_archive_test_[a-f0-9]{32}", schema)
    target = "ai_analysis_restore_" + uuid4().hex
    assert re.fullmatch(r"ai_analysis_restore_[a-f0-9]{32}", target)
    url = make_url(database.url.render_as_string(hide_password=False))
    env = os.environ.copy()
    env.update(
        PGHOST=url.host or "",
        PGPORT=str(url.port or 5432),
        PGUSER=url.username or getpass.getuser(),
        PGPASSWORD=url.password or "",
        PGDATABASE=url.database or "postgres",
    )
    archive = tmp_path / "ai-analysis-backup.sql"

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
        recovered = AiAnalysisStore(restored)
        assert ReportStore(restored).get_report(report.report_id) == report
        assert recovered.get(completed_id) == completed
        assert recovered.get(failed_id) == failed
        assert recovered.get(history_id) == history_completed
        assert ReportStore(restored).get_report(history_report.report_id) == history_report
        assert recovered.budget() == before_budget
        assert not recovered.reserve_qualification(qualification_id)
        assert not recovered.reserve(completed_id, report, MODEL)
        assert not recovered.reserve(
            history_id,
            history_report,
            MODEL,
            prompt_version="report-history-v2",
            evidence_context=context,
        )
        with restored.connect() as connection:
            assert (
                connection.execute(
                    select(ai_budget_reservations).order_by(ai_budget_reservations.c.request_id)
                )
                .mappings()
                .all()
                == before_ledger
            )
            assert (
                connection.execute(select(ai_analyses).order_by(ai_analyses.c.request_id))
                .mappings()
                .all()
                == before_analyses
            )
            assert (
                connection.scalar(
                    select(ai_analyses.c.audit).where(ai_analyses.c.request_id == completed_id)
                )
                == audit
            )

        assert recovered.reserve_qualification(uuid4())
        assert recovered.budget()["reserved_pln"] == "5.00"
        assert recovered.budget()["remaining_pln"] == "45.00"
        # The restored guard remains active, and restoring a copy did not alter the original.
        with pytest.raises(DBAPIError), restored.begin() as connection:
            connection.execute(text("UPDATE ai_budget_controls SET reserved_grosz=0"))
        assert store.budget() == before_budget
    finally:
        restored.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)'))
        admin.dispose()
