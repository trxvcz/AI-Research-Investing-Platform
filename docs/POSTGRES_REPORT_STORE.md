# PostgreSQL — kontrakt trwałych rewizji

Aktualny stan po pilocie SEC: właściwa baza Docker ma **head0007_sec_receipts**, `/ready`200 i pierwszy rzeczywisty raport, po backupie przed migracją i po imporcie. [Odbiór SEC](SEC_VERIFICATION.md). Poniższe aktualizacje P1/P4 dokumentują wcześniejsze etapy.

Status: wdrożone i przetestowane lokalnie 2026-10-30. Weryfikacja: [POSTGRES_VERIFICATION](POSTGRES_VERIFICATION.md).

Zakres P1-02a: wyłącznie magazyn zwalidowanych raportów v1. Bez migracji M0, źródeł zewnętrznych, składania zleceń, automatycznych analiz i zakupu hostingu. Instrument registry, research jobs i raw snapshot storage to dalsze zadania.

Aktualizacja P1-02b1: minimalny [rejestr instrumentów](INSTRUMENT_REGISTRY.md) został wdrożony migracją `0002_instruments`. Nowe raporty z kanonicznym UUID instrumentu wymagają zgodnego wpisu katalogowego. Istniejące streamy i tekstowe ID zachowują tryb legacy; bez backfill. Research jobs, raw snapshoty i temporalne listingi pozostają dalszym zakresem.

Aktualizacja P1-02b2: [manualny ledger przebiegów i raw snapshoty](RUNS_AND_SNAPSHOTS.md) zostały wdrożone migracją `0003_runs_snapshots`, która jest aktualnym head bazy deweloperskiej. Automatyczny worker/kolejka i temporalne listingi pozostają dalszym zakresem.

## Granice i zapis

Aktualizacja P4-00 (2026-11-02): aktualny head to `0005_provider_quota`, dodający [trwałe limity darmowych wywołań](FREE_ONLY_PROVIDERS.md). Właściwa baza Docker nadal wymaga backupu i upgrade head po jej uruchomieniu. Testy migracji i całej platformy na pomocniczym PostgreSQL: 605 Python +9 Node PASS.

Aktualizacja P1-02c (2026-11-02): [worker deterministyczny](AUTOMATIC_WORKER.md) i migracja `0004_worker` są zaimplementowane oraz przetestowane na oddzielnym lokalnym PostgreSQL. Kod wymaga aktualnego head0004; Docker jest niedostępny i jego bazy deweloperskiej nie migrowano. Po wznowieniu Docker najpierw wykonać backup i jawny `alembic upgrade head`, następnie `/ready`. Nie zmieniano DSN ani wolumenu Docker.

Backend używa SQLAlchemy 2 i psycopg 3; migracje są jawnie wykonywane Alembic. Brak create_all przy starcie i brak SQLite fallbacku. DSN jest wyłącznie w serwerowym ALPHASENSE_DATABASE_URL, akceptowany driver postgresql+psycopg. Bez DSN API walidacyjne działa, a operacje magazynu dają 503. Przy skonfigurowanym DSN /ready sprawdza połączenie, wersję migracji i dostęp do tabel; /health nie łączy się z bazą. Komunikaty HTTP nie zwracają DSN, parametrów SQL ani raportów w błędach.

Dwie tabele: report_streams (report_id UUID PK, instrument_id, asset_type, data_origin, created_at) i report_revisions (revision_id UUID PK, report_id FK, revision int>0, parent_revision_id UUID/null, generated_at_utc, checksum, input_sha256, payload JSONB, stored_at). Unikalne (report_id, revision), (report_id, revision_id); złożony FK rodzica (report_id,parent_revision_id) do (report_id,revision_id) zapobiega rodzicowi z obcego raportu. Pierwsza rewizja ma null rodzica; kolejne wymagają poprzedniej. Treść JSONB zawiera pełny zwalidowany ReportRevision, nie link do mutowalnego pliku.

Transakcja tworzy stream przez INSERT ON CONFLICT DO NOTHING, blokuje go SELECT FOR UPDATE, sprawdza retry revision_id i najnowszą rewizję, zapisuje nową rewizję i commit. Stream zachowuje instrument_id/asset_type/data_origin; nie wolno ich zmienić między rewizjami. Nowa rewizja ma dokładnie numer latest+1, rodzica latest.revision_id oraz generated_at_utc ≥ latest.generated_at_utc. Identyczny retry istniejącej rewizji jest dozwolony także po dodaniu następnej; inna treść lub konflikt globalnego revision_id daje 409. Lock serializuje konkurencyjny zapis tego samego report_id; unique/FK i trigger dają dodatkową ochronę.

Migracja dodaje triggery odrzucające UPDATE, DELETE i TRUNCATE obu tabel; trigger INSERT rewizji ponownie blokuje stream i sprawdza ciągłość, stałość identity oraz zgodność indeksowanych metadanych z payload. Pełny JSON Schema i checksum są sprawdzane przez aplikację przy zapisie i odczycie. Trigger nie certyfikuje licencji ani treści źródeł i nie oblicza pythonowego canonical JSON hash. Właściciel DB/superuser może zmienić schemat i wyłączyć ochronę; to nie WORM ani zabezpieczenie przed administratorem. Runtime produkcyjny musi mieć osobną rolę z ograniczonymi uprawnieniami.

## API i wyniki

- POST /v1/reports przyjmuje ReportRevision, zwraca StoredRevisionInfo: report_id, revision_id, revision, checksum, status, generated_at_utc oraz created. Nowy zapis HTTP 201; identyczny retry HTTP 200. Nie generuje i nie poprawia raportu klienta.
- GET /v1/reports/{report_id} zwraca najnowszy ReportRevision.
- GET /v1/reports/{report_id}/revisions/{revision} zwraca określoną rewizję (revision≥1).
- GET /v1/reports/{report_id}/revisions?after_revision=0&limit=50 zwraca RevisionPage: items metadanych (bez created), next_after_revision lub null; limit 1–100, rosnący klucz revision. Nieznany report_id daje 404.

422: błędny kontrakt/UUID/paginacja. 409: konflikt lub nieciągła historia. 503: magazyn nieskonfigurowany/niedostępny albo odczyt niespójny z kontraktem/checksum. Odczyt weryfikuje payload i metadane, nie tylko ufa JSONB. Brak endpointów aktualizacji/usuwania. API lokalne do czasu auth/RBAC; źródła URL nigdy nie są pobierane.

Granica PostgreSQL dodatkowo odrzuca NUL (U+0000) w tekście jako HTTP 422 przed transakcją: JSONB nie potrafi go przechować. Inspector bezstanowy nie stanowi gwarancji zapisywalności dowolnego tekstu. Nie zamieniamy NUL na inny znak i nie zmieniamy checksum klienta.

## Odbiór

Testy na rzeczywistym PostgreSQL: upgrade migracji, powtórzenie upgrade, zapis/odczyt po utworzeniu nowego engine, retry, konflikty, obcy rodzic/instrument, ciągłość czasu, równoległe zapisy, blokada UPDATE/DELETE/TRUNCATE i bezpośredniego INSERT z pominięciem numeru; backup/restore przez pg_dump w formacie SQL i psql do osobnej testowej bazy i ponowna weryfikacja checksum. Testy izolują schematy/bazy i nie usuwają danych użytkownika. Brak PostgreSQL oznacza jawnie pominięte testy integracyjne, nigdy zastąpienie bazy przez SQLite.

Downgrade pobiera ACCESS EXCLUSIVE przed sprawdzeniem pustej historii. Dla niepustej bazy odmawia usunięcia tabel; operacji tej nie należy traktować jako przycisku czyszczenia danych. Zmiany istniejącego schematu w kolejnych zadaniach wymagają nowych migracji.

## Uruchomienie na tym komputerze

Obecnie PostgreSQL 17.11 działa w kontenerze `alphasense-storage-db-1` na 127.0.0.1:55432, z named volume `alphasense-storage_postgres_reports`. Baza `alphasense` ma wykonaną migrację i pozostaje bez raportów użytkownika; testy tworzyły tylko własne losowe schematy/bazę restore. Po odtworzeniu kontenera z tym samym wolumenem obie próbne rewizje i ich hashe przetrwały. Sekrety są w lokalnych ignorowanych plikach połączenia; nie kopiować ich do repo ani logów.

PowerShell z katalogu repo:

```powershell
$localDb = Get-Content -Raw .local-postgres/dev-connection.json | ConvertFrom-Json
$env:ALPHASENSE_DATABASE_URL = $localDb.url
.\.venv\Scripts\python.exe -m uvicorn alphasense.api:app --app-dir services/backend/src --host 127.0.0.1 --port 8081
```

Po uruchomieniu Docker Desktop można wystartować istniejący projekt tym samym lokalnym plikiem konfiguracji:

```powershell
docker compose --env-file .local-postgres/compose.env -p alphasense-storage -f compose.postgres.yaml up -d --wait
```

Zatrzymanie bez usuwania danych: to samo polecenie Compose z `stop`. Nie używać `down -v`, jeśli dane mają zostać zachowane. Wolumen i lokalne pliki połączenia nie są częścią Git. Wcześniejszy klaster przenośny w `.local-postgres/data` jest zatrzymany; jego dane zachowano. Nie uruchamiać go na tym samym porcie równocześnie z kontenerem.

## Nowe stanowisko — Docker Compose

Osobny `compose.postgres.yaml` zachowuje oryginalne Compose demonstratora. Dla świeżego projektu, bez istniejącego wolumenu, hasło ustawić lokalnie i zachować w bezpiecznej konfiguracji do kolejnych uruchomień; nie zapisywać w śledzonym pliku:

```powershell
$env:ALPHASENSE_POSTGRES_PASSWORD = Read-Host 'Hasło lokalnej bazy' -MaskInput
docker compose -p alphasense-storage -f compose.postgres.yaml up -d --wait
$escapedPassword = [uri]::EscapeDataString($env:ALPHASENSE_POSTGRES_PASSWORD)
$env:ALPHASENSE_DATABASE_URL = "postgresql+psycopg://alphasense:${escapedPassword}@127.0.0.1:55432/alphasense"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

To lokalna rola właściciela do developmentu, nie produkcyjny podział uprawnień. Zmiana POSTGRES_PASSWORD w istniejącym wolumenie nie zmienia hasła roli w bazie — nie nadpisywać losowo pliku konfiguracji. Testy wykonano zarówno na PostgreSQL natywnym, jak i Docker. Obraz jest przypięty do wersji, nie do digestu; produkcja wymaga osobnego hardeningu.

## Przykład i testy

Po starcie API:

```powershell
$receipt = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8081/v1/reports -ContentType application/json -Body (Get-Content -Raw services/backend/tests/fixtures/report.synthetic.json)
Invoke-RestMethod "http://127.0.0.1:8081/v1/reports/$($receipt.report_id)"
```

Ten przykład **zapisuje syntetyczny raport**. Nie jest analizą rzeczywistego instrumentu. Powtórzenie tej samej treści jest idempotentne; zmiana tej rewizji wymaga nowego ID i ponownego seal_report, a kolejna rewizja poprawnego rodzica i numeru.

Testy na przygotowanym lokalnym klastrze:

```powershell
$testDb = Get-Content -Raw .local-postgres/test-connection.json | ConvertFrom-Json
$env:ALPHASENSE_TEST_DATABASE_URL = $testDb.url
$env:ALPHASENSE_PG_BIN = $testDb.bin
.\.venv\Scripts\python.exe -m pytest
```

Nie wpisywać DSN ręcznie w logach. Testy tworzą własne schematy/bazę restore z UUID i usuwają wyłącznie je. Backup/restore wymaga pg_dump oraz psql zgodnych z wersją serwera. W CI skonfigurowano natywny PostgreSQL 16 na ubuntu-24.04 (peer auth użytkownika runnera, bez haseł w plikach workflow); lokalnie zweryfikowano PostgreSQL 17.11. Zdalnego CI nie wykonywano.

Źródła projektu migracji: [PostgreSQL — blokady](https://www.postgresql.org/docs/17/explicit-locking.html), [Alembic — tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html). Pakiet Windows pochodzi z [dystrybucji EDB wskazanej przez PostgreSQL](https://www.postgresql.org/download/windows/); dane pobrane z archiwum nie są dostawcą danych finansowych.
