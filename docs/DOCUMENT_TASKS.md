# Trwałe zadania dokumentów

Osobna kolejka PostgreSQL i proces `alphasense.document_task_worker` wykonują pracę niezależnie od otwartego panelu. Bieżący tryb `validate_saved_draft` odtwarza deterministyczną weryfikację dokumentu i szkicu z istniejącego archiwum. Nie generuje nowych faktów przez LLM. Jest wspólny dla formatów text/HTML/XLSX i nie zawiera reguł dla poszczególnych spółek.

## Co można zlecić

W sekcji „Szkice z dokumentów” otwórz zapisany dokument i wybierz „Zleć weryfikację w tle”. Najpierw trzeba zaimportować dokument i zapisany szkic; ten przyrost nie przyjmuje samego dokumentu do automatycznej ekstrakcji. Monitor „Kolejka dokumentów” pokazuje stan, etap, numer próby, ostatni sygnał wykonawcy, historię i audyt.

`POST /v1/panel/document-tasks` przyjmuje `job_id`, `archive_id` i opcjonalny `mode`. Domyślny tryb to `validate_saved_draft`. Ponowienie z tym samym UUID i żądaniem zwraca istniejące zadanie; inny dokument lub tryb pod tym UUID daje 409. Nowy UUID oznacza osobny przebieg, także dla tego samego dokumentu. HTTP zapisuje intencję i nie uruchamia workera ani dostawcy. Stosuje dotychczasową ochronę lokalnego panelu (Origin, host, JSON i nagłówek panelu); body komendy ma limit 16 KiB przed parsowaniem.

`GET /v1/panel/document-tasks?after_id=UUID&limit=50` udostępnia stronę zadań. `GET /v1/panel/document-tasks/{job_id}` zwraca zadanie, etapy i audyty prób. Odczyty używają spójnego obrazu transakcji, aby zmiana etapu w trakcie odpowiedzi nie wyglądała jak uszkodzenie danych.

Panel sam odświeża widoczną stronę najwyżej 30 razy, co 5 sekund, gdy zawiera niezakończone zadania. Zatrzymuje odczyty po błędzie lub zakończeniu pracy; można jawnie odświeżyć ponownie. Próba zapisu zachowuje UUID w pamięci widoku. Po przeładowaniu strony należy najpierw sprawdzić kolejkę przed osobnym zleceniem.

## Granica użycia modeli

Tryb kontraktowy `model_extract` jest nieaktywny: worker kończy go stanem blocked i kodem `MODEL_EXECUTION_DISABLED`. Nie istnieje tu adapter wykonawczy, ładowanie klucza ani płatny fallback. Formularz panelu zleca wyłącznie weryfikację offline. Nie zmieniono `provider-policy.json`, a poprzednia jednorazowa zgoda na pilot Gemini nie jest zgodą operacyjną.

Audyt uczciwie zapisuje `provider_called=false`, koszt wywołań API `0`, a model, prompt, hashe odpowiedzi dostawcy i tokeny jako null/nie dotyczy. Nie są to pomiary wykorzystania modelu ani całkowitego kosztu infrastruktury. Historyczny `provider_id` wewnątrz walidowanego szkicu jest deklaracją z importu, nie nowym wywołaniem.

Pełna ekstrakcja LLM wymaga kwalifikacji modelu i polityki danych, zaakceptowanego budżetu lub dopuszczonego bezpłatnego projektu oraz osobnego kontraktu rzeczywistych żądań, odpowiedzi i rozliczenia. Obecny audyt dotyczy wykonania offline oraz jawnej odmowy wywołania modelu; nie zastępuje tego przyszłego kontraktu.

## Trwałość, czas i audyt

Migracja `0011_document_tasks` dodaje stan `document_tasks` i dopisywane tabele `document_task_events` oraz `document_task_audits`. Źródłem jest niezmienny wpis archiwum, zachowujący oryginał, szkic oraz deklarowane `source_available_at` i `as_of`. Zadanie wiąże UUID źródła i hashe dokumentu, szkicu oraz kanonicznego wejścia `{packet, draft_json}`. Zmiany decyzji recenzenta nie zmieniają wejścia tego przebiegu.

Worker przechodzi przez queued → reading → validating → archiving → completed. Zakończenie pracy oznacza wykonanie weryfikacji; sam wynik może pozostać needs_review albo rejected. Nie tworzy nowej oceny recenzenta, obserwacji available lub raportu. Oryginalny szkic i wcześniejsze decyzje pozostają zachowane.

Każda próba ma czas rozpoczęcia i zakończenia, wykonawcę, wynik, błąd, hash implementacji i wejścia oraz hash ustrukturyzowanego wyniku, jeśli powstał. Fingerprint obejmuje rzeczywiste pliki workera, magazynu i walidatora, zamiast utożsamiać niezacommitowaną zmianę z HEAD. Hash wejścia nie jest hashem wysłanego promptu, ponieważ prompt nie został wysłany.

Claim korzysta z blokad PostgreSQL i SKIP LOCKED. Wykonawca ma losowy token i czasowe uprawnienie; heartbeat je odnawia. Zapis etapu i zakończenia sprawdza aktualne uprawnienie, również na końcu transakcji. Stary wykonawca nie może opublikować wyniku po przejęciu zadania. Przerwana próba otrzymuje audyt interrupted; po wygaśnięciu uprawnienia dopuszczone są najwyżej trzy próby offline, a następnie failed/RECOVERY_EXHAUSTED. Zwykły błąd lub odmowa modelu jest terminalna i nie powoduje automatycznego ponowienia.

Wejście i terminalny stan zadania są zamrożone, wydarzenia oraz audyty są append-only. Triggery blokują usunięcie i TRUNCATE historii. Downgrade odmówi usunięcia niepustej kolejki i używa NOWAIT także na referencjonowanym archiwum, aby nie czekać niejawnie na blokadę FK. Odczyt sprawdza hashe i zgodność historii; wykryta niezgodność daje redagowany błąd magazynu.

## Start lokalny

Po jawnej migracji i z ustawionym `PYTHONPATH=services/backend/src` oraz `ALPHASENSE_DATABASE_URL`:

```powershell
.venv/Scripts/python.exe -m alphasense.document_task_worker --once
.venv/Scripts/python.exe -m alphasense.document_task_worker --forever --worker-id local-document-worker
```

`Start-DocumentWorker.ps1` uruchamia osobny proces w tle i zapamiętuje PID pod `.local-postgres`. Ponowne wywołanie nie uruchamia drugiego, jeśli zapisany proces tego projektu nadal działa. `Start-Panel.ps1` uruchamia go obok dotychczasowego task workera. Sam serwer HTTP nie uruchamia wykonawcy. Nie jest to supervisor zapewniający autostart po restarcie systemu ani gotowe wdrożenie VPS; auth/TLS i operacyjny nadzór pozostają osobnym etapem.

## Odbiór

Odbiór 2026-11-10: **1069 Python PASS** w jednym pełnym przebiegu (277,44 s), panel **40/40 PASS**, Node **9/9 PASS**, TypeScript/Vite build, Ruff, format (104 pliki), mypy (55 modułów), schematy i OpenAPI PASS. Jedno ostrzeżenie deprecacyjne Starlette/httpx, bez błędów. Niezależny QA bez pozostałych blokerów po poprawkach spójności odczytu i klucza odświeżania audytu w UI.

Testy obejmują współbieżne claim, wygasanie i fencing, przerwane próby, terminalną niezmienność, ochronę SQL historii, błędne hashe, idempotentne żądania i Origin, spójny odczyt podczas zmiany etapu oraz wykonanie w niezależnym procesie. Test pg_dump/restore zachował zadanie z aktywną próbą i po odtworzeniu wznowił je jako próbę 2 z audytem interrupted/completed, bez utraty dokumentu i wcześniejszych decyzji.

Migracja zastosowana na lokalnej bazie Docker: head `0011_document_tasks`. Liczby istniejących instrumentów, raportów, przebiegów, snapshotów, importów, dokumentów i decyzji pozostały identyczne. Backupy publicznego schematu: `.local-postgres/backups/before-document-tasks-20261110T101621Z.dump` oraz `after-document-tasks-20261110T102157Z.dump`; listy zawartości sprawdzone. Kopie pozostają lokalne i ignorowane przez Git.

Przycisk w przeglądarce zlecił weryfikację jawnie syntetycznego dokumentu. Zadanie `a8018cdf-7eda-4409-b1db-6212a01cd1dd` pozostało queued po restarcie API, identyczne ponowienie nie utworzyło duplikatu, a osobny proces CLI zakończył je jako completed z pięcioma etapami i jednym audytem. Wynik zawiera 12500000 PLN i nadal wymaga przeglądu semantycznego. Przegląd w przeglądarce potwierdził wyświetlenie historii i rozwiniętego audytu. Dodatkowe zadanie tej samej próbki w trybie model_extract zakończyło się blocked/MODEL_EXECUTION_DISABLED z `provider_called=false`.

Uruchomiono lokalny worker przez `Start-DocumentWorker.ps1`; dwukrotne wywołanie skryptu zachowało ten sam żywy proces. `/ready`, `/panel/` i istniejący raport GOOGL zwracają 200 po migracji i odbiorze. Bez nowych wywołań Gemini oraz bez zmiany uprawnień do płatnych wywołań. Nie deklarujemy odbioru ekstrakcji nowego dokumentu przez LLM ani wdrożenia na VPS.
