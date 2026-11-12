# Odbiór SEC i pierwszego rzeczywistego raportu

Data: 2026-11-02. Gałąź `codex/sec-fundamentals-source`. Python3.12.14, PostgreSQL17.11 w Dockerze. Bez nowych zależności, LLM, płatnych fallbacków i zleceń. [Instrukcja](SEC_FUNDAMENTALS.md), [dopuszczenie źródła](sources/SEC_EDGAR_ADMISSION.md).

## Testy i QA

- **745 testów Python PASS, bez pominięć**, pełny końcowy przebieg na Dockerze. **9 testów Node PASS**. Ruff check/format:71 plików, mypy:31 modułów, pip check i schema drift:PASS. 29 schematów v1 +4 legacy. Pozostaje istniejące ostrzeżenie Starlette/httpx dla TestClient; zdalnego CI nie uruchamiano.
- Parser:40 testów na jawnie syntetycznych kształtach SEC. CIK/listing/URL, najnowszy10-K, accession, okresy, USD, duplikaty i konflikty, brak jednej metryki, brak starego fallbacku, Decimal i utrata precyzji, acceptanceDateTime i konserwatywne first_seen. Kontekst kwartalny z tego samego formularza nie blokuje poprawnego rocznego; nie jest używany w jego zastępstwie.
- Transport:54 testy mockHTTP. Stały host/ścieżki, prawidłowy identyfikator, TLS, typ i kodowanie JSON, rzeczywiste bajty/limity/długość, błędy403/429, brak proxy/przekierowań/retry i brak ujawniania nagłówków. Nie są to54 rzeczywiste zapytania do SEC.
- Import:13 testów Docker. Exact-byte archiwum i zużycie trwałej quota, cache bez sieci, częściowe pobranie i wznowienie tylko brakującej części, first_seen po refresh, historyczne retry starego run_id, odrzucenie podmiany tożsamości przed siecią, publiczny raw upload niewystarczający do utworzenia przebiegu SEC oraz automatyczny raport partial.
- Potwierdzenia:22 testy Docker. Publiczne uploady niewidoczne dla cache, zgodność metadata i rzeczywistego hasha, stabilny pierwszy zatwierdzony wpis przy równoległych zapisach, niezmienność historii, FK, SQL guards i bezpieczny downgrade.
- Migracja pipeline:8 testów Docker; zachowane manual i deterministic, jawny nowy pipeline, niezgodne state/definition odrzucone, downgrade odmawia usunięcia obsługi SEC przy jego historii.
- Eksport: testy escapowania nieufnego HTML, brak skryptów i zewnętrznych zależności, jawne missing, idempotencja oraz odmowa nadpisania istniejącego pliku. Wybrany run_id workera nie wykonuje innych zadań kolejki.

Pracę dzielono na parser, transport, migracje i niezależną integrację/testy z rozłączną własnością plików. QA wykrył i doprowadził do regresji: nadmierne odrzucanie kontekstów kwartalnych, możliwość użycia ręcznie przesłanego raw jako cache SEC, zmianę wejść przy retry starego run_id oraz błędną obsługę zmienionego instrumentu. Poprawiono je; testy retestów przechodzą. Dodano wewnętrzne receipts zamiast uznawania publicznego snapshotu za dowód pobrania przez adapter.

Pełna regresja wykryła też blokadę podczas downgrade nowej tabeli z FK. Cofanie0007 blokuje teraz z NOWAIT również tabele nadrzędne przed DROP, więc równoległy upload nie powoduje zawieszenia. Historyczny test blokady rejestracji został przypięty do migracji0002, którą faktycznie bada; późniejszy pełny łańcuch celowo odmawia operacji przez NOWAIT. Nie zmieniano migracji0001–0005 ani nie osłabiono ochrony historii.

## Właściwa baza i rzeczywisty przebieg

Docker był dostępny na127.0.0.1:55432. Po zakończeniu testów wykonano poprawny pg_dump do ignorowanego lokalnego katalogu i upgrade bazy `alphasense` z0003 do **0007_sec_receipts**. Pierwsza próba backupu podczas testów nie powiodła się przez blokady; migracja wtedy nie ruszyła. Po usunięciu przyczyny backup i migracja przeszły. Dotychczasowe rewizje zachowano; przed importem baza deweloperska miała0 raportów i0 instrumentów. Końcowa kopia zawiera już dane SEC.

Rzeczywisty importer wykonał **3 GET do data.sec.gov**, po jednej rezerwacji quota, z kontaktem jawnie zatwierdzonym przez użytkownika wyłącznie dla SEC. Zachowano trzy raw snapshoty i trzy wewnętrzne potwierdzenia. Dane dotyczą Apple, CIK0000320193/AAPL/XNAS, roku2025; nie przedstawiamy ich jako sprawozdania za2026.

| Wynik | Wartość |
|---|---|
| Run | `f99a80d5-2f48-42d8-baa0-ff45899c8642` |
| Rewizja raportu | `a41c688e-5c37-5df5-aeec-c459d8e8a52d` |
| Status przebiegu / raportu | completed / partial |
| Okres | 2024-09-29–2025-09-27 |
| as_of archiwum | 2026-11-02T16:16:17.765340Z |
| Przychód / wynik netto | 416161000000 USD /112010000000 USD |
| Filing | `0000320193-25-000079`, filed2025-10-31, acceptance2025-10-31T10:01:26Z |

Liczby porównano z Consolidated Statements of Operations w [oficjalnym Form10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm), gdzie tabela podaje miliony USD. Adapter używa wartości API w USD bez dodatkowego mnożenia. Marża jest obliczeniem net_income/revenue, bez wyceny lub sygnału inwestycyjnego.

| Oryginał | Bajty | SHA256 |
|---|---:|---|
| submissions |163586| `2a1c62401f90039b5f3c10a80e3c4bb7f112c6e833ef0a163469f8b949396510` |
| revenue |18356| `4495f7a16b4ade43dfa8041ac6477074122cbd5b88033e3e0f68b3f919e7ffbf` |
| net_income |50767| `9b6ac23b024662c95dc7b4088a448bf60a31ff672e2f328161c5ceda6a8b9915` |

Ponowienie tego samego importu i eksportu zwróciło ten sam run/revision/as_of, bez podmiany bajtów i bez nowych pobrań. Licznik danych SEC pozostał3. Zapisane pliki: `artifacts/sec-research/a41c688e-5c37-5df5-aeec-c459d8e8a52d/report.json` i `report.html`. Nazwa firmy w HTML pochodzi ze zgodnego wpisu registry; treść źródeł jest escapowana. Narzędzie Browser Use odrzuciło otwarcie protokołu file, dlatego **wizualnego QA nie wykonano** i nie obchodzono tej blokady inną przeglądarką lub serwerem.

## Granice odbioru

Pierwszy raport jest ograniczonym rzeczywistym pilotem: dwa fakty i marża, bez cen, wyceny, DCF, wykresów, syntezy, prognoz i LLM. first_seen nie jest historycznym dowodem dostępności zbiorczego pliku w dacie filingowej. Krótkie okresy, poprawki10-K/A, stare strony submissions i inne waluty pozostają zablokowane/poza zakresem. Nie ma jeszcze React, schedulera, auth/RBAC ani gwarancji pracy24/7.

Kontakt SEC pozostaje w ignorowanej lokalnej konfiguracji. Nie zapisano go w raporcie, schematach lub kodzie. Zachowano istniejące pliki i plan Kronosa; nie zmieniano master planu ani obcego repo, nie wykonywano stagingu, commita, resetu, push i zakupów. Koszt lokalnych zasobów nie był mierzony.
