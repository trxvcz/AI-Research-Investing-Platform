# Automatyczny worker — pierwszy deterministyczny przyrost

Status: zaimplementowany lokalnie; odbiór i instrukcje poniżej. To pierwszy ograniczony wykonawca deterministyczny, bez adapterów dostawców i harmonogramu. Testy bazy wykonano na PostgreSQL 17.11; dostępność i migrację konkretnej bazy należy sprawdzić przed uruchomieniem. [Weryfikacja](WORKER_VERIFICATION.md).

Aktualizacja SEC: kod i baza Docker mają head0007 po backupie, obejmujący [trwałe limity](FREE_ONLY_PROVIDERS.md) i [pilot SEC](SEC_FUNDAMENTALS.md). Sam worker nie pobiera źródeł; importer SEC zapisuje je osobno. Na innym stanowisku wymagany jest backup i jawny upgrade head.

Kontrakt: pipeline_version `deterministic-research-v1` jest jawnie opt-in w RunCreate/RunState. Manual-research-v1 działa jak dotychczas. Nowy worker nie pobiera źródeł, nie wykonuje kodu danych i nie wywołuje LLM. Kolejką jest PostgreSQL; Redis/Celery, scheduler i powiadomienia pozostają osobnymi zadaniami.

## Własność i odzyskiwanie

Migracja0004_worker dodaje worker_jobs (run_id UUID PK/FK, status queued/running/completed/dead, attempts int0..3, worker_id nullable text128, lease_token UUID|null, lease_expires_at timestamptz|null, implementation_hash64, pipeline_git_sha40/64, last_error_code|null, created_at,updated_at) i append-only worker_claims (run_id,attempt1..3 PK,lease_token UUID UNIQUE,worker_id,implementation_hash,pipeline_git_sha,claimed_at,initial_expires_at). worker_jobs jest celowo mutowalnym stanem operacyjnym; historia analizy pozostaje w immutable run_events. Nowe funkcje SQL z0003 dopuszczają oba pipeline, bez zmiany historycznych migracji.

Job powstaje leniwie przy claim: worker wybiera wyłącznie automatyczne runy bez terminalnego joba, najstarsze created_at/run_id. Kolejność blokad zawsze research_runs FOR UPDATE SKIP LOCKED, potem worker_jobs FOR UPDATE; brak trzymania joblock przed runlock. Claim nadaje losowy token, inkrementuje attempts (maks.3), lease15–300s (default60), zapisuje immutable claim. W tej samej transakcji startuje queued lub wznawia failed bez raportu; running po crash zachowuje etap. Existing active lease nie może zostać przejęty. Czas pochodzi z DB clock_timestamp, nie zegara procesu.

Każda mutacja workera blokuje run/job, sprawdza token, owner i lease>czasDB przed i po zapisie. ReportStore.append może używać pożyczonej aktywnej Connection tego samego engine: raport i advance etapu report są jedną transakcją. Utrata lease oznacza rollback. Fencing dotyczy zapisów etapów, raportu i zakończenia, nie tylko momentu claim. Renew przed etapami przedłuża lease. Public ResearchStore.apply odrzuca auto pipeline; worker używa core transition pod własnym fence w tej samej transakcji. Klient HTTP nie otrzymuje tokenu.

Po wygaśnięciu lease inny worker kontynuuje bieżący etap z nowym tokenem. Zmiana implementation_hash/git SHA albo wyczerpane3 próby kończy job dead i dopisuje failed na niezakończonym etapie pod lockiem (cleanup nie wykonuje analizy). Błędy deterministycznego wejścia lub konflikt wynikowego artefaktu kończą dead od razu; nie retry tych samych niepoprawnych danych. Awaria infrastruktury zostawia lease do odzyskania; brak nieograniczonej pętli płatnego fallbacku. Brak endpointu ponownego uruchamiania dead; nowe wejście wymaga nowego run_id.

## Format i obliczenia

Odnowienie lease musi zakończyć się przed jego pierwotnym terminem ważności. Pauza procesu ponad ten termin cofa transakcję; renewal nie przywraca wygasłego uprawnienia. Tekst raportu nieobsługiwany przez JSONB (np. NUL) kończy job jako dead po pierwszej próbie, z kodem INPUT_UNSTORABLE. Oryginalne bajty pozostają w archiwum.

Każdy zamrożony snapshot ma media_type application/json i bytes UTF-8 będące istniejącym ResearchInput. JSON duplicate keys, NaN/Infinity i nieprawidłowa struktura są odrzucane. Packet instrument_id/asset_type/data_origin/as_of odpowiada runowi i rejestrowi. AvailableObservation każdego pakietu wskazuje dokładnie source_id i str(snapshot_id) tego pliku; available_at nie może poprzedzać snapshot.available_at. Wszystkie łączone obserwacje przechodzą ponownie ResearchInput (limit1000, brak duplikatów, jednostki/okresy/daty jak w kontrakcie). Source provenance pochodzi z archiwum, nigdy z wymyślonych linków.

Engine API w worker_engine.py: WorkerInputError(code: str), load_input(state:RunState, instrument:InstrumentRecord, snapshots:list[tuple[SnapshotRecord,bytes]])->ResearchInput; fundamental_section(data)->ReportSection; technical_section(data)->ReportSection; compile_report(state,instrument,snapshots,git_sha,implementation_hash)->ReportRevision. Implementacja czysta, bez DB/files/shell/network. ReportID=uuid5(NAMESPACE_URL,'alphasense:worker-report:'+str(run_id)), revisionID=uuid5(NAMESPACE_URL,'alphasense:worker-revision:'+str(run_id)); revision1,parentnull. generated_at_utc=run.created_at (stabilne po retry); as_of i retrieved_at źródeł nie mogą być późniejsze od tego czasu.

Fundamental: facts tylko z dostępnych revenue/net_income (max40); jednostka currency i znana waluta. Net margin tylko dla jednoznacznej pary zgodnych okresów/waluty, najnowszego period_end i niezerowego revenue. Zero revenue nie staje się zerową marżą, brak/ambiguous/nieprzedstawialny wynik pozostaje jawną luką. Metoda ratio-net-margin-v1. Nie implementujemy wyceny/DCF/peers. Sekcja ma partial jeśli są fakty, inaczej blocked.

Technical: last-3-observation SMA wyłącznie dla co najmniej3 available close, dodatnich, punktowych period_start=period_end, bez duplikatów czasu, wspólna currency i unit=currency_per_unit. Nie udajemy 3-dniowego wskaźnika ani zgodności kalendarza. Przy braku tych warunków blocked. Metoda last3-observation-sma-v1. Brak sygnałów kup/sprzedaj, backtestu i performance. Finite arithmetic; nie zapisujemy inf/NaN.

Synthesis blocked (brak syntezy), scenarios not_applicable z wyjaśnieniem. Report.status partial gdy co najmniej jedna sekcja ma wyniki, inaczej blocked; brak udawania pełnego badania. model_provenance/prompt=null, charts=[]. methodology_version='deterministic-research-v1:'+implementation_hash[:16]. Limitations podaje pełny implementation hash i ograniczenia. Brakujące/nieadekwatne obserwacje zachowujemy, nigdy nie zastępujemy zerem.

## Wykonanie

WorkerStore(engine): claim(worker_id,implementation_hash,git_sha,lease_seconds=60)->WorkerLease|None; renew(lease)->WorkerLease; apply(lease,RunCommand)->RunEventWrite; publish(lease,ReportRevision,RunAdvance)->RunEventWrite (report+advance atomic); fail(lease,code,reason)->None (run failure+deadjob); finish(lease,RunFinish)->RunEventWrite (terminalrun+job completed/dead); get_job(run_id)->WorkerJobRecord. WorkerLease: run_id,worker_id,token,attempt,expires_at,implementation_hash,pipeline_git_sha. JobRecord nie pokazuje tokenu. Nie ma HTTP claim/renew/mutation endpointów; CLI jest wykonawcą.

Worker CLI `python -m alphasense.worker --once` default, albo `--forever --poll-seconds 2`, --worker-id default local-worker, --lease-seconds15..300. Git SHA odczytany lokalnie git rev-parse HEAD albo jawne --git-sha; nie zgadujemy. implementation_hash liczy SHA zawartości modułów alphasense i requirements-dev.lock. Worker bierze run, ładuje/zapamiętuje frozen inputs, automatycznie wykonuje każdy etap. Data sprawdza archiwum, validate dekoduje JSON/Pydantic, fundamental/technical uruchamiają czyste funkcje, report kompiluje i publikuje, review sprawdza report checksum i provenance/finalizuje. Restart może przeliczyć czyste funkcje, ale nie dopisuje drugi raz zakończonego etapu i nie tworzy drugiej rewizji.

GET /v1/research-runs/{id}/worker-job zwraca WorkerJobRecord lub404 gdy jeszcze nieclaimowane. Worker nie jest automatycznie uruchamiany w FastAPI. WorkerJobRecord: run_id,status,attempts,worker_id,lease_expires_at,implementation_hash,pipeline_git_sha,last_error_code,created_at,updated_at. Nie ujawnia tokenu ani DSN. Oryginalne manualne runy i raporty pozostają niezmienione.

## Odbiór

RealPG: pojedynczy zwycięzca równoległych claims, SKIPLOCKED, expiry/takeover, stale token odrzucony i bez artefaktu, renew, restart na etapie, maxattempts, codechange, atomic publish+advance rollback, manualauto APIguard, crash po raporcie przed finish bez duplikatu. Pure golden fixtures net margin, zero/missing, ambiguity, SMA, PIT, malicious JSON. End-to-end automatyczne zakończenie na partial/blocked i failure manifest dla invalid input, backup/restore/reclaim i bez zmiany starych danych. Nie uruchamiać prawdziwych dostawców ani płatnego przetwarzania.


## Uruchomienie lokalne

Worker jest osobnym procesem; start FastAPI nie uruchamia go automatycznie. W katalogu repozytorium, z aktywnym PostgreSQL i ustawionym `ALPHASENSE_DATABASE_URL` (jak w [instrukcji magazynu](POSTGRES_REPORT_STORE.md)):

```powershell
$env:PYTHONPATH = 'services/backend/src'
# Najpierw kopia bazy; migracje zawsze wykonujemy jawnie.
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alphasense.worker --once
# Osobny terminal dla procesu oczekującego na kolejne przebiegi:
.\.venv\Scripts\python.exe -m alphasense.worker --forever --worker-id local-worker --poll-seconds 2
```

`--once` jest też domyślnym trybem. Ctrl+C zatrzymuje proces; rozpoczęty przebieg można przejąć po wygaśnięciu lease. Nie zmieniamy w ten sposób wejść ani raportu. Wyłączenie komputera nie uruchamia workera ponownie — usługa systemowa/automatyczny start i scheduler pozostają osobnym zadaniem. Awaria infrastruktury kończy proces z kodem1; po usunięciu przyczyny uruchomić go ponownie. Trzy porzucone próby lub inny hash kodu kończą przebieg jako failed, job jako dead. Nowy eksperyment wymaga nowego run_id.

Przykład syntetyczny korzysta z trzech nowych, zgodnych fixture. Przy działającym API na porcie8081 poniższe polecenia **zapisują dane syntetyczne** w skonfigurowanej bazie:

```powershell
$baseUrl = 'http://127.0.0.1:8081'
$fixtureDir = 'services/backend/tests/fixtures'
Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/instruments" -ContentType application/json -Body (Get-Content -Raw "$fixtureDir/worker-instrument.synthetic.json")
Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/snapshots" -ContentType application/json -Body (Get-Content -Raw "$fixtureDir/worker-snapshot.synthetic.json")
$run = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/research-runs" -ContentType application/json -Body (Get-Content -Raw "$fixtureDir/worker-run.synthetic.json")
.\.venv\Scripts\python.exe -m alphasense.worker --once
Invoke-RestMethod "$baseUrl/v1/research-runs/$($run.run_id)"
Invoke-RestMethod "$baseUrl/v1/research-runs/$($run.run_id)/worker-job"
Invoke-RestMethod "$baseUrl/v1/research-runs/$($run.run_id)/events"
```

Przykład ma stałe UUID: identyczny retry jest idempotentny. W pustej kolejce daje jeden raport partial: przychód100, wynik netto25, marża0.25 oraz średnia z cen1,2,3 równa2. Są to wyłącznie wartości syntetyczne. Jeśli kolejka ma starsze zadania, `--once` wybierze najstarsze kwalifikujące się zadanie; tryb ciągły obsłuży kolejne. Odczyt worker-job przed pierwszym przejęciem zwraca404. Stare fixture `run.synthetic.json` i `snapshot.synthetic.json` nadal opisują manualny ledger i nie uruchamiają automatycznej analizy.

## Granice operacyjne

API i baza są lokalnym pilotem bez auth/RBAC. Actor jest deklaracją; token zabezpiecza współpracę procesów, nie zastępuje uprawnień użytkowników ani administratora DB. Nie udostępniać publicznie. Brak LLM oznacza zablokowaną syntezę, a brak danych może poprawnie zakończyć workflow raportem blocked. Ukończenie przebiegu nie oznacza kompletnego badania. Nie wykonujemy płatnych fallbacków, pobierania URL źródeł, kodu strategii ani zleceń.


Można wykonać wyłącznie wskazany przebieg: `python -m alphasense.worker --once --run-id UUID`. Inne zadania kolejki pozostają wtedy bez zmian. Pipeline `sec-fundamentals-v1` odczytuje trzy potwierdzone oryginały SEC; manualny i deterministyczny format pakietów pozostają obsługiwane.
