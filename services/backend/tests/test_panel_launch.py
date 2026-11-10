"""Panel launches use synthetic SEC payloads in isolated PostgreSQL, never network."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from test_runs import database as database
from test_sec_fundamentals import CIK
from test_sec_fundamentals_v2 import expanded
from test_sec_import import SyntheticTransport, configured_policy

from alphasense import panel_launch, sec_import
from alphasense.api import app
from alphasense.db import ReportStore, get_store
from alphasense.db_schema import research_runs
from alphasense.provider_policy import ProviderDenied
from alphasense.sec_fundamentals import SecInputError
from alphasense.sec_transport import SecTransportError

HEADERS = {"Origin": "http://127.0.0.1", "X-AlphaSense-Panel": "1"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Forged origins are rejected before opening storage.
    app.dependency_overrides[get_store] = lambda: object()
    try:
        with TestClient(app, base_url="http://127.0.0.1") as connection:
            yield connection
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://attacker.invalid", "X-AlphaSense-Panel": "1"},
        {"Origin": "http://127.0.0.1"},
        {**HEADERS, "Sec-Fetch-Site": "cross-site"},
        {**HEADERS, "Host": "attacker.invalid"},
    ],
)
def test_panel_launch_rejects_untrusted_origin(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/v1/panel/analyses", json={"symbol": "AAPL", "run_id": str(uuid4())}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PANEL_ORIGIN_REQUIRED"


@pytest.mark.postgres
def test_panel_launch_catalog_is_explicit_and_rejects_unknown(
    prepared: tuple[TestClient, SyntheticTransport],
) -> None:
    client, _ = prepared
    assert set(panel_launch.CATALOG) == {"AAPL", "GOOGL"}  # synthetic fixture catalog
    response = client.post(
        "/v1/panel/analyses",
        json={"symbol": "UNKNOWN", "run_id": str(uuid4())},
        headers=HEADERS,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SYMBOL_UNSUPPORTED"
    assert "UNKNOWN" not in response.text


@pytest.fixture
def prepared(
    database: Engine, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> tuple[TestClient, SyntheticTransport]:
    values = expanded()
    values["submissions"]["tickers"] = ["AAPL", "GOOGL"]
    values["submissions"]["exchanges"] = ["Nasdaq", "Nasdaq"]
    transport = SyntheticTransport(values)
    monkeypatch.setattr(panel_launch, "CATALOG", {"AAPL": CIK, "GOOGL": CIK})
    monkeypatch.setattr(panel_launch, "SecTransport", lambda _agent: transport)
    policy = configured_policy()
    monkeypatch.setattr(panel_launch, "load_policy", lambda: policy)
    monkeypatch.setattr(sec_import.time, "sleep", lambda _seconds: None)
    app.dependency_overrides[get_store] = lambda: ReportStore(database)
    return client, transport


@pytest.mark.postgres
def test_launch_imports_executes_and_retry_returns_exact_revision(
    database: Engine,
    prepared: tuple[TestClient, SyntheticTransport],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, transport = prepared
    body = {"symbol": " aapl ", "run_id": str(uuid4())}
    response = client.post("/v1/panel/analyses", json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed" and result["revision"] == 1
    assert result["report_id"] and result["instrument_id"]
    assert len(transport.calls) == 8

    def unavailable_transport(_agent: str) -> None:
        raise SecTransportError("SEC_USER_AGENT_INVALID")

    monkeypatch.delenv("ALPHASENSE_SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(panel_launch, "SecTransport", unavailable_transport)
    again = client.post("/v1/panel/analyses", json=body, headers=HEADERS)
    assert again.status_code == 200 and again.json() == result
    assert client.get("/v1/panel/analyses/" + body["run_id"]).json() == result
    assert len(transport.calls) == 8
    conflict = client.post("/v1/panel/analyses", json={**body, "symbol": "GOOGL"}, headers=HEADERS)
    assert conflict.status_code == 409 and len(transport.calls) == 8
    # A new analysis uses the trusted cache but produces its own immutable run.
    fresh = client.post(
        "/v1/panel/analyses", json={**body, "run_id": str(uuid4())}, headers=HEADERS
    )
    assert fresh.status_code == 200 and fresh.json()["status"] == "completed"
    assert fresh.json()["run_id"] != result["run_id"]
    assert len(transport.calls) == 8
    with database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(research_runs)) == 2


@pytest.mark.postgres
def test_duplicate_inflight_request_is_denied_before_import(
    database: Engine, prepared: tuple[TestClient, SyntheticTransport]
) -> None:
    client, transport = prepared
    run_id = str(uuid4())
    with database.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "panel-analysis-launch-v1"},
        )
        response = client.post(
            "/v1/panel/analyses", json={"symbol": "AAPL", "run_id": run_id}, headers=HEADERS
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ANALYSIS_BUSY"
    assert not transport.calls


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ProviderDenied("secret-value"), 403, "SOURCE_POLICY_DENIED"),
        (SecTransportError("secret-value"), 502, "SEC_UNAVAILABLE"),
        (SecInputError("secret-value"), 422, "SEC_INPUT_UNSUPPORTED"),
    ],
)
def test_import_failures_are_redacted_and_retry_uses_same_run_id(
    prepared: tuple[TestClient, SyntheticTransport],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status: int,
    code: str,
) -> None:
    client, transport = prepared
    original = panel_launch.load_policy

    def fail() -> None:
        raise failure

    monkeypatch.setattr(panel_launch, "load_policy", fail)
    body = {"symbol": "AAPL", "run_id": str(uuid4())}
    response = client.post("/v1/panel/analyses", json=body, headers=HEADERS)
    assert response.status_code == status and response.json()["detail"]["code"] == code
    assert "secret-value" not in response.text and not transport.calls
    assert client.get("/v1/panel/analyses/" + body["run_id"]).status_code == 404
    monkeypatch.setattr(panel_launch, "load_policy", original)
    retried = client.post("/v1/panel/analyses", json=body, headers=HEADERS)
    assert retried.status_code == 200 and retried.json()["status"] == "completed", (
        retried.text,
        client.get("/v1/runs/" + body["run_id"]).text,
    )


@pytest.mark.postgres
def test_alphabet_explicit_tag_and_replay_preserve_frozen_selection(
    prepared: tuple[TestClient, SyntheticTransport], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, transport = prepared
    # Simulate a pre-mapping Alphabet run using the prior explicit tag.
    monkeypatch.setitem(
        panel_launch.REVENUE_CONCEPTS,
        "GOOGL",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    old = {"symbol": "GOOGL", "run_id": str(uuid4())}
    response = client.post("/v1/panel/analyses", json=old, headers=HEADERS)
    assert response.status_code == 200, response.text
    previous = response.json()
    assert (
        transport.calls[1].revenue_concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    monkeypatch.setitem(panel_launch.REVENUE_CONCEPTS, "GOOGL", "Revenues")
    replay = client.post("/v1/panel/analyses", json=old, headers=HEADERS)
    assert replay.status_code == 200 and replay.json() == previous
    assert len(transport.calls) == 8
    transport.values["revenue"]["tag"] = "Revenues"
    new = client.post("/v1/panel/analyses", json={**old, "run_id": str(uuid4())}, headers=HEADERS)
    assert new.status_code == 200 and new.json()["status"] == "completed", new.text
    assert new.json()["report_id"] != previous["report_id"]
    # Submissions and net income reused; exactly the newly configured tag fetched.
    assert len(transport.calls) == 9
    assert transport.calls[-1].resource == "revenue"
    assert transport.calls[-1].revenue_concept == "Revenues"
    assert client.get("/v1/panel/analyses/" + old["run_id"]).json() == previous


@pytest.mark.postgres
def test_dynamic_listing_uses_catalog_identity_and_submissions_verification(
    prepared: tuple[TestClient, SyntheticTransport], monkeypatch: pytest.MonkeyPatch
) -> None:
    from alphasense.sec_catalog import CatalogEntry

    client, transport = prepared
    transport.values["submissions"]["tickers"].append("MSFT")
    transport.values["submissions"]["exchanges"].append("Nasdaq")
    monkeypatch.setattr(
        panel_launch,
        "resolve_symbol",
        lambda symbol: CatalogEntry(
            symbol=symbol, cik=CIK, exchange_mic="XNAS", display_name="Synthetic Microsoft"
        ),
    )
    response = client.post(
        "/v1/panel/analyses", json={"symbol": "MSFT", "run_id": str(uuid4())}, headers=HEADERS
    )
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    assert all(call.cik == CIK for call in transport.calls)
    previous = response.json()

    def missing_catalog(_symbol: str) -> CatalogEntry:
        raise AssertionError("Replay must not consult current catalog")

    monkeypatch.setattr(panel_launch, "resolve_symbol", missing_catalog)
    replay = client.post(
        "/v1/panel/analyses", json={"symbol": "MSFT", "run_id": previous["run_id"]}, headers=HEADERS
    )
    assert replay.status_code == 200 and replay.json() == previous
    assert len(transport.calls) == 8
