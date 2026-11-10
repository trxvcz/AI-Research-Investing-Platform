"""Explicitly refreshed official SEC listing catalog; local reads never fetch."""

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from alphasense.contracts import Contract, Timestamp
from alphasense.db import ReportStore, get_store
from alphasense.instrument_contracts import DisplayName, SearchQuery, Symbol
from alphasense.provider_policy import ProviderDenied, load_policy
from alphasense.sec_catalog_transport import CATALOG_URL, MAX_CATALOG_BYTES, fetch_catalog
from alphasense.sec_contracts import CIK, SEC_PROVIDER_ID
from alphasense.sec_import import SecImporter, _FetchFailure
from alphasense.sec_transport import SecResponse, SecTransportError

CACHE = Path(__file__).resolve().parents[4] / ".local-postgres" / "sec-catalog"
router = APIRouter(prefix="/v1/panel", tags=["panel"])


class CatalogEntry(Contract):
    symbol: Symbol
    cik: CIK
    exchange_mic: Literal["XNAS", "XNYS"]
    display_name: DisplayName


class CatalogPage(Contract):
    items: list[CatalogEntry]
    retrieved_at: Timestamp | None
    source_url: str = CATALOG_URL


class CatalogError(ValueError):
    pass


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("Duplicate catalog field")
        result[key] = value
    return result


def parse_catalog(raw: bytes) -> list[CatalogEntry]:
    try:
        if not raw or len(raw) > MAX_CATALOG_BYTES:
            raise CatalogError("Catalog size")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if not isinstance(data, dict) or data.get("fields") != [
            "cik",
            "name",
            "ticker",
            "exchange",
        ]:
            raise CatalogError("Catalog shape")
        rows = data.get("data")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 50000:
            raise CatalogError("Catalog rows")
        entries = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 4:
                raise CatalogError("Catalog row")
            cik, name, symbol, exchange = row
            if (
                type(cik) is not int
                or not 1 <= cik <= 9999999999
                or not isinstance(name, str)
                or not isinstance(symbol, str)
                or exchange is not None
                and not isinstance(exchange, str)
            ):
                raise CatalogError("Catalog identity")
            if exchange not in {"Nasdaq", "NYSE"}:
                continue
            entries.append(
                CatalogEntry(
                    symbol=symbol,
                    cik=f"{cik:010d}",
                    exchange_mic="XNAS" if exchange == "Nasdaq" else "XNYS",
                    display_name=name,
                )
            )
        if not entries:
            raise CatalogError("No supported listings")
        return sorted(entries, key=lambda item: (item.symbol, item.cik, item.exchange_mic))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CatalogError("Official SEC catalog invalid") from None


def read_catalog() -> CatalogPage:
    pointer = CACHE / "latest.json"
    if not pointer.exists():
        return CatalogPage(items=[], retrieved_at=None)
    try:
        if CACHE.is_symlink() or pointer.is_symlink() or pointer.stat().st_size > 2048:
            raise CatalogError("Catalog cache invalid")
        metadata = json.loads(pointer.read_text(encoding="utf-8"), object_pairs_hook=_unique)
        digest = metadata["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise CatalogError("Catalog checksum invalid")
        target = CACHE / (digest + ".json")
        if target.is_symlink() or target.stat().st_size > MAX_CATALOG_BYTES:
            raise CatalogError("Catalog cache invalid")
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest or metadata["source_url"] != CATALOG_URL:
            raise CatalogError("Catalog checksum mismatch")
        page = CatalogPage(items=parse_catalog(raw), retrieved_at=metadata["retrieved_at"])
        if page.retrieved_at is None or page.retrieved_at > datetime.now(UTC):
            raise CatalogError("Catalog timestamp invalid")
        return page
    except (OSError, ValueError, TypeError, KeyError):
        raise CatalogError("Official SEC catalog cache unavailable") from None


def save_catalog(response: SecResponse) -> CatalogPage:
    if response.url != CATALOG_URL or response.retrieved_at > datetime.now(UTC):
        raise CatalogError("Catalog response identity invalid")
    page = CatalogPage(items=parse_catalog(response.content), retrieved_at=response.retrieved_at)
    if CACHE.is_symlink():
        raise CatalogError("Catalog cache invalid")
    CACHE.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(response.content).hexdigest()
    target = CACHE / (digest + ".json")
    if target.is_symlink():
        raise CatalogError("Catalog cache invalid")
    try:
        with target.open("xb") as stream:
            stream.write(response.content)
    except FileExistsError:
        if target.read_bytes() != response.content:
            raise CatalogError("Catalog immutable archive conflict") from None
    pointer = CACHE / "latest.json"
    if pointer.is_symlink():
        raise CatalogError("Catalog cache invalid")
    metadata = {
        "sha256": digest,
        "source_url": CATALOG_URL,
        "retrieved_at": response.retrieved_at.isoformat(),
    }
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=CACHE, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(json.dumps(metadata) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, pointer)
    finally:
        if temporary is not None and Path(temporary).exists():
            Path(temporary).unlink()
    return page


def resolve_symbol(symbol: str) -> CatalogEntry:
    matches = [entry for entry in read_catalog().items if entry.symbol == symbol]
    if len(matches) != 1:
        raise CatalogError("Symbol unavailable or ambiguous")
    return matches[0]


@router.get("/catalog")
def catalog_search(
    query: SearchQuery = "", limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> CatalogPage:
    try:
        page = read_catalog()
        needle = query.strip().casefold()
        items = [
            entry
            for entry in page.items
            if needle in entry.symbol.casefold() or needle in entry.display_name.casefold()
        ]
        return page.model_copy(update={"items": items[:limit]})
    except CatalogError:
        raise HTTPException(
            503,
            detail={
                "code": "CATALOG_UNAVAILABLE",
                "message": "Katalog SEC jest niedostępny. Odśwież katalog.",
            },
        ) from None


@router.post("/catalog/refresh")
def catalog_refresh(
    request: Request, store: Annotated[ReportStore, Depends(get_store)]
) -> CatalogPage:
    from alphasense.panel_launch import verify_panel_request

    verify_panel_request(request)
    store.check_ready()
    try:
        importer = SecImporter(
            store.engine,
            load_policy(),
            lambda _payload: fetch_catalog(os.environ.get("ALPHASENSE_SEC_USER_AGENT", "")),
        )
        result = importer.gateway.invoke(SEC_PROVIDER_ID, None, classification="public")
        if isinstance(result, _FetchFailure):
            raise SecTransportError(result.code)
        page = save_catalog(result)
        return page.model_copy(update={"items": page.items[:30]})
    except ProviderDenied:
        raise HTTPException(
            403,
            detail={
                "code": "CATALOG_POLICY_DENIED",
                "message": "Odświeżenie katalogu zablokowane przez politykę SEC lub limit.",
            },
        ) from None
    except (CatalogError, SecTransportError, OSError, ValidationError):
        raise HTTPException(
            502,
            detail={
                "code": "CATALOG_REFRESH_FAILED",
                "message": "Nie udało się odświeżyć oficjalnego katalogu SEC.",
            },
        ) from None
