"""Trusted internal receipts; raw uploads alone are never SEC cache entries."""

import re
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Connection, Engine, RowMapping, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from alphasense.db import CorruptReport, StoreUnavailable
from alphasense.db_schema import raw_snapshots, sec_ingestions
from alphasense.report_contracts import ReportUUID, Sha256
from alphasense.sec_contracts import (
    SEC_CONCEPTS,
    SEC_LICENSE,
    SEC_SOURCE_IDS,
    SecFetchRequest,
    sec_url,
)
from alphasense.snapshot_contracts import SnapshotRecord
from alphasense.snapshots import decode_snapshot


def _request_for_url(url: str) -> SecFetchRequest:
    for role, tag in SEC_CONCEPTS.items():
        match = re.fullmatch(
            r"https://data\.sec\.gov/api/xbrl/companyconcept/CIK([0-9]{10})/us-gaap/"
            + tag
            + r"\.json",
            url,
        )
        if match:
            return SecFetchRequest.model_validate({"cik": match[1], "resource": role})
    submissions = re.fullmatch(r"https://data\.sec\.gov/submissions/CIK([0-9]{10})\.json", url)
    concept = re.fullmatch(
        r"https://data\.sec\.gov/api/xbrl/companyconcept/CIK([0-9]{10})/us-gaap/"
        r"(RevenueFromContractWithCustomerExcludingAssessedTax|Revenues|SalesRevenueNet|NetIncomeLoss)"
        r"\.json",
        url,
    )
    if submissions:
        return SecFetchRequest(cik=submissions[1], resource="submissions")
    if concept:
        if concept[2] == "NetIncomeLoss":
            return SecFetchRequest(cik=concept[1], resource="net_income")
        return SecFetchRequest.model_validate(
            dict(
                cik=concept[1],
                resource="revenue",
                revenue_concept=concept[2],
            )
        )
    raise ValueError("SEC receipt URL is not a supported resource")


def _validate_identity(snapshot: SnapshotRecord, request: SecFetchRequest) -> None:
    if (
        snapshot.data_origin != "live"
        or snapshot.source_id != SEC_SOURCE_IDS[request.resource]
        or str(snapshot.source_url) != sec_url(request)
        or snapshot.license != SEC_LICENSE
        or snapshot.media_type != "application/json"
        or snapshot.available_at != snapshot.retrieved_at
        or snapshot.as_of != snapshot.retrieved_at
    ):
        raise ValueError("SEC receipt snapshot identity conflict")


def _decode_receipt(connection: Connection, receipt: RowMapping) -> SnapshotRecord:
    try:
        row = (
            connection.execute(
                select(raw_snapshots).where(raw_snapshots.c.snapshot_id == receipt["snapshot_id"])
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError("SEC receipt raw snapshot is missing")
        snapshot, _content = decode_snapshot(dict(row))
        request = _request_for_url(receipt["source_url"])
        _validate_identity(snapshot, request)
        expected = {
            "instrument_id": snapshot.instrument_id,
            "cik": request.cik,
            "resource": request.resource,
            "source_url": str(snapshot.source_url),
            "sha256": snapshot.sha256,
            "retrieved_at": snapshot.retrieved_at,
        }
        if any(receipt[name] != value for name, value in expected.items()):
            raise ValueError("SEC receipt metadata conflict")
        return snapshot
    except (ValidationError, ValueError, TypeError, KeyError):
        raise CorruptReport("SEC ingestion receipt integrity check failed") from None


class SecReceiptStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def find(
        self, instrument_id: UUID, url: str, sha256: str | None = None
    ) -> SnapshotRecord | None:
        checked_id = TypeAdapter(ReportUUID).validate_python(instrument_id)
        _request_for_url(url)
        checked_hash = TypeAdapter(Sha256 | None).validate_python(sha256)
        query = select(sec_ingestions).where(
            sec_ingestions.c.instrument_id == checked_id,
            sec_ingestions.c.source_url == url,
        )
        if checked_hash is not None:
            query = query.where(sec_ingestions.c.sha256 == checked_hash)
        query = query.order_by(
            sec_ingestions.c.retrieved_at.desc(), sec_ingestions.c.snapshot_id
        ).limit(1)
        try:
            with self.engine.connect() as connection:
                receipt = connection.execute(query).mappings().one_or_none()
                return _decode_receipt(connection, receipt) if receipt is not None else None
        except SQLAlchemyError:
            raise StoreUnavailable("SEC ingestion receipt storage unavailable") from None

    def record(self, snapshot: SnapshotRecord, request: SecFetchRequest) -> SnapshotRecord:
        checked = SnapshotRecord.model_validate(snapshot.model_dump(mode="python", warnings=False))
        resource = SecFetchRequest.model_validate(request.model_dump(mode="python", warnings=False))
        _validate_identity(checked, resource)
        try:
            with self.engine.begin() as connection:
                row = (
                    connection.execute(
                        select(raw_snapshots).where(
                            raw_snapshots.c.snapshot_id == checked.snapshot_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise ValueError("SEC receipt snapshot is not archived")
                stored, _content = decode_snapshot(dict(row))
                if stored != checked:
                    raise ValueError("SEC receipt candidate differs from archived snapshot")
                connection.execute(
                    insert(sec_ingestions)
                    .values(
                        snapshot_id=checked.snapshot_id,
                        instrument_id=checked.instrument_id,
                        cik=resource.cik,
                        resource=resource.resource,
                        source_url=sec_url(resource),
                        sha256=checked.sha256,
                        retrieved_at=checked.retrieved_at,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["instrument_id", "source_url", "sha256"]
                    )
                )
                winner = (
                    connection.execute(
                        select(sec_ingestions).where(
                            sec_ingestions.c.instrument_id == checked.instrument_id,
                            sec_ingestions.c.source_url == sec_url(resource),
                            sec_ingestions.c.sha256 == checked.sha256,
                        )
                    )
                    .mappings()
                    .one()
                )
                return _decode_receipt(connection, winner)
        except IntegrityError:
            raise ValueError("SEC receipt identity conflict") from None
        except SQLAlchemyError:
            raise StoreUnavailable("SEC ingestion receipt storage unavailable") from None
