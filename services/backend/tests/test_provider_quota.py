"""Durable free-only quota gates on isolated real PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError
from test_runs import database as database

from alphasense.db import StoreUnavailable
from alphasense.db_schema import MIGRATION_HEAD, provider_quota_windows
from alphasense.provider_contracts import ProviderGrant
from alphasense.provider_quota import QuotaDenied, QuotaStore

ROOT = Path(__file__).resolve().parents[3]


def grant(**changes: Any) -> ProviderGrant:
    now = datetime.now(UTC)
    payload: dict[str, Any] = dict(
        provider_id="synthetic-quota-test",
        enabled=True,
        capability="data",
        execution="remote",
        billing="free_no_billing",
        max_charge_usd=0,
        paid_fallback=False,
        hard_cap_verified=True,
        quality_pass=True,
        terms_url="https://example.invalid/fixture",
        terms_sha256="1" * 64,
        reviewed_at=now - timedelta(days=1),
        review_expires_at=now + timedelta(days=1),
        data_policy="public_only",
        quota_scope="synthetic-quota-" + uuid4().hex,
        quota_limit=1,
        quota_window_start=now - timedelta(minutes=1),
        quota_window_end=now + timedelta(hours=1),
    )
    payload.update(changes)
    return ProviderGrant.model_validate(payload)


def test_non_postgresql_quota_store_is_not_a_fallback() -> None:
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(StoreUnavailable):
            QuotaStore(engine)
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_two_processes_compete_for_last_slot_with_one_winner(database: Engine) -> None:
    identity = grant()
    barrier = Barrier(2)

    def attempt(_index: int) -> str | int:
        barrier.wait(timeout=5)
        try:
            return QuotaStore(database).reserve(identity)
        except QuotaDenied as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, range(2)))
    assert results.count(0) == 1 and results.count("QUOTA_EXHAUSTED") == 1
    with database.connect() as connection:
        assert connection.execute(select(provider_quota_windows.c.used)).scalar_one() == 1


@pytest.mark.postgres
def test_quota_survives_new_engine_and_failed_external_operation(database: Engine) -> None:
    identity = grant()
    assert QuotaStore(database).reserve(identity) == 0
    # A failed adapter is outside the committed reservation: it must not refund capacity.
    with pytest.raises(RuntimeError):
        raise RuntimeError("Synthetic adapter failure")
    with database.connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    replacement = create_engine(
        database.url,
        hide_parameters=True,
        connect_args={"options": f"-c search_path={schema}"},
    )
    try:
        with pytest.raises(QuotaDenied, match="^QUOTA_EXHAUSTED$"):
            QuotaStore(replacement).reserve(identity)
    finally:
        replacement.dispose()


@pytest.mark.postgres
def test_same_account_scope_is_shared_between_provider_ids(database: Engine) -> None:
    identity = grant()
    QuotaStore(database).reserve(identity)
    same_scope = ProviderGrant.model_validate(
        {
            **identity.model_dump(),
            "provider_id": "second-synthetic-adapter",
        }
    )
    with pytest.raises(QuotaDenied, match="^QUOTA_EXHAUSTED$"):
        QuotaStore(database).reserve(same_scope)


@pytest.mark.postgres
@pytest.mark.parametrize("change", ["limit", "end", "overlap"])
def test_config_changes_cannot_reset_a_spent_window(database: Engine, change: str) -> None:
    identity = grant()
    QuotaStore(database).reserve(identity)
    payload = identity.model_dump()
    if change == "limit":
        payload["quota_limit"] = 2
    elif change == "end":
        payload["quota_window_end"] += timedelta(seconds=1)
    else:
        payload["quota_window_start"] -= timedelta(seconds=1)
    with pytest.raises(QuotaDenied, match="^QUOTA_CONFLICT$"):
        QuotaStore(database).reserve(ProviderGrant.model_validate(payload))
    with database.connect() as connection:
        assert connection.execute(select(provider_quota_windows.c.used)).scalar_one() == 1


@pytest.mark.postgres
@pytest.mark.parametrize("window", ["expired", "future", "zero"])
def test_inactive_or_zero_allowance_denies_without_reserving(database: Engine, window: str) -> None:
    now = datetime.now(UTC)
    changes: dict[str, Any] = {}
    if window == "expired":
        changes.update(
            quota_window_start=now - timedelta(hours=2), quota_window_end=now - timedelta(hours=1)
        )
    elif window == "future":
        changes.update(
            quota_window_start=now + timedelta(hours=1), quota_window_end=now + timedelta(hours=2)
        )
    else:
        changes.update(quota_limit=0)
    expected = "QUOTA_EXHAUSTED" if window == "zero" else "QUOTA_WINDOW"
    with pytest.raises(QuotaDenied, match=f"^{expected}$"):
        QuotaStore(database).reserve(grant(**changes))
    with database.connect() as connection:
        assert connection.execute(select(provider_quota_windows)).all() == []


@pytest.mark.postgres
def test_adjacent_windows_are_allowed_but_overlap_is_not(database: Engine) -> None:
    identity = grant()
    QuotaStore(database).reserve(identity)
    with database.begin() as connection:
        connection.execute(
            provider_quota_windows.insert().values(
                quota_scope=identity.quota_scope,
                window_start=identity.quota_window_end,
                window_end=identity.quota_window_end + timedelta(hours=1),
                quota_limit=2,
                used=0,
            )
        )
    with pytest.raises(DBAPIError), database.begin() as connection:
        connection.execute(
            provider_quota_windows.insert().values(
                quota_scope=identity.quota_scope,
                window_start=identity.quota_window_start + timedelta(seconds=1),
                window_end=identity.quota_window_end,
                quota_limit=2,
                used=0,
            )
        )


@pytest.mark.postgres
@pytest.mark.parametrize("operation", ["refund", "increase", "definition", "delete", "truncate"])
def test_direct_sql_cannot_refund_reset_or_remove_history(database: Engine, operation: str) -> None:
    identity = grant(quota_limit=3)
    QuotaStore(database).reserve(identity)
    with pytest.raises(DBAPIError), database.begin() as connection:
        if operation == "delete":
            connection.execute(provider_quota_windows.delete())
        elif operation == "truncate":
            connection.execute(text("TRUNCATE provider_quota_windows"))
        else:
            values = {"used": 0 if operation == "refund" else 3}
            if operation == "definition":
                values = {"used": 2, "quota_limit": 4}
            connection.execute(provider_quota_windows.update().values(**values))


@pytest.mark.postgres
def test_empty_migration_roundtrip_and_nonempty_downgrade_refusal(database: Engine) -> None:
    with database.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0004_worker")
        command.upgrade(config, "head")
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            MIGRATION_HEAD
        )
    QuotaStore(database).reserve(grant())
    with pytest.raises(RuntimeError, match="non-empty provider quota history"):
        with database.begin() as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0004_worker")
    with database.connect() as connection:
        assert connection.execute(select(provider_quota_windows.c.used)).scalar_one() == 1


@pytest.mark.postgres
def test_unavailable_schema_raises_sanitized_storage_error(database: Engine) -> None:
    with database.begin() as connection:
        connection.execute(text("ALTER TABLE provider_quota_windows RENAME TO missing_quota"))
    try:
        with pytest.raises(StoreUnavailable, match="^Provider quota storage unavailable$"):
            QuotaStore(database).reserve(grant())
    finally:
        with database.begin() as connection:
            connection.execute(text("ALTER TABLE missing_quota RENAME TO provider_quota_windows"))


@pytest.mark.postgres
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_old_snapshot_isolation_is_denied_before_any_reservation(
    database: Engine, isolation: str
) -> None:
    with database.connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    isolated = create_engine(
        database.url,
        hide_parameters=True,
        isolation_level=isolation,
        connect_args={"options": f"-c search_path={schema}"},
    )
    try:
        with pytest.raises(QuotaDenied, match="^QUOTA_ISOLATION$"):
            QuotaStore(isolated).reserve(grant())
        with database.connect() as connection:
            assert connection.execute(select(provider_quota_windows)).all() == []
    finally:
        isolated.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_direct_insert_cannot_use_old_snapshot_to_bypass_overlap_guard(
    database: Engine, isolation: str
) -> None:
    identity = grant()
    with database.connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    isolated = create_engine(
        database.url,
        hide_parameters=True,
        isolation_level=isolation,
        connect_args={"options": f"-c search_path={schema}"},
    )
    try:
        with pytest.raises(DBAPIError), isolated.begin() as connection:
            connection.execute(
                provider_quota_windows.insert().values(
                    quota_scope=identity.quota_scope,
                    window_start=identity.quota_window_start,
                    window_end=identity.quota_window_end,
                    quota_limit=1,
                    used=0,
                )
            )
        with database.connect() as connection:
            assert connection.execute(select(provider_quota_windows)).all() == []
    finally:
        isolated.dispose()
