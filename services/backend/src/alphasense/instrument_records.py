"""Shared payload/index consistency check without database or error-layer imports."""

from collections.abc import Mapping

from alphasense.instrument_contracts import InstrumentCreate, InstrumentRecord


def decode_instrument(row: Mapping[str, object]) -> InstrumentRecord:
    data = InstrumentCreate.model_validate(row["payload"])
    expected = {
        "instrument_id": data.instrument_id,
        "symbol": data.symbol,
        "exchange_mic": data.exchange_mic,
        "currency": data.currency,
        "asset_type": data.asset_type,
        "data_origin": data.data_origin,
        "as_of": data.as_of,
        "available_at": data.available_at,
    }
    if any(row[key] != value for key, value in expected.items()):
        raise ValueError("Instrument integrity check failed")
    return InstrumentRecord.model_validate({**data.model_dump(), "created_at": row["created_at"]})
