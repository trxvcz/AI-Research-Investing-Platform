# Weryfikacja pierwszego przyrostu Python — 2026-10-30

Gałąź: `codex/p1-contracts-fastapi`. Środowisko: Windows, Python 3.12.14, Node 24.21.0. Biblioteki przypięte w requirements-dev.lock; FastAPI 0.162.0, Pydantic 2.14.2. Nie zmieniano istniejących raportów, kodu demonstratora Node ani master planu. Nie kopiowano kandydata zmian z C:. Nie wykonywano commit/push.

## Wyniki

- `npm test`: 4/4 PASS.
- `python -m pytest -q`: 69/69 PASS (49 kontraktów, 20 API).
- `ruff check`, `ruff format --check`: PASS dla nowego backendu.
- `mypy`: PASS dla czterech modułów źródłowych.
- `pip check`: PASS, brak zerwanych zależności.
- Eksport schematów `--check`: PASS; trzy pliki v1 zgodne z Pydantic.
- Draft202012Validator.check_schema: PASS dla siedmiu schematów; format checker jest włączony przy walidacji fixture i testów danych.
- HTTP smoke w TestClient: health/ready, poprawny POST, partial/blocked, 422, OpenAPI, 404 nieistniejących zasobów i brak UI z CDN.

Na Windows TestClient potrzebował rozszerzonych uprawnień do lokalnego socketpair pętli asyncio. Próby w ograniczonym środowisku zawieszały się przed wykonaniem aplikacji; zostały zakończone. Pełny zestaw po rozszerzeniu uprawnień zakończył się poprawnie. Pozostało jedno ostrzeżenie deprecacji Starlette dotyczące użycia httpx w TestClient; testy przechodzą. Nie uruchamiano odrębnego procesu Uvicorn, przeglądarki, kontenerów ani zdalnego CI.

## Niezależny przegląd

Backend i QA pracowały niezależnie z rozłącznym właścicielstwem plików. QA wykrył rozjazd końcowego newline w regex JSON Schema/Pydantic i możliwość obcięcia timestampów poniżej mikrosekundy. Oba błędy naprawiono: dodatkowe wykluczenie końcowego whitespace w schema oraz limit sześciu cyfr ułamka. Testy regresyjne i niezależny retest PASS, także dla równego as_of i available_at z sześcioma cyframi.

Brak kodu sieciowego dostawców, zapisu payloadów i narzędzi brokerskich. Redakcja 422 sprawdzona testami. Ograniczenia: brak auth, limitu całego body i walidacji licencji/autentyczności source_id/snapshot_id. Punktowy PIT sprawdza deklarowane daty, nie potwierdza historycznej dostępności źródła. Status complete nie dowodzi kompletności metryk wymaganych do badania.

## Pozostały zakres

P1-00b raport/legacy, PostgreSQL/migracje, aktualna weryfikacja darmowego źródła, adapter i rzeczywisty raport partial; następnie React. Stare schematy M0 pozostają szkicami i nie otrzymały runtime walidatora. Nie oznaczono całego M1 ani fazy 1 jako ukończonych.

Brak wywołań API dostawców danych/LLM i opłat za takie wywołania. Pobierano darmowe biblioteki z PyPI. Kosztu pracy i lokalnych obliczeń nie mierzono. Oryginalny manifest nadal dotyczy startera, nie nowego przyrostu; nie regenerowano go, aby nie sugerować innego pochodzenia plików.
