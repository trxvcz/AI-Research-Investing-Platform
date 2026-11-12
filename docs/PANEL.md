# Lokalny panel badań

Stan 2026-11-04. React/TypeScript w `apps/panel`, FastAPI i istniejący PostgreSQL. Dane pozostają w dotychczasowym magazynie.

## Uruchamianie

1. Uruchom Docker Desktop i istniejący kontener PostgreSQL projektu.
2. Kliknij dwukrotnie `Otworz panel.cmd` w katalogu repozytorium.
3. Otworzy się http://127.0.0.1:8082/panel/.

Launcher używa istniejącego `.venv`, zbudowanego `apps/panel/dist` i prywatnej konfiguracji `.local-postgres/dev-connection.json` lub zmiennej `ALPHASENSE_DATABASE_URL`. Uruchamia serwer w tle tylko na 127.0.0.1. Samo otwarcie panelu nie uruchamia workera ani pobierania danych. Kliknięcie uruchomienia analizy wykonuje import i worker dla wskazanego zadania. Zamknięcie karty pozostawia lokalny serwer w tle. Przy niedostępnej bazie panel pokazuje błąd i przycisk ponowienia.

## Dostępny zakres

Wyszukiwanie spółek, stronicowane listy analiz, stan i ostatni błąd przebiegu. Raport otwiera dokładną rewizję przypisaną do przebiegu. Osobna historia pozwala wybrać inne rewizje. W raporcie są obserwacje, okresy, `as_of`, `available_at`, źródła, sekcje oraz ograniczenia. Braki są jawne. Pobranie JSON/HTML czyta wybraną rewizję. Lista przebiegów jest stabilnie uporządkowana według UUID, nie chronologicznie.

Panel odczytuje archiwum i udostępnia jawne polecenia uruchomienia analizy oraz odświeżenia katalogu SEC. Brak logowania oznacza, że jest przeznaczony wyłącznie do lokalnego użytku. Host blokuje pozostałe metody zapisu i obce nagłówki Host. Polecenie analizy wymaga tego samego Origin, nagłówka panelu i JSON. Host stosuje CSP, nie ładuje zewnętrznych skryptów ani fontów. Nie wystawiaj go publicznie. Nie dodano PWA/offline ani schedulera.

## Rozwój

Z katalogu repo z ustawionym `PYTHONPATH=services/backend/src` eksportuj kontrakt przez `python scripts/export_panel_openapi.py`. W `apps/panel` uruchom `npm ci`, `npm run generate` i `npm run build`. Typy są generowane z OpenAPI, wywołania odczytu używają fetch. CI sprawdza zgodność kontraktu oraz kompilację. Pełny generowany klient operacji pozostaje osobnym zakresem.

Nowe endpointy to `GET /v1/panel/runs` (instrument_id, after_id, limit) oraz `GET /v1/panel/reports/{report_id}/{revision}/html`. Pozostałe odczyty wykorzystują istniejące API instrumentów i raportów.

## Weryfikacja 2026-11-04

Pełna regresja dała 752 PASS i jeden błąd nowego fixture testowego (duplikat symbolu instrumentu). Po naprawie fixture wszystkie 10 testów panelu/eksportu przeszło. Pozostałych testów nie powtarzano. Node 9/9 PASS, build React/TypeScript PASS, Ruff/format/mypy PASS, eksport schematów i zgodność OpenAPI PASS. Niezależny QA wykrył nadpisanie nagłówka HTML przez etykietę źródła; naprawiono i dodano regresję. Zachowano wcześniejsze pliki eksportu.

Na rzeczywistej bazie `/ready`200, raport Apple revision1 partial i eksport HTML200. W przeglądarce potwierdzono widok Apple, liczby, daty, źródła, historię oraz wyszukiwanie bez wyników i powrót do AAPL. Kontener PostgreSQL wznowiony, bez migracji lub pobierania SEC. Panel dostępny lokalnie na porcie8082.

## Nowa analiza z panelu

Obsługiwany katalog pilota obejmuje AAPL, GOOGL i GOOG. Symbol wpisany w wyszukiwarkę przeszukuje archiwum; osobny przycisk uruchomienia analizy jawnie inicjuje pracę. Backend wyznacza CIK i MIC z zamkniętego katalogu, a importer weryfikuje symbol/giełdę w odpowiedzi SEC przed rejestracją. Nieznane symbole są odrzucane, bez zgadywania emitenta i bez zapytań do innych dostawców.

[Form 10-K Alphabet](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm) potwierdza CIK0001652044 oraz GOOGL/GOOG na Nasdaq (sprawdzono 2026-11-04). Każdy symbol zachowuje osobny instrument; to nie jest historyczny katalog wszystkich listingów.

POST `/v1/panel/analyses` przyjmuje symbol i UUID przebiegu. Najpierw używa potwierdzonego archiwum SEC; brakujące zasoby pobiera przez istniejącą bramkę free-only. Nie wymusza odświeżenia zapisanych danych. Następnie wykonuje worker tylko dla tego przebiegu i zwraca jego wynik. GET `/v1/panel/analyses/{run_id}` udostępnia stan konkretnej analizy. Klient zachowuje UUID przy ponowieniu po błędzie połączenia; nie ponawia POST automatycznie. Raport częściowy jest poprawnym wynikiem ograniczonego zakresu, nie pełną wyceną.

Wykonanie jest synchroniczne, bez nowej kolejki importu ani schedulera. Przerwanie procesu przed utworzeniem przebiegu może pozostawić częściowe archiwum bez wpisu analizy. Ręczne ponowienie korzysta z potwierdzonych części. Po utworzeniu przebiegu działa istniejący trwały worker z lease/fencing. Brak serwera w tle po restarcie komputera wymaga ponownego otwarcia launchera.

Do nowych pobrań potrzebny jest zapisany lokalnie User-Agent SEC. Launcher przekazuje go przez środowisko, bez ujawniania w panelu. Na potrzeby tego przyrostu świadomie otwarto okno 2026-11-04 00:00–2026-11-05 00:00 UTC z limitem20 prób. Ważność przeglądu dostawcy pozostała bez zmian (do2026-11-09). Okno nie odnawia się automatycznie; po jego zakończeniu nowe pobranie pokaże odmowę, a potwierdzone archiwum pozostaje użyteczne.

Kontynuacja odbioru 2026-11-05: po przerwie poprzednie okno wygasło. Ustawiono nowe niepokrywające się okno 2026-11-05T00:00:00Z–2026-11-06T00:00:00Z z tym samym limitem20 prób, bez kasowania historii quota i bez automatycznego odnawiania.

Odbiór 2026-11-06: rzeczywiste polecenie panelu dla AAPL zakończone completed, nowy raport30b655d2-fd40-5576-b2c9-2fcf7eb69c66 revision1. Wykorzystano archiwum, bez nowych zapytań SEC. Okno pobrań z5 listopada wygasło; GOOGL wymaga otwarcia aktualnego okna przed pierwszym pobraniem. Build panelu i5 testów formularza PASS, Node9 PASS.

## Odbiór GOOGL — 2026-11-06

Otwarto jawne okno SEC 2026-11-06T00:00:00Z–2026-11-07T00:00:00Z, limit20 prób, bez zmiany daty ważności dopuszczenia i bez kasowania starych liczników. Proces panelu uruchomiono ponownie z zapisanym lokalnym User-Agent po pierwszej odmowie konfiguracji. Ponowiono ten sam run_id.

Przebieg37e24153-b65d-42ed-8aa8-21454bdf3571 zakończony completed; instrument30335065-ae8b-5025-8dda-e5381dd11de7; raport55d1341d-55b0-525a-87e5-d9f84505c595 revision1, statuspartial. Wynik netto132170000000USD za2025 pochodzi z SEC NetIncomeLoss, snapshot2c411c96-68b3-418d-a78f-8024eb7fcfeb. Przychód missing: brak pasującego rocznego faktu dla wybranego tagu. Nie zastąpiono braku zerem ani innym tagiem. JSON i eksportHTML zwracają200. Zakres pozostaje częściowy.

Weryfikacja końcowa2026-11-06: pełny zestaw769 PASS i1 błąd ANALYSIS_BUSY podczas równoległego rzeczywistego ponowienia GOOGL (blokada advisory wspólna dla schematów tej instancji PostgreSQL). Po zakończeniu wywołań panelu retest całego test_panel_launch.py11/11 PASS. Nie deklarujemy pojedynczego pełnego przebiegu770/770. Ruff/mypy/schematy/OpenAPI i Node9/9 PASS. Powtórzenie rzeczywistego UUID GOOGL zwraca ten sam report_id i revision1.

## Przychód Alphabet — 2026-11-06

Jawnie zweryfikowano SEC companyconcept/CIK0001652044/us-gaap/Revenues.json przez istniejącą bramkę free-only. Snapshot4f81e2e0-eac9-4392-abcc-3c47dc938936 zawiera pasujący roczny przychód2025:402836000000USD. Nowy przebieg54dd5110-092e-4e6d-90df-f3eeb20d75a5 completed, raportb9ffc575-9e9b-5e26-bdd3-6a56e76ef396 revision1. Wynik netto132170000000USD pochodzi z wcześniejszego trustedcache. Zachowano poprzedni raport z brakującym przychodem. Mapowanie dla nowych GOOGL/GOOG wybiera Revenues jawnie, bez automatycznego fallbacku.

Weryfikacja mapowania:12/12 testów uruchamiania PASS, Ruff/mypy/schematy/OpenAPI PASS, Node9/9 PASS. Nowy raport Alphabet zawiera przychód i wynik netto; pozostaje partial ze względu na ograniczony zakres fundamentów, brak cen/wyceny i pozostałych sekcji.

## Wyszukiwanie katalogu SEC — 2026-11-06

GET `/v1/panel/catalog?query=` przeszukuje lokalną kopię oficjalnego katalogu po symbolu lub nazwie. Sam odczyt nie pobiera danych. POST `/v1/panel/catalog/refresh` jawnie pobiera ustalony zasób SEC z istniejącą bramką free-only, quota i pacing. W panelu służy do tego przycisk „Pobierz katalog SEC”.

Oryginalne bajty są zachowywane lokalnie w ignorowanym `.local-postgres/sec-catalog` pod SHA256; wskaźnik najnowszej kopii jest wymieniany atomowo. Odczyt sprawdza hash, adres źródła i datę pobrania. To osobny lokalny cache katalogu, poza backupem samej bazy PostgreSQL; przenosząc instalację należy skopiować również ten katalog lub jawnie pobrać nową kopię. Nie jest to katalog historycznych listingów.

Wybór symbolu wyznacza CIK i MIC po stronie serwera. Niejednoznaczny symbol jest odrzucany. Katalog pokazuje tylko Nasdaq i NYSE. Obsługa fundamentów nadal jest ograniczona do rocznych danych US-GAAP/USD i poprawnie zweryfikowanego listingu w submissions. Obecność w katalogu nie gwarantuje udanej analizy, obsługi ETF/ADR/IFRS ani kompletności metryk. Dla Alphabet pozostaje jawny tag Revenues; pozostałe spółki używają ustalonego domyślnego tagu, bez automatycznego przełączania źródeł.

Odbiór katalogu2026-11-06: oficjalny zasób pobrany i zapisany, retrieved_at2026-11-06T13:57:38.057337Z. GETqueryMSFT zwrócił MICROSOFT CORP, CIK0000789019, XNAS. Nowy przebieg81a0d9b2-95a4-4271-819d-778c1230ab3e completed, raport9b4b8215-ed39-5ec3-ad6e-83c7b616125c revision1.

Końcowy odbiór katalogu2026-11-06: pełna regresja809 Python PASS (338s), Node9/9 PASS, panel6/6 PASS i build PASS. Ruff/format/mypy/schematy/OpenAPI PASS. Niezależny przegląd transportu/cache/guardów bez nowych blokujących uwag; wskazany problem replay poprawiono i objęto testem. Potwierdzono rzeczywisty refreshkatalogu, wyszukanieMSFT i zakończoną analizę. Bez migracji.

## Porównywanie zapisanych analiz

Widok raportu zawiera panel porównania. Raport po lewej to aktualnie wybrana dokładna rewizja. Raport po prawej pochodzi z listy zakończonych/zapisanych przebiegów tej samej spółki. Dane są pobierane z istniejących odczytów API; funkcja nie pobiera danych SEC, nie modyfikuje raportów ani nie tworzy nowej rewizji.

Klucz porównania obejmuje metrykę, jednostkę, walutę oraz początek i koniec okresu. Tylko zgodne, pojedyncze obserwacje available pozwalają policzyć różnicę prawa−lewa. Brak lub niejednoznaczność nie stają się zerem. Zmiana procentowa wymaga dodatniej wartości bazowej; dla zera lub wartości ujemnej nie jest prezentowana. Nieprzedstawialny wynik jest odrzucany. Różne okresy pozostają oddzielnymi wierszami; ta funkcja nie realizuje analizyYoY ani porównania stóp zwrotu. Daty as_of, metodologia i źródła pozwalają ocenić, skąd pochodzi zmiana.

Odbiór porównań2026-11-09: panel16/16 i Node9/9 PASS, TypeScript/VitebuildPASS, test realnych zapisanych raportówGOOGL PASS (netincome0, revenue missing→available bezfikcyjnej różnicy). Niezależny przegląd wyboru raportów i anulowania starych odczytów bez blokujących uwag. Bez zmian backendu i migracji, nie powtarzano testówPython. Odbiór wizualny niedokończony z powodu błędu połączenia przeglądarki; serwerHTTP odpowiada200.

## Archiwum źródeł w raporcie

Przy każdym źródle można rozwinąć metadane archiwum. Panel pobiera je wyłącznie z lokalnego API i porównuje tożsamość snapshotu, instrument, źródło, URL, datę pobrania i hash z wybraną rewizją raportu. Dopiero po zgodnym odczycie udostępnia pobranie oryginalnych bajtów jako załącznika. Plik ma rozszerzenie `.bin`, ponieważ endpoint celowo podaje `application/octet-stream` i `nosniff`. Nie renderujemy treści dokumentów jako HTML. Pobranie nie odpytuje SEC i nie zmienia archiwum.

Hash potwierdza zgodność zapisanych danych z raportem, nie jest podpisem źródła ani niezależnym potwierdzeniem prawdziwości treści. Weryfikację dokładnych bajtów wykonuje istniejący endpoint archiwum. Metadane źródeł użytych w raporcie nie stanowią listy wszystkich zasobów pobranych przez importer.

Odbiór archiwum2026-11-09: panel20/20testów iTypeScript/VitebuildPASS, Node9/9PASS, schematy/OpenAPIPASS. Odczyt źródłaGOOGL(snapshot2c411c96-68b3-418d-a78f-8024eb7fcfeb) potwierdził23800b, zgodnyhash, metadane200 i załącznik200 znosniff. Przegląd integracji: wyłącznie lokalneGET, źródła jako tekst, bezHTMLrender i bez zmianraportów. Nie powtarzano pełnej regresjiPython przy tej zmianiefrontendowej.
