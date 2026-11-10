"""Consume durable quota before a provider call; failures never refund attempts."""

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import StoreUnavailable
from alphasense.db_schema import provider_quota_windows
from alphasense.provider_contracts import ProviderGrant


class QuotaDenied(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class QuotaStore:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise StoreUnavailable("PostgreSQL required")
        self.engine = engine

    def reserve(self, grant: ProviderGrant) -> int:
        checked = ProviderGrant.model_validate(grant.model_dump(mode="python"))
        try:
            with self.engine.begin() as connection:
                isolation = connection.execute(
                    text("SELECT current_setting('transaction_isolation')")
                ).scalar_one()
                if isolation != "read committed":
                    raise QuotaDenied("QUOTA_ISOLATION")
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": checked.quota_scope},
                )
                now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                if not checked.quota_window_start <= now < checked.quota_window_end:
                    raise QuotaDenied("QUOTA_WINDOW")
                if checked.quota_limit == 0:
                    raise QuotaDenied("QUOTA_EXHAUSTED")
                rows = (
                    connection.execute(
                        select(provider_quota_windows)
                        .where(
                            provider_quota_windows.c.quota_scope == checked.quota_scope,
                            provider_quota_windows.c.window_start < checked.quota_window_end,
                            provider_quota_windows.c.window_end > checked.quota_window_start,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .all()
                )
                if rows:
                    row = rows[0]
                    if len(rows) != 1 or (
                        row["window_start"],
                        row["window_end"],
                        row["quota_limit"],
                    ) != (
                        checked.quota_window_start,
                        checked.quota_window_end,
                        checked.quota_limit,
                    ):
                        raise QuotaDenied("QUOTA_CONFLICT")
                    if row["used"] >= row["quota_limit"]:
                        raise QuotaDenied("QUOTA_EXHAUSTED")
                    used = int(row["used"])
                else:
                    connection.execute(
                        provider_quota_windows.insert().values(
                            quota_scope=checked.quota_scope,
                            window_start=checked.quota_window_start,
                            window_end=checked.quota_window_end,
                            quota_limit=checked.quota_limit,
                            used=0,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    used = 0
                connection.execute(
                    provider_quota_windows.update()
                    .where(
                        provider_quota_windows.c.quota_scope == checked.quota_scope,
                        provider_quota_windows.c.window_start == checked.quota_window_start,
                    )
                    .values(
                        used=used + 1,
                        updated_at=connection.execute(
                            text("SELECT clock_timestamp()")
                        ).scalar_one(),
                    )
                )
                after = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                if not checked.quota_window_start <= after < checked.quota_window_end:
                    raise QuotaDenied("QUOTA_WINDOW")
                return checked.quota_limit - used - 1
        except SQLAlchemyError:
            raise StoreUnavailable("Provider quota storage unavailable") from None
