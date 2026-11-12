"""Canonical v1 validation contracts, independent of the legacy Node demo."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    model_validator,
)

TIMESTAMP_PATTERN = r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:[Zz]|[+-]\d{2}:\d{2})"


def timestamp_input(value: object) -> str | datetime:
    """Reject epoch coercion and dates without an explicit time and timezone."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not re.fullmatch(TIMESTAMP_PATTERN, value):
        raise ValueError("RFC3339 timestamp with timezone required")
    return value


Timestamp = Annotated[
    AwareDatetime,
    BeforeValidator(timestamp_input),
    AfterValidator(lambda value: value.astimezone(UTC)),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date-time",
            "pattern": f"^{TIMESTAMP_PATTERN}$",
            "not": {"pattern": r"\s$"},
        }
    ),
]
# Python's JSON Schema regex accepts a final newline before `$`, while Pydantic's
# Rust regex uses a strict end anchor. The explicit exclusion keeps both in sync.
Identifier = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"^\S(?:.*\S)?$"),
    Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
]
Unit = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=64, pattern=r"^\S(?:.*\S)?$"),
    Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
]
Reason = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"^\S(?:.*\S)?$"),
    Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
]
Metric = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$"),
    Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
]
Currency = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[A-Z]{3}$"),
    Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
]
Number = Annotated[
    float,
    Field(strict=True, allow_inf_nan=False),
    # JSONB normalizes signed zero; normalize before checksum calculation too.
    AfterValidator(lambda value: 0.0 if value == 0 else value),
]
Count = Annotated[int, Field(strict=True, ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ObservationBase(Contract):
    metric: Metric
    unit: Unit
    currency: Currency | None
    period_start: Timestamp
    period_end: Timestamp

    @model_validator(mode="after")
    def check_period(self) -> Self:
        if self.period_start > self.period_end:
            raise ValueError("period_start must not exceed period_end")
        return self


class AvailableObservation(ObservationBase):
    status: Literal["available"]
    value: Number
    source_id: Identifier
    snapshot_id: Identifier
    event_time: Timestamp
    available_at: Timestamp

    @model_validator(mode="after")
    def check_chronology(self) -> Self:
        if not self.period_end <= self.event_time <= self.available_at:
            raise ValueError("period_end <= event_time <= available_at required")
        return self


class AbsentObservation(ObservationBase):
    status: Literal["missing", "not_applicable"]
    value: None
    reason: Reason


Observation = Annotated[AvailableObservation | AbsentObservation, Field(discriminator="status")]


class ResearchInput(Contract):
    schema_version: Literal["1.0"]
    instrument_id: Identifier
    asset_type: Literal["equity", "etf", "commodity"]
    as_of: Timestamp
    data_origin: Literal["synthetic", "live"]
    observations: Annotated[list[Observation], Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def check_point_in_time_and_duplicates(self) -> Self:
        seen: set[tuple[str, str, str | None, datetime, datetime]] = set()
        for observation in self.observations:
            if observation.period_end > self.as_of:
                raise ValueError("observation period exceeds as_of")
            if (
                isinstance(observation, AvailableObservation)
                and observation.available_at > self.as_of
            ):
                raise ValueError("observation was unavailable at as_of")
            key = (
                observation.metric,
                observation.unit,
                observation.currency,
                observation.period_start,
                observation.period_end,
            )
            if key in seen:
                raise ValueError("duplicate observation context")
            seen.add(key)
        return self


class ValidationResult(Contract):
    schema_version: Literal["1.0"]
    instrument_id: Identifier
    as_of: Timestamp
    data_origin: Literal["synthetic", "live"]
    status: Literal["complete", "partial", "blocked"]
    available_count: Count
    missing_count: Count
    not_applicable_count: Count


class HealthResult(Contract):
    status: Literal["ok"] = "ok"
    mode: Literal["validation-only", "postgresql"] = "validation-only"
    research_only: Literal[True] = True
    external_providers_enabled: bool = False


def summarize(payload: ResearchInput) -> ValidationResult:
    """Summarize supplied observations, without asserting research completeness."""
    available = sum(item.status == "available" for item in payload.observations)
    missing = sum(item.status == "missing" for item in payload.observations)
    not_applicable = sum(item.status == "not_applicable" for item in payload.observations)
    status: Literal["complete", "partial", "blocked"] = (
        "blocked" if available == 0 else "partial" if missing else "complete"
    )
    return ValidationResult(
        schema_version="1.0",
        instrument_id=payload.instrument_id,
        as_of=payload.as_of,
        data_origin=payload.data_origin,
        status=status,
        available_count=available,
        missing_count=missing,
        not_applicable_count=not_applicable,
    )
