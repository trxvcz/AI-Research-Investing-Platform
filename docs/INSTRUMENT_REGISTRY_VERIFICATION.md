# Weryfikacja rejestru instrumentów — 2026-10-30

Gałąź `codex/p1-instrument-registry`, Python 3.12.14, PostgreSQL 17.11 w istniejącym Dockerze. Bez nowych zależności, zewnętrznych danych, providerów LLM, brokerów i płatnych usług.

## Wyniki

- **295 testów Python PASS**, bez pominięć, na rzeczywistym PostgreSQL. **4 testy Node PASS**.
- Ruff check/format, mypy 13 modułów źródłowych, pip check i kontrola eksportu 12 schematów v1: PASS. Testy walidują łącznie 16 schematów (4 legacy +12 v1).
- Fixture InstrumentCreate i błędne kształty: model/schema odrzucają kontrolne znaki ASCII, NUL, nieprawidłowe UUID/URL/MIC/waluty i zbyt precyzyjne daty. Reguły między polami są dodatkowo walidowane w Pydantic.
- Rejestracja/get/retry z zachowaniem created_at, konflikty PK i naturalnego klucza, rozdzielenie synthetic/live, nullMIC dla commodity i unikalność, równoległe identyczne/konfliktowe rejestracje, UUID keyset, literalne wyszukiwanie `%`/`_`, bramki typów i brakujące ID: PASS.
- Migracja0001→0002 zachowuje payloady, checksum i dawne string/UUID ID bez backfill. Metadata SQLAlchemy odpowiada schematowi. Triggery i constraints chronią nowe wpisy i powiązania; UPDATE/DELETE/TRUNCATE rejestru odrzucone. Downgrade nie usuwa danych i czeka na trwający zapis przed kontrolą.
- Nowy raport wiąże się przez FK, nieznany UUID lub sprzeczny asset_type/origin daje409 bez pozostawienia streamu. Legacy UUID może wykonać retry i następną rewizję bez przepisywania historii. Uszkodzony rekord rejestru nie może zostać podstawą nowego powiązania.
- HTTP przez TestClient+PG: rejestracja 201, retry 200, odczyt instrumentu i powiązanego raportu. Osobne testy pokrywają 404/409/422/503, redakcję błędów i walidację parametrów. Auth nie wdrożono.
- Backup SQL/restore do osobnej bazy potwierdza instrument, FK i raport z zachowanym checksum.

Końcowe typecheck wymagało przekazania dict(RowMapping) do wspólnego walidatora; po połączeniu obu ścieżek odczytu ponownie przeszło 29 testów store i integracji rejestru/raportów. Pozostało znane ostrzeżenie Starlette/httpx w TestClient. Zdalnego CI nie wykonywano; istniejący job PostgreSQL 16 obejmuje nowe testy automatycznie.

## Migracja deweloperska

Przed upgrade wykonano pełny pg_dump do nowego pliku z UUID w nazwie, w ignorowanym `.local-postgres/backups/`. Następnie migracja bazy `alphasense` do `0002_instruments` i check_ready: PASS. Zastany stan zawierał 0 rewizji; kontrolę zachowania istniejących wpisów potwierdzono na danych w testach migracyjnych. W bazie deweloperskiej pozostawiono 0 instrumentów, bez automatycznego seedowania lub podmiany danych.

## Niezależny przegląd i ograniczenia

Migrację i store tworzono z rozłączną własnością plików, koordynator zintegrował modele/API/raporty i pełne testy. Read-only QA zgłosił potrzebę pełnego payload↔metadata decode przed linkowaniem raportu. Dodano wspólny walidator i negatywną próbę uszkodzonego katalogu; niezależny retest poprawnego/błędnego rekordu PASS. Nie znaleziono dalszych blokujących uwag. Dane źródeł nie są instrukcjami i nie są pobierane.

Metadane pozostają deklaracją operatora, a nie certyfikowanym MIC, licencją lub historycznym uniwersum. Samo powiązanie po stabilnym ID nie udowadnia historycznej eligibility; do backtestów potrzebne temporalne listingi, corporate actions i delistingi. Registry nie oferuje zmiany tickera, aktywacji/dezaktywacji ani deduplikacji aliasów różnych dostawców. Brak auth/RBAC i globalnego limitu body: API nadal lokalne.

Nie zmieniano master planu, migracji0001, oryginalnych raportów ani runtime Node; nie kopiowano wcześniejszych zmian spoza repo. Zachowano zastane pliki i zmiany użytkownika. Nie wykonywano commita, stagingu, resetu ani push. Koszt lokalnych obliczeń/pracy nie był mierzony; brak wywołań dostawców danych/LLM.
