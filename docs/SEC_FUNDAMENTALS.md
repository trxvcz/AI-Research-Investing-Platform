# Pierwsze rzeczywiste fundamenty — SEC EDGAR

Status: adapter odczytu, archiwum i pipeline `sec-fundamentals-v1` działają lokalnie. Pierwszy rzeczywisty raport Apple został zapisany w PostgreSQL i wyeksportowany do JSON/HTML. Wynik jest **partial**: obejmuje przychód, wynik netto i marżę, bez wyceny, LLM, cen, rekomendacji i zleceń. [Weryfikacja](SEC_VERIFICATION.md), [dopuszczenie źródła](sources/SEC_EDGAR_ADMISSION.md).

## Źródło i ograniczenia zakresu

Adapter wykonuje tylko trzy typy GET na `data.sec.gov`: submissions/CIK oraz dwa companyconcept/us-gaap dla revenue i NetIncomeLoss. API SEC nie wymaga klucza ani uwierzytelnienia. Oficjalne opisy: [API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [zasady dostępu](https://www.sec.gov/about/developer-resources), [polityka publikacji](https://www.sec.gov/about/privacy-information).

Obsługujemy wyłącznie equity, USD, zgodny CIK i listing Nasdaq/XNAS lub NYSE/XNYS, najnowszy dostępny w recent formularz10-K i jednoznaczny roczny kontekst. Nie jest to historyczne uniwersum listingów. Obsługa starszych stron submissions, 10-K/A, IFRS, niestandardowych tagów i krótkich lat przejściowych pozostaje dalszym zadaniem. Zmienione/niejednoznaczne konteksty blokują import zamiast wybierania wygodniejszej starszej liczby.

Tag przychodu jest jawny: RevenueFromContractWithCustomerExcludingAssessedTax (domyślny), Revenues albo SalesRevenueNet. Nie ma automatycznej zamiany tagu ani płatnego źródła zastępczego. Przy braku jednej metryki druga może określić okres, a brak pozostaje missing. Gdy nie da się ustalić okresu rocznego, nie powstaje przebieg z fikcyjnym wejściem. Współistniejące konteksty kwartalne nie blokują poprawnego rocznego kontekstu; nie stają się jednak rocznymi danymi.

## Daty, oryginalne bajty i zaufany cache

Trzy odpowiedzi zachowujemy jako niezmienione bajty BYTEA z SHA256, URL i limitami istniejącego archiwum. Limit to1MiB na odpowiedź; większa jest odrzucana bez obcięcia. Snapshoty pobrane przez adapter otrzymują niezmienne wewnętrzne potwierdzenie `sec_ingestions` (migracja0007). Sam publiczny upload pliku do `/v1/snapshots` nie tworzy potwierdzenia i nie może zatruć cache ani zostać użyty jako wejście przebiegu SEC.

Cache korzysta wyłącznie z tych potwierdzeń. Identyczne bajty przy ponownym pobraniu zachowują wcześniejszy snapshot i first_seen; zmienione bajty tworzą nowy snapshot. Równoległe zapisy tego samego kontekstu zachowują pierwszy zatwierdzony wpis. Awaria pomiędzy archiwizacją a potwierdzeniem może zostawić niepowiązany raw snapshot; nie staje się on zaufanym cache. Historii nie usuwamy automatycznie.

`available_at` oznacza konserwatywny lokalny czas pierwszego pobrania. Nie cofamy go do daty filed. `event_time` pochodzi z rzeczywistego acceptanceDateTime zgłoszenia SEC; sama data filed nie daje fikcyjnej godziny publikacji. Początek/koniec okresu sprawozdawczego to daty kalendarzowe reprezentowane jako UTC00:00, bez twierdzenia o intraday dostępności. `as_of` nowego przebiegu wynika z zamrożonego zestawu wejść. Raport zawiera także ID/hash źródła potwierdzającego acceptanceDateTime.

Tak pobrane w2026 dane dotyczące2025 nie stanowią dowodu, że zbiorczy plik o tych samych bajtach był dostępny w2025. Nie używać tego pilota do historycznego backtestu bez oddzielnej polityki PIT i danych filingowych.

## Zasady pobierania

Każde pobranie przechodzi przez bramkę free-only oraz zatwierdzoną rezerwację limitu PostgreSQL. Konfiguracja włącza tylko `sec-edgar-public-v1`; modele i płatne zastępstwa pozostają wyłączone. Lokalny limit wynosi20 prób w jawnie skonfigurowanym oknie UTC. Jest to limit aplikacji, nie opublikowana przez SEC dzienna quota. Po upływie okna lub ważności przeglądu nowe pobrania są blokowane do świadomej aktualizacji konfiguracji; cache nadal pozwala odtworzyć zamrożony przebieg.

SEC ogranicza łączny ruch użytkownika do10 zapytań/s. Aplikacja jest bardziej zachowawcza: jedna aktywna operacja HTTP oraz co najmniej1s po jej zakończeniu, ze wspólną blokadą PostgreSQL. Inne aplikacje używające SEC wymagają oddzielnej koordynacji operatora. Równoległa zajęta blokada kończy próbę odmową bez wykonania HTTP; nie uruchamiamy automatycznej pętli ponowień.

Transport używa TLS, stałego hosta i ograniczonych ścieżek. Nie przyjmuje URL z dokumentu, nie używa proxy środowiskowych, cookies, przekierowań ani ponowień po403/429. Weryfikuje typ JSON, kodowanie identity i rzeczywistą długość odpowiedzi. Timeout dotyczy operacji gniazda; nie jest gwarancją absolutnego czasu procesu ani systemowego DNS.

User-Agent z nazwą aplikacji i kontaktem podaje operator. Na tym komputerze użytkownik przekazał go wyłącznie do zapytań SEC; zapisano go w ignorowanym `.local-postgres/sec-user-agent.txt`. Nie jest częścią repozytorium, raportu ani logów aplikacji. Do SEC trafiają tylko dozwolone publiczne identyfikatory zapytań i ten zatwierdzony nagłówek; nie wysyłamy raportów/prywatnych dokumentów do modeli.

## Uruchomienie

Właściwa baza Docker ma już head `0007_sec_receipts`, zastosowany po udanym backupie. Na innym stanowisku najpierw należy wykonać kopię, ustawić ALPHASENSE_DATABASE_URL i jawnie uruchomić `alembic upgrade head`.

```powershell
$env:PYTHONPATH = 'services/backend/src'
# Tylko na tym komputerze: wcześniej zapisane, ignorowane dane połączenia i identyfikator SEC.
$env:ALPHASENSE_DATABASE_URL = (Get-Content -Raw .local-postgres/dev-connection.json | ConvertFrom-Json).url
$env:ALPHASENSE_SEC_USER_AGENT = Get-Content -Raw .local-postgres/sec-user-agent.txt

.\.venv\Scripts\python.exe -m alphasense.sec_import --cik 0000320193 --symbol AAPL --mic XNAS
# Odpowiedź zawiera run_id. Wykonanie tylko tego zadania:
.\.venv\Scripts\python.exe -m alphasense.worker --once --run-id TU_UUID_PRZEBIEGU
```

Nowy import bez `--refresh` używa dostępnych potwierdzonych archiwów. `--refresh` pobiera trzy odpowiedzi, zużywając quota, i nie zmienia starych snapshotów. Ponowienie istniejącego `--run-id` zawsze wraca do jego zamrożonych wejść, także z `--refresh`; nowy eksperyment wymaga nowego run_id. Zmieniona tożsamość/CIK/tag przy tym samym ID jest odrzucana przed pobraniem.

Snapshoty i potwierdzenia są zapisane przed utworzeniem przebiegu; błąd pobrania/parsowania może pozostawić częściowe archiwum bez zadania. Kolejna próba korzysta z już potwierdzonych części. Sam import tworzy queued; worker jest osobnym procesem. Nie dodano schedulera ani automatycznego startu.

Eksport zapisuje `report.json` i `report.html` pod UUID rewizji w `artifacts/sec-research`. HTML jest samodzielny, escapuje dane źródłowe i nie ładuje skryptów. Istniejących plików o innej treści nie nadpisuje. Powtórzony eksport tej samej rewizji jest idempotentny.

Na tym komputerze raport pilota ma rewizję `a41c688e-5c37-5df5-aeec-c459d8e8a52d`. API nie uruchamia importu SEC ani modeli przy starcie; pobranie jest jawnym poleceniem CLI. Podgląd pliku przez narzędzie przeglądarkowe zablokowała polityka protokołu file; nie deklarujemy wizualnego QA. Strukturę, escapowanie i ochronę plików potwierdzają testy eksportu.
