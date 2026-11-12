"""Declared immutable listing identity; no provider or licensing certification."""

import re
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Currency, Identifier, Reason, Timestamp
from alphasense.report_contracts import ReportUUID, SourceURL

CONTROL_PATTERN = r"[\x00-\x1f\x7f]"
Symbol = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9._-]*$"),
    Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
]
MIC = Annotated[
    str, StringConstraints(strict=True, min_length=4, max_length=4, pattern=r"^[A-Z0-9]{4}$")
]
DisplayName = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=200, pattern=r"^\S(?:[^\x00-\x1f\x7f]*\S)?$"
    ),
    Field(json_schema_extra={"not": {"pattern": CONTROL_PATTERN + r"|\s$"}}),
]
SourceID = Annotated[
    Identifier, Field(json_schema_extra={"not": {"pattern": CONTROL_PATTERN + r"|\s$"}})
]
License = Annotated[
    Reason, Field(json_schema_extra={"not": {"pattern": CONTROL_PATTERN + r"|\s$"}})
]
SearchQuery = Annotated[
    str,
    StringConstraints(strict=True, max_length=128, pattern=r"^[^\x00-\x1f\x7f]*$"),
    Field(json_schema_extra={"not": {"pattern": CONTROL_PATTERN}}),
]


def no_url_controls(value: object) -> object:
    if isinstance(value, str) and re.search(CONTROL_PATTERN, value):
        raise ValueError("URL contains control characters")
    return value


InstrumentURL = Annotated[
    SourceURL,
    BeforeValidator(no_url_controls),
    Field(json_schema_extra={"not": {"pattern": CONTROL_PATTERN}}),
]


class InstrumentCreate(Contract):
    schema_version: Literal["1.0"]
    instrument_id: ReportUUID
    symbol: Symbol
    exchange_mic: MIC | None
    currency: Currency
    display_name: DisplayName
    asset_type: Literal["equity", "etf", "commodity"]
    data_origin: Literal["synthetic", "live"]
    as_of: Timestamp
    available_at: Timestamp
    source_id: SourceID
    source_url: InstrumentURL | None
    license: License

    @model_validator(mode="after")
    def check_declarations(self) -> Self:
        if self.available_at > self.as_of:
            raise ValueError("metadata was unavailable at as_of")
        if self.asset_type != "commodity" and self.exchange_mic is None:
            raise ValueError("exchange MIC required for listed equity or ETF")
        if self.data_origin == "live" and self.source_url is None:
            raise ValueError("live source URL required")
        for value in (self.source_id, self.license, self.display_name):
            if re.search(CONTROL_PATTERN, value):
                raise ValueError("metadata contains control characters")
        return self


class InstrumentRecord(InstrumentCreate):
    created_at: Timestamp


class InstrumentWrite(InstrumentRecord):
    created: bool


class InstrumentPage(Contract):
    items: Annotated[list[InstrumentRecord], Field(max_length=100)]
    next_after_id: ReportUUID | None
