"""Append-only PostgreSQL instrument identities; no provider discovery or updates."""

from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine, RowMapping, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from alphasense.db import CorruptReport, StoreUnavailable, get_store
from alphasense.db_schema import instruments
from alphasense.instrument_contracts import (
    InstrumentCreate,
    InstrumentPage,
    InstrumentRecord,
    InstrumentWrite,
    SearchQuery,
)
from alphasense.instrument_records import decode_instrument
from alphasense.report_contracts import ReportUUID


class InstrumentConflict(Exception):
    """The requested identity conflicts with an existing immutable instrument."""


class InstrumentNotFound(Exception):
    """The requested instrument identity has not been registered."""


def _decode(row: RowMapping) -> InstrumentRecord:
    try:
        return decode_instrument(dict(row))
    except (ValidationError, ValueError, TypeError, KeyError):
        raise CorruptReport("Instrument integrity check failed") from None


class InstrumentStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def create(self, data: InstrumentCreate) -> InstrumentWrite:
        # Never trust mutable Pydantic instances passed by an internal caller.
        checked = InstrumentCreate.model_validate(data.model_dump(mode="python"))
        payload = checked.model_dump(mode="json")
        try:
            with self.engine.begin() as connection:
                inserted = connection.execute(
                    insert(instruments)
                    .values(
                        instrument_id=checked.instrument_id,
                        symbol=checked.symbol,
                        exchange_mic=checked.exchange_mic,
                        currency=checked.currency,
                        asset_type=checked.asset_type,
                        data_origin=checked.data_origin,
                        as_of=checked.as_of,
                        available_at=checked.available_at,
                        payload=payload,
                    )
                    .on_conflict_do_nothing()
                    .returning(instruments.c.instrument_id)
                ).scalar_one_or_none()
                row = (
                    connection.execute(
                        select(instruments).where(
                            instruments.c.instrument_id == checked.instrument_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise InstrumentConflict("Instrument identity conflict")
                stored = _decode(row)
                original = InstrumentCreate.model_validate(
                    stored.model_dump(exclude={"created_at"}, mode="python")
                )
                if original.model_dump(mode="json") != payload:
                    raise InstrumentConflict("Instrument identity conflict")
                return InstrumentWrite(**stored.model_dump(), created=inserted is not None)
        except IntegrityError:
            raise InstrumentConflict("Instrument identity conflict") from None
        except SQLAlchemyError:
            raise StoreUnavailable("Instrument storage unavailable") from None

    def get(self, instrument_id: UUID) -> InstrumentRecord:
        checked_id = TypeAdapter(ReportUUID).validate_python(instrument_id)
        try:
            with self.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(instruments).where(instruments.c.instrument_id == checked_id)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise InstrumentNotFound("Instrument not found")
                return _decode(row)
        except SQLAlchemyError:
            raise StoreUnavailable("Instrument storage unavailable") from None

    def search(
        self,
        query: str = "",
        after_id: UUID | None = None,
        limit: int = 50,
        data_origin: Literal["synthetic", "live"] | None = None,
    ) -> InstrumentPage:
        checked_query = TypeAdapter(SearchQuery).validate_python(query)
        checked_id = TypeAdapter(ReportUUID | None).validate_python(after_id)
        checked_origin = TypeAdapter(Literal["synthetic", "live"] | None).validate_python(
            data_origin
        )
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid pagination")
        statement = select(instruments).order_by(instruments.c.instrument_id).limit(limit + 1)
        if checked_id is not None:
            statement = statement.where(instruments.c.instrument_id > checked_id)
        if checked_origin is not None:
            statement = statement.where(instruments.c.data_origin == checked_origin)
        if checked_query:
            statement = statement.where(
                or_(
                    instruments.c.symbol.icontains(checked_query, autoescape=True),
                    instruments.c.payload["display_name"].astext.icontains(
                        checked_query, autoescape=True
                    ),
                )
            )
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(statement).mappings().all()
                # The lookahead row is validated too: corruption is never hidden by pagination.
                records = [_decode(row) for row in rows]
                items = records[:limit]
                cursor = items[-1].instrument_id if len(records) > limit else None
                return InstrumentPage(items=items, next_after_id=cursor)
        except SQLAlchemyError:
            raise StoreUnavailable("Instrument storage unavailable") from None


def get_instrument_store() -> InstrumentStore:
    return InstrumentStore(get_store().engine)
