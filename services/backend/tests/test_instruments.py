"""Immutable instrument registry checks on real isolated PostgreSQL schemas."""

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
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, select, text

from alphasense.db import CorruptReport, StoreUnavailable
from alphasense.db_schema import instruments
from alphasense.instrument_contracts import InstrumentCreate
from alphasense.instruments import InstrumentConflict, InstrumentNotFound, InstrumentStore

ROOT = Path(__file__).resolve().parents[3]


def sample(**changes: Any) -> InstrumentCreate:
    payload = {
        "schema_version": "1.0",
        "instrument_id": str(uuid4()),
        "symbol": "DEMO",
        "exchange_mic": "XNAS",
        "currency": "USD",
        "display_name": "Synthetic registry fixture",
        "asset_type": "equity",
        "data_origin": "synthetic",
        "as_of": "2024-02-01T00:00:00Z",
        "available_at": "2024-01-31T00:00:00Z",
        "source_id": "synthetic-registry-fixture",
        "source_url": None,
        "license": "generated fixture",
    }
    payload.update(changes)
    return InstrumentCreate.model_validate(payload)


@pytest.fixture
def database() -> Iterator[Engine]:
    dsn = os.environ.get("ALPHASENSE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Real PostgreSQL requires ALPHASENSE_TEST_DATABASE_URL")
    schema = "instrument_test_" + uuid4().hex
    assert re.fullmatch(r"instrument_test_[a-f0-9]{32}", schema)
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


def test_non_postgres_engine_is_rejected() -> None:
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(StoreUnavailable):
            InstrumentStore(engine)
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_create_get_and_canonical_retry_preserve_server_timestamp(database: Engine) -> None:
    store = InstrumentStore(database)
    data = sample()
    created = store.create(data)
    assert created.created is True
    assert store.get(data.instrument_id).model_dump() == created.model_dump(exclude={"created"})
    payload = data.model_dump(mode="json")
    payload["as_of"] = "2024-02-01T01:00:00+01:00"
    retry = store.create(InstrumentCreate.model_validate(payload))
    assert retry.created is False
    assert retry.created_at == created.created_at
    assert retry.instrument_id == created.instrument_id
    with database.connect() as connection:
        assert len(connection.execute(select(instruments)).all()) == 1


@pytest.mark.postgres
def test_lookup_unknown_identity_is_not_found(database: Engine) -> None:
    with pytest.raises(InstrumentNotFound):
        InstrumentStore(database).get(uuid4())


@pytest.mark.parametrize("field,value", [("currency", "EUR"), ("display_name", "Changed fixture")])
@pytest.mark.postgres
def test_same_id_with_changed_payload_conflicts(database: Engine, field: str, value: str) -> None:
    store = InstrumentStore(database)
    original = sample()
    first = store.create(original)
    payload = original.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(InstrumentConflict):
        store.create(InstrumentCreate.model_validate(payload))
    assert store.get(original.instrument_id).created_at == first.created_at
    assert store.get(original.instrument_id).currency == "USD"


@pytest.mark.postgres
def test_natural_key_cannot_be_split_by_uuid_currency_or_asset_type(database: Engine) -> None:
    store = InstrumentStore(database)
    store.create(sample())
    for changes in [{}, {"currency": "EUR"}, {"asset_type": "etf"}]:
        with pytest.raises(InstrumentConflict):
            store.create(sample(**changes))
    assert len(store.search().items) == 1


@pytest.mark.postgres
def test_null_mic_commodity_natural_key_is_unique(database: Engine) -> None:
    store = InstrumentStore(database)
    store.create(sample(asset_type="commodity", exchange_mic=None))
    with pytest.raises(InstrumentConflict):
        store.create(sample(asset_type="commodity", exchange_mic=None))


@pytest.mark.postgres
def test_search_is_literal_case_insensitive_and_origin_filtered(database: Engine) -> None:
    store = InstrumentStore(database)
    literal = sample(
        symbol="A_B", display_name="Synthetic 50% A_B / C", instrument_id=str(UUID(int=1))
    )
    other = sample(
        symbol="AXB", display_name="Synthetic 50 pct AXB", instrument_id=str(UUID(int=2))
    )
    declared_live_fixture = sample(
        symbol="DEMO", data_origin="live", source_url="https://example.invalid/fixture"
    )
    for data in [literal, other, declared_live_fixture]:
        store.create(data)
    for query in ["%", "_", " / ", "a_b"]:
        assert [item.instrument_id for item in store.search(query).items] == [literal.instrument_id]
    assert len(store.search("synthetic", data_origin="synthetic").items) == 2
    assert [item.instrument_id for item in store.search(data_origin="live").items] == [
        declared_live_fixture.instrument_id
    ]
    assert store.search("' OR TRUE --").items == []


@pytest.mark.postgres
def test_uuid_keyset_has_no_duplicates_and_cursor_need_not_match_filter(database: Engine) -> None:
    store = InstrumentStore(database)
    for index in range(1, 5):
        store.create(sample(instrument_id=str(UUID(int=index)), symbol=f"DEMO{index}"))
    first = store.search(limit=2)
    assert [item.instrument_id.int for item in first.items] == [1, 2]
    assert first.next_after_id == UUID(int=2)
    second = store.search(after_id=first.next_after_id, limit=2)
    assert [item.instrument_id.int for item in second.items] == [3, 4]
    assert second.next_after_id is None
    filtered = store.search("DEMO4", after_id=UUID(int=2), limit=1)
    assert [item.instrument_id.int for item in filtered.items] == [4]
    assert filtered.next_after_id is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": "\x00"},
        {"query": "x" * 129},
        {"query": "\n"},
        {"after_id": "not-a-uuid"},
        {"data_origin": "paid"},
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
    ],
)
@pytest.mark.postgres
def test_direct_search_calls_validate_arguments(database: Engine, kwargs: dict[str, Any]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        InstrumentStore(database).search(**kwargs)


@pytest.mark.postgres
def test_mutated_instance_is_revalidated_before_write(database: Engine) -> None:
    model = sample()
    model.display_name = "Synthetic\x00fixture"
    with pytest.raises(ValidationError):
        InstrumentStore(database).create(model)
    assert InstrumentStore(database).search().items == []


@pytest.mark.postgres
def test_parallel_identical_registration_is_idempotent(database: Engine) -> None:
    data = sample()
    barrier = Barrier(2)

    def register() -> bool:
        barrier.wait(timeout=5)
        return InstrumentStore(database).create(data).created

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: register(), range(2)))
    assert sorted(results) == [False, True]
    assert len(InstrumentStore(database).search().items) == 1


@pytest.mark.postgres
def test_parallel_natural_key_registration_has_one_winner(database: Engine) -> None:
    data = [sample(), sample()]
    barrier = Barrier(2)

    def register(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            InstrumentStore(database).create(data[index])
            return "created"
        except InstrumentConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(register, range(2)))
    assert sorted(results) == ["conflict", "created"]
    assert len(InstrumentStore(database).search().items) == 1


@pytest.mark.postgres
def test_reads_and_retry_detect_metadata_corruption(database: Engine) -> None:
    store = InstrumentStore(database)
    data = sample()
    store.create(data)
    with database.begin() as connection:
        connection.execute(text("ALTER TABLE instruments DISABLE TRIGGER USER"))
        connection.execute(
            instruments.update()
            .where(instruments.c.instrument_id == data.instrument_id)
            .values(symbol="CORRUPT")
        )
        connection.execute(text("ALTER TABLE instruments ENABLE TRIGGER USER"))
    with pytest.raises(CorruptReport):
        store.get(data.instrument_id)
    with pytest.raises(CorruptReport):
        store.search()
    with pytest.raises(CorruptReport):
        store.create(data)


@pytest.mark.postgres
def test_created_at_is_validated_on_read(database: Engine) -> None:
    store = InstrumentStore(database)
    data = sample()
    store.create(data)
    with database.begin() as connection:
        connection.execute(text("ALTER TABLE instruments DISABLE TRIGGER USER"))
        connection.execute(
            text("UPDATE instruments SET created_at='infinity' WHERE instrument_id=:instrument_id"),
            {"instrument_id": data.instrument_id},
        )
        connection.execute(text("ALTER TABLE instruments ENABLE TRIGGER USER"))
    with pytest.raises((CorruptReport, StoreUnavailable)):
        store.get(data.instrument_id)
