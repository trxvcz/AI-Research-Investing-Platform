"""Read-only ratio endpoint composes the existing archive/history admission boundary."""

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test_financial_ratios import ratio_history

import alphasense.financial_ratios_api as module
from alphasense.financial_history_api import financial_history
from alphasense.financial_ratios import FinancialRatiosInvalid


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(module.router)
    history = ratio_history()
    app.dependency_overrides[financial_history] = lambda: history
    with TestClient(app) as current:
        yield current, app, history


def path(history):
    return f"/v1/panel/reports/{history.report_id}/{history.revision}/financial-ratios"


def test_read_only_exact_identity_no_store_mutation(client):
    current, _, history = client
    response = current.get(path(history))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["report_checksum"] == history.report_checksum
    assert response.json()["history"] == history.model_dump(mode="json")
    assert len(response.json()["ratios"]) == 12
    assert current.post(path(history), json={}).status_code == 405


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (404, "REPORT_NOT_FOUND"),
        (503, "HISTORY_ARCHIVE_UNAVAILABLE"),
        (422, "HISTORY_UNSUPPORTED"),
    ],
)
def test_inherits_history_refusals(client, status, code):
    current, app, history = client

    def denied():
        raise HTTPException(status, detail={"code": code})

    app.dependency_overrides[financial_history] = denied
    response = current.get(path(history))
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_value_range_refusal_suppresses_diagnostics(client, monkeypatch):
    current, _, history = client

    def denied(_history):
        raise FinancialRatiosInvalid("RATIOS_VALUE_OUT_OF_RANGE")

    monkeypatch.setattr(module, "build_financial_ratios", denied)
    response = current.get(path(history))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "RATIOS_VALUE_OUT_OF_RANGE"
    assert "Traceback" not in response.text


def test_original_history_dependency_retains_path_validation():
    app = FastAPI()
    app.include_router(module.router)
    # Invalid paths fail validation before any archive access. Supply the store
    # dependencies to avoid the real configured database during this unit test.
    from alphasense.db import get_store
    from alphasense.snapshots import get_snapshot_store

    app.dependency_overrides[get_store] = object
    app.dependency_overrides[get_snapshot_store] = object
    with TestClient(app) as current:
        assert current.get(f"/v1/panel/reports/{uuid4()}/0/financial-ratios").status_code == 422
        assert current.get("/v1/panel/reports/not-uuid/1/financial-ratios").status_code == 422
