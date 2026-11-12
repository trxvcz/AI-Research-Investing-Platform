"""Independent free-only admission tests; callbacks are synthetic spies, never network I/O."""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

import pytest
from pydantic import ValidationError

from alphasense.db import StoreUnavailable
from alphasense.provider_contracts import ProviderGrant, ProviderPolicy
from alphasense.provider_policy import FreeOnlyGateway, ProviderDenied, load_policy
from alphasense.provider_quota import QuotaDenied

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def test_already_underflowed_binary_float_cannot_be_used_as_zero_charge_evidence() -> None:
    # The server loader preserves raw JSON using Decimal. Direct internal callers must
    # also avoid treating an already rounded Python float as proof of no charge.
    for amount in (0.0, 1e-400, -0.0):
        with pytest.raises(ValidationError):
            grant(max_charge_usd=amount)


def grant(**changes: Any) -> ProviderGrant:
    values = {
        "provider_id": "synthetic-free",
        "enabled": True,
        "capability": "data",
        "execution": "remote",
        "billing": "free_no_billing",
        "max_charge_usd": 0,
        "paid_fallback": False,
        "hard_cap_verified": True,
        "quality_pass": True,
        "terms_url": "https://example.invalid/synthetic-terms",
        "terms_sha256": hashlib.sha256(b"synthetic terms, not a verified provider").hexdigest(),
        "reviewed_at": NOW - timedelta(days=1),
        "review_expires_at": NOW + timedelta(days=1),
        "data_policy": "public_only",
        "quota_scope": "synthetic-account",
        "quota_limit": 10,
        "quota_window_start": NOW - timedelta(hours=1),
        "quota_window_end": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return ProviderGrant.model_validate(values)


def policy(*grants: ProviderGrant) -> ProviderPolicy:
    return ProviderPolicy(schema_version="1.0", policy="free-only-v1", providers=grants)


class QuotaSpy:
    """Test backend only; durable reservation behavior has separate real PostgreSQL tests."""

    def __init__(self, remaining: int = 10, error: Exception | None = None) -> None:
        self.remaining = remaining
        self.error = error
        self.calls = 0
        self.lock = Lock()

    def reserve(self, _grant: ProviderGrant) -> int:
        with self.lock:
            self.calls += 1
            if self.error is not None:
                raise self.error
            if self.remaining <= 0:
                raise QuotaDenied("QUOTA_EXHAUSTED")
            self.remaining -= 1
            return self.remaining


def gateway(
    admitted: ProviderGrant | None = None,
    quota: QuotaSpy | None = None,
    adapters: dict[str, Any] | None = None,
    clock: Any = None,
) -> tuple[FreeOnlyGateway, QuotaSpy, list[object]]:
    calls: list[object] = []

    def invoke(payload: object) -> object:
        calls.append(payload)
        return {"synthetic": True}

    backend = quota or QuotaSpy()
    instance = FreeOnlyGateway(
        policy(admitted or grant()),
        adapters if adapters is not None else {"synthetic-free": invoke},
        backend,
        clock=clock or (lambda: NOW),
    )
    return instance, backend, calls


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"quality_pass": False},
        {"billing": "paid", "max_charge_usd": 0},
        {"billing": "unknown", "max_charge_usd": 0},
        {"max_charge_usd": None},
        {"max_charge_usd": 0.000001},
        {"max_charge_usd": 1000000},
        {"paid_fallback": True},
        {"billing": "free_tier", "hard_cap_verified": False},
        {"terms_url": None},
        {"terms_url": "http://example.invalid/synthetic-terms"},
        {"terms_url": "https://name:private@example.invalid/synthetic-terms"},
        {"terms_url": "https://example.invalid/synthetic-terms#unreviewed"},
        {"terms_sha256": None},
        {"reviewed_at": None},
        {"review_expires_at": None},
        {"reviewed_at": NOW + timedelta(seconds=1)},
        {"review_expires_at": NOW},
        {"review_expires_at": NOW - timedelta(seconds=1)},
        {"quota_limit": 0},
        {"quota_window_start": NOW + timedelta(seconds=1)},
        {"quota_window_end": NOW},
        {"data_policy": "no_transfer"},
        {"data_policy": "local_only", "execution": "remote"},
    ],
)
def test_ineligible_provider_is_denied_before_quota_or_callback(changes: dict[str, Any]) -> None:
    instance, quota, calls = gateway(grant(**changes))
    with pytest.raises(ProviderDenied):
        instance.invoke("synthetic-free", {"synthetic": True}, classification="public")
    assert calls == [] and quota.calls == 0


@pytest.mark.parametrize("billing", ["free_no_billing", "free_tier"])
def test_explicit_verified_free_provider_reserves_before_call(billing: str) -> None:
    quota = QuotaSpy()
    order: list[str] = []

    def adapter(payload: object) -> object:
        assert quota.calls == 1 and quota.remaining == 9
        order.append("adapter")
        return payload

    instance, backend, _calls = gateway(grant(billing=billing), quota, {"synthetic-free": adapter})
    payload = {"synthetic": True, "value": 0}
    assert instance.invoke("synthetic-free", payload, classification="public") == payload
    assert order == ["adapter"] and backend.calls == 1


@pytest.mark.parametrize("provider", ["unknown", "paid-fallback", "synthetic-free"])
def test_unregistered_adapter_is_never_called(provider: str) -> None:
    instance, quota, calls = gateway(adapters={})
    with pytest.raises(ProviderDenied):
        instance.invoke(provider, "synthetic", classification="public")
    assert quota.calls == 0 and calls == []


@pytest.mark.parametrize(
    ("execution", "data_policy", "classification", "allowed"),
    [
        ("remote", "public_only", "public", True),
        ("remote", "public_only", "private", False),
        ("remote", "public_only", "secret", False),
        ("local", "public_only", "private", False),
        ("local", "local_only", "private", True),
        ("local", "local_only", "public", True),
        ("local", "local_only", "secret", False),
        ("local", "no_transfer", "public", False),
    ],
)
def test_data_policy_controls_transfer(
    execution: str,
    data_policy: str,
    classification: Any,
    allowed: bool,
) -> None:
    instance, quota, calls = gateway(grant(execution=execution, data_policy=data_policy))
    if allowed:
        assert instance.invoke("synthetic-free", "synthetic", classification=classification)
        assert calls == ["synthetic"] and quota.calls == 1
    else:
        with pytest.raises(ProviderDenied):
            instance.invoke("synthetic-free", "PRIVATE-PAYLOAD", classification=classification)
        assert calls == [] and quota.calls == 0


def test_exhaustion_stops_instead_of_switching_to_paid_fallback() -> None:
    paid_calls: list[object] = []
    quota = QuotaSpy(remaining=0)
    instance, _backend, calls = gateway(
        quota=quota,
        adapters={"synthetic-free": calls_not_expected, "paid-fallback": paid_calls.append},
    )
    with pytest.raises(ProviderDenied) as denied:
        instance.invoke("synthetic-free", "synthetic", classification="public")
    assert denied.value.code == "QUOTA_EXHAUSTED"
    assert calls == [] and paid_calls == [] and quota.calls == 1


def calls_not_expected(_payload: object) -> object:
    raise AssertionError("An ineligible provider callback was invoked")


def test_failed_adapter_is_not_retried_and_attempt_is_consumed() -> None:
    attempts: list[object] = []
    fallback: list[object] = []

    def broken(payload: object) -> object:
        attempts.append(payload)
        raise RuntimeError("PRIVATE-PAYLOAD and credential=value")

    instance, quota, _calls = gateway(
        adapters={"synthetic-free": broken, "paid-fallback": fallback.append}
    )
    with pytest.raises(ProviderDenied) as denied:
        instance.invoke("synthetic-free", "PRIVATE-PAYLOAD", classification="public")
    assert denied.value.code == "PROVIDER_FAILED"
    assert str(denied.value) == "PROVIDER_FAILED"
    assert "PRIVATE" not in repr(denied.value) and "credential" not in repr(denied.value)
    assert denied.value.__cause__ is None
    assert attempts == ["PRIVATE-PAYLOAD"] and fallback == []
    assert quota.calls == 1 and quota.remaining == 9


def test_quota_storage_failure_prevents_any_adapter_call() -> None:
    instance, quota, calls = gateway(quota=QuotaSpy(error=StoreUnavailable("Storage unavailable")))
    with pytest.raises(StoreUnavailable):
        instance.invoke("synthetic-free", "synthetic", classification="public")
    assert calls == [] and quota.calls == 1


def test_concurrent_attempts_cannot_pass_single_available_reservation() -> None:
    instance, quota, calls = gateway(quota=QuotaSpy(remaining=1))

    def attempt(index: int) -> bool:
        try:
            instance.invoke("synthetic-free", {"index": index}, classification="public")
            return True
        except ProviderDenied:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(20)))
    assert sum(results) == 1 and len(calls) == 1 and quota.remaining == 0


def test_expired_review_is_checked_again_at_each_invocation() -> None:
    clock = [NOW]
    instance, quota, calls = gateway(clock=lambda: clock[0])
    instance.invoke("synthetic-free", "first", classification="public")
    clock[0] = NOW + timedelta(days=1)
    with pytest.raises(ProviderDenied):
        instance.invoke("synthetic-free", "second", classification="public")
    assert calls == ["first"] and quota.calls == 1


def test_server_policy_does_not_admit_unknown_external_providers() -> None:
    path = Path(__file__).resolve().parents[3] / "config" / "provider-policy.json"
    configured = ProviderPolicy.model_validate_json(path.read_text("utf-8"))
    assert configured.policy == "free-only-v1"
    quota = QuotaSpy()
    instance = FreeOnlyGateway(configured, {}, quota, clock=lambda: NOW)
    with pytest.raises(ProviderDenied):
        instance.invoke("unapproved-test-provider", "synthetic", classification="public")
    assert quota.calls == 0


def test_policy_and_grants_are_frozen_and_unknown_fields_rejected() -> None:
    admitted = grant()
    configured = policy(admitted)
    with pytest.raises(ValidationError):
        admitted.paid_fallback = True
    with pytest.raises(ValidationError):
        configured.providers = ()
    payload = json.loads(configured.model_dump_json())
    payload["providers"][0]["budget_override"] = 1000000
    with pytest.raises(ValidationError):
        ProviderPolicy.model_validate(payload)


def test_constructed_or_copied_invalid_policy_cannot_bypass_admission() -> None:
    forged = grant().model_copy(update={"max_charge_usd": Decimal("NaN")})
    configured = policy(grant()).model_copy(update={"providers": (forged,)})
    quota = QuotaSpy()
    with pytest.raises((ProviderDenied, ValidationError, ValueError)):
        instance = FreeOnlyGateway(configured, {"synthetic-free": calls_not_expected}, quota)
        instance.invoke("synthetic-free", "synthetic", classification="public")
    assert quota.calls == 0


@pytest.mark.parametrize("now", [NOW.replace(tzinfo=None), "2026-11-02", None])
def test_invalid_server_clock_cannot_admit_call(now: Any) -> None:
    instance, quota, calls = gateway(clock=lambda: now)
    with pytest.raises(ProviderDenied) as denied:
        instance.invoke("synthetic-free", "synthetic", classification="public")
    assert denied.value.code == "POLICY_CLOCK_INVALID"
    assert calls == [] and quota.calls == 0


def test_waiting_for_quota_cannot_send_payload_after_review_expiry() -> None:
    clock = [NOW]

    class WaitingQuota(QuotaSpy):
        def reserve(self, admitted: ProviderGrant) -> int:
            remaining = super().reserve(admitted)
            clock[0] = NOW + timedelta(days=1)
            return remaining

    instance, quota, calls = gateway(quota=WaitingQuota(), clock=lambda: clock[0])
    with pytest.raises(ProviderDenied):
        instance.invoke("synthetic-free", "PRIVATE-PAYLOAD", classification="public")
    assert calls == [] and quota.calls == 1 and quota.remaining == 9


@pytest.mark.parametrize("classification", ["PUBLIC", "unknown", None, True])
def test_invalid_classification_is_denied_before_transfer(classification: Any) -> None:
    instance, quota, calls = gateway()
    with pytest.raises(ProviderDenied):
        instance.invoke("synthetic-free", "PRIVATE-PAYLOAD", classification=classification)
    assert calls == [] and quota.calls == 0


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"1.0","policy":"free-only-v1","providers":[],"providers":[]}',
        b'{"schema_version":"1.0","policy":"free-only-v1","providers":[],"value":NaN}',
        b'{"schema_version":"1.0","policy":"free-only-v1","providers":[],"value":Infinity}',
        b"\xff\xfe\x00",
        b" " * 65537,
    ],
)
def test_malformed_server_configuration_is_sanitized(tmp_path: Path, raw: bytes) -> None:
    config = tmp_path / "policy.json"
    config.write_bytes(raw)
    with pytest.raises(ProviderDenied) as denied:
        load_policy(config)
    assert denied.value.code == "POLICY_INVALID"
    assert str(config) not in repr(denied.value)


def write_raw_charge_policy(tmp_path: Path, charge_token: str) -> Path:
    serialized = policy(grant()).model_dump_json()
    serialized, substitutions = re.subn(
        r'("max_charge_usd"\s*:\s*)[^,}]+',
        lambda match: match.group(1) + charge_token,
        serialized,
    )
    assert substitutions == 1
    destination = tmp_path / "exact-charge-policy.json"
    destination.write_text(serialized, encoding="utf-8")
    return destination


@pytest.mark.parametrize("token", ["1e-400", "5e-324", '"1e-400"', '"0.00000000000000000001"'])
def test_positive_charge_cannot_underflow_into_a_free_call(tmp_path: Path, token: str) -> None:
    configured = load_policy(write_raw_charge_policy(tmp_path, token))
    exact_amount = Decimal(token.strip('"'))
    assert exact_amount > 0
    assert configured.providers[0].max_charge_usd == exact_amount
    quota = QuotaSpy()
    instance = FreeOnlyGateway(
        configured, {"synthetic-free": calls_not_expected}, quota, clock=lambda: NOW
    )
    with pytest.raises(ProviderDenied) as denied:
        instance.invoke("synthetic-free", "PRIVATE-PAYLOAD", classification="public")
    assert denied.value.code == "CHARGE_NOT_ALLOWED"
    assert quota.calls == 0


@pytest.mark.parametrize("token", ["0", "0.0", '"0"', "0e-400"])
def test_exact_zero_numeric_or_decimal_string_still_allows_verified_free_call(
    tmp_path: Path,
    token: str,
) -> None:
    configured = load_policy(write_raw_charge_policy(tmp_path, token))
    quota = QuotaSpy()
    calls: list[object] = []
    instance = FreeOnlyGateway(
        configured, {"synthetic-free": calls.append}, quota, clock=lambda: NOW
    )
    instance.invoke("synthetic-free", {"synthetic": True}, classification="public")
    assert calls == [{"synthetic": True}] and quota.calls == 1


@pytest.mark.parametrize("token", ["-1e-400", "true", "false", "1e999999999999999999999"])
def test_invalid_exact_charge_is_sanitized_before_any_call(tmp_path: Path, token: str) -> None:
    quota = QuotaSpy()
    with pytest.raises(ProviderDenied) as denied:
        configured = load_policy(write_raw_charge_policy(tmp_path, token))
        instance = FreeOnlyGateway(
            configured, {"synthetic-free": calls_not_expected}, quota, clock=lambda: NOW
        )
        instance.invoke("synthetic-free", "PRIVATE-PAYLOAD", classification="public")
    assert denied.value.code == "POLICY_INVALID"
    assert "PRIVATE" not in repr(denied.value) and quota.calls == 0


def test_constructor_revalidation_preserves_exact_tiny_decimal() -> None:
    admitted = grant(max_charge_usd=Decimal("1e-400"))
    configured = ProviderPolicy.model_validate(policy(admitted).model_dump(mode="python"))
    assert configured.providers[0].max_charge_usd == Decimal("1e-400")
    instance, quota, calls = gateway(configured.providers[0])
    with pytest.raises(ProviderDenied) as denied:
        instance.invoke("synthetic-free", "synthetic", classification="public")
    assert denied.value.code == "CHARGE_NOT_ALLOWED"
    assert quota.calls == 0 and calls == []
