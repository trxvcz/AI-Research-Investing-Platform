"""Admit immutable expanded SEC runs and five fixed additional concept receipts."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0008_sec_fundamentals_v2"
down_revision = "0007_sec_receipts"
branch_labels = None
depends_on = None

EXTRAS = {
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "debt_current": "LongTermDebtCurrent",
    "debt_noncurrent": "LongTermDebtNoncurrent",
    "operating_cf": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
}
OLD = "resource IN ('submissions','revenue','net_income')"
NEW = (
    "resource IN ('submissions','revenue','net_income','cash','debt_current',"
    "'debt_noncurrent','operating_cf','capex')"
)


def _historical(name: str):
    spec = importlib.util.spec_from_file_location(
        "historical_" + name, Path(__file__).with_name(name + ".py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Historical migration unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt_sql(expanded: bool) -> str:
    sql = _historical("0007_sec_receipts").CHECK_INSERT_SQL.replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )
    if expanded:
        cases = "".join(f" WHEN '{role}' THEN 'sec-edgar-{role}-v2'" for role in EXTRAS)
        sql = sql.replace(
            "WHEN 'net_income' THEN 'sec-edgar-net-income-v1' END",
            "WHEN 'net_income' THEN 'sec-edgar-net-income-v1'" + cases + " END",
        )
        cases = "".join(
            f" WHEN '{role}' THEN NEW.source_url = "
            "'https://data.sec.gov/api/xbrl/companyconcept/CIK' || NEW.cik || "
            f"'/us-gaap/{tag}.json'"
            for role, tag in EXTRAS.items()
        )
        sql = sql.replace(" ELSE false END;", cases + " ELSE false END;")
    return sql


def _guards(expanded: bool):
    for sql in _historical("0006_sec_pipeline")._guards(sec=True):
        yield (
            sql.replace("'sec-fundamentals-v1'", "'sec-fundamentals-v1','sec-fundamentals-v2'")
            if expanded
            else sql
        )


def upgrade() -> None:
    op.drop_constraint("ck_sec_ingestion_resource", "sec_ingestions", type_="check")
    op.create_check_constraint("ck_sec_ingestion_resource", "sec_ingestions", NEW)
    op.execute(_receipt_sql(True))
    for sql in _guards(True):
        op.execute(sql)


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Offline downgrade disabled to protect v2 history")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE research_runs, run_events, worker_jobs, worker_claims, "
            "sec_ingestions IN ACCESS EXCLUSIVE MODE NOWAIT"
        )
    )
    if bind.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM research_runs WHERE "
            "definition->>'pipeline_version'='sec-fundamentals-v2') "
            "OR EXISTS(SELECT 1 FROM sec_ingestions WHERE resource NOT IN "
            "('submissions','revenue','net_income'))"
        )
    ):
        raise RuntimeError("Refusing to remove non-empty SEC v2 history")
    for sql in _guards(False):
        op.execute(sql)
    op.execute(_receipt_sql(False))
    op.drop_constraint("ck_sec_ingestion_resource", "sec_ingestions", type_="check")
    op.create_check_constraint("ck_sec_ingestion_resource", "sec_ingestions", OLD)
