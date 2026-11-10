# AlphaSense starter

## Prywatny wariant wdrożenia

Dodano osobny pakiet FastAPI/React/PostgreSQL z logowaniem właściciela, HTTPS przez Caddy, izolowaną bazą i polityką restartu kontenerów. Sprawdzony lokalnie w osobnym projekcie; VPS pozostaje do uruchomienia i odbioru. [Instrukcja i ograniczenia](docs/PRIVATE_DEPLOYMENT.md).

## Historia SEC i harmonogramy analiz

Panel pokazuje trwałą historię zmian etapów importu SEC i pozwala tworzyć wstrzymane harmonogramy dla wybranych spółek. Osobny scheduler zapisuje zlecenia, pomija zaległe terminy bez masowego nadrabiania i respektuje aktualny mechanizm źródeł oraz limitów w workerze. Starsza historia jest jawnie oznaczona jako niepełna. [Zakres, API i start](docs/SEC_SCHEDULES.md).

## Rejestr wykonawców

Panel pokazuje żywe sygnały procesów SEC i dokumentów, także podczas bezczynności, oraz historię uruchomień i zakończeń. Brak sygnału przez 45 sekund oznacza utratę kontaktu; stare obserwacje nie pozostają oznaczone jako aktualne. To monitoring procesów, odrębny od wyniku zadania i użycia LLM. [Zakres i działanie](docs/WORKER_SESSIONS.md).

## Kolejka dokumentów i audyt wykonania

Zapisany szkic można zlecić do weryfikacji w osobnym procesie. PostgreSQL zachowuje zadanie, etapy, próby, hashe i audyt, a panel pokazuje postęp. Worker działa także po zamknięciu panelu; `Start-DocumentWorker.ps1` uruchamia go osobno. Obecny tryb odtwarza weryfikację offline. Nowa ekstrakcja LLM pozostaje jawnie zablokowana i nie zużywa budżetu Gemini. [Zakres i start](docs/DOCUMENT_TASKS.md).

## Archiwum szkiców i przegląd faktów

Panel ma sekcję „Szkice z dokumentów”: lokalny import dokumentu i zapisanego szkicu JSON, cytaty z kontekstem, oryginały do pobrania oraz trwała historia decyzji dla każdego faktu. Akceptacja pozostaje oceną szkicu i nie publikuje metryk w raporcie. Import nie wywołuje modelu. [Zakres, API i instrukcja](docs/DOCUMENT_ARCHIVE.md).

## Agent analizy dokumentów — kierunek wspólny dla spółek

Dodano wspólne czytniki text/HTML/XLSX i agenta proponującego fakty z cytatami, zamiast parserów dla każdego emitenta. Gemini jest przygotowanym, nieaktywnym adapterem; szkice wymagają oceny i nie stają się automatycznie raportami. [Zakres i konfiguracja](docs/DOCUMENT_RESEARCH_AGENT.md). Jednorazowy autoryzowany pilot Gemini na danych syntetycznych zakończył się poprawnym szkicem do przeglądu; stałe wywołania pozostają nieaktywne. PDF/OCR i benchmark wielu dokumentów pozostają do wykonania.


## Trwałe zadania i nadzór wykonania

Panel ma jawny wybór rynku; GPW jest oznaczone jako adapter w przygotowaniu i nie jest kierowane do SEC. Panel zapisuje nowe zlecenia obsługiwanych rynków w PostgreSQL, a osobny taskworker wykonuje import i analizę. Widok „Zadania i wykonawcy” pokazuje stan, etap, heartbeat i błędy. Zweryfikowano zachowanie zadania po restarcieAPI oraz wykonanie w osobnym procesie. [Start i ograniczenia](docs/DURABLE_TASKS.md). [Rozpoznanie źródeł GPW](docs/sources/GPW_DISCOVERY.md) jest dokumentacją dopuszczenia, bez aktywnego adaptera lub predykcji GPW.


## Rozszerzone fundamenty SEC v2

Dodano gotówkę, dwie części długu długoterminowego, przepływy operacyjne, nakłady inwestycyjne i obliczenie OCF−capex w osobnym pipeline. Baza ma migrację0008 po backupie. Rzeczywisty pilot Apple v2 odebrano2026-11-09:7 dostępnych metryk, FCF i osobny raportpartial; źródła porównano z10-K. [Zakres i status](docs/SEC_FUNDAMENTALS_V2.md).

## Lokalny panel badań — 2026-11-04

Panel React/TypeScript pokazuje spółki, przebiegi analiz, błędy, dokładne rewizje raportów, źródła i daty dostępności danych. Obsługuje pobranie JSON/HTML. Uruchom `Otworz panel.cmd` i otwórz http://127.0.0.1:8082/panel/. Wymaga działającej lokalnej bazy PostgreSQL. [Instrukcja i zakres](docs/PANEL.md). Panel pozwala wyszukać spółkę w lokalnej kopii oficjalnego katalogu SEC i jawnie uruchomić analizę; przycisk pobrania katalogu odświeża listę Nasdaq/NYSE. Najpierw korzysta z archiwum; nowe pobrania wymagają aktywnego okna limitu SEC.


## Plan rozszerzenia — Kronos, 2026-11-02

Dodano do planu opcjonalne „Scenariusze cenowe”: świece dzienne, horyzont 5/20 sesji, porównanie z baseline, osobny worker modelu i cache. **To plan, bez wdrożonego modelu/API prognoz/hostingu.** Najpierw darmowe źródło i kontrakty, potem lokalny benchmark mini/small i ocena walk-forward z kontrolą okresu pretrainingu. Hosting zaczyna się od lokalnego pilota; CPU/hybryda/GPU wybierane dopiero po pomiarze i dopuszczeniu kosztów, bez automatycznych zakupów. [Architektura i hosting](docs/architecture/kronos-scenarios.md), [zadania KR-00–KR-06](docs/roadmap/issues.md#kronos--opcjonalne-scenariusze-cenowe-2026-11-02).

## Pierwszy rzeczywisty raport — SEC, 2026-11-02

Działa [adapter SEC i pipeline fundamentów](docs/SEC_FUNDAMENTALS.md). Pobrano trzy oryginalne odpowiedzi dla Apple, zapisano ich hashe i wewnętrzne potwierdzenia, a worker utworzył raport **partial** za rok2025: przychód, wynik netto i marża. Liczby porównano z10-K; nie ma wyceny, cen ani LLM. JSON/HTML znajdują się lokalnie w `artifacts/sec-research/a41c688e-5c37-5df5-aeec-c459d8e8a52d/`. **745 testów Python +9 Node PASS** na Dockerze; baza `alphasense` ma head0007 po backupie, a `/ready` daje200. [Odbiór i ograniczenia](docs/SEC_VERIFICATION.md). Podgląd wizualny HTML był zablokowany przez politykę przeglądarki; eksport jest sprawdzony testami.

## Bieżący kierunek projektu — 2026-10-30

Pracujemy w `D:/repos/AI Research Investing Platform`. Obowiązuje wyłącznie research, darmowe źródła i brak płatnych fallbacków. Starsze wzmianki o włączaniu płatnych providerów nie są aktualną zgodą na ich użycie. Konfiguracje modeli i źródeł pozostają przykładami. Nowa bramka Python egzekwuje dopuszczenie wywołań i trwałe limity; polityka dopuszcza tylko przejrzany pilot SEC; modele i nieznani dostawcy pozostają zablokowani.

[Zasada wyłącznie darmowych wywołań](docs/FREE_ONLY_PROVIDERS.md) jest zaimplementowana: dokładna kontrola opłat, aktualnych warunków i polityki danych, brak płatnego fallbacku oraz limit PostgreSQL współdzielony między procesami. Błąd dostawcy zużywa próbę; restart nie zeruje licznika. Selektor Node również odrzuca płatne opcje przy dowolnym budżecie. **605 testów Python +9 Node PASS** (2026-11-02), niezależny QA i retest. Migracja0005 została przetestowana; właściwa baza Docker ma już head0007. Aktualny pilot SEC opisano w sekcji pierwszego rzeczywistego raportu.

ADR-0001 został zaakceptowany: Python/FastAPI i React są celem, Node M0 pozostaje demonstratorem. FastAPI obsługuje lokalną walidację obserwacji, kontrolę czasu dostępności, jawne braki oraz opcjonalny magazyn raportów PostgreSQL. Nie pobiera danych ani nie wywołuje LLM. Lokalny panel React udostępnia odczyt archiwum przez FastAPI. Szczegóły: [backend — start i testy](docs/BACKEND.md), [kontrakty v1](docs/DOMAIN_CONTRACTS_V1.md), [discovery](docs/architecture/current-state.md), [stan docelowy](docs/architecture/target-state.md), [ADR-0001](docs/adr/0001-platform-architecture.md), [zadania](docs/roadmap/issues.md). Nie skopiowano wcześniejszych zmian z C:.

Dodano [kontrakt raportu v1](docs/REPORT_CONTRACT_V1.md): jawne źródła, referencje do dostępnych obserwacji, reguły rewizji i checksum. `/v1/reports/inspect` waliduje otrzymany JSON i rozpoznaje M0, bez automigracji lub zapisu. Generowanie raportów badawczych pozostaje osobnym zadaniem; osobne endpointy magazynu opisano poniżej.

[PostgreSQL i trwałe rewizje](docs/POSTGRES_REPORT_STORE.md) są dostępne: jawne migracje, POST raportu, GET latest/history, idempotentne retry i ochrona historii przed nadpisaniem. Lokalna baza `alphasense` działa w Dockerze; instrukcja podłączenia API w podlinkowanym dokumencie. Zweryfikowano backup/restore i zachowanie rewizji po odtworzeniu kontenera z wolumenem.

[Minimalny rejestr instrumentów](docs/INSTRUMENT_REGISTRY.md) działa: UUID, symbol, MIC, waluta, typ, daty i źródło; API rejestracji/odczytu/wyszukiwania i powiązania nowych raportów, bez zmiany starych.

[Przebiegi i archiwum](docs/RUNS_AND_SNAPSHOTS.md) są dostępne: niezmienne bajty z SHA256, zamrożone wejścia, historia etapów/błędów, idempotentne polecenia, wznowienie i powiązanie wyniku raportu. To manualny ledger, bez automatycznego wykonywania analiz. Odbiór tego etapu: **416 testów Python +4 Node PASS**, migracja0003 zastosowana w Dockerze po lokalnym backupie.

[Automatyczny worker](docs/AUTOMATIC_WORKER.md) jest zaimplementowany: osobny proces Python, kolejka PostgreSQL dla jawnie wybranego `deterministic-research-v1`, ograniczone ponowienia, czasowe uprawnienie wykonawcy i odrzucanie zapisów po jego utracie, atomowy zapis raportu oraz odzyskiwanie po przerwaniu. Ograniczone obliczenia obejmują przychód/wynik netto, marżę oraz średnią z trzech obserwacji ceny; wynik pozostaje partial albo blocked. **507 testów Python +4 Node PASS** na lokalnym PostgreSQL17.11 (2026-11-02), w tym backup/restore i wznowienie. Migracja0004 została przetestowana i zastosowana wraz z kolejnymi migracjami na bazie Docker (head0007). Worker nie uruchamia się razem z API. [Instrukcja i przykład](docs/AUTOMATIC_WORKER.md), [weryfikacja](docs/WORKER_VERIFICATION.md). Kolejne adaptery, szersza analityka, historyczne listingi pozostają do implementacji.

Samodzielny starter, bez połączenia z repozytorium trxvcz/AlphaSense. Dokumentacja po polsku. Node.js 22+; demo bez zależności i kluczy.

## Start
1. Rozpakuj ZIP do NOWEGO katalogu i otwórz go w Codex.
2. Opcjonalnie skopiuj .env.example do .env. Node nie ładuje go automatycznie; użyj node --env-file=.env services/api/server.mjs.
3. Uruchom npm test, następnie npm run demo, następnie npm start.
4. Otwórz http://127.0.0.1:8080 i raporty z listy. Demo zapisuje nowy katalog artifacts/<uuid> z report.json, report.html i chart.svg. Nigdy nie nadpisuje analizy.
Alternatywnie: docker compose up --build; aplikacja na tym samym adresie. Dane pozostają w wolumenie.
Raport w kontenerze utworzysz przez: docker compose --profile demo run --rm demo. Po lokalnym npm run demo raporty są w katalogu artifacts; wolumen kontenera jest osobnym magazynem.

## Co działa
Deterministyczne role data → fundamental → technical → report → reviewer, jawny trace, raport i wykres z syntetycznym wejściem, API health/ready/reports, PWA shell offline, testy, szkielet gateway i kontrakty. Wieloagentowy runtime oznacza role ze strukturą wejść/wyjść; demo nie wywołuje LLM. Obliczenia są ilustracyjne, nie są rekomendacją ani wynikiem inwestycyjnym.

## Co wymaga implementacji
Kolejne źródła danych i LLM, pełne rozliczanie zasobów/budżetu, harmonogram i operacyjne wdrożenie workera, baza produkcyjna, autoryzacja, web push/Telegram, discovery, backtest i walk-forward, eksport PDF, monitoring i HA. PWA cache'uje tylko publiczną powłokę; prywatne raporty nie są offline. To nie jest gotowe wdrożenie produkcyjne ani gwarancja 24/7.

## Polecenie dla Codex
„Przeczytaj AGENTS.md i TASKS.md. Kontynuuj zadania po zaakceptowanym ADR-0001, deleguj niezależne moduły, zachowaj research-only. Każdą zmianę potwierdź testami. Nie modyfikuj trxvcz/AlphaSense. Wyłącznie darmowe źródła; bez płatnych providerów i fallbacków.”

Pliki config/*.json są przykładami polityk docelowych, nie automatycznie aktywną konfiguracją dema. docs/ROADMAP.md określa bramki. docs/OPERATIONS.md opisuje wdrożenie. Raport weryfikacji pakietu leży obok ZIP.
