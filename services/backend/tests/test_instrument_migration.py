"""Instrument migration gates on isolated schemas in a real PostgreSQL server."""

import json
import os
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from alphasense.db_schema import MIGRATION_HEAD, instruments, report_revisions, report_streams
from alphasense.report_contracts import ReportContent, ReportRevision, seal_report

ROOT = Path(__file__).resolve().parents[3]


def config(connection: Connection) -> Config:
    value = Config(str(ROOT / "alembic.ini"))
    value.attributes["connection"] = connection
    return value


@pytest.fixture
def database() -> Iterator[Connection]:
    dsn = os.environ.get("ALPHASENSE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real PostgreSQL requires ALPHASENSE_TEST_DATABASE_URL")
    schema = "instrument_migration_" + uuid4().hex
    assert re.fullmatch(r"instrument_migration_[a-f0-9]{32}", schema)
    engine = create_engine(dsn, hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            command.upgrade(config(connection), "head")
            connection.commit()
            yield connection
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def instrument_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "instrument_id": str(uuid4()),
        "symbol": "SYNTH",
        "exchange_mic": "XDEM",
        "currency": "USD",
        "display_name": "Synthetic migration fixture",
        "asset_type": "equity",
        "data_origin": "synthetic",
        "as_of": "2024-02-01T00:00:00Z",
        "available_at": "2024-01-31T00:00:00Z",
        "source_id": "synthetic-fixture",
        "source_url": None,
        "license": "generated fixture",
    }


def insert_instrument(connection: Connection, payload: dict[str, Any]) -> None:
    connection.execute(
        instruments.insert().values(
            instrument_id=payload["instrument_id"],
            symbol=payload["symbol"],
            exchange_mic=payload["exchange_mic"],
            currency=payload["currency"],
            asset_type=payload["asset_type"],
            data_origin=payload["data_origin"],
            as_of=datetime.fromisoformat(payload["as_of"]),
            available_at=datetime.fromisoformat(payload["available_at"]),
            payload=payload,
        )
    )


def insert_legacy_report(connection: Connection, instrument_id: str) -> ReportRevision:
    payload = json.loads(
        (ROOT / "services/backend/tests/fixtures/report.synthetic.json").read_text()
    )
    payload.pop("checksum")
    payload.pop("input_sha256")
    payload["input"]["instrument_id"] = instrument_id
    sealed = seal_report(ReportContent.model_validate(payload))
    connection.execute(
        report_streams.insert().values(
            report_id=sealed.report_id,
            instrument_id=instrument_id,
            asset_type=sealed.input.asset_type,
            data_origin=sealed.input.data_origin,
        )
    )
    connection.execute(
        report_revisions.insert().values(
            revision_id=sealed.revision_id,
            report_id=sealed.report_id,
            revision=1,
            parent_revision_id=None,
            generated_at_utc=sealed.generated_at_utc,
            checksum=sealed.checksum,
            input_sha256=sealed.input_sha256,
            payload=sealed.model_dump(mode="json"),
        )
    )
    return sealed


@pytest.mark.postgres
@pytest.mark.parametrize("legacy_id", ["DEMO-EQUITY", "c28cc0d5-9f57-4a36-9020-3af5067f6dd6"])
def test_upgrade_does_not_backfill_or_rewrite_existing_reports(
    database: Connection, legacy_id: str
) -> None:
    command.downgrade(config(database), "0001_report_store")
    database.commit()
    sealed = insert_legacy_report(database, legacy_id)
    database.commit()
    before = database.scalar(text("SELECT payload FROM report_revisions"))
    database.commit()
    command.upgrade(config(database), "head")
    database.commit()
    row = (
        database.execute(
            text(
                "SELECT payload, registry_instrument_id FROM report_revisions "
                "JOIN report_streams USING(report_id)"
            )
        )
        .mappings()
        .one()
    )
    assert row["registry_instrument_id"] is None
    assert row["payload"] == before
    assert ReportRevision.model_validate(row["payload"]).checksum == sealed.checksum


@pytest.mark.postgres
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE instruments SET symbol='OTHER'",
        "DELETE FROM instruments",
        "TRUNCATE instruments",
    ],
)
def test_registry_is_immutable(database: Connection, statement: str) -> None:
    insert_instrument(database, instrument_payload())
    database.commit()
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(text(statement))
    assert database.scalar(text("SELECT count(*) FROM instruments")) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("mic", ["XDEM", None])
def test_natural_key_prevents_two_ids_even_without_mic(
    database: Connection, mic: str | None
) -> None:
    first = instrument_payload()
    first.update(exchange_mic=mic, asset_type="commodity" if mic is None else "equity")
    insert_instrument(database, first)
    second = deepcopy(first)
    second["instrument_id"] = str(uuid4())
    with pytest.raises(DBAPIError), database.begin_nested():
        insert_instrument(database, second)
    assert database.scalar(text("SELECT count(*) FROM instruments")) == 1


@pytest.mark.postgres
@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "bad lowercase"),
        ("currency", "usd"),
        ("exchange_mic", "XX"),
        ("available_at", "2024-02-02T00:00:00Z"),
        ("exchange_mic", None),
    ],
)
def test_database_shape_and_time_constraints(database: Connection, field: str, value: Any) -> None:
    payload = instrument_payload()
    payload[field] = value
    with pytest.raises(DBAPIError), database.begin_nested():
        insert_instrument(database, payload)


@pytest.mark.postgres
def test_payload_cannot_disagree_with_indexed_metadata(database: Connection) -> None:
    payload = instrument_payload()
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(
            instruments.insert().values(
                instrument_id=payload["instrument_id"],
                symbol="OTHER",
                exchange_mic="XDEM",
                currency="USD",
                asset_type="equity",
                data_origin="synthetic",
                as_of=datetime.fromisoformat(payload["as_of"]),
                available_at=datetime.fromisoformat(payload["available_at"]),
                payload=payload,
            )
        )


@pytest.mark.postgres
@pytest.mark.parametrize(
    "case", ["missing_link", "unknown", "wrong_type", "wrong_origin", "wrong_text"]
)
def test_new_stream_requires_consistent_registered_identity(
    database: Connection, case: str
) -> None:
    payload = instrument_payload()
    insert_instrument(database, payload)
    values = {
        "report_id": uuid4(),
        "instrument_id": payload["instrument_id"],
        "asset_type": "equity",
        "data_origin": "synthetic",
        "registry_instrument_id": payload["instrument_id"],
    }
    if case == "missing_link":
        values["registry_instrument_id"] = None
    elif case == "unknown":
        values["registry_instrument_id"] = str(uuid4())
    elif case == "wrong_type":
        values["asset_type"] = "etf"
    elif case == "wrong_origin":
        values["data_origin"] = "live"
    else:
        values["instrument_id"] = "LEGACY"
    with pytest.raises(DBAPIError), database.begin_nested():
        database.execute(report_streams.insert().values(**values))


@pytest.mark.postgres
def test_registered_stream_and_legacy_stream_are_supported(database: Connection) -> None:
    payload = instrument_payload()
    insert_instrument(database, payload)
    for identifier, link in [
        (payload["instrument_id"], payload["instrument_id"]),
        ("LEGACY", None),
    ]:
        database.execute(
            report_streams.insert().values(
                report_id=uuid4(),
                instrument_id=identifier,
                asset_type="equity",
                data_origin="synthetic",
                registry_instrument_id=link,
            )
        )
    assert database.scalar(text("SELECT count(*) FROM report_streams")) == 2


@pytest.mark.postgres
def test_empty_downgrade_preserves_legacy_reports(database: Connection) -> None:
    sealed = insert_legacy_report(database, "LEGACY")
    database.commit()
    command.downgrade(config(database), "0001_report_store")
    database.commit()
    assert database.scalar(text("SELECT checksum FROM report_revisions")) == sealed.checksum
    command.upgrade(config(database), "head")
    database.commit()
    assert database.scalar(text("SELECT registry_instrument_id FROM report_streams")) is None


@pytest.mark.postgres
def test_nonempty_registry_downgrade_is_refused(database: Connection) -> None:
    insert_instrument(database, instrument_payload())
    database.commit()
    with pytest.raises(RuntimeError, match="non-empty instrument registry"):
        command.downgrade(config(database), "0001_report_store")
    database.rollback()
    assert database.scalar(text("SELECT count(*) FROM instruments")) == 1
    assert database.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


@pytest.mark.postgres
def test_downgrade_waits_for_inflight_registration(database: Connection) -> None:
    # This verifies the historical 0002 registration lock. Later migrations use
    # NOWAIT on the same parent table and intentionally refuse a full-chain downgrade.
    command.downgrade(config(database), "0002_instruments")
    database.commit()
    schema = database.scalar(text("SELECT current_schema()"))
    assert re.fullmatch(r"instrument_migration_[a-f0-9]{32}", schema)
    database.commit()

    def downgrade() -> str:
        with database.engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            try:
                command.downgrade(config(connection), "0001_report_store")
            except RuntimeError as error:
                assert "non-empty instrument registry" in str(error)
                return "refused"
        return "removed"

    with database.engine.connect() as writer:
        writer.execute(text(f'SET search_path TO "{schema}"'))
        writer.commit()
        insert_instrument(writer, instrument_payload())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(downgrade)
            try:
                waiting = False
                for _ in range(100):
                    waiting = bool(
                        database.scalar(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE NOT granted "
                                "AND mode='AccessExclusiveLock' "
                                "AND relation='instruments'::regclass)"
                            )
                        )
                    )
                    if waiting:
                        break
                    time.sleep(0.02)
                assert waiting, "downgrade must wait for the registration transaction"
                database.commit()
                writer.commit()
                assert future.result(timeout=5) == "refused"
            finally:
                writer.rollback()
    assert database.scalar(text("SELECT count(*) FROM instruments")) == 1
