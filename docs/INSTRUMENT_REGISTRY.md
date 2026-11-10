# Rejestr instrumentów — P1-02b1

Status: wdrożone i przetestowane lokalnie 2026-10-30. Baza deweloperska ma migrację `0002_instruments`; nie dodano do niej przykładowych instrumentów. [Weryfikacja](INSTRUMENT_REGISTRY_VERIFICATION.md).

Nowszy przyrost [przebiegów i archiwum](RUNS_AND_SNAPSHOTS.md) podniósł aktualny head bazy do `0003_runs_snapshots`, bez zmiany historii tego rejestru.

Zakres: minimalny niezmienny rejestr pojedynczej tożsamości/listingu, PostgreSQL i API. Bez pobierania danych, brokerów, automatycznego dopasowania tickera do spółki, zmian tickera, delistingów i corporate actions. Dane są deklaracją klienta, a nie wynikiem weryfikacji dostawcy. Nie certyfikujemy kodów MIC/ISO ani praw do źródła.

## Uzgodniony kontrakt

InstrumentCreate: schema_version=`1.0`, instrument_id (UUID 8-4-4-4-12, jak ReportUUID), symbol (1–32: `[A-Z0-9][A-Z0-9._-]*`), exchange_mic (4 wielkie litery/cyfry lub null), currency (3 wielkie litery), display_name (1–200 znaków, bez brzegowego whitespace i kontrolnych znaków ASCII C0+DEL), asset_type (`equity`, `etf`, `commodity`), data_origin (`synthetic`, `live`), as_of i available_at (Timestamp z dotychczasową normalizacją UTC i limitem mikrosekund), source_id (Identifier), source_url (SourceURL lub null), license (Reason). Wszystkie pola są wymagane; brak oznaczamy null tylko tam, gdzie jest dozwolony, bez placeholderów. Equity/ETF wymaga exchange_mic; commodity może mieć null, np. gdy brak notowania giełdowego. available_at ≤ as_of. Live wymaga source_url; synthetic może mieć null. NUL i inne kontrolne znaki ASCII C0+DEL w deklarowanych tekstach są odrzucane przed DB. Źródłowe metadane nie są pobierane ani wykonywane.

InstrumentRecord dodaje created_at z serwera DB. InstrumentWrite dodaje created=true/false. InstrumentPage: items (maks.100 InstrumentRecord), next_after_id (UUID lub null). UUID klienta pozwala na idempotentne retry; nigdy nie wyprowadzamy ID z tickera. Przykłady są jawnie syntetyczne.

## PostgreSQL i zgodność raportów

Migracja `0002_instruments` tworzy instruments: instrument_id UUID PK, symbol, exchange_mic, currency, asset_type, data_origin, as_of, available_at, payload JSONB (InstrumentCreate) i created_at. Unikalność `(exchange_mic,symbol,data_origin) NULLS NOT DISTINCT`: ten sam symbol bez MIC też nie dostaje dwóch ID. Nie rozdzielamy tej samej tożsamości przez zmianę waluty lub typu aktywa. UPDATE/DELETE/TRUNCATE są blokowane triggerami. Ticker reuse i metadata corrections wymagają przyszłego modelu historycznych listingów; ten przyrost nie pozwala nadpisać tożsamości.

Dodajemy nullable registry_instrument_id FK do report_streams. Brak backfill, bez zmiany payloadów/checksum i starych triggerów rewizji. Istniejące streamy pozostają legacy (null), także gdy ich dawne tekstowe ID przypomina UUID. Przy tworzeniu nowego streamu, którego input.instrument_id jest kanonicznym małym UUID, wymagamy instrumentu w rejestrze, zgodnego asset_type i data_origin; ustawiamy FK. Stare tekstowe ID pozostają obsługiwane w trybie legacy bez powiązania. Downgrade nie może usuwać niepustego rejestru lub powiązań; blokuje tabele przed kontrolą. Trigger nowych streamów również egzekwuje zarejestrowany UUID i zgodność identity.

To nie jest pełny instrument master. Waluta listingu nie oznacza automatycznie waluty każdej obserwacji finansowej. Rejestr nie tworzy wstecznej historii notowań ani dowodu availability ze starego raportu. Brak automatycznej konwersji starych ID. Obecność MIC/URL/licencji jest kontrolą deklaracji, nie certyfikatem autentyczności.

Powiązanie po stabilnym ID nie używa metadanych rejestru jako cech analitycznych: nie kopiuje symbolu, nazwy, waluty ani źródła do istniejącego raportu. Dlatego ID zarejestrowane później może służyć identyfikacji wcześniejszego researchu. Tego rejestru **nie wolno używać do historycznego doboru uniwersum ani ustalania dostępności notowania w backteście**. Do tego potrzebny będzie osobny temporalny model listingów z rewizjami i właściwymi datami dostępności.

## API

- POST /v1/instruments → InstrumentWrite, 201 nowy /200 identyczny retry. Zmiana danych tego ID lub zajęty naturalny klucz pod innym ID daje 409. Brak update/delete.
- GET /v1/instruments/{instrument_id} → InstrumentRecord lub 404.
- GET /v1/instruments?query=&after_id=&limit=50&data_origin= → InstrumentPage, rosnąco po UUID, limit1–100. Query do128 znaków, bez kontrolnych znaków ASCII C0+DEL; literalne case-insensitive substring symbol/display_name, `%` i `_` nie są wildcardami. after_id może nie należeć do filtra; to dolna granica UUID, nie token snapshotu. Nowe rekordy przed kursorem wymagają ponownego wyszukiwania od początku.

DSN wyłącznie serwerowy, ten sam engine co report store. Bez DSN operacje DB dają503, stateless validators pozostają dostępne. Błędy DB/danych bez treści dokumentów i DSN. Lokalny charakter API i ograniczenia auth/body limit pozostają jak wcześniej.

## Kryteria odbioru

Kontrakty/schema/formaty i negatywne wejścia, SQL search escaping i paginacja, idempotencja i równoległe próby rejestracji, DB append-only i constraints, powiązanie nowego raportu, brak zmiany istniejących raportów przy upgrade z0001, odmowa niebezpiecznego downgrade, restore rejestru oraz powiązanego raportu. Pełne testy Node/Python i read-only QA. Zmiany historycznych migracji0001 są wykluczone.

## Start i przykład

Z istniejącym kontenerem PostgreSQL, po wykonaniu kopii bezpieczeństwa, nowe stanowisko projektu aktualizuje bazę jawnie:

```powershell
$localDb = Get-Content -Raw .local-postgres/dev-connection.json | ConvertFrom-Json
$env:ALPHASENSE_DATABASE_URL = $localDb.url
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn alphasense.api:app --app-dir services/backend/src --host 127.0.0.1 --port 8081
```

Na tym komputerze migrację już wykonano po lokalnym pg_dump. W drugim terminalu można **zapisać syntetyczny przykład**:

```powershell
$instrument = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8081/v1/instruments -ContentType application/json -Body (Get-Content -Raw services/backend/tests/fixtures/instrument.synthetic.json)
Invoke-RestMethod "http://127.0.0.1:8081/v1/instruments/$($instrument.instrument_id)"
Invoke-RestMethod 'http://127.0.0.1:8081/v1/instruments?query=demo&data_origin=synthetic&limit=20'
```

Nowy rzeczywisty instrument wymaga własnego UUID i jawnych, sprawdzonych przez operatora metadanych. Nie zmieniać etykiety przykładu na live w celu udawania danych rzeczywistych. Nowy raport korzysta ze zwróconego UUID jako input.instrument_id i musi zostać ponownie zapieczętowany z jego uwzględnieniem; brakujące lub sprzeczne ID daje409. Poprzedni syntetyczny raport DEMO-EQUITY pozostaje legacy i nie łączy się automatycznie z przykładowym tickerem DEMO.

Komendy testowe i podłączenie PostgreSQL opisuje [backend](BACKEND.md) oraz [magazyn raportów](POSTGRES_REPORT_STORE.md). Nie uruchamiać downgrade w celu czyszczenia rejestru: ID jest trwałe, a operacje zmiany/dezaktywacji wymagają przyszłego modelu listingów.
