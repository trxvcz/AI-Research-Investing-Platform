# Backend Python — walidacja wejść i raportów

Wdrożone lokalnie: kontrakty wejść i koperty raportu v1, FastAPI do walidacji i rozpoznawania legacy M0 oraz opcjonalny [magazyn PostgreSQL](POSTGRES_REPORT_STORE.md). Nie ma jeszcze kolejkowania, pobierania danych, generowania analiz/raportów ani React. Node M0 pozostaje na porcie 8080 i korzysta z istniejących plików. Nowe API ma osobny port 8081. Start poniżej bez DSN uruchamia tryb validation-only; instrukcja PostgreSQL opisuje podłączenie przygotowanej lokalnej bazy.

Dodano [rejestr instrumentów](INSTRUMENT_REGISTRY.md): POST/GET `/v1/instruments`, GET po UUID, literalne wyszukiwanie i powiązania nowych raportów. Baza deweloperska ma migrację `0002_instruments`; po aktualizacji innych stanowisk jawnie wykonać `python -m alembic upgrade head`. Bez DSN rejestr daje503, tak jak magazyn raportów.

Dodano [manualne przebiegi i raw snapshots](RUNS_AND_SNAPSHOTS.md). Aktualny head deweloperski to `0003_runs_snapshots`: POST/GET snapshotów, attachment oryginalnych bajtów, POST/GET przebiegów i zdarzeń. POST upload ma cap1500000 bajtów przed parserem, snapshot maks.1 MiB. Nowe run pozostają queued bez operatora/wykonawcy; nie uruchomiono background workera.

## Start w PowerShell

Z katalogu głównego repo, z działającym Pythonem 3.12+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m uvicorn alphasense.api:app --app-dir services/backend/src --host 127.0.0.1 --port 8081
```

W sesji implementacyjnej użyto Python 3.12.14 z runtime Codex do utworzenia `.venv`, bo polecenie systemowe python wskazywało niedostępny alias WindowsApps. Nie zmieniano instalacji systemowych. Lock obejmuje środowisko deweloperskie wraz z zależnościami pośrednimi; nie jest obrazem produkcyjnym ani potwierdzeniem braku podatności. Nie wymaga kluczy API. Na Linux odpowiednik interpretera środowiska to `.venv/bin/python`.

## Sprawdzenie API

W drugim terminalu PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8081/health
Invoke-RestMethod http://127.0.0.1:8081/ready
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8081/v1/validate -ContentType application/json -Body (Get-Content -Raw services/backend/tests/fixtures/research-input.synthetic.json)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8081/v1/reports/inspect -ContentType application/json -Body (Get-Content -Raw services/backend/tests/fixtures/report.synthetic.json)
```

Fixture jest syntetyczna: revenue=0, net_margin jest missing. Odpowiedź ma status partial, available_count=1, missing_count=1. Complete oznacza tylko kompletność podanych obserwacji, nie gotowość analizy inwestycyjnej. Live jest deklaracją klienta, nie certyfikatem autentyczności.

Inspector zwraca wyłącznie metadane raportu. Dla v1 sprawdza też relacje źródeł, evidence i checksum. Dla M0 zwraca oryginalny legacy_status oraz `migration_status=blocked_missing_provenance`, bez podnoszenia wersji. Nie przyjmuje ścieżek/URL do pobrania i nie zapisuje raportów. Szczegóły i granice: [REPORT_CONTRACT_V1](REPORT_CONTRACT_V1.md).

`/openapi.json` udostępnia opis API. UI Swagger/Redoc jest wyłączone, aby nie ładować zewnętrznych skryptów. `/research-runs`, niewersjonowane `/reports` i trasy zleceń nie istnieją w nowym API. Z DSN dostępne są POST/GET `/v1/reports` i historia rewizji. `/health` nie łączy się z DB; `/ready` przy skonfigurowanym DSN sprawdza połączenie, migrację i dostęp do tabel, a bez DSN sygnalizuje wyłącznie gotowość validation-only. Nie sprawdza dostawców danych.

## Kontrole lokalne i CI

```powershell
npm test
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check services/backend migrations
.\.venv\Scripts\python.exe -m ruff format --check services/backend migrations
.\.venv\Scripts\python.exe -m mypy
$env:PYTHONPATH = 'services/backend/src'
.\.venv\Scripts\python.exe -m alphasense.schemas --check
```

Po celowej zmianie kontraktów uruchomić generator bez `--check`, przejrzeć różnice i powtórzyć kontrole. Pydantic jest jedynym źródłem v1, JSON Schema jest eksportem. Relacje czasu, duplikaty, evidence i hashe są sprawdzane dodatkowo w Pydantic. Testy sprawdzają metasyntaksę 33 schematów (4 legacy +29 v1), fixture z date-time validation, zgodność eksportu i złe wejścia. Inspector M0 używa lokalnego schematu z wyłączonym pobieraniem referencji; nie zmienia starego runtime Node. Bez ALPHASENSE_TEST_DATABASE_URL testy PostgreSQL są jawnie pomijane — nie jest to pełne potwierdzenie przyrostu storage.

CI ma osobny job Python 3.12 z tymi kontrolami obok istniejącego joba Node. Job backend także instaluje Node 22 dla testu zgodności oryginalnego raportu M0 i uruchamia lokalny PostgreSQL runnera do integracji. Nie wykonywano push ani zdalnego CI. Weryfikacja: [pierwszy przyrost](P1_VERIFICATION.md), [raport/legacy](P1_REPORT_VERIFICATION.md), [PostgreSQL](POSTGRES_VERIFICATION.md).

## Granice bezpieczeństwa

Serwer uruchamiać na loopback 127.0.0.1. Nie ma auth/RBAC, globalnego limitu body, rate limiting ani kontroli dostępu do źródeł; nie jest przeznaczony do publicznego wystawienia. Lista ma limit 1000 obserwacji, a pola tekstowe mają ograniczenia; nie zastępuje to limitu rozmiaru żądania. Handler 422 nie zwraca danych wejściowych, kontekstu błędu ani nieznanych nazw pól.

Walidatory i inspector nie zapisują payloadów; endpointy raportów, instrumentów, snapshotów i przebiegów jawnie zapisują dane w skonfigurowanym PostgreSQL. API nie wykonuje zewnętrznych wywołań dostawców. Polityka darmowych źródeł jest zachowana przez brak aktywnych providerów. Techniczna bramka dla przyszłych adapterów/gateway pozostaje osobnym zadaniem. Nie przesyłać sekretów lub prywatnych dokumentów jako danych testowych.


## Automatyczne przebiegi

[Worker deterministyczny](AUTOMATIC_WORKER.md) działa jako osobny proces Python, wyłącznie dla `deterministic-research-v1`. Wymaga migracji0004 i PostgreSQL. API udostępnia odczyt `/v1/research-runs/{run_id}/worker-job`, bez tokenu; publiczne polecenia events nie sterują automatycznym przebiegiem. Dotychczasowy `manual-research-v1` pozostaje ręcznym rejestrem.


## Dopuszczenie darmowych wywołań

[Bramka free-only i trwałe limity](FREE_ONLY_PROVIDERS.md) wymagają head0005. Domyślna konfiguracja provider-policy.json ma pustą listę dostawców. Bramka jest używana przez przyszłe adaptery serwera, bez publicznego endpointu nadawania zgody; istniejący worker pozostaje deterministyczny.


## Rzeczywisty pilot SEC

[SEC fundamentals](SEC_FUNDAMENTALS.md) używa osobnego CLI i pipeline sec-fundamentals-v1. Baza Docker ma head0007 po backupie, `/ready`200. Pierwszy raport Apple jest partial, z raw/hash/receipts i konserwatywnym first_seen; nie dodano importu sieciowego przy starcie FastAPI.
