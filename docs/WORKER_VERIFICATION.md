# Weryfikacja automatycznego workera — P1-02c

To zapis historycznego odbioru P1-02c. Aktualny stan bazy Docker i pierwszego przebiegu rzeczywistego źródła opisuje [SEC_VERIFICATION](SEC_VERIFICATION.md).

Odbiór lokalny: 2026-11-02, gałąź `codex/p1-automatic-worker`. Python3.12.14, PostgreSQL17.11, bez nowych zależności, pobrań źródeł i wywołań LLM. [Kontrakt, ograniczenia i uruchomienie](AUTOMATIC_WORKER.md).

## Wyniki

- **507 testów Python PASS, bez pominięć**, oraz **4 testy Node PASS**. Jeden istniejący komunikat Starlette/httpx o deprecacji TestClient; brak błędów testów.
- Ruff check i format: PASS (50 plików); mypy: PASS (22 moduły); pip check i brak driftu eksportowanych schematów: PASS. 25 schematów v1 i 4 legacy. Zdalnego CI nie uruchamiano.
- Pure engine: 44 testy, obejmujące dokładne wejścia/provenance/PIT, duplikaty kluczy JSON, niepoprawne UTF8 i liczby niefinitywne; marżę, zero/braki, niejednoznaczność, przepełnienie/underflow oraz średnią z trzech obserwacji bez udawania kalendarza sesji.
- Real PostgreSQL: jeden zwycięzca równoległych claims, SKIP LOCKED, odnowienie, wygaśnięcie i przejęcie; stary token nie zapisuje etapów ani raportu. Utrata ważności przy końcowej kontroli cofa raport i advance oraz finish/fail wraz ze zmianą joba. Odnowienie nie może wskrzesić lease, który wygasł w trakcie transakcji.
- Trzy porzucone próby oraz zmiana hasha kodu lub Git SHA kończą run jako failed i job jako dead. Złe wejście i tekst raportu nieobsługiwany przez JSONB kończą się po pierwszej próbie, bez fikcyjnego raportu; oryginalne bajty nadal są w archiwum.
- E2E: queued→start→data→validate→fundamental→technical→report→review→finish działa automatycznie na zarchiwizowanych pakietach. Wynik partial lub blocked jest osobny od statusu zakończenia pracy. Przykład z dokumentacji rzeczywiście daje marżę0.25 i SMA2.0 z liczb syntetycznych. CLI `--once` zapisuje rzeczywisty Git SHA i hash modułów oraz lockfile.
- Restart po publikacji przed review kończy ten sam raport bez dodatkowej rewizji. pg_dump SQL i psql odtwarzają osobną bazę: bajty, raport, job i claims pozostają identyczne; po wygaśnięciu lease nowy wykonawca kończy review. Źródłowy checkpoint pozostaje bez zmian.
- Migracja0004 zachowuje historyczne dane i migracje0001–0003, dodaje job/claims, ograniczenia i ochronę historii. Cofnięcie odmawia usunięcia automatycznych przebiegów lub historii workera. Dwa starsze testy zaktualizowano o nową trasę OpenAPI i aktualny MIGRATION_HEAD; nie osłabiono asercji ochrony danych.
- HTTP udostępnia job bez tokenu; publiczne polecenia events odrzucają automatyczny pipeline. Stare manualne przebiegi zachowują obsługę i nie są pobierane przez worker. Niepoprawne metadane joba dają zanonimizowany błąd magazynu.

## QA i środowisko

Migracja, czysty engine i testy kolejki powstały z rozłączną własnością plików. Niezależna recenzja wykryła trzy problemy: niezanonimizowany błąd odczytu metadanych, zbędne ponowienia raportu zawierającego NUL oraz możliwość odnowienia po pierwotnym terminie. Poprawiono je i dodano regresje; recenzent potwierdził brak dalszych blockerów. Koordynator wykonał pełną regresję po poprawkach.

Docker jest obecnie niedostępny; nie znaleziono jego procesu/usługi API ani instalacji w standardowej lokalizacji/rejestrze. Nie zmieniano konfiguracji ani wolumenu Docker. Uruchomiono wcześniej przygotowany pomocniczy PostgreSQL na127.0.0.1:55433. Wszystkie integracje używały izolowanych schematów i osobnych baz restore, a ich sprzątanie obejmowało wyłącznie zasoby testowe. Bazy deweloperskiej Docker nie migrowano: po jej wznowieniu wymaga backupu oraz jawnego upgrade do0004. Nie zmieniano DSN aplikacji na pomocniczą bazę.

Nie wykonywano stagingu, commita, resetu, push ani kopiowania wcześniejszych zmian z C:. Zachowano istniejące pliki i master plan. Koszt lokalnych obliczeń nie był mierzony; brak wywołań płatnych dostawców.

Po zakończeniu testów pomocniczy PostgreSQL zatrzymano poprawnie. Nie pozostawiono uruchomionego workera ani procesu testowego; kod i instrukcja są gotowe do uruchomienia po migracji właściwej bazy.

## Granice

To ograniczony worker dla jawnie wybranego pipeline, bez schedulerów, automatycznego startu po restarcie komputera, auth/RBAC i gwarancji24/7. Raport nie jest pełnym badaniem: brak syntezy, wyceny, scenariuszy, wykresów i adaptera rzeczywistych danych. Daty/licencje i origin są deklaracjami wymagającymi weryfikacji przyszłego adaptera. Administrator DB może zmienić zabezpieczenia. Nie wystawiać API publicznie.
