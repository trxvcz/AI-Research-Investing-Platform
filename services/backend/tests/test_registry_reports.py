"""New stable-ID report links and unchanged legacy histories on real PostgreSQL."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from test_migrations import insert_report
from test_store import ROOT, next_revision, sample
from test_store import database as database

from alphasense.db import CorruptReport, ReportNotFound, ReportStore, RevisionConflict, get_store
from alphasense.db_schema import report_streams
from alphasense.instrument_contracts import InstrumentCreate
from alphasense.instruments import InstrumentStore, get_instrument_store
from alphasense.report_contracts import ReportContent, seal_report

pytestmark = pytest.mark.postgres


def instrument(**changes):
    path = Path(__file__).parent / "fixtures/instrument.synthetic.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["instrument_id"] = str(uuid4())
    payload.update(changes)
    return InstrumentCreate.model_validate(payload)


def linked_report(instrument_id):
    payload = sample().model_dump(mode="json", exclude={"checksum", "input_sha256"})
    payload["input"]["instrument_id"] = str(instrument_id)
    return seal_report(ReportContent.model_validate(payload))


def test_new_report_links_to_registry_and_retry_is_immutable(database) -> None:
    engine = database[0]
    registered = InstrumentStore(engine).create(instrument())
    report = linked_report(registered.instrument_id)
    store = ReportStore(engine)
    assert store.append(report).created is True
    assert store.append(report).created is False
    second = next_revision(report)
    store.append(second)
    with engine.connect() as connection:
        link = connection.scalar(
            select(report_streams.c.registry_instrument_id).where(
                report_streams.c.report_id == report.report_id
            )
        )
    assert link == registered.instrument_id
    assert store.get_report(report.report_id, 1).checksum == report.checksum


@pytest.mark.parametrize("case", ["unknown", "type", "origin"])
def test_new_canonical_uuid_requires_matching_registered_identity(database, case) -> None:
    engine = database[0]
    data = instrument()
    if case == "type":
        data = instrument(asset_type="commodity")
    elif case == "origin":
        data = instrument(data_origin="live", source_url="https://example.invalid/synthetic-test")
    if case != "unknown":
        InstrumentStore(engine).create(data)
    report = linked_report(data.instrument_id)
    with pytest.raises(RevisionConflict):
        ReportStore(engine).append(report)
    with pytest.raises(ReportNotFound):
        ReportStore(engine).get_report(report.report_id)


def test_existing_legacy_uuid_retry_and_next_revision_are_not_backfilled(database) -> None:
    engine = database[0]
    report = linked_report(uuid4())
    with engine.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_report_store")
        insert_report(connection, report.model_dump(mode="json"))
        command.upgrade(config, "head")
    store = ReportStore(engine)
    assert store.append(report).created is False
    assert store.get_report(report.report_id).checksum == report.checksum
    store.append(next_revision(report))
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(report_streams.c.registry_instrument_id).where(
                    report_streams.c.report_id == report.report_id
                )
            )
            is None
        )


def test_corrupt_registry_cannot_be_used_to_link_new_report(database) -> None:
    engine = database[0]
    registered = InstrumentStore(engine).create(instrument())
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE instruments DISABLE TRIGGER USER"))
        connection.execute(text("UPDATE instruments SET asset_type='etf'"))
        connection.execute(text("ALTER TABLE instruments ENABLE TRIGGER USER"))
    payload = linked_report(registered.instrument_id).model_dump(
        mode="json", exclude={"checksum", "input_sha256"}
    )
    payload["input"]["asset_type"] = "etf"
    with pytest.raises(CorruptReport):
        ReportStore(engine).append(seal_report(ReportContent.model_validate(payload)))


def test_http_registration_then_persisted_report(database) -> None:
    import alphasense.api as api

    engine = database[0]
    registry = InstrumentStore(engine)
    reports = ReportStore(engine)
    data = instrument()
    api.app.dependency_overrides[get_instrument_store] = lambda: registry
    api.app.dependency_overrides[get_store] = lambda: reports
    try:
        with TestClient(api.app) as client:
            first = client.post("/v1/instruments", json=data.model_dump(mode="json"))
            assert first.status_code == 201
            assert (
                client.post("/v1/instruments", json=data.model_dump(mode="json")).status_code == 200
            )
            assert (
                client.get(f"/v1/instruments/{data.instrument_id}").json()["symbol"] == data.symbol
            )
            report = linked_report(data.instrument_id)
            assert (
                client.post("/v1/reports", json=report.model_dump(mode="json")).status_code == 201
            )
            assert client.get(f"/v1/reports/{report.report_id}").json()["input"][
                "instrument_id"
            ] == str(data.instrument_id)
    finally:
        api.app.dependency_overrides.clear()
