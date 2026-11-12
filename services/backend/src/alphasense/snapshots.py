"""Atomic immutable byte archive. URLs are metadata, never fetch instructions."""

import hashlib
from collections.abc import Mapping
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from alphasense.db import CorruptReport, StoreUnavailable, get_store
from alphasense.db_schema import instruments, raw_snapshots
from alphasense.instrument_records import decode_instrument
from alphasense.report_contracts import ReportUUID
from alphasense.snapshot_contracts import (
    SnapshotCreate,
    SnapshotMetadata,
    SnapshotPage,
    SnapshotRecord,
    SnapshotWrite,
)


class SnapshotConflict(Exception):
    """An immutable archive identity or registered instrument conflicts."""


class SnapshotNotFound(Exception):
    """The requested snapshot or instrument is not archived."""


def decode_snapshot(row: Mapping[str, object]) -> tuple[SnapshotRecord, bytes]:
    try:
        metadata = SnapshotMetadata.model_validate(row["metadata"])
        expected = {
            "snapshot_id": metadata.snapshot_id,
            "instrument_id": metadata.instrument_id,
            "data_origin": metadata.data_origin,
            "source_id": metadata.source_id,
            "as_of": metadata.as_of,
            "available_at": metadata.available_at,
            "retrieved_at": metadata.retrieved_at,
            "sha256": metadata.sha256,
            "byte_length": metadata.byte_length,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise ValueError("snapshot metadata conflicts with index")
        stored_bytes = row["content"]
        if not isinstance(stored_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("snapshot content is not bytes")
        content = bytes(stored_bytes)
        if (
            len(content) != metadata.byte_length
            or hashlib.sha256(content).hexdigest() != metadata.sha256
        ):
            raise ValueError("snapshot content checksum mismatch")
        record = SnapshotRecord.model_validate(
            {**metadata.model_dump(mode="python"), "created_at": row["created_at"]}
        )
        return record, content
    except (ValidationError, ValueError, TypeError, KeyError):
        raise CorruptReport("Snapshot integrity check failed") from None


def _registered_origin(connection: Connection, instrument_id: UUID) -> str | None:
    row = (
        connection.execute(select(instruments).where(instruments.c.instrument_id == instrument_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    try:
        return decode_instrument(dict(row)).data_origin
    except (ValidationError, ValueError, TypeError, KeyError):
        raise CorruptReport("Instrument integrity check failed") from None


def _check_read_identity(connection: Connection, record: SnapshotRecord) -> None:
    if _registered_origin(connection, record.instrument_id) != record.data_origin:
        raise CorruptReport("Snapshot instrument integrity check failed")


class SnapshotStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def create(self, data: SnapshotCreate) -> SnapshotWrite:
        checked = SnapshotCreate.model_validate(data.model_dump(mode="python"))
        content = checked.raw_bytes()
        metadata = SnapshotMetadata.model_validate(checked.model_dump(exclude={"content_base64"}))
        payload = metadata.model_dump(mode="json")
        try:
            with self.engine.begin() as connection:
                if _registered_origin(connection, checked.instrument_id) != checked.data_origin:
                    raise SnapshotConflict("Registered instrument identity required")
                inserted = connection.execute(
                    insert(raw_snapshots)
                    .values(
                        snapshot_id=checked.snapshot_id,
                        instrument_id=checked.instrument_id,
                        data_origin=checked.data_origin,
                        source_id=checked.source_id,
                        as_of=checked.as_of,
                        available_at=checked.available_at,
                        retrieved_at=checked.retrieved_at,
                        sha256=checked.sha256,
                        byte_length=checked.byte_length,
                        metadata=payload,
                        content=content,
                    )
                    .on_conflict_do_nothing(index_elements=["snapshot_id"])
                    .returning(raw_snapshots.c.snapshot_id)
                ).scalar_one_or_none()
                row = (
                    connection.execute(
                        select(raw_snapshots).where(
                            raw_snapshots.c.snapshot_id == checked.snapshot_id
                        )
                    )
                    .mappings()
                    .one()
                )
                stored, stored_bytes = decode_snapshot(dict(row))
                stored_metadata = stored.model_dump(mode="json", exclude={"created_at"})
                if stored_metadata != payload or stored_bytes != content:
                    raise SnapshotConflict("Snapshot identity conflict")
                return SnapshotWrite(**stored.model_dump(), created=inserted is not None)
        except IntegrityError:
            raise SnapshotConflict("Snapshot identity conflict") from None
        except SQLAlchemyError:
            raise StoreUnavailable("Snapshot storage unavailable") from None

    def get(self, snapshot_id: UUID) -> SnapshotRecord:
        return self.content(snapshot_id)[0]

    def content(self, snapshot_id: UUID) -> tuple[SnapshotRecord, bytes]:
        checked_id = TypeAdapter(ReportUUID).validate_python(snapshot_id)
        try:
            with self.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(raw_snapshots).where(raw_snapshots.c.snapshot_id == checked_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise SnapshotNotFound("Snapshot not found")
                record, content = decode_snapshot(dict(row))
                _check_read_identity(connection, record)
                return record, content
        except SQLAlchemyError:
            raise StoreUnavailable("Snapshot storage unavailable") from None

    def list(
        self, instrument_id: UUID, after_id: UUID | None = None, limit: int = 50
    ) -> SnapshotPage:
        checked_instrument = TypeAdapter(ReportUUID).validate_python(instrument_id)
        checked_after = TypeAdapter(ReportUUID | None).validate_python(after_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid pagination")
        statement = (
            select(raw_snapshots)
            .where(raw_snapshots.c.instrument_id == checked_instrument)
            .order_by(raw_snapshots.c.snapshot_id)
            .limit(limit + 1)
        )
        if checked_after is not None:
            statement = statement.where(raw_snapshots.c.snapshot_id > checked_after)
        try:
            with self.engine.connect() as connection:
                origin = _registered_origin(connection, checked_instrument)
                if origin is None:
                    raise SnapshotNotFound("Instrument not found")
                rows = connection.execute(statement).mappings().all()
                records = [decode_snapshot(dict(row))[0] for row in rows]
                if any(record.data_origin != origin for record in records):
                    raise CorruptReport("Snapshot instrument integrity check failed")
                items = records[:limit]
                cursor = items[-1].snapshot_id if len(records) > limit else None
                return SnapshotPage(items=items, next_after_id=cursor)
        except SQLAlchemyError:
            raise StoreUnavailable("Snapshot storage unavailable") from None


def get_snapshot_store() -> SnapshotStore:
    return SnapshotStore(get_store().engine)
