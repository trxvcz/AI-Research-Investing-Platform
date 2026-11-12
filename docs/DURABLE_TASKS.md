# Trwałe zadania i nadzór wykonania

Pierwszy przyrost pod samodzielną platformę: API zapisuje zlecenie przed pobraniem danych. Import i obliczenia wykonuje osobny proces, a stan jest przechowywany w PostgreSQL. To nie jest pełny system wielorynkowy ani gotowe wdrożenie VPS.

POST `/v1/panel/tasks` przyjmuje symbol i UUID przebiegu, zwraca rekord zadania. Odczyty listy i konkretnego zadania są dostępne przez GET. Ponowienie tego samego UUID z tą samą tożsamością nie tworzy duplikatu. Zmiana symbolu przy tym UUID jest konfliktem. Wybrana tożsamość emitenta i pipeline są zamrażane przy przyjęciu zlecenia.

Wykonawca przejmuje zadanie czasową dzierżawą, utrzymuje heartbeat i publikuje wynik tylko przy zachowaniu aktualnego uprawnienia. Restart API nie usuwa kolejki. Zadanie porzucone przez przerwany proces może zostać ponownie przejęte; liczba przejęć jest ograniczona. Błąd dostawcy/polityki jest widoczny jako błąd zadania i nie uruchamia nieograniczonej pętli zapytań.

Panel pokazuje rzeczywiste zadania, etapy import/analiza, heartbeat, identyfikator wykonawcy i błędy. Nie sugeruje, że działają modele LLM, predykcje lub niezależni agenci ról, których jeszcze nie wdrożono.

## Uruchamianie lokalne

`Start-TaskWorker.ps1` uruchamia osobny proces w tle. `Otworz panel.cmd` wywołuje go wraz z panelem. Zapisany PID i rozpoznanie nazwy wykonawcy ograniczają przypadkowe wielokrotne uruchomienia na tym stanowisku. Kolejka i lease pozostają źródłem prawdy, nawet gdy uruchomionych jest wiele procesów. Sam skrypt nie jest usługą systemową i nie gwarantuje autostartu po restarcie Windows.

Docelowo VPS wymaga supervisor/systemd lub kontenerów z restart policy, auth/TLS i prywatnej bazy, monitoringu oraz testu restore. Ten przyrost nie wystawia serwera publicznie. Źródła i limity free-only nadal obowiązują również w tle; brak darmowych danych lub zgody blokuje wykonanie.

## GPW i predykcje

Oddzielne rozpoznanie źródeł GPW jest w docs/sources/GPW_DISCOVERY.md. GPW, ceny i predykcje nie są dodawane przez samą kolejkę. Do uruchomienia modeli potrzebne są kontrakty świec/prognoz, dopuszczenie danych, testy jakości i kosztów.

## Odbiór lokalny2026-11-09

Po backupie `.local-postgres/backups/before-tasks-20261109.dump` (273153b, SHA256ae4bff62d7a5932a94633946535f06917cf19e52c2f97660802a03a315b99be0) zastosowano migrację0009_import_tasks.

Zadanie1516c178-810f-4bcc-bd97-23f995b12b3c/AAPL zwróciłoqueued iattempt0 przed wykonaniem. Po restarcie procesuAPI nadalqueued. Osobny `alphasense.task_worker --once --worker-id acceptance-worker` wykonał je na trustedcache, bez zapytańSEC. Wynikcompleted, attempt1, heartbeat, worker_idacceptance-worker, raport65bec960-5491-5e99-aa57-d7adc38584b0 revision1. Terminalne zadanie zachowuje historię tożsamości i wyniku.

Przegląd wykrył, że globalny advisorylock mógł blokować odzyskanie po zawieszeniu żywego procesu. Nowy taskworker nie trzyma tej blokady; używa lease/fencing własnego zadania i istniejącego workera analitycznego. Przed każdym nowym pobraniem sprawdza uprawnienie. Trwającego HTTP nie anuluje. Wspólny pacingSEC nadal blokuje równoległe wywołania; wiele workerów może otrzymać kontrolowany błąd zajętości źródła. Domyślnie uruchamiany jest jeden taskworker.

Monitoring przedstawia aktualny stan zadania, nie pełny append-only dziennik wszystkich etapów ani heartbeat bezczynnych procesów. Historyczne etapy analizy po imporcie pozostają w istniejącym ledgerze przebiegów. Scheduler, automatyczny retry błędów dostawcy, LLM i predykcje nie zostały dodane przez ten przyrost.

Końcowa weryfikacja2026-11-09:836 Python PASS, Node9/9PASS, panel24/24PASS iTypeScript/VitebuildPASS. Ruff/format/mypy/schematy/OpenAPIPASS. Po dwukrotnym uruchomieniu Start-TaskWorker.ps1 pozostał ten sam żywy proces; `/ready`200. Worker działa lokalnie w tle. VPS nie został wdrożony, GPW/predykcje pozostają nieaktywne.

## Tożsamość rynku

Nowe zlecenie może jawnie podać exchange_mic XNAS, XNYS lub XWAR. Brak pola zachowuje zgodność z wcześniejszym klientem SEC. Dla aktywnych rynków serwer porównuje MIC z rozpoznanym instrumentem i zamraża go w istniejącym żądaniu kolejki. Odczyt zadania ujawnia zamrożony MIC bez migracji danych. Ten sam UUID ze zmienionym symbolem lub jawnym innym MIC jest konfliktem.

XWAR oznacza GPW. Do czasu dodania adaptera żądanie otrzymuje UNSUPPORTED_MARKET przed odczytem katalogu SEC i nie tworzy zadania ani zapytania do dostawcy. Nie mapujemy polskiego symbolu do podobnego oznaczenia z innej giełdy. Pełny rejestr ISIN i aliasów historycznych oraz zadania nieobsługiwanych źródeł pozostają kolejnymi przyrostami.

Zakres użytkowania potwierdzony2026-11-09: VPS wyłącznie prywatnie dla właściciela. Nie planujemy publicznej ani komercyjnej dystrybucji danych w tym wdrożeniu. Zmiana zakresu wymaga ponownego dopuszczenia źródeł.

Końcowy odbiór tożsamości rynku2026-11-09:839 Python PASS, panel26/26 ibuildPASS, Node9/9PASS, Ruff/mypy/schematy/OpenAPIPASS. Kontrola lokalnegoAPI:PKN+XWAR otrzymujeUNSUPPORTED_MARKET, istniejące zadanieApple zachowujeXNAS; `/ready`200. WznowionoDocker i taskworker po przerwie. Bez migracji. Dla prywatnego pilotaORLEN potwierdzonoHTTPSHEAD200, XLSX13143b oraz robotsDisallowpuste. ParserIFRS/PLN, importfinansowy i predykcjeGPW pozostają do wykonania.
