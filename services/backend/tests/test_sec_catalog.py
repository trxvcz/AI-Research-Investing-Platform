"""Catalog reads are offline and reject malformed or tampered cache data."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from alphasense import sec_catalog
from alphasense.sec_catalog import (
    CatalogError,
    parse_catalog,
    read_catalog,
    resolve_symbol,
    save_catalog,
)
from alphasense.sec_catalog_transport import CATALOG_URL, MAX_CATALOG_BYTES
from alphasense.sec_transport import SecResponse


def raw(rows: list[object] | None = None) -> bytes:
    return json.dumps(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": rows
            or [
                [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
                [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
                [123, "Unsupported exchange", "OTHER", "OTC"],
            ],
        }
    ).encode()


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "catalog"
    monkeypatch.setattr(sec_catalog, "CACHE", path)
    return path


def test_empty_cache_has_no_network_and_no_claimed_timestamp(cache: Path) -> None:
    assert read_catalog().items == [] and read_catalog().retrieved_at is None


def test_strict_rows_supported_exchange_and_deterministic_search(cache: Path) -> None:
    page = save_catalog(SecResponse(CATALOG_URL, raw(), datetime.now(UTC)))
    assert [entry.symbol for entry in page.items] == ["BRK-B", "MSFT"]
    assert resolve_symbol("MSFT").cik == "0000789019"
    assert resolve_symbol("BRK-B").exchange_mic == "XNYS"
    assert [entry.symbol for entry in sec_catalog.catalog_search("micro", 10).items] == ["MSFT"]
    assert read_catalog() == page
    assert len(list(cache.glob("*.json"))) == 2


@pytest.mark.parametrize(
    "content",
    [
        b"{}",
        b"[]",
        b"not json",
        b'{"fields":[],"fields":[]}',
        raw([[True, "Name", "TEST", "NYSE"]]),
        raw([[0, "Name", "TEST", "NYSE"]]),
        raw([[123, "Name", "bad symbol", "NYSE"]]),
        raw([[123, "Name", "TEST", "OTC"]]),
        raw([[123, "Name", "TEST"]]),
        b"x" * (MAX_CATALOG_BYTES + 1),
    ],
)
def test_malformed_catalog_is_rejected(content: bytes) -> None:
    with pytest.raises(CatalogError):
        parse_catalog(content)


def test_duplicate_symbol_is_ambiguous_and_not_silently_picked(cache: Path) -> None:
    save_catalog(
        SecResponse(
            CATALOG_URL,
            raw(
                [
                    [1, "One", "DUPE", "NYSE"],
                    [2, "Two", "DUPE", "Nasdaq"],
                ]
            ),
            datetime.now(UTC),
        )
    )
    with pytest.raises(CatalogError):
        resolve_symbol("DUPE")


def test_tampering_fails_closed_and_does_not_delete_archive(cache: Path) -> None:
    save_catalog(SecResponse(CATALOG_URL, raw(), datetime.now(UTC)))
    archive = next(path for path in cache.glob("*.json") if path.name != "latest.json")
    archive.write_bytes(b"tampered")
    with pytest.raises(CatalogError):
        read_catalog()
    with pytest.raises(HTTPException) as error:
        sec_catalog.catalog_search("MSFT", 10)
    assert error.value.status_code == 503
    assert archive.read_bytes() == b"tampered"


def test_source_identity_and_immutable_bytes(cache: Path) -> None:
    with pytest.raises(CatalogError):
        save_catalog(SecResponse("https://attacker.invalid/", raw(), datetime.now(UTC)))
    first = SecResponse(CATALOG_URL, raw(), datetime.now(UTC))
    save_catalog(first)
    save_catalog(first)
    assert len(list(cache.glob("*.json"))) == 2


def test_refresh_requires_origin_and_preserves_previous_cache_on_failure(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from alphasense.api import app
    from alphasense.db import get_store

    previous = save_catalog(SecResponse(CATALOG_URL, raw(), datetime.now(UTC)))
    called = []

    def invoke(*args: object, **kwargs: object) -> SecResponse:
        called.append(True)
        return SecResponse(CATALOG_URL, b"malformed", datetime.now(UTC))

    monkeypatch.setattr(sec_catalog, "load_policy", lambda: object())
    monkeypatch.setattr(
        sec_catalog,
        "SecImporter",
        lambda *args: SimpleNamespace(gateway=SimpleNamespace(invoke=invoke)),
    )
    app.dependency_overrides[get_store] = lambda: SimpleNamespace(
        engine=object(), check_ready=lambda: None
    )
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            assert client.post("/v1/panel/catalog/refresh", json={}).status_code == 403
            assert not called
            response = client.post(
                "/v1/panel/catalog/refresh",
                json={},
                headers={"Origin": "http://127.0.0.1", "X-AlphaSense-Panel": "1"},
            )
            assert response.status_code == 502
            assert called == [True]
            assert read_catalog() == previous
    finally:
        app.dependency_overrides.clear()
