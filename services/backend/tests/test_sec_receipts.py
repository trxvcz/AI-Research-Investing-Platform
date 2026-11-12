"""Internal receipt ownership and first-seen cache gates on real PostgreSQL."""

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from test_runs import database as database
from test_runs import instrument

from alphasense.db import CorruptReport
from alphasense.db_schema import MIGRATION_HEAD, sec_ingestions
from alphasense.instrument_contracts import InstrumentCreate
from alphasense.sec_contracts import SEC_LICENSE, SEC_SOURCE_IDS, SecFetchRequest, sec_url
from alphasense.sec_receipts import SecReceiptStore
from alphasense.snapshot_contracts import SnapshotCreate, SnapshotRecord
from alphasense.snapshots import SnapshotStore

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.postgres
REQUEST = SecFetchRequest(cik="0000000123", resource="submissions")


def identity(engine: Engine) -> InstrumentCreate:
    return instrument(engine, data_origin="live", source_url=sec_url(REQUEST))


def snapshot(
    engine: Engine,
    registered: InstrumentCreate,
    *,
    raw: bytes = b'{"synthetic":true}\n',
    retrieved: datetime | None = None,
    **changes: Any,
) -> SnapshotRecord:
    when = retrieved or datetime.now(UTC)
    values = dict(
        schema_version="1.0",
        snapshot_id=uuid4(),
        instrument_id=registered.instrument_id,
        data_origin="live",
        source_id=SEC_SOURCE_IDS[REQUEST.resource],
        source_url=sec_url(REQUEST),
        license=SEC_LICENSE,
        as_of=when,
        available_at=when,
        retrieved_at=when,
        media_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        content_base64=base64.b64encode(raw).decode("ascii"),
    )
    values.update(changes)
    result = SnapshotStore(engine).create(SnapshotCreate.model_validate(values))
    return SnapshotRecord.model_validate(result.model_dump(exclude={"created"}))


def test_public_raw_upload_is_not_an_internal_sec_cache_entry(database: Engine) -> None:
    registered = identity(database)
    uploaded = snapshot(database, registered)
    receipts = SecReceiptStore(database)
    assert receipts.find(registered.instrument_id, sec_url(REQUEST)) is None
    assert receipts.find(registered.instrument_id, sec_url(REQUEST), uploaded.sha256) is None
    assert receipts.record(uploaded, REQUEST) == uploaded
    assert receipts.find(registered.instrument_id, sec_url(REQUEST)) == uploaded


def test_identical_bytes_retain_first_committed_receipt_after_refresh(database: Engine) -> None:
    registered = identity(database)
    first = snapshot(database, registered)
    later = snapshot(database, registered, retrieved=first.retrieved_at + timedelta(seconds=1))
    receipts = SecReceiptStore(database)
    assert first.snapshot_id != later.snapshot_id
    assert receipts.record(first, REQUEST) == first
    assert receipts.record(later, REQUEST) == first
    assert receipts.record(first, REQUEST) == first
    with database.connect() as connection:
        assert len(connection.execute(select(sec_ingestions)).all()) == 1


def test_find_selects_latest_trusted_content_not_latest_public_upload(database: Engine) -> None:
    registered = identity(database)
    first = snapshot(database, registered, raw=b'{"synthetic":1}')
    second = snapshot(
        database,
        registered,
        raw=b'{"synthetic":2}',
        retrieved=first.retrieved_at + timedelta(seconds=1),
    )
    untrusted = snapshot(
        database,
        registered,
        raw=b'{"synthetic":3}',
        retrieved=first.retrieved_at + timedelta(seconds=2),
    )
    receipts = SecReceiptStore(database)
    receipts.record(first, REQUEST)
    receipts.record(second, REQUEST)
    assert receipts.find(registered.instrument_id, sec_url(REQUEST)) == second
    assert receipts.find(registered.instrument_id, sec_url(REQUEST), first.sha256) == first
    assert receipts.find(registered.instrument_id, sec_url(REQUEST), untrusted.sha256) is None


def test_concurrent_identical_receipts_return_one_stable_winner(database: Engine) -> None:
    registered = identity(database)
    candidates = [snapshot(database, registered), snapshot(database, registered)]
    barrier = Barrier(2)

    def record(index: int) -> SnapshotRecord:
        barrier.wait(timeout=5)
        return SecReceiptStore(database).record(candidates[index], REQUEST)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, (0, 1)))
    assert results[0] == results[1] and results[0] in candidates
    assert SecReceiptStore(database).find(registered.instrument_id, sec_url(REQUEST)) == results[0]
    with database.connect() as connection:
        assert len(connection.execute(select(sec_ingestions)).all()) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"source_id": "manual-upload"},
        {"license": "generated fixture"},
        {"media_type": "text/plain"},
        {"source_url": "https://data.sec.gov/submissions/CIK0000000456.json"},
    ],
)
def test_receipt_rejects_raw_identity_mismatch(database: Engine, change: dict[str, Any]) -> None:
    registered = identity(database)
    uploaded = snapshot(database, registered, **change)
    with pytest.raises(ValueError):
        SecReceiptStore(database).record(uploaded, REQUEST)


def test_receipt_rejects_backdated_availability_and_unarchived_candidate(database: Engine) -> None:
    registered = identity(database)
    when = datetime.now(UTC)
    uploaded = snapshot(database, registered, retrieved=when, available_at=when - timedelta(days=1))
    with pytest.raises(ValueError):
        SecReceiptStore(database).record(uploaded, REQUEST)
    proper = snapshot(database, registered)
    forged = proper.model_copy(update={"snapshot_id": uuid4()})
    with pytest.raises(ValueError):
        SecReceiptStore(database).record(forged, REQUEST)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE sec_ingestions SET retrieved_at=retrieved_at + INTERVAL '1 day'",
        "DELETE FROM sec_ingestions",
        "TRUNCATE sec_ingestions",
    ],
)
def test_receipt_history_cannot_be_mutated(database: Engine, statement: str) -> None:
    registered = identity(database)
    SecReceiptStore(database).record(snapshot(database, registered), REQUEST)
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(text(statement))


@pytest.mark.parametrize(
    "change",
    [
        {"cik": "0000000456"},
        {"resource": "net_income"},
        {"sha256": "a" * 64},
        {"source_url": "https://example.invalid/PRIVATE"},
        {"retrieved_at": datetime(2024, 1, 1, tzinfo=UTC)},
        {"instrument_id": UUID(int=1)},
    ],
)
def test_sql_insert_guard_binds_all_receipt_metadata(
    database: Engine, change: dict[str, Any]
) -> None:
    registered = identity(database)
    uploaded = snapshot(database, registered)
    values = dict(
        snapshot_id=uploaded.snapshot_id,
        instrument_id=registered.instrument_id,
        cik=REQUEST.cik,
        resource=REQUEST.resource,
        source_url=sec_url(REQUEST),
        sha256=uploaded.sha256,
        retrieved_at=uploaded.retrieved_at,
    )
    values.update(change)
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(sec_ingestions.insert().values(**values))


def test_receipt_reads_verify_hash_and_metadata_not_just_fk(database: Engine) -> None:
    registered = identity(database)
    uploaded = snapshot(database, registered)
    receipts = SecReceiptStore(database)
    receipts.record(uploaded, REQUEST)
    with database.begin() as connection:
        connection.execute(text("ALTER TABLE sec_ingestions DISABLE TRIGGER USER"))
        connection.execute(sec_ingestions.update().values(cik="0000000456"))
        connection.execute(text("ALTER TABLE sec_ingestions ENABLE TRIGGER USER"))
    with pytest.raises(CorruptReport):
        receipts.find(registered.instrument_id, sec_url(REQUEST))


def test_receipt_reads_verify_actual_raw_byte_hash(database: Engine) -> None:
    registered = identity(database)
    uploaded = snapshot(database, registered)
    receipts = SecReceiptStore(database)
    receipts.record(uploaded, REQUEST)
    with database.begin() as connection:
        connection.execute(text("ALTER TABLE raw_snapshots DISABLE TRIGGER USER"))
        connection.execute(text("UPDATE raw_snapshots SET content=decode('00','hex')"))
        connection.execute(text("ALTER TABLE raw_snapshots ENABLE TRIGGER USER"))
    with pytest.raises(CorruptReport):
        receipts.find(registered.instrument_id, sec_url(REQUEST))


def test_empty_receipt_downgrade_and_reupgrade_are_safe(database: Engine) -> None:
    with database.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0006_sec_pipeline")
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD


def test_downgrade_refuses_nonempty_internal_receipts(database: Engine) -> None:
    registered = identity(database)
    SecReceiptStore(database).record(snapshot(database, registered), REQUEST)
    with pytest.raises(RuntimeError, match="non-empty SEC ingestion receipts"):
        with database.begin() as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0006_sec_pipeline")
