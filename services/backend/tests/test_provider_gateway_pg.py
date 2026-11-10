"""Admission and actual durable reservation together, using synthetic callbacks only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import Engine, select
from test_provider_policy import policy
from test_provider_quota import grant
from test_runs import database as database

from alphasense.db_schema import provider_quota_windows
from alphasense.provider_policy import FreeOnlyGateway, ProviderDenied
from alphasense.provider_quota import QuotaStore

pytestmark = pytest.mark.postgres


def test_failed_callback_consumes_durable_slot_without_fallback(database: Engine) -> None:
    approved = grant()
    attempts: list[object] = []
    paid_attempts: list[object] = []

    def fail(payload: object) -> object:
        attempts.append(payload)
        raise RuntimeError("PRIVATE-CREDENTIAL-AND-DOCUMENT")

    gateway = FreeOnlyGateway(
        policy(approved),
        {approved.provider_id: fail, "paid-provider": paid_attempts.append},
        QuotaStore(database),
    )
    with pytest.raises(ProviderDenied, match="^PROVIDER_FAILED$") as error:
        gateway.invoke(approved.provider_id, {"synthetic": True}, classification="public")
    assert "PRIVATE" not in str(error.value)
    replacement = FreeOnlyGateway(
        policy(approved), {approved.provider_id: fail}, QuotaStore(database)
    )
    with pytest.raises(ProviderDenied, match="^QUOTA_EXHAUSTED$"):
        replacement.invoke(approved.provider_id, {"synthetic": True}, classification="public")
    assert len(attempts) == 1 and paid_attempts == []
    with database.connect() as connection:
        assert connection.scalar(select(provider_quota_windows.c.used)) == 1


def test_two_gateway_instances_share_last_slot_before_any_callback(database: Engine) -> None:
    approved = grant()
    calls: list[object] = []
    barrier = Barrier(2)

    def invoke(index: int) -> str:
        gateway = FreeOnlyGateway(
            policy(approved), {approved.provider_id: calls.append}, QuotaStore(database)
        )
        barrier.wait(timeout=5)
        try:
            gateway.invoke(approved.provider_id, index, classification="public")
            return "allowed"
        except ProviderDenied as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, (1, 2)))
    assert sorted(results) == ["QUOTA_EXHAUSTED", "allowed"]
    assert len(calls) == 1


@pytest.mark.parametrize("change", [{"billing": "paid"}, {"max_charge_usd": 0.01}])
def test_paid_call_never_reserves_or_invokes(database: Engine, change: dict[str, object]) -> None:
    approved = grant(**change)
    calls: list[object] = []
    gateway = FreeOnlyGateway(
        policy(approved), {approved.provider_id: calls.append}, QuotaStore(database)
    )
    with pytest.raises(ProviderDenied, match="^CHARGE_NOT_ALLOWED$"):
        gateway.invoke(approved.provider_id, {"synthetic": True}, classification="public")
    assert calls == []
    with database.connect() as connection:
        assert connection.execute(select(provider_quota_windows)).all() == []
