"""Raw archive preserves exact bytes and verifies them on every retrieval path."""

import base64
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, select, text
from test_instruments import sample as instrument_sample
from test_store import database as database

from alphasense.db import CorruptReport, StoreUnavailable
from alphasense.db_schema import instruments, raw_snapshots
from alphasense.instruments import InstrumentStore
from alphasense.snapshot_contracts import SnapshotCreate
from alphasense.snapshots import SnapshotConflict, SnapshotNotFound, SnapshotStore, decode_snapshot


def sample_snapshot(
    instrument_id: UUID, content: bytes = b"synthetic raw bytes", **changes: Any
) -> SnapshotCreate:
    payload = {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "instrument_id": str(instrument_id),
        "data_origin": "synthetic",
        "source_id": "synthetic-archive-source",
        "source_url": None,
        "license": "generated fixture",
        "as_of": "2024-02-01T00:00:00Z",
        "available_at": "2024-01-30T00:00:00Z",
        "retrieved_at": "2024-01-31T00:00:00Z",
        "media_type": "application/octet-stream",
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_length": len(content),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    payload.update(changes)
    return SnapshotCreate.model_validate(payload)


def registered(database: tuple[Engine, str]) -> UUID:
    data = instrument_sample()
    InstrumentStore(database[0]).create(data)
    return data.instrument_id


def test_snapshot_store_rejects_non_postgres() -> None:
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(StoreUnavailable):
            SnapshotStore(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize("corruption", [None, "bytes", "index", "metadata", "created_at"])
def test_shared_decoder_verifies_metadata_indexes_and_exact_bytes(corruption: str | None) -> None:
    data = sample_snapshot(uuid4(), b"\x00\xffexact bytes")
    row: dict[str, object] = {
        key: getattr(data, key)
        for key in [
            "snapshot_id",
            "instrument_id",
            "data_origin",
            "source_id",
            "as_of",
            "available_at",
            "retrieved_at",
            "sha256",
            "byte_length",
        ]
    }
    row.update(
        metadata=data.model_dump(mode="json", exclude={"content_base64"}),
        content=data.raw_bytes(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    if corruption is None:
        record, content = decode_snapshot(row)
        assert record.snapshot_id == data.snapshot_id
        assert content == data.raw_bytes()
        return
    if corruption == "bytes":
        row["content"] = b"changed"
    elif corruption == "index":
        row["byte_length"] = 1
    elif corruption == "metadata":
        metadata = data.model_dump(mode="json", exclude={"content_base64"})
        metadata["license"] = "\x00"
        row["metadata"] = metadata
    else:
        row["created_at"] = datetime(2026, 1, 1)
    with pytest.raises(CorruptReport):
        decode_snapshot(row)


@pytest.mark.parametrize(
    "content,media_type",
    [
        (b"\x00\xff\xfeRAW\r\n\x00", "application/octet-stream"),
        (b'{  "a": 1,\r\n"b":2  }\n', "application/json"),
        (b"a,b\r\n1,2\r\n", "text/csv"),
        (b"not actually a PDF; synthetic byte fixture", "application/pdf"),
    ],
)
@pytest.mark.postgres
def test_content_roundtrip_preserves_exact_bytes(
    database: tuple[Engine, str], content: bytes, media_type: str
) -> None:
    instrument_id = registered(database)
    data = sample_snapshot(instrument_id, content, media_type=media_type)
    store = SnapshotStore(database[0])
    result = store.create(data)
    record, downloaded = store.content(data.snapshot_id)
    assert result.created is True
    assert record == store.get(data.snapshot_id)
    assert downloaded == content
    assert record.sha256 == hashlib.sha256(content).hexdigest()
    assert record.byte_length == len(content)
    assert store.list(instrument_id).items == [record]
    with database[0].connect() as connection:
        row = connection.execute(select(raw_snapshots)).mappings().one()
        assert "content_base64" not in row["metadata"]
        assert "created_at" not in row["metadata"]
        assert row["content"] == content


@pytest.mark.postgres
def test_unknown_availability_stays_null(database: tuple[Engine, str]) -> None:
    instrument_id = registered(database)
    store = SnapshotStore(database[0])
    data = sample_snapshot(instrument_id, available_at=None)
    assert store.create(data).available_at is None
    assert store.get(data.snapshot_id).available_at is None


@pytest.mark.postgres
def test_retry_is_idempotent_and_same_bytes_can_have_distinct_snapshot_ids(
    database: tuple[Engine, str],
) -> None:
    instrument_id = registered(database)
    store = SnapshotStore(database[0])
    first = sample_snapshot(instrument_id)
    written = store.create(first)
    retry = store.create(first)
    assert written.created is True
    assert retry.created is False
    assert retry.created_at == written.created_at
    assert store.create(sample_snapshot(instrument_id)).created is True
    assert len(store.list(instrument_id).items) == 2


@pytest.mark.parametrize("change", ["bytes", "metadata"])
@pytest.mark.postgres
def test_snapshot_id_cannot_be_reused_for_different_data(
    database: tuple[Engine, str], change: str
) -> None:
    instrument_id = registered(database)
    store = SnapshotStore(database[0])
    original = sample_snapshot(instrument_id)
    store.create(original)
    if change == "bytes":
        conflicting = sample_snapshot(
            instrument_id, b"changed bytes", snapshot_id=str(original.snapshot_id)
        )
    else:
        conflicting = sample_snapshot(
            instrument_id, snapshot_id=str(original.snapshot_id), license="Changed declaration"
        )
    with pytest.raises(SnapshotConflict):
        store.create(conflicting)
    assert store.content(original.snapshot_id)[1] == original.raw_bytes()
    assert len(store.list(instrument_id).items) == 1


@pytest.mark.postgres
def test_unregistered_or_wrong_origin_instrument_is_not_archived(
    database: tuple[Engine, str],
) -> None:
    store = SnapshotStore(database[0])
    with pytest.raises(SnapshotConflict):
        store.create(sample_snapshot(uuid4()))
    instrument_id = registered(database)
    with pytest.raises(SnapshotConflict):
        store.create(
            sample_snapshot(
                instrument_id, data_origin="live", source_url="https://example.invalid/fixture"
            )
        )
    assert store.list(instrument_id).items == []


@pytest.mark.postgres
def test_archive_source_need_not_match_registry_source(database: tuple[Engine, str]) -> None:
    instrument_id = registered(database)
    data = sample_snapshot(instrument_id, source_id="independent-synthetic-archive-source")
    assert SnapshotStore(database[0]).create(data).source_id == data.source_id


@pytest.mark.postgres
def test_missing_snapshot_and_instrument_are_not_found(database: tuple[Engine, str]) -> None:
    store = SnapshotStore(database[0])
    with pytest.raises(SnapshotNotFound):
        store.get(uuid4())
    with pytest.raises(SnapshotNotFound):
        store.content(uuid4())
    with pytest.raises(SnapshotNotFound):
        store.list(uuid4())


@pytest.mark.postgres
def test_uuid_keyset_is_scoped_to_instrument(database: tuple[Engine, str]) -> None:
    instrument_id = registered(database)
    other = instrument_sample(symbol="OTHER")
    InstrumentStore(database[0]).create(other)
    store = SnapshotStore(database[0])
    for index in range(1, 5):
        store.create(sample_snapshot(instrument_id, snapshot_id=str(UUID(int=index))))
    store.create(sample_snapshot(other.instrument_id, snapshot_id=str(UUID(int=5))))
    first = store.list(instrument_id, limit=2)
    assert [item.snapshot_id.int for item in first.items] == [1, 2]
    assert first.next_after_id == UUID(int=2)
    second = store.list(instrument_id, after_id=first.next_after_id, limit=2)
    assert [item.snapshot_id.int for item in second.items] == [3, 4]
    assert second.next_after_id is None


@pytest.mark.postgres
def test_mutable_create_instance_is_revalidated_before_transaction(
    database: tuple[Engine, str],
) -> None:
    instrument_id = registered(database)
    data = sample_snapshot(instrument_id)
    data.content_base64 = base64.b64encode(b"tampered").decode("ascii")
    with pytest.raises(ValidationError):
        SnapshotStore(database[0]).create(data)
    assert SnapshotStore(database[0]).list(instrument_id).items == []


@pytest.mark.postgres
def test_parallel_identical_retry_has_one_creation(database: tuple[Engine, str]) -> None:
    data = sample_snapshot(registered(database))
    barrier = Barrier(2)

    def upload() -> bool:
        barrier.wait(timeout=5)
        return SnapshotStore(database[0]).create(data).created

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: upload(), range(2)))
    assert sorted(results) == [False, True]


@pytest.mark.parametrize("corruption", ["bytes", "metadata", "registry"])
@pytest.mark.postgres
def test_all_read_paths_detect_corruption(database: tuple[Engine, str], corruption: str) -> None:
    instrument_id = registered(database)
    data = sample_snapshot(instrument_id)
    store = SnapshotStore(database[0])
    store.create(data)
    with database[0].begin() as connection:
        if corruption == "registry":
            connection.execute(text("ALTER TABLE instruments DISABLE TRIGGER USER"))
            connection.execute(instruments.update().values(symbol="CORRUPT"))
            connection.execute(text("ALTER TABLE instruments ENABLE TRIGGER USER"))
        else:
            connection.execute(text("ALTER TABLE raw_snapshots DISABLE TRIGGER USER"))
            if corruption == "bytes":
                connection.execute(raw_snapshots.update().values(content=b"tampered bytes"))
            else:
                connection.execute(raw_snapshots.update().values(source_id="corrupt-index"))
            connection.execute(text("ALTER TABLE raw_snapshots ENABLE TRIGGER USER"))
    for operation in [
        lambda: store.get(data.snapshot_id),
        lambda: store.content(data.snapshot_id),
        lambda: store.list(instrument_id),
    ]:
        with pytest.raises(CorruptReport):
            operation()


@pytest.mark.postgres
def test_snapshot_survives_new_engine(database: tuple[Engine, str]) -> None:
    data = sample_snapshot(registered(database), b"\x00\xffpersistent bytes")
    original = SnapshotStore(database[0]).create(data)
    engine = create_engine(
        os.environ["ALPHASENSE_TEST_DATABASE_URL"],
        hide_parameters=True,
        connect_args={"options": f"-c search_path={database[1]}"},
    )
    try:
        record, content = SnapshotStore(engine).content(data.snapshot_id)
        assert record.created_at == original.created_at
        assert content == data.raw_bytes()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "kwargs", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"after_id": "not-a-uuid"}]
)
@pytest.mark.postgres
def test_direct_list_calls_validate_pagination(
    database: tuple[Engine, str], kwargs: dict[str, Any]
) -> None:
    with pytest.raises((ValueError, ValidationError)):
        SnapshotStore(database[0]).list(registered(database), **kwargs)
