# Historia importów SEC i scheduler

Zmiany etapów kolejki SEC są dopisywane do trwałej historii, a osobny proces schedulera zamienia terminy wybrane przez użytkownika w zlecenia importu i analizy. Scheduler nie pobiera danych, nie wykonuje modeli i nie publikuje raportów. Dotychczasowy worker SEC nadal egzekwuje politykę źródła, pacing i quota.

## Historia etapów

Migracja `0013_import_task_events` dodaje append-only `import_task_events`. Trigger zapisuje zdarzenie w tej samej transakcji co utworzenie lub istotna zmiana zadania: status, etap, próba, wykonawca, błąd lub powiązanie instrumentu/raportu. Sam heartbeat, przedłużenie lease i aktualizacja czasu nie tworzą fikcyjnego nowego etapu. Zdarzenia nie zawierają tokenu lease ani surowego żądania do dostawcy.

Nowe zadanie zaczyna od `created`, później ma `transition`. Istniejące zadania otrzymują jeden `legacy_snapshot` stanu znanego w chwili migracji. Nie rekonstruujemy ich dawnych etapów ani czasów. Panel oznacza tę historię jako niepełną.

`GET /v1/panel/tasks/{run_id}/events?after_sequence=0&limit=100` udostępnia kolejne zdarzenia i informację o pokryciu historii. Odczyt ma spójny snapshot transakcji, sprawdza ciągłość i tożsamość danych oraz zgodność ostatniej istotnej zmiany z bieżącym stanem zadania. Historia ma limit ochronny 10000 zdarzeń podczas weryfikacji. Trigger blokuje UPDATE, DELETE i TRUNCATE, a downgrade odmawia usunięcia niepustej historii. Migracja blokuje zapisy kolejki z NOWAIT na czas utworzenia migawki i triggerów, aby nie powstała luka w historii.

W „Zadania i wykonawcy” wybierz „Historia etapów”. Zakończone zlecenie wskazuje dokładny raport i rewizję; samo przejście do importu lub analizy nie oznacza powodzenia.

## Harmonogramy

Formularz „Harmonogramy analiz SEC” przyjmuje symbol, Nasdaq/NYSE, pierwszy termin ze strefą oraz odstęp. Kontrakt dopuszcza 3600–2592000 sekund, a formularz 1–720 pełnych godzin. To stałe odstępy czasu, liczone względem pierwszego terminu w UTC; nie jest to kalendarz „codziennie o danej lokalnej godzinie” zmieniający się wraz z DST.

Nowy harmonogram w formularzu jest wstrzymany. Włącz go osobno, po sprawdzeniu konfiguracji. Domyślnie `refresh=false`: importer korzysta z zaufanego archiwum i pobiera brakujące źródła. Opcja „Pobieraj nowe dane SEC w limitach” ustawia `refresh=true`; nie wolno utożsamiać ponownej analizy archiwum z pobraniem aktualnych danych. Czas dostępności źródeł pozostaje w raporcie.

Symbol i rynek są raz rozwiązywane z lokalnego katalogu lub istniejącej ścieżki pilota. Harmonogram zamraża CIK, instrument, MIC, pipeline, pojęcie przychodu oraz tryb odświeżania. Tworzenie nie odświeża katalogu i nie wywołuje SEC. Ponowienie tego samego UUID korzysta z zamrożonej tożsamości, także po zmianie katalogu.

Włączanie i pauza to dopisywane komendy z UUID i oczekiwaną rewizją. Utrata odpowiedzi pozwala powtórzyć tę samą komendę; stary widok otrzymuje 409 i wymaga odświeżenia. Nie zmieniamy historii. Odstęp, pierwszy termin i tożsamość są niezmienne: dla innej konfiguracji utwórz nowy harmonogram i wstrzymaj stary. Nie ma usuwania historii.

## Dispatch i przerwy

`alphasense.sec_scheduler` sprawdza terminy w osobnym procesie. Jeden termin jest zapisywany transakcyjnie razem z zadaniem, potwierdzeniem i kolejną datą. Identyfikator zadania to UUID5 harmonogramu i terminu w UTC. Restart lub dwa równoczesne procesy nie tworzą dwóch zleceń tego samego terminu. Batch obejmuje najwyżej 20 harmonogramów, ale transakcja dotyczy jednego harmonogramu — wcześniej zatwierdzone pozycje pozostają trwałe, jeśli późniejsza operacja się nie powiedzie.

Po dłuższej przerwie obsługiwany jest tylko ostatni należny termin, a liczba wcześniejszych pominiętych terminów jest zapisywana w `skipped_slots`. Nie odtwarzamy całej zaległej kolejki. Jeżeli w chwili decyzji istnieje już zadanie queued/running tego instrumentu, termin otrzymuje `skipped_busy` i nie tworzy nowego zadania. Kolejny termin jest przesuwany również przy takim pominięciu. Ręczne, jawne zlecenie użytkownika może powstać później; scheduler nie zakazuje pracy ręcznej.

Zwykły błąd źródła nie jest ponawiany w ramach tego samego zadania. Następny włączony termin jest osobnym zleceniem według ustalonej częstotliwości. Pauza nie anuluje zadania już zapisanego w kolejce. Scheduler nie resetuje limitów, nie odnawia wygasłej polityki źródła i nie uruchamia płatnego fallbacku. Brak wymaganych dopuszczeń lub dostępnej quota może zablokować import w workerze.

Daty `scheduled_for` i `dispatched_at` opisują harmonogram, nie udają historycznego czasu pozyskania danych. Raport używa rzeczywistych dowodów i dat dostępności źródeł. Zapis zlecenia nie oznacza ukończonej analizy.

## API i uruchomienie

- `POST /v1/panel/schedules` — zapis harmonogramu; domyślnie disabled/bez wymuszonego odświeżania.
- `GET /v1/panel/schedules?after_id=UUID&limit=50` — strona konfiguracji.
- `GET /v1/panel/schedules/{schedule_id}` — zamrożona konfiguracja i stan.
- `POST /v1/panel/schedules/{schedule_id}/commands` — włączanie/pauza z kontrolą rewizji.
- `GET /v1/panel/schedules/{schedule_id}/occurrences?after_sequence=0&limit=50` — potwierdzenia terminów i pominięcia.

Zapisy wymagają dotychczasowego lokalnego Origin i nagłówka panelu, JSON oraz limitu body 16 KiB. Nie jest to autoryzacja dla publicznego VPS. Odczyty list mają spójny snapshot. Weryfikacja stanu harmonogramu korzysta z agregatów i ostatniego potwierdzenia, bez ponownego sprawdzania każdego dawnego zadania; paginowane potwierdzenia weryfikują ograniczoną stronę. Agregacja nadal wymaga pracy liniowej względem historii po stronie bazy.

Migracja `0014_sec_schedules` dodaje konfiguracje, komendy i potwierdzenia oraz dopuszcza rodzaj procesu `sec_scheduler` w rejestrze. Chroni niezmienność konfiguracji i historii oraz odmawia downgrade z niepustą historią. Przed DROP blokuje także referencjonowane tabele z NOWAIT.

```powershell
$env:PYTHONPATH='services/backend/src'
.venv/Scripts/python.exe -m alphasense.sec_scheduler --once
.venv/Scripts/python.exe -m alphasense.sec_scheduler --forever --worker-id local-sec-scheduler
```

Wymagany jest skonfigurowany `ALPHASENSE_DATABASE_URL`. `Start-SecScheduler.ps1` uruchamia proces w tle i chroni przed powieleniem procesu przez ten sam launcher. `Start-Panel.ps1` uruchamia go obok workerów. Scheduler zapisuje heartbeat również podczas bezczynności. Sam serwer HTTP nie dispatchuje terminów.

Panel ogranicza automatyczne odczyty do 30, zatrzymuje je po błędzie i pozwala jawnie odświeżyć. Nierozstrzygnięte żądania zachowują UUID w pamięci widoku; po przeładowaniu sprawdź listę przed utworzeniem osobnej operacji.

## Odbiór

Odbiór 2026-11-10: **1153 Python PASS** w jednym pełnym przebiegu (205,68 s), panel **53/53 PASS**, Node **9/9 PASS**, TypeScript/Vite build, Ruff, format (119 plików), mypy (63 moduły), schematy i OpenAPI PASS. Jedno ostrzeżenie deprecacyjne Starlette/httpx, bez błędów. Niezależny przegląd schedulera i frontendu nie znalazł pozostałych P1/P2; uwaga o odczycie całej historii została poprawiona i objęta testem ograniczonej liczby zapytań dla 30 terminów.

Testy obejmują pełną historię nowego zadania, brak zdarzeń od heartbeat, odzyskiwanie próby i odrzucenie starego właściciela, legacy backfill, niezmienność SQL, rollback zlecenia z historią, równoległy dispatch, pominięcie zajętego instrumentu, ograniczone nadrabianie, terminy przyszłe/wstrzymane, pause/resume i idempotentne ponowienia po zmianie katalogu. Koordynator zweryfikował, że dispatcher nie uruchamia importera. Test pg_dump/restore zachował harmonogram, potwierdzenie terminu, zadanie i jego historię; po odtworzeniu nie powstał duplikat terminu i można było idempotentnie wstrzymać harmonogram.

Migracje zastosowano na lokalnej bazie Docker: head `0014_sec_schedules`. Dotychczasowe instrumenty, raporty, przebiegi, snapshoty, importy, dokumenty, decyzje, zadania dokumentowe, audyty i sesje pozostały zachowane; sprawdzono liczby wierszy. Backupy publicznego schematu: `.local-postgres/backups/before-sec-schedules-20261110T123908Z.dump` i `after-sec-schedules-20261110T124335Z.dump`; listy zawartości sprawdzone, pliki pozostają ignorowane przez Git.

Rzeczywisty odbiór lokalny: wcześniejsze zadanie Apple ma pojedynczy legacy_snapshot z chwili migracji, bez wymyślonej historii. Przeglądarka potwierdziła ostrzeżenie o niepełnym pokryciu oraz formularz domyślnie wstrzymanego harmonogramu z odświeżaniem wyłączonym. Tworzenie i sterowanie konfiguracją sprawdzono przez testy API/UI; nie zapisywano arbitralnego harmonogramu wybranej za użytkownika spółki w głównej bazie.

Scheduler działa w tle jako trzeci rodzaj wykonawcy, a ponowne wywołanie launchera zachowało ten sam proces. Przy końcowym odczycie trzy procesy mają aktualny heartbeat, lista harmonogramów pozostaje pusta, `/ready`, `/panel/` i wcześniejszy raport GOOGL zwracają 200. Bez nowych pobrań SEC i wywołań modeli w ramach odbioru. Publiczne wdrożenie VPS, auth/TLS i supervisor pozostają do wykonania.
