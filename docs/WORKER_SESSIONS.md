# Rejestr wykonawców i historii procesów

Rejestr pokazuje sygnały procesów SEC i weryfikacji dokumentów również wtedy, gdy kolejka jest pusta. Jest oddzielony od lease zadań, wyników analiz i użycia modeli. „Sygnał aktualny” znaczy wyłącznie, że proces niedawno zapisał kontakt z PostgreSQL; nie dowodzi poprawnego ukończenia zadania ani pracy LLM.

## Sesje i obserwacje

Każdy start CLI tworzy nowy losowy UUID sesji, nazwę logiczną wykonawcy, rodzaj, tryb once/forever, PID, hash plików runtime i czas startu. Restart nie nadpisuje wcześniejszej sesji. Nazwa logiczna może wystąpić w wielu sesjach; rejestr nie jest mechanizmem wyboru jednego właściciela zadań i nie zastępuje ich fencing.

Proces zapisuje heartbeat co 10 sekund, niezależnie od tego, czy czeka, czy wykonuje pracę. Czas jest wyznaczany przez bazę, a stan wyliczany podczas odczytu:

- online — brak zakończenia i od ostatniego sygnału minęło mniej niż 45 sekund;
- stale — brak zakończenia i upłynęło co najmniej 45 sekund, także dokładnie na granicy;
- stopped — proces zapisał zakończenie, niezależnie od wieku ostatniego sygnału.

Stale oznacza brak świeżego kontaktu, nie potwierdzoną śmierć procesu. Nowy sygnał tego samego procesu może przywrócić online. Zakończona sesja jest niezmienna i nie może wznowić kontaktu. PID ma znaczenie na maszynie wykonawcy, nie jest zdalnym poleceniem sterującym procesem.

Powód completed opisuje normalne zakończenie procesu, także `--once` bez znalezionego zadania. Interrupted oznacza obsłużony KeyboardInterrupt; error przechowuje wyłącznie stały kod WORKER_RUNTIME_FAILED albo WORKER_MONITOR_FAILED. Wyjątki, dokumenty, klucze i connection stringi nie są treścią rejestru. O wyniku konkretnego zadania informuje jego kolejka.

## Integracja runtime

Wspólny `WorkerSessionMonitor` obejmuje oba wejścia CLI po sprawdzeniu gotowości bazy i przed pierwszym pobraniem zadania. Jeśli rejestracja się nie powiedzie, proces nie rozpoczyna pracy. Niepowodzenie późniejszego heartbeat zatrzymuje pobieranie kolejnych zadań po powrocie bieżącej operacji; nie odbiera praw do trwającego zadania, które chronią osobne lease.

Przy wyjściu monitor zatrzymuje wątek i próbuje zapisać powód zakończenia. Jeśli heartbeat utknął lub baza jest niedostępna, nie udaje poprawnego zamknięcia; sesja może przejść w stale. Błąd zapisu zakończenia nie zastępuje pierwotnego wyjątku jego treścią. Nagłe zabicie procesu nie zapisuje fikcyjnego stopped.

To obserwowalność, nie supervisor. Nie dodano automatycznego restartowania, schedulera, zdalnego kill/restart ani kontroli VPS. Auth/TLS i autostart po restarcie systemu pozostają osobnymi zadaniami.

## Magazyn i API

Migracja `0012_worker_sessions` dodaje jedną tabelę. Tożsamość i start sesji są zamrożone; heartbeat jest aktualizowany monotonicznie, zakończenie zapisuje się raz. Triggery blokują zmianę zakończonej sesji, usuwanie i TRUNCATE. Downgrade odmawia usunięcia niepustej historii i używa NOWAIT. Nie zapisujemy każdego heartbeat jako osobnego wydarzenia, aby rejestr nie rósł od bezczynności.

`GET /v1/panel/workers?kind=document_validation&after_id=UUID&limit=50` zwraca sesje, wspólny czas obserwacji i próg 45 sekund. Filtr rodzaju jest opcjonalny; drugi rodzaj to sec_import. Strony są uporządkowane po UUID, nie po dacie. `GET /v1/panel/workers/{session_id}` odczytuje jedną sesję. Brak endpointów zapisu lub sterowania. Odczyt wyznacza czas obserwacji po pobraniu wierszy, aby równoległy heartbeat nie wyglądał jak sygnał z przyszłości.

## Panel

Sekcja „Rejestr wykonawców” pokazuje sygnał, rodzaj procesu, nazwę, PID, start, koniec, powód i szczegóły sesji. Domyślnie odświeża co 5 sekund, także dla pustej strony lub bezczynnych wykonawców, maksymalnie 30 odczytów. Można wstrzymać i wznowić podgląd. Błąd zatrzymuje automatyczne odczyty.

Nieaktualna obserwacja nie utrzymuje oznaczenia online. W trakcie odczytu, po błędzie, pauzie, wyczerpaniu limitu lub upływie ważności kontaktu panel pokazuje „Stan nieaktualny”. Do wyznaczenia upływu czasu używa zegara monotonicznego przeglądarki oraz czasu serwera, a nie daty ustawionej na komputerze użytkownika. Historyczne stale/stopped pozostają opisem wskazanej obserwacji. Widok ma jawny czas obserwacji; pusta strona nie dowodzi braku sesji na innych stronach.

## Odbiór

Odbiór 2026-11-10: **1110 Python PASS** w jednym pełnym przebiegu (421,97 s), panel **46/46 PASS**, Node **9/9 PASS**, TypeScript/Vite build, Ruff, format (111 plików), mypy (59 modułów), schematy i OpenAPI PASS. Jedno ostrzeżenie deprecacyjne Starlette/httpx, bez błędów. Końcowy przegląd bezpieczeństwa i integracji wykonał koordynator; niezależna recenzja podagenta QA nie została ukończona z powodu limitu użycia, więc nie deklarujemy jej zaliczenia.

Testy obejmują dokładną granicę 45 sekund, wznowienie kontaktu stale, niezmienność zakończonej sesji, idempotencję start/stop, wyścig heartbeat i stop, błędne metadane, ochronę SQL i read-only API, rejestrację przed pobraniem zadania, reakcję na awarię monitora oraz brak treści wyjątków w rejestrze. Test pg_dump/restore zachował zakończoną sesję wraz z jej tożsamością, czasami i powodem zakończenia.

Migracja `0012_worker_sessions` została zastosowana na lokalnej bazie Docker po backupie; liczby istniejących instrumentów, raportów, przebiegów, snapshotów, importów, dokumentów, decyzji, zadań dokumentowych i ich audytów pozostały identyczne. Kopie publicznego schematu są w ignorowanym katalogu: `.local-postgres/backups/before-worker-sessions-20261110T120753Z.dump` oraz `after-worker-sessions-20261110T121601Z.dump`; sprawdzono listy zawartości.

Rzeczywisty odbiór: oba lokalne workery po restarcie zarejestrowały osobne sesje i odnawiały heartbeat podczas bezczynności. Kontrolny proces `acceptance-clean-session` zakończył się normalnie jako stopped/completed. Proces `acceptance-abrupt-session` zakończony bez zapisu końca przeszedł po 45 sekundach w stale, zachowując stopped_at=null. Te dwie jawnie testowe sesje pozostają w historii. Działające procesy SEC i dokumentów nadal mają online; `/ready`, `/panel/` i wcześniejszy raport GOOGL zwracają 200.

Odbiór w przeglądarce potwierdził trzy stany. Po wstrzymaniu podglądu aktualne sygnały zmieniły opis na „Stan nieaktualny”; po wznowieniu i nowym odczycie odzyskały „Sygnał aktualny”. W tym przyroście brak nowych wywołań modeli i brak zmiany polityki bezpłatnych źródeł. VPS, supervisor i scheduler pozostają do wykonania.
