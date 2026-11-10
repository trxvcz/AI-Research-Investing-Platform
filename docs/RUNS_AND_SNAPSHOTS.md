# Trwałe przebiegi i surowe snapshoty — P1-02b2

Status: zaimplementowane i przetestowane lokalnie 2026-10-30. Migracja `0003_runs_snapshots` wykonana w bazie deweloperskiej Docker po pg_dump. [Weryfikacja](RUNS_SNAPSHOTS_VERIFICATION.md).

Ten dokument opisuje pipeline `manual-research-v1`. Dodany później [worker deterministyczny](AUTOMATIC_WORKER.md) obsługuje osobny, jawnie wybrany pipeline; poniższe ograniczenia ręcznego wykonania dotyczą manualnego rejestru.

Zakres: PostgreSQL ledger przebiegu i archiwum bajtów dostarczonych przez klienta. Nie jest to automatyczny worker, kolejka, scheduler, adapter źródła ani silnik analiz. Etapy są jawnymi deklaracjami operatora/wykonawcy; finalizacja sprawdza istniejący raport i jego provenance. Zero zewnętrznych pobrań, wywołań LLM i wykonywania kodu źródeł. Rejestr danych pozostaje synthetic/live bez fikcyjnych zer.

## Archiwum

SnapshotMetadata: schema_version=1.0, snapshot_id UUID, instrument_id UUID, data_origin synthetic/live, source_id SourceID, source_url InstrumentURL|null, license License, as_of Timestamp, available_at Timestamp|null, retrieved_at Timestamp, media_type (application/json,text/plain,text/csv,application/pdf,application/octet-stream), sha256 Sha256 i byte_length (1–1048576). Known available_at ≤ as_of i ≤ retrieved_at; unknown pozostaje null. Live wymaga URL. Brak pola ścieżki pliku; URL jest danymi, nie poleceniem pobrania.

SnapshotCreate dodaje content_base64: kanoniczny RFC4648 base64 (maks.1398104 znaków), po zdekodowaniu długość i SHA256 muszą zgadzać się z metadata. Nie parsujemy bajtów i nie serializujemy JSON ponownie. NUL w bajtach jest poprawny; kontrolne znaki ASCII w tekstowych metadanych są odrzucane jak w rejestrze. SnapshotRecord dodaje created_at serwera, SnapshotWrite createdbool. SnapshotPage: items metadata (maks.100), next_after_id UUID|null.

SnapshotStore(engine): create(SnapshotCreate)->SnapshotWrite; get(UUID)->SnapshotRecord; content(UUID)->tuple[SnapshotRecord,bytes]; list(instrument_id,after_id=None,limit=50)->SnapshotPage. get/list/download sprawdzają metadata i hash rzeczywistych bajtów; korupcja daje503. Identyczny retry ID jest idempotentny, zmienione metadata/bajty tego ID dają409. Te same bajty pod różnymi snapshot_id są dozwolone. Instrument musi istnieć, być spójny i mieć ten sam origin. Unknown availability można archiwizować, ale nie używać do przebiegu as-of.

POST /v1/snapshots →201/200; GET /v1/snapshots/{id}; GET /v1/snapshots/{id}/content →bytes tylko application/octet-stream, Content-Disposition attachment ze stałą nazwą UUID, nosniff; GET /v1/instruments/{id}/snapshots?after_id=&limit=. Limit ciała uploadu1500000 bajtów jest egzekwowany przed parsowaniem JSON (także chunked, bez zaufania Content-Length), przekroczenie413. Żadnych inline HTML/PDF previews.

raw_snapshots przechowuje metadata JSONB, content BYTEA i indeksowane snapshot_id/instrument_id/origin/source_id/as_of/available_at/retrieved_at/sha256/byte_length/created_at. Transakcja zapisuje je atomowo; brak częściowego pliku i brak niekontrolowanych ścieżek. Trigger sprawdza octet_length oraz encode(sha256(content),'hex'), tożsamość i metadata. UPDATE/DELETE/TRUNCATE są blokowane. Pilotażowy magazyn BYTEA ma ograniczony rozmiar; późniejsze object storage nie może zmienić hashy historii.

## Przebieg

Stały plan STEPS=(data,validate,fundamental,technical,report,review). Wersja pipeline_version='manual-research-v1'. RunCreate: action='create' (default), schema_version=1.0, run_id UUID, instrument_id UUID, as_of Timestamp, snapshot_ids list1–32 unikalnych UUID, pipeline_version (default powyżej). Walidowane snapshoty są zamrożone przy utworzeniu: ten sam instrument/origin, known available_at ≤ run.as_of, snapshot.as_of ≤ run.as_of. Rejestr nie jest historycznym uniwersum; origin pochodzi z katalogu. Wznowienie nie podmienia wejść.

RunState: run_id,instrument_id,as_of,snapshot_ids,pipeline_version,data_origin,sequence(1..2147483647),status(queued,running,failed,completed),current_step Step|null,completed_steps (dokładny prefiks STEPS),error_code SourceID|null,error_reason License|null,report_revision_id UUID|null,report_status ReportStatus|null,created_at i updated_at z serwera. Status completed/terminalfailed ma wszystkie etapy zakończone, current_step=null i raport; queued nie ma wykonanych etapów; pozostałe stany wskazują pierwszy niezakończony etap. Terminalne failed z raportem nie jest wznawialne.

RunCommand to unia po action. Wszystkie operacje mają request_id UUID (idempotency per run), expected_sequence, actor SourceID. Start(action=start) działa tylko queued. Advance(action=advance) ma step i kończy dokładnie current_step; nie kończy finalnego review. Fail(action=fail) ma step,error_code SourceID,reason License; tylko running i bieżący etap. Resume(action=resume) działa tylko failed bez finalnego raportu, wraca do tego samego etapu. Finish(action=finish) ma report_revision_id i działa tylko running/review; wiąże istniejącą rewizję raportu. Nie można przeskoczyć, powtórzyć zakończonego etapu ani dopisać zdarzenia po wyniku końcowym.

RunEvent: run_id,event_id UUID,sequence,kind(created/start/advance/fail/resume/finish),request (RunCreate albo RunCommand),state RunState,created_at Timestamp. Początkowe zdarzenie ma sequence1,event_id=run_id,kindcreated. Kolejne event_id=request_id. RunEventWrite dodaje createdbool; RunWrite to RunState+createdbool. RunEventPage items (maks.100),next_after_sequence int|null. ResearchStore(engine): create(RunCreate)->RunWrite, get(UUID)->RunState, apply(run_id,RunCommand)->RunEventWrite, events(run_id,after_sequence=0,limit=50)->RunEventPage.

Zmiany są append-only: research_runs (run_id PK,instrument_id FK,as_of,definition JSONB,created_at), run_snapshots(run_id FK,snapshot_id FK,PKpary), run_events(run_id FK,event_id,sequence,kind,request JSONB,state JSONB,created_at;PK run_id/sequence,UNIQUE run_id/event_id,optional report_revision_id FK). Lock research_runs FOR UPDATE serializuje create/commands. expected_sequence jest optimistic compare-and-swap; identyczny request_id+request zwraca istniejące zdarzenie nawet po dalszym postępie, zmieniony request lub stary sequence daje409. Nie ma leases, fencing ani background retry; to kontrolowany ledger, nie rozproszony executor. Readiness nie uruchamia migracji.

Finalizacja weryfikuje ReportRevision pełnym walidatorem, instrument_id, as_of i origin. Każde źródło raportu musi należeć do zamrożonych snapshotów i mieć dokładnie source_id,snapshot_id=str(UUID),sha256,source_url/retrieved_at/license z archiwum. Raport może wykorzystać podzbiór wejść (np.blocked bez liczb); pozostałe bajty nadal są w audycie przebiegu. Wynik report.status jest jawny; failed raport daje terminalny status failed, pozostałe completed z oddzielnym report_status partial/blocked/complete. Zakończenie workflow nie gwarantuje kompletności badania.

Konserwatywna bramka pilota: observation.available_at nie może poprzedzać available_at wskazanego snapshotu. Wcześniejszej historycznej dostępności liczby nie wyprowadzamy z późniejszego zbiorczego pliku — wymaga osobnego, właściwie udokumentowanego snapshotu/filingu. Same metadane klienta nie certyfikują historii; created_at archiwum jest rzeczywistym czasem zapisu lokalnego, a retrieved_at/available_at pozostają deklaracjami do weryfikacji przez przyszły adapter.

POST /v1/research-runs →RunWrite 201/200; GET /v1/research-runs/{id}; POST /v1/research-runs/{id}/events (RunCommand) →RunEventWrite201/200; GET /v1/research-runs/{id}/events?after_sequence=0&limit=50. Brak aktywnego workera oznacza, że nowy przebieg pozostaje queued, dopóki operator/wykonawca nie zapisze polecenia.

## DB, bezpieczeństwo i odbiór

Migracja0003_runs_snapshots jest addytywna; nie przepisuje instrumentów i raportów. Nowe tabele mają append-only triggery, FK, kontrolę metadanych/ciągłości sekwencji. Pełne semantyczne przejścia sprawdza aplikacja. Downgrade blokuje wszystkie nowe tabele przed kontrolą i odmawia, jeśli którakolwiek ma dane. Admin DB może wyłączyć zabezpieczenia; produkcja wymaga auth/RBAC i oddzielnej roli runtime. Błędy 404/409/422/503 nie odbijają treści ani DSN.

Testy: dokładne bajty (w tym whitespace/NUL/nonUTF8), hash/limity/atomowość, idempotencja i konflikty, unknown/future availability, zamrożone wejścia, kolejność etapów, fail/resume po nowym engine, CASrównoległość, finalizacja/provenance, niezmienność historii, migracja zachowująca dane0002 oraz backup/restore całego zestawu. Bez PostgreSQL testy integracyjne są jawnie pominięte, nie zastąpione SQLite. Nie wysyłamy danych do żadnego dostawcy.

## Uruchomienie i przykład syntetyczny

API korzysta z tego samego ALPHASENSE_DATABASE_URL co rejestr i raporty. Na tym komputerze migracja już działa; na innym stanowisku należy jawnie wykonać `python -m alembic upgrade head` po kopii bazy. Start opisuje [BACKEND](BACKEND.md). Bez DSN operacje DB dają503, a walidatory stateless pozostają dostępne.

Przykład **zapisuje syntetyczne dane** do lokalnej bazy. Nie jest analizą spółki ani weryfikacją rzeczywistego źródła:

```powershell
$baseUrl = 'http://127.0.0.1:8081'
$instrument = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/instruments" -ContentType application/json -Body (Get-Content -Raw services/backend/tests/fixtures/instrument.synthetic.json)
$snapshot = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/snapshots" -ContentType application/json -Body (Get-Content -Raw services/backend/tests/fixtures/snapshot.synthetic.json)
$run = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/research-runs" -ContentType application/json -Body (Get-Content -Raw services/backend/tests/fixtures/run.synthetic.json)
Invoke-RestMethod "$baseUrl/v1/research-runs/$($run.run_id)"
```

Pliki przykładowe mają ustalone UUID i są zgodne ze sobą. Powtórzenie identycznej rejestracji/uploadu/utworzenia przebiegu jest idempotentne; nowy eksperyment wymaga nowego run_id. Nowy przebieg ma status queued i nie wykonuje obliczeń samodzielnie.

Jawny zapis rozpoczęcia (gdy status queued):

```powershell
$command = @{action='start'; request_id=[guid]::NewGuid().ToString(); expected_sequence=$run.sequence; actor='local-operator'}
$event = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/research-runs/$($run.run_id)/events" -ContentType application/json -Body ($command | ConvertTo-Json)
$state = $event.state
Invoke-RestMethod "$baseUrl/v1/research-runs/$($run.run_id)/events?limit=20"
```

Advance deklaruje zakończenie dokładnie current_step przez operatora/wykonawcę; nie uruchamia algorytmu. Fail zapisuje error_code i reason, resume wraca do tego samego etapu. Każda nowa komenda wymaga nowego request_id i aktualnej expected_sequence. Retry po niepewnym wyniku używa oryginalnego request_id oraz identycznej treści, bez zmiany sekwencji w tym żądaniu. Po konflikcie najpierw odczytać aktualny run. System nie ma jeszcze leases, workera ani automatycznego retry.

Finish wymaga running/review i istniejącej rewizji raportu z tym samym instrumentem/as_of/origin oraz źródłami zgodnymi z archiwum. Stary `report.synthetic.json` ma legacy ID instrumentu i snapshotu, więc nie należy wiązać go z tym przykładem bez jawnego mapowania i ponownego seal_report. Raport oraz liczby musi przygotować osobny, zweryfikowany moduł; ledger ich nie wymyśla.

Pobranie oryginalnych bajtów: GET `/v1/snapshots/{snapshot_id}/content`. Odpowiedź ma zawsze tryb attachment i application/octet-stream, niezależnie od zadeklarowanego media_type. Limit 1 MiB nie obcina pliku: większy upload jest odrzucany. Unknown available_at jest archiwizowalne, ale blokuje użycie w run; nie zastępujemy go czasem pobrania lub datą filed.
