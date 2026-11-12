"""Fail-closed provider admission and invocation. No active network adapters."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from alphasense.provider_contracts import DataClassification, ProviderGrant, ProviderPolicy
from alphasense.run_contracts import Actor

POLICY_PATH = Path(__file__).resolve().parents[4] / "config" / "provider-policy.json"


class ProviderDenied(Exception):
    """A stable reason without provider exception, payload or credentials."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class QuotaBackend(Protocol):
    def reserve(self, grant: ProviderGrant) -> int: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration key")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("Non-finite configuration value")


def load_policy(path: Path = POLICY_PATH) -> ProviderPolicy:
    """Read bounded, trusted server configuration, never client-provided evidence."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("Policy too large")
        return ProviderPolicy.model_validate(
            json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_object,
                parse_constant=_constant,
                parse_float=Decimal,
            )
        )
    except (OSError, ValueError, TypeError, RecursionError, InvalidOperation):
        raise ProviderDenied("POLICY_INVALID") from None


def _admit(grant: ProviderGrant, classification: DataClassification, now: datetime) -> None:
    if not grant.enabled:
        raise ProviderDenied("PROVIDER_DISABLED")
    if grant.billing not in ("free_no_billing", "free_tier") or grant.max_charge_usd != 0:
        raise ProviderDenied("CHARGE_NOT_ALLOWED")
    if grant.paid_fallback:
        raise ProviderDenied("PAID_FALLBACK_NOT_ALLOWED")
    if grant.billing == "free_tier" and not grant.hard_cap_verified:
        raise ProviderDenied("HARD_CAP_UNVERIFIED")
    if not grant.quality_pass:
        raise ProviderDenied("QUALITY_UNVERIFIED")
    terms = grant.terms_url
    if (
        terms is None
        or terms.scheme != "https"
        or terms.username is not None
        or terms.password is not None
        or terms.host is None
        or terms.fragment is not None
        or grant.terms_sha256 is None
        or grant.reviewed_at is None
        or grant.review_expires_at is None
        or not grant.reviewed_at <= now < grant.review_expires_at
    ):
        raise ProviderDenied("TERMS_UNVERIFIED")
    if (
        classification == "secret"
        or grant.data_policy == "no_transfer"
        or (
            classification == "private"
            and not (grant.execution == "local" and grant.data_policy == "local_only")
        )
        or (grant.data_policy == "local_only" and grant.execution != "local")
    ):
        raise ProviderDenied("DATA_POLICY_DENIED")
    if grant.quota_limit == 0:
        raise ProviderDenied("QUOTA_EXHAUSTED")
    if not grant.quota_window_start <= now < grant.quota_window_end:
        raise ProviderDenied("QUOTA_WINDOW")


class FreeOnlyGateway[T]:
    """Trusted adapters only; quota is committed before a single permitted invocation.

    There is deliberately no automatic fallback or refund after uncertain failures.
    Production callers supply QuotaStore, not an in-memory quota substitute.
    """

    def __init__(
        self,
        policy: ProviderPolicy,
        adapters: Mapping[str, Callable[[object], T]],
        quota: QuotaBackend,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        try:
            checked = ProviderPolicy.model_validate(
                policy.model_dump(mode="python", warnings=False)
            )
        except (ValidationError, ValueError, TypeError):
            raise ProviderDenied("POLICY_INVALID") from None
        self._grants = {grant.provider_id: grant for grant in checked.providers}
        self._adapters = MappingProxyType(dict(adapters))
        self._quota = quota
        self._clock = clock

    def invoke(self, provider_id: str, payload: object, *, classification: DataClassification) -> T:
        try:
            provider_id = TypeAdapter(Actor).validate_python(provider_id)
            classification = TypeAdapter(DataClassification).validate_python(classification)
        except ValidationError:
            raise ProviderDenied("REQUEST_INVALID") from None
        grant = self._grants.get(provider_id)
        if grant is None:
            raise ProviderDenied("PROVIDER_NOT_APPROVED")
        adapter = self._adapters.get(provider_id)
        if adapter is None or not callable(adapter):
            raise ProviderDenied("ADAPTER_NOT_REGISTERED")
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ProviderDenied("POLICY_CLOCK_INVALID")
        _admit(grant, classification, now.astimezone(UTC))
        # Import here keeps contracts/configuration independent of DB availability.
        from alphasense.provider_quota import QuotaDenied

        try:
            self._quota.reserve(grant)
        except QuotaDenied as error:
            raise ProviderDenied(error.code) from None
        # A reservation can wait for a DB lock. Recheck review and data-policy deadline
        # before sending any payload; spent quota is intentionally retained on denial.
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ProviderDenied("POLICY_CLOCK_INVALID")
        _admit(grant, classification, now.astimezone(UTC))
        try:
            return adapter(payload)
        except Exception:
            raise ProviderDenied("PROVIDER_FAILED") from None


def configured_gateway[T](adapters: Mapping[str, Callable[[object], T]]) -> FreeOnlyGateway[T]:
    """Construct the server gateway with the deny-by-default file and durable quota."""
    from alphasense.db import get_store
    from alphasense.provider_quota import QuotaStore

    return FreeOnlyGateway(load_policy(), adapters, QuotaStore(get_store().engine))
