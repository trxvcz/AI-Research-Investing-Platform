"""Server-owned provider admission evidence; never accepted from a public request."""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, ConfigDict, Field, model_validator

from alphasense.contracts import Contract, Timestamp
from alphasense.instrument_contracts import InstrumentURL
from alphasense.report_contracts import Sha256
from alphasense.run_contracts import Actor

QuotaLimit = Annotated[int, Field(strict=True, ge=0, le=1000000)]
DataClassification = Literal["public", "private", "secret"]


def exact_charge(value: object) -> Decimal:
    # Policy JSON is decoded with Decimal before validation. In particular, positive
    # amounts smaller than a binary float must never round down to a free call.
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("An exact non-negative charge is required")
    if isinstance(value, float) and value == 0:
        raise ValueError("Binary float zero is ambiguous; use an integer or exact decimal zero")
    if isinstance(value, str) and value != value.strip():
        raise ValueError("Charge cannot contain surrounding whitespace")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid charge") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("An exact non-negative charge is required")
    return amount


ChargeAmount = Annotated[Decimal, BeforeValidator(exact_charge), Field(ge=0, allow_inf_nan=False)]


class ProviderGrant(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: Actor
    enabled: bool = Field(strict=True)
    capability: Literal["data", "model"]
    execution: Literal["local", "remote"]
    billing: Literal["free_no_billing", "free_tier", "paid", "unknown"]
    max_charge_usd: ChargeAmount | None
    paid_fallback: bool = Field(strict=True)
    hard_cap_verified: bool = Field(strict=True)
    quality_pass: bool = Field(strict=True)
    terms_url: InstrumentURL | None
    terms_sha256: Sha256 | None
    reviewed_at: Timestamp | None
    review_expires_at: Timestamp | None
    data_policy: Literal["no_transfer", "public_only", "local_only"]
    quota_scope: Actor
    quota_limit: QuotaLimit
    quota_window_start: Timestamp
    quota_window_end: Timestamp

    @model_validator(mode="after")
    def valid_intervals(self) -> Self:
        if self.quota_window_start >= self.quota_window_end:
            raise ValueError("Quota interval must be non-empty")
        if (
            self.reviewed_at is not None
            and self.review_expires_at is not None
            and self.reviewed_at >= self.review_expires_at
        ):
            raise ValueError("Review interval must be non-empty")
        return self


class ProviderPolicy(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    policy: Literal["free-only-v1"]
    providers: Annotated[tuple[ProviderGrant, ...], Field(max_length=32)]

    @model_validator(mode="after")
    def unique_providers(self) -> Self:
        if len({item.provider_id for item in self.providers}) != len(self.providers):
            raise ValueError("Provider IDs must be unique")
        return self
